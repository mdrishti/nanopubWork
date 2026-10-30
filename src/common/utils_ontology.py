"""
src/common/utils_ontology.py

Shared ontology map loader for the Sequence Ontology (SO) OBO file.
"""

from src.common.utils import print_to_log


def load_so_name_map(obo_path: str) -> dict:
    """
    Parse the SO OBO file and return { 'SO:XXXXXXX' -> term_name }.
    Used to look up SequenceVariantTypeName from the SO id in annotations.
    """
    so_map = {}
    current_id = None
    with open(obo_path, 'r', encoding='utf-8') as fh:
        for line in fh:
            line = line.strip()
            if line.startswith('id: SO:'):
                current_id = line[4:]       # e.g. "SO:0000159"
            elif line.startswith('name: ') and current_id:
                so_map[current_id] = line[6:]   # e.g. "deletion"
                current_id = None
            elif line == '[Term]':
                current_id = None
    print_to_log(f"SO OBO map loaded: {len(so_map)} terms", "kg-log.txt")
    return so_map
