import json
import time
import urllib.request
import urllib.error
import difflib

from src.common.utils import print_to_log


class GeneResolutionNetworkError(RuntimeError):
    """
    Raised instead of returning None when a lookup fails because network
    connectivity is down, as opposed to a normal "no match found" outcome
    (HTTP 404, empty result set, malformed query, etc). Lets callers
    distinguish "genuinely unresolved" from "we couldn't even check" so a
    dropped connection doesn't get silently recorded as a confirmed non-match.
    """


def _is_network_error(e: Exception) -> bool:
    """
    True if `e` looks like lost/interrupted connectivity (DNS failure,
    connection refused/reset, timeout) rather than a normal HTTP-level
    failure. Deliberately narrow: urllib.error.HTTPError (404, etc) is never
    classified as a network error — only failures where the underlying cause
    is an OSError-family connectivity problem.
    """
    if isinstance(e, urllib.error.URLError) and isinstance(e.reason, OSError):
        return True
    if isinstance(e, (OSError, ConnectionError, TimeoutError)) and not isinstance(e, urllib.error.HTTPError):
        return True
    return False


def _call_with_network_retry(fn, log_file: str, label: str, retries: int = 3, base_delay: int = 5):
    """
    Call fn() (a zero-arg callable performing one urllib request), retrying
    with backoff on transient connectivity errors (timeout, connection
    reset/aborted, etc) before finally raising GeneResolutionNetworkError.

    A single reset/timeout is common under NCBI/UniProt's rate limiting or
    momentary server-side hiccups and does NOT reliably mean the network
    itself is down — only a connection that stays broken across several
    retries is treated as a genuine outage. urllib.error.HTTPError (404, etc)
    is not retried — it propagates immediately for the caller's own handling.
    """
    delay = base_delay
    last_exc = None
    for attempt in range(retries):
        try:
            return fn()
        except urllib.error.HTTPError:
            raise
        except Exception as e:
            if _is_network_error(e):
                last_exc = e
                print_to_log(
                    f"Transient connection error for {label} (attempt {attempt + 1}/{retries}): "
                    f"{e} — retrying in {delay}s", log_file
                )
                time.sleep(delay)
                delay *= 2
                continue
            raise
    raise GeneResolutionNetworkError(str(last_exc)) from last_exc


# Minimum difflib.SequenceMatcher ratio for a fuzzy gene-symbol candidate to be
# accepted. Gene symbols are short and paralog families differ by one letter
# (fimA/fimH/fimC, clsA/clsB), so this is set high on purpose. Only used when
# the exact-match query returns nothing, and only accepted when there is a
# single best candidate (a tie at/above threshold is treated as no-match, not
# guessed).
GENE_FUZZY_MATCH_THRESHOLD = 0.92


def _best_fuzzy_symbol_match(query_symbol: str, candidates: list[str]) -> tuple[str, float] | None:
    """
    Score candidate gene symbols against query_symbol with difflib and return
    (best_candidate, score) if there is a single candidate at/above
    GENE_FUZZY_MATCH_THRESHOLD, else None (no match, or an ambiguous tie).
    """
    if not candidates:
        return None
    q = query_symbol.strip().lower()
    scored = sorted(
        ((c, difflib.SequenceMatcher(None, q, c.strip().lower()).ratio()) for c in candidates if c),
        key=lambda pair: pair[1],
        reverse=True,
    )
    if not scored:
        return None
    best_symbol, best_score = scored[0]
    if best_score < GENE_FUZZY_MATCH_THRESHOLD:
        return None
    if len(scored) > 1 and scored[1][1] == best_score:
        return None
    return best_symbol, best_score


NCBI_ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
NCBI_ESUMMARY_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"


def _ncbi_get(url: str, log_file: str, retries: int = 3) -> dict | None:
    """
    GET a JSON URL from an NCBI endpoint, retrying on HTTP 429 AND on
    transient connectivity errors (timeout, connection reset) with backoff.
    Only escalates to GeneResolutionNetworkError if connectivity errors
    persist across every retry — a single reset/timeout is common under
    NCBI's rate limiting and is not a reliable "network is down" signal.
    Returns parsed JSON dict, or None for a non-network HTTP error (404 etc).
    """
    delay = 5
    last_network_exc = None
    print_to_log(f"NCBI API call: GET {url}", log_file)
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=15) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                print_to_log(
                    f"NCBI rate-limited (429) for {url} — waiting {delay}s "
                    f"(attempt {attempt + 1}/{retries})", log_file
                )
                time.sleep(delay)
                delay *= 2
            else:
                print_to_log(f"NCBI HTTP error {e.code} for {url}: {e}", log_file)
                return None
        except Exception as e:
            if _is_network_error(e):
                last_network_exc = e
                print_to_log(
                    f"NCBI transient connection error for {url} (attempt "
                    f"{attempt + 1}/{retries}): {e} — retrying in {delay}s", log_file
                )
                time.sleep(delay)
                delay *= 2
            else:
                print_to_log(f"NCBI request failed for {url}: {e}", log_file)
                return None
    if last_network_exc is not None:
        raise GeneResolutionNetworkError(str(last_network_exc)) from last_network_exc
    print_to_log(f"NCBI request gave up after {retries} retries: {url}", log_file)
    return None
