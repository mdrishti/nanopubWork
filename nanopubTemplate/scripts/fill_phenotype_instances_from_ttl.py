#!/usr/bin/env python3
"""
Fills "Declaring an MVIKG phenotype observation" (nanopubTemplate/
mvikg-phenotype-template-sosa.trig) from a builder .ttl. Third stage of
the sample -> variant -> phenotype pipeline: the template's sub:sample and
sub:variant placeholders are nt:ExternalUriPlaceholders, so both have to
be filled with *published* (signed) trusty IRIs -- run
fill_sample_instances_from_ttl.py and fill_variant_instances_from_ttl_sosa.py
(and sign their output) first.

All triples come from template.render() (template_filler.Template reading
the template's own nt:hasStatement tree) -- this script's only job is
extraction and supplying the placeholder values dict. The fixed,
non-placeholder statement in the template (dct:isPartOf
<https://w3id.org/spaces/mvikg/r/kg>) is rendered through automatically by
the filler; nothing here needs to know that IRI.

Usage:
    python3 fill_phenotype_instances_from_ttl.py <path-to-batch.ttl> [out_dir] [sample_map.json] [variant_map.json]

out_dir defaults to ../phenotype-instances (relative to this script).
sample_map.json defaults to ../sample-instances-signed/_sample_map.json.
variant_map.json defaults to ../variant-instances-sosa-signed/_variant_map.json.

Pairing logic (phenotype -> variant link, the template's one optional
field):
- Phenotype is asserted gene-scoped in the .ttl, never on a variant node
  directly (a known gap documented in csvw/README.md) -- so "the
  phenotype for variant i" is inferred, not read off an edge.
- If the gene has exactly one variant, every phenotype bnode for that gene
  links to it (unambiguous one-to-many).
- If the gene has more than one variant, phenotypes link to a specific
  variant only when the phenotype-bnode count equals the variant count --
  paired positionally, both lists taken off the same gene node in .ttl
  declaration order (verified by eye on ahpC: VAR_001 "T77I" pairs with
  the phenotype bnode whose evidence text says "Thr77 substituted by
  Ile"). A count mismatch with >1 variant is genuinely ambiguous, so the
  variant link is left unfilled for those phenotypes (the sample link
  alone is still enough to publish them -- mvikg:isAssociatedWithVariant
  is optional).
- A phenotype whose gene's sample has no signed instance is skipped
  outright (sosa:isResultOf sample is required, unlike the variant link).
"""
import datetime
import json
import re
import sys
from pathlib import Path

import rdflib
from rdflib import Namespace, RDF, RDFS

sys.path.insert(0, str(Path(__file__).parent))
from template_filler import Template

TEMPLATE_PATH = Path(__file__).parent.parent / "mvikg-phenotype-template-sosa.trig"
TEMPLATE_URI = "https://w3id.org/np/RAR0BDV3XFKzSqviAGWtP_qnWTlYxMbCDQ0YYGbsbfdt4/templateVersion"

SOSA = Namespace("http://www.w3.org/ns/sosa/")
BIOLINK = Namespace("https://w3id.org/biolink/vocab/")
MVIKG = Namespace("https://w3id.org/mvikg#")

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
  sub:assertion prov:wasDerivedFrom <{gene_node}> .
}}

sub:pubinfo {{
  this: dct:created "{timestamp}"^^xsd:dateTime ;
    rdfs:label "{label}" ;
    dct:creator orcid:0000-0000-0000-0000 ;
    dct:license <https://creativecommons.org/licenses/by/4.0/> ;
    npx:hasNanopubType npx:ExampleNanopub ;
    npx:introduces sub:phenotype ;
    nt:wasCreatedFromTemplate <{template_uri}> ;
    nt:wasCreatedFromProvenanceTemplate <https://w3id.org/np/RA-yPZEYODCS39dWOWm7NA_ClOGFHzPi8iYhLzoZf19GI> ;
    nt:wasCreatedFromPubinfoTemplate <https://w3id.org/np/RA4o9JqSxNO2Z47itbAcxvpVfdR97t_7usxmdR90URXQs> .
}}
"""


def slugify(s):
    return re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-")


def extract_records(ttl_path, sample_map, variant_map):
    g = rdflib.Graph()
    g.parse(ttl_path, format="turtle")

    records, skipped = [], []

    for gene_node in g.subjects(RDF.type, BIOLINK.GenomicEntity):
        phenotype_nodes = list(g.objects(gene_node, BIOLINK.has_phenotype))
        if not phenotype_nodes:
            continue

        gene_label = g.value(gene_node, RDFS.label)

        sample_node = g.value(gene_node, SOSA.isFeatureOfInterestOf)
        sample_iri = sample_map.get(str(sample_node)) if sample_node is not None else None
        if sample_iri is None:
            skipped.append((str(gene_label), str(gene_node),
                             f"no signed sample instance for {sample_node} (run fill_sample_instances_from_ttl.py first)"))
            continue

        variants = list(g.objects(gene_node, BIOLINK.has_sequence_variant))
        variant_by_phenotype = {}
        if len(variants) == 1:
            variant_iri = variant_map.get(str(variants[0]))
            for p in phenotype_nodes:
                variant_by_phenotype[p] = variant_iri
        elif len(variants) == len(phenotype_nodes) and variants:
            for v, p in zip(variants, phenotype_nodes):
                variant_by_phenotype[p] = variant_map.get(str(v))
        # else: >1 variant, count mismatch -- no variant link, sample link still fires

        for idx, phenotype_node in enumerate(phenotype_nodes):
            description = g.value(phenotype_node, RDFS.label)
            if description is None:
                skipped.append((str(gene_label), str(phenotype_node), "no rdfs:label (required phenotypeDescription)"))
                continue
            compared_to = g.value(phenotype_node, MVIKG.comparedTo)
            variant_iri = variant_by_phenotype.get(phenotype_node)

            records.append({
                "gene_label": str(gene_label),
                "gene_node": str(gene_node),
                "idx": idx,
                "values": {
                    "sample": sample_iri,
                    "variant": variant_iri,
                    "phenotypeDescription": str(description),
                    "comparedTo": str(compared_to) if compared_to is not None else None,
                },
            })

    return records, skipped


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <path-to-batch.ttl> [out_dir] [sample_map.json] [variant_map.json]",
              file=sys.stderr)
        sys.exit(1)

    ttl_path = Path(sys.argv[1])
    out_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(__file__).parent.parent / "phenotype-instances"
    sample_map_path = Path(sys.argv[3]) if len(sys.argv) > 3 else \
        Path(__file__).parent.parent / "sample-instances-signed" / "_sample_map.json"
    variant_map_path = Path(sys.argv[4]) if len(sys.argv) > 4 else \
        Path(__file__).parent.parent / "variant-instances-sosa-signed" / "_variant_map.json"
    out_dir.mkdir(parents=True, exist_ok=True)

    sample_map = json.loads(sample_map_path.read_text())
    variant_map = json.loads(variant_map_path.read_text())

    records, skipped = extract_records(ttl_path, sample_map, variant_map)

    print(f"{len(records)} fillable phenotype observations, {len(skipped)} skipped\n")
    for lbl, node, reason in skipped:
        print(f"  SKIP {lbl} ({node}): {reason}")
    print()

    template = Template(str(TEMPLATE_PATH))
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for i, record in enumerate(records):
        slug = f"phenotype-{i:02d}-{slugify(record['gene_label'])}"
        assertion_body = "\n".join("  " + line for line in template.render(record["values"]))
        content = WRAPPER.format(
            slug=slug,
            assertion_body=assertion_body,
            gene_node=record["gene_node"],
            timestamp=timestamp,
            label=f"phenotype: {record['values']['phenotypeDescription'][:60]}",
            template_uri=TEMPLATE_URI,
        )
        out_path = out_dir / f"{slug}.trig"
        out_path.write_text(content)
        print(f"wrote {out_path}")

    print(f"\n{len(records)} instance files written to {out_dir}")


if __name__ == "__main__":
    main()
