# Nanopub submission template — schema spec

Companion to `NANOPUB_INGESTION_PLAN.md`. Defines the columns of the
researcher-facing submission template. Reuses the existing four-tab shape
(`Strains`, `Genes`, `Variants`, `Phenotypes`) already parsed by
`_process_xlsx` in `src/kgBuilderClaudeSkills.py`, so a submitted file can be
routed through the same builder code with no new parsing logic for the
columns that already exist. New columns are additive and optional only —
existing behavior for files that omit them is unchanged.

Legend: **[existing]** = column already handled by `_process_xlsx`.
**[new]** = added for this pipeline. All **[new]** columns are optional.

## Strains

| Column | Status | Notes |
|---|---|---|
| `doc_id` | [existing] | Join key across all tabs. For direct submissions (no paper), submitter can leave blank or use a project code; pipeline mints one if absent, same as today. |
| `strain_name` | [existing] | |
| `taxon_name` | [existing] | |
| `taxon_id` | [existing] | Trusted only if purely numeric (existing rule unchanged). |
| `ncbi_taxon_id` | [new] | Explicit alias for `taxon_id` on the submission form, to make clear to a non-paper-curator submitter that this means an NCBI Taxonomy ID specifically. If filled, validated against NCBI (existence + name match) rather than trusted blindly — this is the one behavior difference from `taxon_id`'s current "trust if numeric" rule. |
| `genome_accession` | [new] | GenBank/RefSeq assembly accession (e.g. `GCA_000005845.2`). Maps to `dcterms:identifier`, same target predicate as existing `Accession` column. Validated against NCBI if present. |
| `Project ID` | [existing] | Optional. |
| `PMC ID` | [existing] | Optional; blank is expected/normal for direct submissions with no associated paper. |
| `Accession` | [existing] | Optional ("future schema" column, already present). |
| `biome` | [existing] | Free text or GOLD/JGI URI. |
| `evidence` | [existing] | Reused as the review-flag mechanism (see below), not a new column. |

## Genes

| Column | Status | Notes |
|---|---|---|
| `doc_id` | [existing] | Join key. |
| `organism_context` | [existing] | Join key; must match a `strain_name`/`taxon_name` in Strains tab for this `doc_id`. |
| `gene` | [existing] | Required (row skipped if blank — existing rule). |
| `ncbi_gene_id` | [new] | Validated against NCBI Gene if present. |
| `uniprot_accession` | [new] | Validated against UniProt if present. |
| `evidence` | [existing] | |

## Variants

| Column | Status | Notes |
|---|---|---|
| `doc_id`, `organism_context`, `variant_gene` | [existing] | Join keys. |
| `variant_id` | [existing] | Optional, auto-generated if absent. |
| `location_start`, `location_end`/`location_stop`, `ref`, `alt`, `length`, `effect` | [existing] | As today; comma-delimited multi-value lists still supported via `expand_variant_row_lists`. |
| `hgvs_notation` | [new] | If supplied, treated as the authoritative variant description; pipeline can cross-check against the raw start/stop/ref/alt columns if both are present and flag a mismatch. |
| `variant_type` / `SequenceVariantTypeName` | [existing] | |
| `evidence` | [existing] | |

## Phenotypes

| Column | Status | Notes |
|---|---|---|
| `doc_id`, `variant_id` | [existing] | Join keys. |
| `phenotype_description` | [existing] | Free text. |
| `ontology_term` | [new] | Optional ontology ID (e.g. GO/ChEBI/ATC) for the phenotype/compound, if the submitter knows one. Free text in `phenotype_description` remains the fallback, same policy as biome text today — no guessed ontology matches. |
| `phenotype_objective`, `type_of_experiment`, `context_sentence`, `comparison_to` | [existing] | |

## Review-flag mechanism

No new "flag" column is introduced. The existing `evidence` column (present
in every tab, already used for the `ECO:0000035`-style unresolved-entity
pattern) is reused to carry review status:

- ID field supplied and validated -> no flag, `evidence` untouched.
- ID field supplied but fails validation -> flagged, worse than blank (a
  wrong ID is treated as a stronger red flag than a missing one).
- ID field blank -> falls back to existing name-based resolution; flagged
  only if that resolution also fails (same as current unresolved-entity
  behavior).

This keeps the review queue derivable from data already flowing through the
existing evidence/placeholder machinery, rather than adding parallel
bookkeeping.
