"""
Build an unsigned nanopub (assertion + provenance + pubinfo named graphs,
plus a head graph) for one approved submission, ready for a human to sign
and publish separately (see ../NANOPUB_INGESTION_PLAN.md).

Deliberately does NOT sign or publish anything -- no nanopub server call,
no key pair required. That step needs a submitter/pipeline-operator nanopub
identity that doesn't exist yet; this script stops at producing the
unsigned .trig file, which the operator can sign with the `np` CLI (Java
nanopub tool) or the `nanopub` Python library once that's set up.

Refuses to run for a submission that isn't 'approved' in the review queue
(../data/processed/review_queue.tsv) -- the review gate sits before this
step, not after, per the plan.

Usage:
    pipenv run python3 -m scripts.build_nanopub <submission_id> <assertion_ttl_path> <output_dir>

Example:
    pipenv run python3 -m scripts.build_nanopub sub001 /tmp/render_out4/assertion.ttl data/processed/nanopubs
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

from rdflib import Dataset, Graph, Namespace, Literal, URIRef, RDF, XSD

from scripts.review_queue import _read_all as _read_queue_rows

NP = Namespace("http://www.nanopub.org/nschema#")
NPX = Namespace("http://purl.org/nanopub/x/")
PROV = Namespace("http://www.w3.org/ns/prov#")
DCTERMS = Namespace("http://purl.org/dc/terms/")

# Placeholder base -- not a registered/resolvable nanopub server. Swap for a
# real trusty-URI base once signing/publishing is actually wired up; keeping
# it a plain placeholder here is intentional so an unsigned draft can never
# be mistaken for a published, resolvable nanopub URI.
NANOPUB_BASE = "https://example.org/nanopub-drafts/"


def _get_approved_row(submission_id: str) -> dict:
    for row in _read_queue_rows():
        if row["submission_id"] == submission_id:
            return row
    raise ValueError(f"No review-queue entry for submission_id '{submission_id}'")


def build_nanopub(submission_id: str, assertion_ttl_path: Path, output_dir: Path) -> Path:
    row = _get_approved_row(submission_id)
    if row["status"] != "approved":
        raise ValueError(
            f"Submission '{submission_id}' is not approved (status: {row['status']}) "
            f"-- review and approve it first via scripts.review_queue"
        )

    base = f"{NANOPUB_BASE}{submission_id}/"
    np_uri = URIRef(base)
    assertion_graph_uri = URIRef(f"{base}assertion")
    provenance_graph_uri = URIRef(f"{base}provenance")
    pubinfo_graph_uri = URIRef(f"{base}pubinfo")
    head_graph_uri = URIRef(f"{base}head")

    ds = Dataset()
    ds.bind("np", NP)
    ds.bind("npx", NPX)
    ds.bind("prov", PROV)
    ds.bind("dcterms", DCTERMS)

    # assertion graph: the generated RDF from render_submission_rdf.py, verbatim
    assertion_graph = ds.graph(assertion_graph_uri)
    source_graph = Graph()
    source_graph.parse(str(assertion_ttl_path), format="turtle")
    for triple in source_graph:
        assertion_graph.add(triple)

    # provenance graph: how the assertion came to be, and the review decision
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    prov_graph = ds.graph(provenance_graph_uri)
    prov_graph.add((assertion_graph_uri, PROV.wasAttributedTo, Literal(f"submission:{submission_id}")))
    prov_graph.add((assertion_graph_uri, PROV.generatedAtTime, Literal(row["submitted_at"], datatype=XSD.dateTime)))
    prov_graph.add((assertion_graph_uri, NPX.wasReviewedBy, Literal(row["reviewer"])))
    prov_graph.add((assertion_graph_uri, DCTERMS.description, Literal(row["decision_notes"] or "approved, no reviewer notes")))

    # pubinfo graph: about the nanopub itself, not the assertion
    pubinfo_graph = ds.graph(pubinfo_graph_uri)
    pubinfo_graph.add((np_uri, PROV.generatedAtTime, Literal(now, datatype=XSD.dateTime)))
    pubinfo_graph.add((np_uri, DCTERMS.description,
                        Literal("Unsigned draft -- not yet published to any nanopub server.")))

    # head graph: ties the three graphs together as one nanopub
    head_graph = ds.graph(head_graph_uri)
    head_graph.add((np_uri, RDF.type, NP.Nanopublication))
    head_graph.add((np_uri, NP.hasAssertion, assertion_graph_uri))
    head_graph.add((np_uri, NP.hasProvenance, provenance_graph_uri))
    head_graph.add((np_uri, NP.hasPublicationInfo, pubinfo_graph_uri))

    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"{submission_id}.unsigned.trig"
    ds.serialize(destination=str(out_path), format="trig")
    return out_path


def main():
    if len(sys.argv) != 4:
        print(__doc__)
        sys.exit(1)
    submission_id = sys.argv[1]
    assertion_ttl_path = Path(sys.argv[2])
    output_dir = Path(sys.argv[3])

    out_path = build_nanopub(submission_id, assertion_ttl_path, output_dir)
    print(f"Wrote unsigned nanopub draft to {out_path}")
    print("Not signed, not published -- sign with the `np` CLI or the nanopub")
    print("Python library (not yet a project dependency) before publishing.")


if __name__ == "__main__":
    main()
