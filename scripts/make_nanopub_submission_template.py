"""Generate the blank researcher submission xlsx template.

Column set matches nanopub_submission_template_schema.md at the repo root.
Run: pipenv run python3 scripts/make_nanopub_submission_template.py
"""
import openpyxl

OUT_PATH = "templates/mvikg_submission_template.xlsx"

SHEETS = {
    "Strains": [
        "doc_id", "strain_name", "taxon_name", "taxon_id", "ncbi_taxon_id",
        "genome_accession", "Project ID", "PMC ID", "Accession", "biome",
        "evidence",
    ],
    "Genes": [
        "doc_id", "organism_context", "gene", "ncbi_gene_id",
        "uniprot_accession", "evidence",
    ],
    "Variants": [
        "doc_id", "organism_context", "variant_gene", "variant_id",
        "location_start", "location_end", "ref", "alt", "length", "effect",
        "hgvs_notation", "variant_type", "evidence",
    ],
    "Phenotypes": [
        "doc_id", "variant_id", "phenotype_description", "ontology_term",
        "phenotype_objective", "type_of_experiment", "context_sentence",
        "comparison_to",
    ],
}


def main():
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for sheet_name, headers in SHEETS.items():
        ws = wb.create_sheet(sheet_name)
        ws.append(headers)
        for col_idx, header in enumerate(headers, start=1):
            ws.column_dimensions[ws.cell(row=1, column=col_idx).column_letter].width = max(len(header) + 2, 12)
    wb.save(OUT_PATH)
    print(f"Wrote {OUT_PATH}")


if __name__ == "__main__":
    main()
