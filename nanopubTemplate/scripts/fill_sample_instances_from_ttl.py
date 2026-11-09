#!/usr/bin/env python3
"""
Fills "Declaring an MVIKG sample context"
(nanopubTemplate/mvikg-sample-taxon-template-sosa.trig) from a builder
.ttl, one instance per distinct SAMPLE node. This is the first stage of
the sample -> variant -> phenotype pipeline: variant and phenotype
instances reference a *published* (signed) sample nanopub's trusty IRI,
so sample instances have to exist and be signed before the other two
stages can run (see fill_variant_instances_from_ttl_sosa.py and
fill_phenotype_instances_from_ttl.py).

All triples come from template.render() (template_filler.Template reading
the template's own nt:hasStatement tree) -- this script's only job is
extraction from the .ttl and supplying the placeholder values dict. The
one fixed, non-placeholder statement in the template (dct:isPartOf
<https://w3id.org/spaces/mvikg/r/kg>) is rendered through automatically by
the filler; nothing in this script needs to know that IRI.

Usage:
    python3 fill_sample_instances_from_ttl.py <path-to-batch.ttl> [out_dir]

out_dir defaults to ../sample-instances (relative to this script).

Known gap carried over from the variant filler: mvikg:has_biome is left
unfilled. In the .ttl it's a free-text literal on the SAMPLE node, but the
template models biome as an external-URI object property on the taxon
(GOLD-via-OLS4) -- a data-shape mismatch, not a lookup-source gap.
"""
import datetime
import re
import sys
from pathlib import Path

import rdflib
from rdflib import Namespace, RDF, RDFS

sys.path.insert(0, str(Path(__file__).parent))
from template_filler import Template

TEMPLATE_PATH = Path(__file__).parent.parent / "mvikg-sample-taxon-template-sosa.trig"
TEMPLATE_URI = "https://w3id.org/np/RA8sjjlcxhaaPhXbINiQybCYMpBibyGxD-6amKCtg-kuI/templateVersion"

SOSA = Namespace("http://www.w3.org/ns/sosa/")
BIOLINK = Namespace("https://w3id.org/biolink/vocab/")
DCTERMS = Namespace("http://purl.org/dc/terms/")
DCMITYPE = Namespace("http://purl.org/dc/dcmitype/")

WRAPPER = """@prefix this: <http://purl.org/nanopub/temp/{slug}/> .
@prefix sub: <http://purl.org/nanopub/temp/{slug}/> .
@prefix np: <http://www.nanopub.org/nschema#> .
@prefix npx: <http://purl.org/nanopub/x/> .
@prefix nt: <https://w3id.org/np/o/ntemplate/> .
@prefix dct: <http://purl.org/dc/terms/> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix prov: <http://www.w3.org/ns/prov#> .
@prefix orcid: <https://orcid.org/> .
@prefix mvikg: <http://example.org/mvikg/> .
@prefix biolink: <https://w3id.org/biolink/vocab/> .
@prefix sosa: <http://www.w3.org/ns/sosa/> .
@prefix dcmitype: <http://purl.org/dc/dcmitype/> .

sub:Head {{
  this: a np:Nanopublication ;
    np:hasAssertion sub:assertion ;
    np:hasProvenance sub:provenance ;
    np:hasPublicationInfo sub:pubinfo .
}}

sub:assertion {{
{assertion_body}
}}

sub:provenance {{
  sub:assertion prov:wasDerivedFrom <{source_node}> .
}}

sub:pubinfo {{
  this: dct:created "{timestamp}"^^xsd:dateTime ;
    rdfs:label "{label}" ;
    dct:creator orcid:0000-0000-0000-0000 ;
    dct:license <https://creativecommons.org/licenses/by/4.0/> ;
    npx:hasNanopubType npx:ExampleNanopub ;
    npx:introduces sub:sample ;
    nt:wasCreatedFromTemplate <{template_uri}> ;
    nt:wasCreatedFromProvenanceTemplate <https://w3id.org/np/RA-yPZEYODCS39dWOWm7NA_ClOGFHzPi8iYhLzoZf19GI> ;
    nt:wasCreatedFromPubinfoTemplate <https://w3id.org/np/RA4o9JqSxNO2Z47itbAcxvpVfdR97t_7usxmdR90URXQs> .
}}
"""


def slugify(s):
    return re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-")


def extract_records(ttl_path):
    g = rdflib.Graph()
    g.parse(ttl_path, format="turtle")

    records, skipped = [], []

    for sample_node in g.subjects(RDF.type, SOSA.Sample):
        organism = g.value(sample_node, SOSA.isSampleOf)
        taxon = g.value(organism, BIOLINK.in_taxon) if organism is not None else None
        if taxon is None:
            skipped.append((str(sample_node), "no taxon resolvable via sosa:isSampleOf -> biolink:in_taxon"))
            continue

        project_node = g.value(sample_node, DCTERMS.isPartOf)
        project_uri = g.value(project_node, DCTERMS.isReferencedBy) if project_node is not None else None

        sample_label = g.value(sample_node, RDFS.label)

        records.append({
            "sample_node": str(sample_node),
            "label": str(sample_label) if sample_label is not None else str(sample_node).rsplit("/", 1)[-1],
            "values": {
                "taxon": str(taxon),
                "project": str(project_uri) if project_uri is not None else None,
                "biome": None,
            },
        })

    return records, skipped


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <path-to-batch.ttl> [out_dir]", file=sys.stderr)
        sys.exit(1)

    ttl_path = Path(sys.argv[1])
    out_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(__file__).parent.parent / "sample-instances"
    out_dir.mkdir(parents=True, exist_ok=True)

    records, skipped = extract_records(ttl_path)

    print(f"{len(records)} fillable sample instances, {len(skipped)} skipped\n")
    for node, reason in skipped:
        print(f"  SKIP {node}: {reason}")
    print()

    template = Template(str(TEMPLATE_PATH))
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for i, record in enumerate(records):
        slug = f"sample-{i:02d}-{slugify(record['label'])}"
        assertion_body = "\n".join("  " + line for line in template.render(record["values"]))
        content = WRAPPER.format(
            slug=slug,
            assertion_body=assertion_body,
            source_node=record["sample_node"],
            timestamp=timestamp,
            label=record["label"],
            template_uri=TEMPLATE_URI,
        )
        out_path = out_dir / f"{slug}.trig"
        out_path.write_text(content)
        print(f"wrote {out_path}")

    print(f"\n{len(records)} instance files written to {out_dir}")


if __name__ == "__main__":
    main()
