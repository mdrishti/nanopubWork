from rdflib import Namespace

# ── Namespaces ────────────────────────────────────────────────────────────────
MVIKGBOX    = Namespace("https://w3id.org/mvikg/abox#")
MVIKG       = Namespace("https://w3id.org/mvikg#")
SOSA        = Namespace("http://www.w3.org/ns/sosa/")
DCTERMS     = Namespace("http://purl.org/dc/terms/")
DCMITYPE    = Namespace("http://purl.org/dc/dcmitype/")
BIOLINK     = Namespace("https://w3id.org/biolink/vocab/")
SO          = Namespace("http://purl.obolibrary.org/obo/SO_")
SO_SEQUENCE_ALTERATION = SO["0001059"]   # generic fallback for unmapped variant types

# Scoped to the two known SO synonym-lookup gaps found in the free-text
# spreadsheet inputs (SO renamed indel -> delins in 2019; "wildtype" is just a
# normalization miss) — not a general synonym-table rebuild.
SO_NAME_SYNONYM_OVERRIDES = {
    "wildtype":   "0000817",  # SO:0000817 wild_type
    "wild type":  "0000817",
    "indel":      "1000032",  # SO:1000032 delins
}
OBO         = Namespace("http://purl.obolibrary.org/obo/")
NCBIPROJECT = Namespace("https://www.ncbi.nlm.nih.gov/bioproject/?term=")
PMC         = Namespace("https://www.ncbi.nlm.nih.gov/pmc/articles/")
