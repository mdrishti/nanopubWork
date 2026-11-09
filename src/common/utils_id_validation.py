"""
Validate submitter-supplied external IDs (NCBI Taxonomy, NCBI Gene, UniProt,
genome assembly accession) for the researcher-submission nanopub pipeline.

This is the inverse direction of the lookups in utils_ncbi.py: those go
name/symbol -> ID (used when no ID is given, e.g. text extracted from a
paper). Here the submitter already supplied an ID; the job is to fetch the
record for that ID and check it against the name/symbol they also gave, not
to search for a match. Kept as a separate module (not added to
utils_ncbi.py) since it's a distinct pipeline stage from paper-extraction
resolution, reusing that module's HTTP/retry/caching/fuzzy-match helpers
rather than duplicating them.
"""
import json
import urllib.parse
import urllib.request
import urllib.error

from src.common.utils import print_to_log
from src.common.utils_ncbi import (
    NCBI_ESEARCH_URL,
    NCBI_ESUMMARY_URL,
    GeneResolutionNetworkError,
    _ncbi_get,
    _call_with_network_retry,
    _best_fuzzy_symbol_match,
)

# Minimum difflib ratio (via _best_fuzzy_symbol_match) for a fetched name to
# count as matching a submitter's claimed name/symbol.
_taxon_id_cache: dict = {}       # taxon_id_str -> fetched_name | None
_gene_id_cache: dict = {}        # gene_id_str -> (official_symbol, aliases) | None
_uniprot_acc_cache: dict = {}    # accession -> fetched_gene_symbols (list) | None
_assembly_acc_cache: dict = {}   # accession -> fetched_taxid | None
_pmc_id_cache: dict = {}         # pmc_id_str -> fetched_title | None

EUROPEPMC_SEARCH_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"


def _names_roughly_match(claimed: str, fetched: str) -> bool:
    """
    True if claimed and fetched name refer to the same organism/strain.

    NCBI's on-file scientific name is often more verbose than what a
    submitter types (e.g. claimed 'Escherichia coli K-12' vs fetched
    'Escherichia coli str. K-12 substr. MG1655') — a whole-string difflib
    ratio (tuned in _best_fuzzy_symbol_match for short gene symbols) scores
    that pair too low despite it being a clear match. Instead: every
    alphanumeric token in the shorter name must appear as a token in the
    longer name. Punctuation-only tokens ('str.', 'substr.') are ignored on
    both sides since they carry no identifying information.
    """
    def tokens(s: str) -> set:
        return {t for t in s.strip().lower().replace('.', ' ').replace('-', ' ').split() if t}

    a, b = tokens(claimed), tokens(fetched)
    if not a or not b:
        return False
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    return shorter.issubset(longer)


def validate_ncbi_taxon_id(taxon_id: str, claimed_name: str | None,
                            log_file: str = "ncbi-lookup.log") -> dict:
    """
    Confirm a submitter-supplied NCBI Taxonomy ID exists and, if
    claimed_name is given, roughly matches the scientific name NCBI has on
    file for it.

    Returns {'status': 'validated'|'mismatch'|'not_found', 'fetched_name': str|None}.
    'mismatch' (ID exists, name doesn't match) is treated by callers as a
    stronger red flag than a missing ID — a wrong ID is worse than no ID.
    """
    taxon_id = str(taxon_id).strip()
    if not taxon_id.isdigit():
        return {'status': 'not_found', 'fetched_name': None}

    if taxon_id in _taxon_id_cache:
        fetched_name = _taxon_id_cache[taxon_id]
    else:
        fetched_name = None
        url = f"{NCBI_ESUMMARY_URL}?db=taxonomy&id={taxon_id}&retmode=json"
        data = _ncbi_get(url, log_file)
        if data:
            doc = data.get('result', {}).get(taxon_id, {})
            fetched_name = doc.get('scientificname') or None
        _taxon_id_cache[taxon_id] = fetched_name
        if fetched_name:
            print_to_log(f"NCBI Taxonomy validate: {taxon_id} -> '{fetched_name}'", log_file)

    if fetched_name is None:
        return {'status': 'not_found', 'fetched_name': None}
    if not claimed_name or _names_roughly_match(claimed_name, fetched_name):
        return {'status': 'validated', 'fetched_name': fetched_name}
    return {'status': 'mismatch', 'fetched_name': fetched_name}


def validate_ncbi_gene_id(gene_id: str, claimed_symbol: str | None,
                           log_file: str = "ncbi-lookup.log") -> dict:
    """
    Confirm a submitter-supplied NCBI Gene ID exists and, if claimed_symbol
    is given, matches the gene's official symbol or a listed alias.

    Returns {'status': 'validated'|'mismatch'|'not_found', 'fetched_symbol': str|None}.
    """
    gene_id = str(gene_id).strip()
    if not gene_id.isdigit():
        return {'status': 'not_found', 'fetched_symbol': None}

    if gene_id in _gene_id_cache:
        cached = _gene_id_cache[gene_id]
    else:
        cached = None
        url = f"{NCBI_ESUMMARY_URL}?db=gene&id={gene_id}&retmode=json"
        data = _ncbi_get(url, log_file)
        if data:
            doc = data.get('result', {}).get(gene_id, {})
            official_symbol = doc.get('name') or None
            aliases_raw = doc.get('otheraliases') or ''
            aliases = [a.strip() for a in aliases_raw.split(',') if a.strip()]
            if official_symbol:
                cached = (official_symbol, aliases)
        _gene_id_cache[gene_id] = cached
        if cached:
            print_to_log(f"NCBI Gene validate: {gene_id} -> '{cached[0]}'", log_file)

    if cached is None:
        return {'status': 'not_found', 'fetched_symbol': None}
    official_symbol, aliases = cached
    if not claimed_symbol:
        return {'status': 'validated', 'fetched_symbol': official_symbol}
    candidates = [official_symbol] + aliases
    if claimed_symbol.strip().lower() in {c.lower() for c in candidates}:
        return {'status': 'validated', 'fetched_symbol': official_symbol}
    if _best_fuzzy_symbol_match(claimed_symbol, candidates):
        return {'status': 'validated', 'fetched_symbol': official_symbol}
    return {'status': 'mismatch', 'fetched_symbol': official_symbol}


def validate_uniprot_accession(accession: str, claimed_symbol: str | None,
                                log_file: str = "ncbi-lookup.log") -> dict:
    """
    Confirm a submitter-supplied UniProt accession exists and, if
    claimed_symbol is given, matches one of the entry's gene names.

    Returns {'status': 'validated'|'mismatch'|'not_found', 'fetched_symbols': list[str]}.
    """
    accession = accession.strip()
    if not accession:
        return {'status': 'not_found', 'fetched_symbols': []}

    if accession in _uniprot_acc_cache:
        fetched_symbols = _uniprot_acc_cache[accession]
    else:
        fetched_symbols = None
        url = f"https://rest.uniprot.org/uniprotkb/{urllib.parse.quote(accession)}.json?fields=gene_names"

        def _do_fetch():
            print_to_log(f"UniProt API call: GET {url}", log_file)
            req = urllib.request.Request(url, headers={'Accept': 'application/json'})
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read())

        try:
            data = _call_with_network_retry(_do_fetch, log_file, f"uniprot_validate:{accession}")
            genes = data.get('genes', []) if data else []
            fetched_symbols = [
                g['geneName']['value'] for g in genes
                if g.get('geneName', {}).get('value')
            ]
        except urllib.error.HTTPError as e:
            if e.code != 404:
                print_to_log(f"UniProt HTTP {e.code} validating '{accession}': {e}", log_file)
            fetched_symbols = None
        except GeneResolutionNetworkError:
            raise
        except Exception as e:
            print_to_log(f"UniProt validation failed for '{accession}': {e}", log_file)
            fetched_symbols = None

        _uniprot_acc_cache[accession] = fetched_symbols
        if fetched_symbols:
            print_to_log(f"UniProt validate: {accession} -> {fetched_symbols}", log_file)

    if fetched_symbols is None:
        return {'status': 'not_found', 'fetched_symbols': []}
    if not claimed_symbol:
        return {'status': 'validated', 'fetched_symbols': fetched_symbols}
    if claimed_symbol.strip().lower() in {s.lower() for s in fetched_symbols}:
        return {'status': 'validated', 'fetched_symbols': fetched_symbols}
    if fetched_symbols and _best_fuzzy_symbol_match(claimed_symbol, fetched_symbols):
        return {'status': 'validated', 'fetched_symbols': fetched_symbols}
    return {'status': 'mismatch', 'fetched_symbols': fetched_symbols}


def validate_pmc_id(pmc_id: str, log_file: str = "ncbi-lookup.log") -> dict:
    """
    Confirm a submitter-supplied PMC ID (e.g. 'PMC1913268') exists in
    EuropePMC.

    No claimed-name cross-check: unlike taxon/gene/accession, there is no
    submitter-supplied title to compare against, so this only confirms
    existence. Do NOT filter the query with 'AND SRC:PMC' — SRC:PMC selects
    records whose primary source-of-record is PMC itself (preprints etc.),
    while most MEDLINE-indexed papers that also have a PMC full-text copy
    are tagged SRC:MED and would be wrongly excluded (verified against
    PMC1913268, a MED-sourced paper with a valid pmcid).

    Returns {'status': 'validated'|'not_found', 'fetched_title': str|None}.
    """
    pmc_id = pmc_id.strip().upper()
    if not pmc_id.startswith('PMC') or not pmc_id[3:].isdigit():
        return {'status': 'not_found', 'fetched_title': None}

    if pmc_id in _pmc_id_cache:
        fetched_title = _pmc_id_cache[pmc_id]
    else:
        fetched_title = None
        query = urllib.parse.quote(f"pmcid:{pmc_id}")
        url = f"{EUROPEPMC_SEARCH_URL}?query={query}&format=json"

        def _do_fetch():
            print_to_log(f"EuropePMC API call: GET {url}", log_file)
            req = urllib.request.Request(url, headers={'Accept': 'application/json'})
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read())

        try:
            data = _call_with_network_retry(_do_fetch, log_file, f"pmc_validate:{pmc_id}")
            results = data.get('resultList', {}).get('result', []) if data else []
            if results:
                fetched_title = results[0].get('title') or None
        except GeneResolutionNetworkError:
            raise
        except Exception as e:
            print_to_log(f"EuropePMC validation failed for '{pmc_id}': {e}", log_file)
            fetched_title = None

        _pmc_id_cache[pmc_id] = fetched_title
        if fetched_title:
            print_to_log(f"EuropePMC validate: {pmc_id} -> '{fetched_title}'", log_file)

    if fetched_title is None:
        return {'status': 'not_found', 'fetched_title': None}
    return {'status': 'validated', 'fetched_title': fetched_title}


def validate_genome_accession(accession: str, claimed_taxon_id: str | None = None,
                               log_file: str = "ncbi-lookup.log") -> dict:
    """
    Confirm a submitter-supplied genome assembly accession (e.g.
    'GCA_000005845.2') exists in NCBI Assembly and, if claimed_taxon_id is
    given, belongs to that taxon.

    Returns {'status': 'validated'|'mismatch'|'not_found', 'fetched_taxid': str|None}.
    """
    accession = accession.strip()
    if not accession:
        return {'status': 'not_found', 'fetched_taxid': None}

    if accession in _assembly_acc_cache:
        fetched_taxid = _assembly_acc_cache[accession]
    else:
        fetched_taxid = None
        term = urllib.parse.quote(f'"{accession}"[Assembly Accession]')
        search_url = f"{NCBI_ESEARCH_URL}?db=assembly&term={term}&retmode=json&retmax=1"
        data = _ncbi_get(search_url, log_file)
        ids = data.get('esearchresult', {}).get('idlist', []) if data else []
        if ids:
            summary_url = f"{NCBI_ESUMMARY_URL}?db=assembly&id={ids[0]}&retmode=json"
            sdata = _ncbi_get(summary_url, log_file)
            if sdata:
                doc = sdata.get('result', {}).get(ids[0], {})
                fetched_taxid = str(doc.get('taxid')) if doc.get('taxid') else None
        _assembly_acc_cache[accession] = fetched_taxid
        if fetched_taxid:
            print_to_log(f"NCBI Assembly validate: {accession} -> taxid {fetched_taxid}", log_file)

    if fetched_taxid is None:
        return {'status': 'not_found', 'fetched_taxid': None}
    if not claimed_taxon_id or str(claimed_taxon_id).strip() == fetched_taxid:
        return {'status': 'validated', 'fetched_taxid': fetched_taxid}
    return {'status': 'mismatch', 'fetched_taxid': fetched_taxid}
