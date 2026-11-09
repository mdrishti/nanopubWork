#!/usr/bin/env python3
"""
Fills "Declaring an MVIKG observation" (nanopubTemplate/mvikg-variant-
template-sosa.trig) from a builder .ttl. Second stage of the sample ->
variant -> phenotype pipeline: the template's sub:sample placeholder is an
nt:ExternalUriPlaceholder, so it has to be filled with a *published*
(signed) sample nanopub's trusty IRI -- run
fill_sample_instances_from_ttl.py and sign its output first, then pass the
resulting sample-node -> trusty-IRI map (see build_sample_map() below, or
just point SAMPLE_MAP_PATH at sample-instances-signed/_sample_map.json)
to this script.

All triples come from template.render() (template_filler.Template reading
the template's own nt:hasStatement tree) -- this script's only job is
extraction and supplying the placeholder values dict. The fixed,
non-placeholder statement in the template (dct:isPartOf
<https://w3id.org/spaces/mvikg/r/kg>) is rendered through automatically by
the filler; nothing here needs to know that IRI.

Usage:
    python3 fill_variant_instances_from_ttl_sosa.py <path-to-batch.ttl> [out_dir] [sample_map.json]

out_dir defaults to ../variant-instances-sosa (relative to this script).
sample_map.json defaults to ../sample-instances-signed/_sample_map.json.

Priorities / known traps:
- The .ttl is the source of truth (not re-derived from the submission xlsx).
- Multiplicity: the ttl mints a fresh record-scoped node per row even for
  the same external gene -- so `sub:gene` is filled with the gene's
  *external* identifier (its dcterms:identifier target), never the
  row-scoped node IRI.
- A gene whose dcterms:identifier is still an unresolved mvikg: placeholder
  (not a real external URI) is skipped -- the template's sub:gene
  placeholder is an nt:ExternalUriPlaceholder and can't take a temp/local
  IRI correctly.
- A gene's sample is skipped (and its variants with it) if that sample
  node has no entry in the sample map -- i.e. its sample instance was
  itself skipped or not yet signed. Run fill_sample_instances_from_ttl.py
  first and check its own skip list.
- No phenotype here: that moved to its own template
  (mvikg-phenotype-template-sosa.trig) and its own filler script
  (fill_phenotype_instances_from_ttl.py), so multiple phenotype nanopubs
  can reference the same variant and/or sample.
- Variant name (rdfs:label), SO type (rdf:type other than the fixed
  biolink:SequenceVariant), start/end coordinate (biolink:start_coordinate /
  end_coordinate) and evidence text (biolink:has_evidence -> dcterms:
  description) are read straight off the variant node when present. Only
  the *first* evidence node's description is used if a variant has more
  than one.
- Frequency (mvikg:frequencyValue / mvikg:frequencyUnit) is not present in
  this .ttl batch, so always left unfilled here -- the template's grouped
  statement just doesn't fire.
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

TEMPLATE_PATH = Path(__file__).parent.parent / "mvikg-variant-template-sosa.trig"
TEMPLATE_URI = "https://w3id.org/np/RAnlONjGChImRjDeXxTwrTmndhfv1guES7EnXlp1CaE3g/templateVersion"

SOSA = Namespace("http://www.w3.org/ns/sosa/")
BIOLINK = Namespace("https://w3id.org/biolink/vocab/")
DCTERMS = Namespace("http://purl.org/dc/terms/")
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
  sub:assertion prov:wasDerivedFrom <{variant_node}> .
}}

sub:pubinfo {{
  this: dct:created "{timestamp}"^^xsd:dateTime ;
    rdfs:label "{variant_name}" ;
    dct:creator orcid:0000-0000-0000-0000 ;
    dct:license <https://creativecommons.org/licenses/by/4.0/> ;
    npx:hasNanopubType npx:ExampleNanopub ;
    npx:introduces sub:variant ;
    nt:wasCreatedFromTemplate <{template_uri}> ;
    nt:wasCreatedFromProvenanceTemplate <https://w3id.org/np/RA-yPZEYODCS39dWOWm7NA_ClOGFHzPi8iYhLzoZf19GI> ;
    nt:wasCreatedFromPubinfoTemplate <https://w3id.org/np/RA4o9JqSxNO2Z47itbAcxvpVfdR97t_7usxmdR90URXQs> .
}}
"""


def slugify(s):
    return re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-")


def extract_records(ttl_path, sample_map):
    g = rdflib.Graph()
    g.parse(ttl_path, format="turtle")

    records, skipped = [], []

    for gene_node in g.subjects(RDF.type, BIOLINK.GenomicEntity):
        variants = list(g.objects(gene_node, BIOLINK.has_sequence_variant))
        if not variants:
            continue

        gene_label = g.value(gene_node, RDFS.label)
        gene_id = g.value(gene_node, DCTERMS.identifier)

        if gene_id is None or str(gene_id).startswith("https://w3id.org/mvikg#"):
            skipped.append((str(gene_label), str(gene_node),
                             "unresolved gene identifier (temp mvikg: placeholder, not an external URI)"))
            continue

        sample_node = g.value(gene_node, SOSA.isFeatureOfInterestOf)
        sample_iri = sample_map.get(str(sample_node)) if sample_node is not None else None
        if sample_iri is None:
            skipped.append((str(gene_label), str(gene_node),
                             f"no signed sample instance for {sample_node} (run fill_sample_instances_from_ttl.py first)"))
            continue

        for variant_node in variants:
            variant_name = g.value(variant_node, RDFS.label)
            if variant_name is None:
                m = re.search(r"VAR_\d+", str(variant_node))
                variant_name = m.group(0) if m else None

            so_type = None
            for t in g.objects(variant_node, RDF.type):
                if t != BIOLINK.SequenceVariant:
                    so_type = t
                    break

            start_coordinate = g.value(variant_node, BIOLINK.start_coordinate)
            end_coordinate = g.value(variant_node, BIOLINK.end_coordinate)

            evidence_text = None
            for evidence_node in g.objects(variant_node, BIOLINK.has_evidence):
                desc = g.value(evidence_node, DCTERMS.description)
                if desc is not None:
                    evidence_text = str(desc)
                    break

            records.append({
                "gene_label": str(gene_label),
                "variant_node": str(variant_node),
                "values": {
                    "gene": str(gene_id),
                    "sample": sample_iri,
                    "variantName": str(variant_name) if variant_name is not None else None,
                    "soType": str(so_type) if so_type is not None else None,
                    "effect": str(g.value(variant_node, MVIKG.effect) or "") or None,
                    "length": str(g.value(variant_node, MVIKG.length) or "") or None,
                    "alt": str(g.value(variant_node, MVIKG.alt) or "") or None,
                    "ref": str(g.value(variant_node, MVIKG.ref) or "") or None,
                    "startCoordinate": int(start_coordinate) if start_coordinate is not None else None,
                    "endCoordinate": int(end_coordinate) if end_coordinate is not None else None,
                    "evidenceText": evidence_text,
                    "freqValue": None,
                    "freqUnit": None,
                },
            })

    return records, skipped


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <path-to-batch.ttl> [out_dir] [sample_map.json]", file=sys.stderr)
        sys.exit(1)

    ttl_path = Path(sys.argv[1])
    out_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(__file__).parent.parent / "variant-instances-sosa"
    sample_map_path = Path(sys.argv[3]) if len(sys.argv) > 3 else \
        Path(__file__).parent.parent / "sample-instances-signed" / "_sample_map.json"
    out_dir.mkdir(parents=True, exist_ok=True)

    sample_map = json.loads(sample_map_path.read_text())

    records, skipped = extract_records(ttl_path, sample_map)

    print(f"{len(records)} fillable gene-variant observations, {len(skipped)} skipped\n")
    for lbl, node, reason in skipped:
        print(f"  SKIP {lbl} ({node}): {reason}")
    print()

    template = Template(str(TEMPLATE_PATH))
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for i, record in enumerate(records):
        slug = f"variant-{i:02d}-{slugify(record['gene_label'])}"
        assertion_body = "\n".join("  " + line for line in template.render(record["values"]))
        content = WRAPPER.format(
            slug=slug,
            assertion_body=assertion_body,
            variant_node=record["variant_node"],
            timestamp=timestamp,
            variant_name=record["values"]["variantName"],
            template_uri=TEMPLATE_URI,
        )
        out_path = out_dir / f"{slug}.trig"
        out_path.write_text(content)
        print(f"wrote {out_path}")

    print(f"\n{len(records)} instance files written to {out_dir}")


if __name__ == "__main__":
    main()
