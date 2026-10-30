# CSVW mapping for researcher submissions

These four `*-metadata.json`
files are [CSVW](https://csvw.org/) table-schema descriptions that map each
tab of the submission template (exported as CSV: `Strains.csv`, `Genes.csv`,
`Variants.csv`, `Phenotypes.csv`) to RDF triples.


For now, the following is covered:
- Column -> predicate mapping (`propertyUrl`)
- Column value -> URI construction for identifier columns (`valueUrl`,
  e.g. `ncbitaxon:{ncbi_taxon_id}`, `uniprotkb:{uniprot_accession}`)
- Record-scoped subject minting (`aboutUrl`), matching the existing
  `GENE-<name>-inRec<doc_id>-<row>` style pattern
- Declaring the cross-tab joins as `foreignKeys` (doc_id/organism_context,
  doc_id/gene, doc_id/variant_id chains)



CSVW's direct mapping is per-row, per-table. Still requires a small Python
step (reusing `src/common/utils_ncbi.py`-style helpers).

- CSVW will emit `ncbitaxon:garbage` if a submitter mistypes an ID. Validation
  against NCBI/UniProt must happen first; only fields that already passed
  validation should be present when CSVW runs.
- evidence/ECO:0000305 vs ECO:0000035 bnode pattern - deciding whether
  a field counts as "resolved with evidence" vs "unresolved, flag for
  review" is computed upstream and can be written into the `evidence` column as a
  pre-formatted string, or handled as a separate post-processing pass.
- hgvs_notation vs genomic coordinates mismatch check is not implemented
- TODO next - gene-scoped (not variant-scoped) phenotype attachment - the existing
  builder attaches phenotypes to the gene-level blank node reached via the
  variant, not directly to the variant node; the phenotype mapping here
  mints its own node and relies on the `foreignKeys` join for traceability,
  but wiring the actual `biolink:has_phenotype` edge from the correct gene
  node is left to the post-processing step until this is validated against
  real data.
 - a `scripts/render_submission_rdf.py` that runs ID validation first, writes the
four CSVs, then invokes a CSVW-to-RDF processor (or a minimal local
implementation of the subset of CSVW used here) against these metadata
files to produce the assertion graph for a nanopub.
