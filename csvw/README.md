# CSVW mapping for researcher submissions

Companion to `../NANOPUB_INGESTION_PLAN.md` and
`../nanopub_submission_template_schema.md`. These four `*-metadata.json`
files are [CSVW](https://csvw.org/) table-schema descriptions that map each
tab of the submission template (exported as CSV: `Strains.csv`, `Genes.csv`,
`Variants.csv`, `Phenotypes.csv`) to RDF, reusing the exact predicates and
minted-URI naming pattern already used by `_process_xlsx` in
`src/kgBuilderClaudeSkills.py` (`mvikgbox:` record-scoped resources,
`dcterms:identifier` one hop to canonical/external identity, `biolink:*`
relation predicates). Namespace prefixes match `src/common/constants.py`.

## What CSVW covers directly

- Column -> predicate mapping (`propertyUrl`)
- Column value -> URI construction for identifier columns (`valueUrl`,
  e.g. `ncbitaxon:{ncbi_taxon_id}`, `uniprotkb:{uniprot_accession}`)
- Record-scoped subject minting (`aboutUrl`), matching the existing
  `GENE-<name>-inRec<doc_id>-<row>` style pattern
- Declaring the cross-tab joins as `foreignKeys` (doc_id/organism_context,
  doc_id/gene, doc_id/variant_id chains)

## What CSVW does *not* cover — needs a thin script on top

CSVW's direct mapping is per-row, per-table; it can't express everything the
existing builder does across rows/tables. These still need a small Python
step (reusing `src/common/utils_ncbi.py`-style helpers), run **before**
CSVW/RDF generation, not instead of it:

- **ID validation.** CSVW will happily emit `ncbitaxon:garbage` if a
  submitter mistypes an ID — it has no live-lookup capability. Validation
  against NCBI/UniProt must happen first; only fields that already passed
  validation should be present when CSVW runs.
- **The evidence/ECO:0000305 vs ECO:0000035 bnode pattern.** Deciding whether
  a field counts as "resolved with evidence" vs "unresolved, flag for
  review" is a business rule, not a column-to-column mapping — this is
  computed upstream and can be written into the `evidence` column as a
  pre-formatted string, or handled as a separate post-processing pass.
- **hgvs_notation vs raw coordinates mismatch check** (noted inline in
  `variants-metadata.json`).
- **Gene-scoped (not variant-scoped) phenotype attachment.** The existing
  builder attaches phenotypes to the gene-level blank node reached via the
  variant, not directly to the variant node; the phenotype mapping here
  mints its own node and relies on the `foreignKeys` join for traceability,
  but wiring the actual `biolink:has_phenotype` edge from the correct gene
  node is left to the post-processing step until this is validated against
  real data.

## Status

Not yet wired into any runnable script. Next step (not started): a small
`scripts/render_submission_rdf.py` that runs ID validation first, writes the
four CSVs, then invokes a CSVW-to-RDF processor (or a minimal local
implementation of the subset of CSVW used here) against these metadata
files to produce the assertion graph for a nanopub.
