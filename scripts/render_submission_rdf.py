"""
Turn one filled-in researcher submission (mvikg_submission_template.xlsx
shape) into an RDF assertion graph, ready to be wrapped as a nanopub.

Pipeline (see ../NANOPUB_INGESTION_PLAN.md):
  1. Load the four tabs (Strains/Genes/Variants/Phenotypes).
  2. Validate submitter-supplied external IDs (src/common/utils_id_validation.py)
     against live NCBI/UniProt, and write the outcome into each row's
     `evidence` column using the existing ECO:0000305 (has evidence) /
     ECO:0000035 (unresolved/no data) convention.
  3. Export the four validated/flagged tabs as CSVs.
  4. Render RDF from those CSVs using the CSVW mapping files in ../csvw/
     (a minimal local renderer covering only the subset of CSVW used there:
     aboutUrl/propertyUrl/valueUrl templates, suppressOutput, datatype --
     not general foreignKey/virtual-column CSVW).
  5. Write the assertion graph as Turtle.

This script does NOT do nanopub construction/signing (later pipeline stage)
and does NOT modify any existing builder.

Run: pipenv run python3 scripts/render_submission_rdf.py <submission.xlsx> <output_dir>
"""
import configparser
import json
import re
import sys
import urllib.parse
from pathlib import Path

import openpyxl
from rdflib import Graph, Literal, RDF, URIRef, XSD

from src.common.utils import normalize_so_id, format_uri
from src.common.utils_ontology import load_so_name_map
from src.common.constants import SO_NAME_SYNONYM_OVERRIDES, SO_SEQUENCE_ALTERATION, SOSA, BIOLINK
from src.common.utils_id_validation import (
    validate_ncbi_taxon_id,
    validate_ncbi_gene_id,
    validate_uniprot_accession,
    validate_genome_accession,
)
from scripts.review_queue import register_submission

REPO_ROOT = Path(__file__).resolve().parent.parent
CSVW_DIR = REPO_ROOT / "csvw"

# "SO_0001059" -> "0001059" -- the numeric half of the existing generic
# sequence_alteration fallback term, reused here so an unmatched variant_type
# gets the same fallback the ClaudeSkills builder already assigns, instead of
# a second ad hoc constant.
SO_SEQUENCE_ALTERATION_ID = str(SO_SEQUENCE_ALTERATION).rsplit("_", 1)[-1]


def _load_so_name_to_id() -> dict:
    config = configparser.ConfigParser()
    config.read(REPO_ROOT / "config.txt")
    so_obo_path = REPO_ROOT / config["input files"]["so_obo"]
    so_name_map = load_so_name_map(str(so_obo_path))  # {'SO:XXXXXXX': term_name}
    return {name.lower(): so_id[3:] for so_id, name in so_name_map.items()}

# tab name -> csv filename, must match the csvw/*-metadata.json "url" fields
TABS = {
    "Strains": "Strains.csv",
    "Genes": "Genes.csv",
    "Variants": "Variants.csv",
    "Phenotypes": "Phenotypes.csv",
}

_PLACEHOLDER_RE = re.compile(r"\{([^}]+)\}")


def load_sheet_rows(wb, sheet_name: str) -> list[dict]:
    """Read a sheet into a list of {header: value_as_str} dicts."""
    ws = wb[sheet_name]
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return []
    headers = [str(h).strip() if h is not None else "" for h in rows[0]]
    out = []
    for row in rows[1:]:
        if all(v is None for v in row):
            continue
        record = {}
        for header, value in zip(headers, row):
            if not header:
                continue
            record[header] = "" if value is None else str(value).strip()
        out.append(record)
    return out


def _append_evidence(record: dict, eco_term: str, comment: str) -> None:
    """
    Append a review-flag note to the row's evidence column, following the
    existing ECO:0000305 (has evidence)/ECO:0000035 (unresolved) convention
    used elsewhere in the pipeline. Multiple notes on one row are
    semicolon-joined rather than overwriting each other.
    """
    note = f"{eco_term}: {comment}"
    existing = record.get("evidence", "")
    record["evidence"] = f"{existing}; {note}" if existing else note


def validate_strains(rows: list[dict]) -> None:
    for r in rows:
        taxon_id = r.get("ncbi_taxon_id", "")
        claimed_name = r.get("taxon_name") or r.get("strain_name")
        if taxon_id:
            result = validate_ncbi_taxon_id(taxon_id, claimed_name)
            if result["status"] == "mismatch":
                _append_evidence(r, "ECO:0000035",
                                  f"ncbi_taxon_id {taxon_id} does not match claimed name "
                                  f"'{claimed_name}' (NCBI has '{result['fetched_name']}')")
            elif result["status"] == "not_found":
                _append_evidence(r, "ECO:0000035", f"ncbi_taxon_id {taxon_id} not found in NCBI Taxonomy")
            else:
                _append_evidence(r, "ECO:0000305", f"ncbi_taxon_id {taxon_id} validated against NCBI Taxonomy")

        genome_accession = r.get("genome_accession", "")
        if genome_accession:
            result = validate_genome_accession(genome_accession, taxon_id or None)
            if result["status"] == "mismatch":
                _append_evidence(r, "ECO:0000035",
                                  f"genome_accession {genome_accession} belongs to taxid "
                                  f"{result['fetched_taxid']}, not claimed {taxon_id}")
            elif result["status"] == "not_found":
                _append_evidence(r, "ECO:0000035", f"genome_accession {genome_accession} not found in NCBI Assembly")
            else:
                _append_evidence(r, "ECO:0000305", f"genome_accession {genome_accession} validated against NCBI Assembly")


def validate_genes(rows: list[dict]) -> None:
    for r in rows:
        gene_symbol = r.get("gene", "")
        ncbi_gene_id = r.get("ncbi_gene_id", "")
        if ncbi_gene_id:
            result = validate_ncbi_gene_id(ncbi_gene_id, gene_symbol)
            if result["status"] == "mismatch":
                _append_evidence(r, "ECO:0000035",
                                  f"ncbi_gene_id {ncbi_gene_id} official symbol "
                                  f"'{result['fetched_symbol']}' does not match claimed '{gene_symbol}'")
            elif result["status"] == "not_found":
                _append_evidence(r, "ECO:0000035", f"ncbi_gene_id {ncbi_gene_id} not found in NCBI Gene")
            else:
                _append_evidence(r, "ECO:0000305", f"ncbi_gene_id {ncbi_gene_id} validated against NCBI Gene")

        uniprot_accession = r.get("uniprot_accession", "")
        if uniprot_accession:
            result = validate_uniprot_accession(uniprot_accession, gene_symbol)
            if result["status"] == "mismatch":
                _append_evidence(r, "ECO:0000035",
                                  f"uniprot_accession {uniprot_accession} gene names "
                                  f"{result['fetched_symbols']} do not match claimed '{gene_symbol}'")
            elif result["status"] == "not_found":
                _append_evidence(r, "ECO:0000035", f"uniprot_accession {uniprot_accession} not found in UniProt")
            else:
                _append_evidence(r, "ECO:0000305", f"uniprot_accession {uniprot_accession} validated against UniProt")


def resolve_variant_types(rows: list[dict], so_name_to_id: dict) -> None:
    """
    Resolve each row's free-text `variant_type` to a real SO numeric ID
    in-place, mirroring the lookup kgBuilderClaudeSkills.py already does for
    SequenceVariantTypeName (synonym overrides first, then the SO name map,
    else the shared SO:0001059 generic sequence_alteration fallback with an
    evidence note) -- so the csvw/variants-metadata.json valueUrl template
    'SO_{variant_type}' is always filled with an id, never raw free text like
    'SNV' or 'missense'. A value that's already a bare SO numeric id (or
    'SO:0001059' form) is normalized and passed through unresolved lookups.
    """
    for r in rows:
        raw = r.get("variant_type", "")
        if not raw:
            continue
        normalized_id = normalize_so_id(raw)
        if normalized_id.isdigit():
            r["variant_type"] = normalized_id
            continue
        normalized_name = raw.strip().lower()
        looked_up_id = SO_NAME_SYNONYM_OVERRIDES.get(normalized_name) or so_name_to_id.get(normalized_name)
        if looked_up_id:
            r["variant_type"] = looked_up_id
        else:
            r["variant_type"] = SO_SEQUENCE_ALTERATION_ID
            _append_evidence(r, "ECO:0000035",
                              f"SO term not matched for variant_type '{raw}' — typed as generic sequence_alteration")


def write_csv(rows: list[dict], path: Path) -> None:
    import csv
    if not rows:
        path.write_text("")
        return
    headers = list(rows[0].keys())
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


def _load_context_prefixes(metadata: dict) -> dict:
    prefixes = {}
    for item in metadata.get("@context", []):
        if isinstance(item, dict):
            prefixes.update(item)
    return prefixes


def _expand_curie(value: str, prefixes: dict) -> str:
    if ":" not in value:
        return value
    prefix, _, local = value.partition(":")
    if prefix in prefixes:
        return prefixes[prefix] + local
    return value


def _render_template(template: str, row: dict, row_index: int, prefixes: dict, quote_values: bool) -> str:
    def substitute(match):
        key = match.group(1)
        if key == "_row":
            raw = str(row_index)
        else:
            raw = row.get(key, "")
        return urllib.parse.quote(raw, safe="") if quote_values else raw

    expanded_template = _expand_curie(template, prefixes) if not _PLACEHOLDER_RE.search(template.split(":", 1)[0]) else template
    filled = _PLACEHOLDER_RE.sub(substitute, expanded_template)
    return _expand_curie(filled, prefixes) if ":" in filled and not filled.startswith("http") else filled


def render_table_rdf(graph: Graph, csv_path: Path, metadata_path: Path) -> tuple[int, list[URIRef]]:
    """Apply one csvw/*-metadata.json mapping to one CSV file, adding triples
    to graph. Returns (triples_added, subject_uri_per_row) -- the per-row
    minted subject URI list is what lets the caller later connect entities
    *across* tables (see add_cross_entity_links below); within this function
    each row is still only linked to its own column values. Covers only:
    aboutUrl, propertyUrl, valueUrl, datatype, suppressOutput -- the subset
    actually used in csvw/*-metadata.json (see csvw/README.md)."""
    metadata = json.loads(metadata_path.read_text())
    prefixes = _load_context_prefixes(metadata)
    schema = metadata["tableSchema"]
    table_about_url = schema.get("aboutUrl")

    import csv as csv_module
    with open(csv_path) as f:
        rows = list(csv_module.DictReader(f))

    added = 0
    subject_uris: list[URIRef] = []
    for row_index, row in enumerate(rows):
        subject_iri = _render_template(table_about_url, row, row_index, prefixes, quote_values=True)
        subject_uris.append(URIRef(subject_iri))

        for col in schema["columns"]:
            if col.get("suppressOutput"):
                continue
            value = row.get(col["name"], "")
            if not value:
                continue
            property_template = col.get("propertyUrl")
            if not property_template:
                continue
            predicate = URIRef(_render_template(property_template, row, row_index, prefixes, quote_values=False))

            col_about = col.get("aboutUrl", table_about_url)
            row_subject = URIRef(_render_template(col_about, row, row_index, prefixes, quote_values=True))

            value_template = col.get("valueUrl")
            if value_template:
                obj_iri = _render_template(value_template, row, row_index, prefixes, quote_values=True)
                obj = URIRef(obj_iri)
            else:
                datatype = col.get("datatype")
                if datatype == "integer":
                    obj = Literal(value, datatype=XSD.integer)
                else:
                    obj = Literal(value)

            graph.add((row_subject, predicate, obj))
            added += 1
    return added, subject_uris


def add_sample_organism_structure(graph: Graph, strains_rows: list[dict],
                                   sample_uris: list[URIRef], metadata_path: Path) -> tuple[int, list[URIRef]]:
    """
    Mint the ORGANISM node for each Strains row and connect it to the SAMPLE
    node (the row's main rendered subject, already carrying rdfs:label/
    biome/identifier per strains-metadata.json), matching
    kgBuilderClaudeSkills.py:346-363 exactly:
        SAMPLE   rdf:type        sosa:Sample
        SAMPLE   sosa:isSampleOf ORGANISM
        ORGANISM biolink:in_taxon <external taxon ID>   (added by CSVW rendering
                                                           via the ncbi_taxon_id
                                                           column's aboutUrl override)

    CSVW's per-row, per-table mapping can mint one subject per row (the
    SAMPLE node, via the table's default aboutUrl) and redirect individual
    columns to a second URI template (the ORGANISM node, via a column-level
    aboutUrl override) -- but it can't mint that second node's rdf:type or
    the sosa:isSampleOf edge connecting the two, since neither comes from a
    column value. That's what this function adds, reusing the same ORGANISM
    URI template the ncbi_taxon_id column in strains-metadata.json already
    points at, so both land on the identical URI.

    Returns (triples_added, organism_uri_per_row) -- the second value lets
    add_document_provenance() attach dcterms:source to the same ORGANISM
    nodes without re-deriving the template a third time.
    """
    from src.common.constants import SOSA
    metadata = json.loads(metadata_path.read_text())
    prefixes = _load_context_prefixes(metadata)
    organism_template = next(
        col["aboutUrl"] for col in metadata["tableSchema"]["columns"]
        if col["name"] == "ncbi_taxon_id"
    )

    added = 0
    organism_uris: list[URIRef] = []
    for row_index, (row, sample_uri) in enumerate(zip(strains_rows, sample_uris)):
        organism_iri = _render_template(organism_template, row, row_index, prefixes, quote_values=True)
        organism_uri = URIRef(organism_iri)
        organism_uris.append(organism_uri)
        graph.add((sample_uri, RDF.type, SOSA.Sample))
        graph.add((sample_uri, SOSA.isSampleOf, organism_uri))
        added += 2
    return added, organism_uris


# Source tag for provenance nodes created from a researcher submission --
# parallel to the existing per-builder tags (mvikg:CSkills, etc.) used by
# kgBuilderClaudeSkills.py, kept distinct so submission-derived data is never
# misrepresented as paper-extracted.
SUBMISSION_SOURCE_TAG = "ResearcherSubmission"


def add_document_provenance(graph: Graph, strains_rows: list[dict],
                             sample_uris: list[URIRef], organism_uris: list[URIRef]) -> int:
    """
    Mint the Project/PMC/IAO-section provenance structure around each
    Strains row's SAMPLE/ORGANISM pair, matching
    kgBuilderClaudeSkills.py:315-333,358-362 exactly (source tag swapped
    for SUBMISSION_SOURCE_TAG -- see module docstring/discussion):
        PROJECT   rdf:type        dcmitype:Dataset
        PMC       rdf:type        dcmitype:Text
        PMC       dcterms:source  mvikg:ResearcherSubmission
        PMC       dcterms:references PROJECT
        SAMPLE    dcterms:isPartOf PROJECT
        SECTION   rdf:type        obo:IAO_0000326
        SECTION   dcterms:source  mvikg:ResearcherSubmission
        ORGANISM  dcterms:source  SECTION
        PMC       dcterms:references SECTION

    PROJECT/PMC are minted from the row's own 'Project ID'/'PMC ID' columns
    when present, else derived from doc_id -- unconditionally, every row
    gets a PROJECT and PMC node, same as the existing builder (not gated on
    the column having a value, unlike the CSVW-mapped columns).
    """
    from src.common.constants import MVIKGBOX, MVIKG, DCMITYPE, DCTERMS, OBO, NCBIPROJECT, PMC

    added = 0
    for row, sample_uri, organism_uri in zip(strains_rows, sample_uris, organism_uris):
        doc_id = row.get("doc_id", "")

        project_id = row.get("Project ID", "")
        project_uri = URIRef(f"{NCBIPROJECT}{project_id}") if project_id else MVIKGBOX[f"PROJECT-{format_uri(doc_id)}"]
        graph.add((project_uri, RDF.type, DCMITYPE.Dataset))
        added += 1

        pmc_id = row.get("PMC ID", "")
        if pmc_id:
            pmc_uri = URIRef(pmc_id) if pmc_id.startswith("http") else URIRef(f"{PMC}{pmc_id}")
        else:
            pmc_uri = URIRef(f"{PMC}{doc_id}")
        graph.add((pmc_uri, RDF.type, DCMITYPE.Text))
        graph.add((pmc_uri, DCTERMS.source, MVIKG[SUBMISSION_SOURCE_TAG]))
        graph.add((pmc_uri, DCTERMS.references, project_uri))
        added += 3

        graph.add((sample_uri, DCTERMS.isPartOf, project_uri))
        added += 1

        section_uri = MVIKGBOX[f"SECTION-IAO_0000326-{doc_id}-{SUBMISSION_SOURCE_TAG}"]
        graph.add((organism_uri, DCTERMS.source, section_uri))
        graph.add((section_uri, RDF.type, OBO.IAO_0000326))
        graph.add((section_uri, DCTERMS.source, MVIKG[SUBMISSION_SOURCE_TAG]))
        graph.add((pmc_uri, DCTERMS.references, section_uri))
        added += 4

    return added


def add_cross_entity_links(graph: Graph, tabs: dict, uris: dict) -> int:
    """
    Add the entity-to-entity triples CSVW's per-table rendering structurally
    cannot produce (see csvw/README.md): Sample -> Gene -> Variant, and
    Gene -> Phenotype. Predicates and direction match the existing pattern
    in kgBuilderClaudeSkills.py (sosa:hasFeatureOfInterest sample->gene --
    uris["Strains"] are SAMPLE node URIs, see add_sample_organism_structure
    above, not ORGANISM URIs -- biolink:has_sequence_variant gene->variant,
    biolink:has_phenotype gene->phenotype -- phenotypes attach at the gene
    level, reached via the variant's gene, not directly to the variant).

    tabs: {table_name: list[row_dict]} (post-validation, same order as rendered)
    uris: {table_name: list[URIRef]} (row-aligned, from render_table_rdf)
    """
    def key(doc_id: str, name: str) -> tuple:
        return (doc_id.strip(), name.strip().lower())

    strain_uri_by_key = {}
    for row, uri in zip(tabs["Strains"], uris["Strains"]):
        strain_uri_by_key[key(row.get("doc_id", ""), row.get("strain_name", ""))] = uri
        if row.get("taxon_name"):
            strain_uri_by_key[key(row.get("doc_id", ""), row.get("taxon_name", ""))] = uri

    gene_uri_by_key = {}
    for row, uri in zip(tabs["Genes"], uris["Genes"]):
        gene_uri_by_key[key(row.get("doc_id", ""), row.get("gene", ""))] = uri

    variant_gene_by_variant_key = {
        (row.get("doc_id", "").strip(), row.get("variant_id", "").strip()): row.get("variant_gene", "")
        for row in tabs["Variants"]
    }

    added = 0

    for row, gene_uri in zip(tabs["Genes"], uris["Genes"]):
        organism_key = key(row.get("doc_id", ""), row.get("organism_context", ""))
        organism_uri = strain_uri_by_key.get(organism_key)
        if organism_uri is not None:
            graph.add((organism_uri, SOSA.hasFeatureOfInterest, gene_uri))
            added += 1

    for row, variant_uri in zip(tabs["Variants"], uris["Variants"]):
        gene_key = key(row.get("doc_id", ""), row.get("variant_gene", ""))
        gene_uri = gene_uri_by_key.get(gene_key)
        if gene_uri is not None:
            graph.add((gene_uri, BIOLINK.has_sequence_variant, variant_uri))
            added += 1

    for row, phenotype_uri in zip(tabs["Phenotypes"], uris["Phenotypes"]):
        variant_key = (row.get("doc_id", "").strip(), row.get("variant_id", "").strip())
        variant_gene = variant_gene_by_variant_key.get(variant_key, "")
        gene_key = key(row.get("doc_id", ""), variant_gene)
        gene_uri = gene_uri_by_key.get(gene_key)
        if gene_uri is not None:
            graph.add((gene_uri, BIOLINK.has_phenotype, phenotype_uri))
            added += 1

    return added


def fill_missing_variant_ids(rows: list[dict]) -> None:
    """variant_id falls back to 'var{row_index}' when blank, matching the
    existing fallback in kgBuilderClaudeSkills.py -- needed here so join
    keys for the Phenotypes link always have something to match on."""
    for i, r in enumerate(rows):
        if not r.get("variant_id"):
            r["variant_id"] = f"var{i}"


def filter_to_rows_with_phenotype(tabs: dict) -> None:
    """
    Restrict Variants/Genes/Strains (in place) to only the records that have
    at least one reported Phenotypes row, keyed through
    (doc_id, variant_id) -> variant_gene -> organism_context. Phenotypes
    itself is left as-is (it's the anchor). Used for test runs where only
    the phenotype-bearing subset of a corpus file is of interest.
    """
    phenotype_keys = {
        (r.get("doc_id", "").strip(), r.get("variant_id", "").strip())
        for r in tabs["Phenotypes"]
    }
    tabs["Variants"] = [
        r for r in tabs["Variants"]
        if (r.get("doc_id", "").strip(), r.get("variant_id", "").strip()) in phenotype_keys
    ]
    gene_keys = {
        (r.get("doc_id", "").strip(), r.get("variant_gene", "").strip().lower())
        for r in tabs["Variants"]
    }
    tabs["Genes"] = [
        r for r in tabs["Genes"]
        if (r.get("doc_id", "").strip(), r.get("gene", "").strip().lower()) in gene_keys
    ]
    organism_keys = {
        (r.get("doc_id", "").strip(), r.get("organism_context", "").strip().lower())
        for r in tabs["Genes"]
    }
    tabs["Strains"] = [
        r for r in tabs["Strains"]
        if (r.get("doc_id", "").strip(), r.get("strain_name", "").strip().lower()) in organism_keys
        or (r.get("doc_id", "").strip(), r.get("taxon_name", "").strip().lower()) in organism_keys
    ]


def main():
    args = sys.argv[1:]
    only_with_phenotype = "--only-with-phenotype" in args
    args = [a for a in args if a != "--only-with-phenotype"]
    if len(args) != 2:
        print(__doc__)
        sys.exit(1)
    submission_path = Path(args[0])
    output_dir = Path(args[1])
    output_dir.mkdir(parents=True, exist_ok=True)

    wb = openpyxl.load_workbook(submission_path)
    tabs = {name: load_sheet_rows(wb, name) for name in TABS}

    fill_missing_variant_ids(tabs["Variants"])
    if only_with_phenotype:
        filter_to_rows_with_phenotype(tabs)

    validate_strains(tabs["Strains"])
    validate_genes(tabs["Genes"])
    resolve_variant_types(tabs["Variants"], _load_so_name_to_id())

    for name, csv_name in TABS.items():
        write_csv(tabs[name], output_dir / csv_name)

    graph = Graph()
    total_triples = 0
    uris = {}
    for name, csv_name in TABS.items():
        metadata_path = CSVW_DIR / f"{name.lower()}-metadata.json"
        added, subject_uris = render_table_rdf(graph, output_dir / csv_name, metadata_path)
        total_triples += added
        uris[name] = subject_uris

    sample_organism_added, organism_uris = add_sample_organism_structure(
        graph, tabs["Strains"], uris["Strains"], CSVW_DIR / "strains-metadata.json"
    )
    total_triples += sample_organism_added
    total_triples += add_document_provenance(graph, tabs["Strains"], uris["Strains"], organism_uris)
    total_triples += add_cross_entity_links(graph, tabs, uris)

    ttl_path = output_dir / "assertion.ttl"
    graph.serialize(destination=str(ttl_path), format="turtle")
    print(f"Wrote {total_triples} triples to {ttl_path}")
    print(f"Wrote validated CSVs to {output_dir}")

    if total_triples == 0:
        print("No triples generated (e.g. nothing survived --only-with-phenotype "
              "filtering, or no rows joined end-to-end) -- skipping review queue, "
              "nothing to review.")
        return

    flag_count = sum(
        row.get("evidence", "").count("ECO:0000035")
        for rows in tabs.values() for row in rows
    )
    submission_id = next(
        (row["doc_id"] for rows in tabs.values() for row in rows if row.get("doc_id")),
        submission_path.stem,
    )
    register_submission(submission_id, flag_count)
    print(f"Registered '{submission_id}' in review queue with {flag_count} flag(s) -- status: pending_review")


if __name__ == "__main__":
    main()
