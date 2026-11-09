#!/usr/bin/env python3
"""
Generic filler for the MVIKG gene-variant nanopub templates: reads a
template .trig file's own nt:hasStatement structure and renders filled
triples in exactly the order the template defines, instead of hard-coding
that order a second time in a generator script.

Why this exists: the templates number their statements with zero-padding
(sub:st01, sub:st02, ...) specifically so that sorting hasStatement entries
alphabetically recovers the intended display order (see the templates'
own comments). This filler reads that same order back out and walks it, so
reordering a template is a template-only edit -- there is nothing in a
generator script to keep in sync.

Not a general nanopub-template engine -- handles exactly what the MVIKG
gene-variant templates use: an nt:AssertionTemplate with a flat/grouped
nt:hasStatement tree, nt:OptionalStatement, nt:GroupedStatement (all-or-
nothing), and placeholders typed:
  - nt:LiteralPlaceholder / nt:ExternalUriPlaceholder / nt:AgentPlaceholder
    (value-bearing: the caller supplies a value, or None to skip)
  - nt:EmbeddedResource / nt:LocalResource / nt:IntroducedResource with
    neither of the above (identity-only: minted as a `sub:<name>` node,
    no value needed -- unless it's typed as BOTH an identity kind AND a
    placeholder kind, like the templates' `sub:project`, in which case a
    value is still required).
"""
import rdflib
from rdflib import Namespace, RDF

NT = Namespace("https://w3id.org/np/o/ntemplate/")
XSD = Namespace("http://www.w3.org/2001/XMLSchema#")

IDENTITY_TYPES = (NT.EmbeddedResource, NT.LocalResource, NT.IntroducedResource)
VALUE_TYPES = (NT.LiteralPlaceholder, NT.ExternalUriPlaceholder, NT.AgentPlaceholder)

# Explicit prefix map matching what the generator scripts' own TriG header
# declares -- NOT rdflib's auto qname, which prefers its own built-in
# bindings (e.g. "dcterms:") over a file's actual "@prefix dct:", producing
# output whose prefixes don't match the header written around it.
PREFIXES = {
    "http://www.w3.org/1999/02/22-rdf-syntax-ns#": "rdf",
    "http://www.w3.org/2000/01/rdf-schema#": "rdfs",
    "https://w3id.org/biolink/vocab/": "biolink",
    "http://example.org/mvikg/": "mvikg",
    "http://purl.org/dc/terms/": "dct",
    "http://qudt.org/schema/qudt/": "qudt",
    "http://qudt.org/vocab/unit/": "unit",
    "http://www.w3.org/ns/sosa/": "sosa",
    "http://purl.org/dc/dcmitype/": "dcmitype",
}


def _qname(term):
    s = str(term)
    for ns, prefix in PREFIXES.items():
        if s.startswith(ns):
            return f"{prefix}:{s[len(ns):]}"
    return f"<{s}>"


def _local_name(term):
    return str(term).rsplit("/", 1)[-1]


def _escape(text):
    return str(text).replace("\\", "\\\\").replace('"', '\\"')


class Template:
    def __init__(self, path):
        self.g = rdflib.ConjunctiveGraph()
        self.g.parse(path, format="trig")
        self.assertion = next(self.g.subjects(RDF.type, NT.AssertionTemplate))
        self.statements = self._ordered_statements(self.assertion)

    def _descendant_ids(self, node):
        """node plus every nt:hasStatement descendant, recursively."""
        ids = {node}
        for child in self.g.objects(node, NT.hasStatement):
            ids |= self._descendant_ids(child)
        return ids

    def _ordered_statements(self, node):
        objs = sorted(self.g.objects(node, NT.hasStatement), key=_local_name)

        # The template convention lists every statement at the top level
        # *and* inside its owning group's own hasStatement list (so the
        # meta-template sees every placeholder). Without deduping, a
        # group's members would be processed twice: once correctly gated
        # by the group, and once as bare top-level statements with no
        # optional/gating logic of their own -- which made an unfilled
        # grouped placeholder (e.g. frequency's numericValue) look like a
        # missing *required* value instead of "group didn't fire".
        group_ids = {o for o in objs if (o, RDF.type, NT.GroupedStatement) in self.g}
        covered = set()
        for gid in group_ids:
            covered |= self._descendant_ids(gid)
        covered -= group_ids  # keep the group nodes themselves, drop only their members

        out = []
        for o in objs:
            if o in covered:
                continue
            is_optional = (o, RDF.type, NT.OptionalStatement) in self.g
            if o in group_ids:
                out.append({"optional": is_optional, "group": True,
                            "members": self._ordered_statements(o)})
            else:
                out.append({"optional": is_optional, "group": False,
                            "triple": (self.g.value(o, RDF.subject),
                                       self.g.value(o, RDF.predicate),
                                       self.g.value(o, RDF.object))})
        return out

    def kind(self, node):
        types = set(self.g.objects(node, RDF.type))
        has_identity = any(t in types for t in IDENTITY_TYPES)
        has_value = any(t in types for t in VALUE_TYPES)
        if has_value:
            uri_valued = NT.ExternalUriPlaceholder in types or NT.AgentPlaceholder in types
            return ("value", "uri" if uri_valued else "literal")
        if has_identity:
            return ("identity", None)
        return ("fixed", None)

    def datatype(self, node):
        return self.g.value(node, NT.hasDatatype)

    def render_term(self, term, values):
        """Render subject/predicate/object as TriG text, or None if a
        required value-bearing placeholder has no value (caller's gate)."""
        kind, subkind = self.kind(term)
        if kind == "fixed":
            return _qname(term)
        if kind == "identity":
            return f"sub:{_local_name(term)}"
        # value-bearing
        val = values.get(_local_name(term))
        if val is None:
            return None
        if subkind == "uri":
            return f"<{val}>"
        dt = self.datatype(term)
        if dt == XSD.integer or dt == XSD.decimal:
            return str(val)
        return f'"{_escape(val)}"^^xsd:string'

    def _group_can_fire(self, members, values):
        """A group fires iff every value-bearing placeholder referenced by
        its members (recursively) has a non-None value."""
        for m in members:
            if m["group"]:
                if not self._group_can_fire(m["members"], values):
                    return False
                continue
            for term in m["triple"]:
                k, _ = self.kind(term)
                if k == "value" and values.get(_local_name(term)) is None:
                    return False
        return True

    def render(self, values, statements=None, indent="  "):
        """Render the ordered, filled statement list as TriG lines (list of
        strings, each a complete 'subject predicate object .' or similar)."""
        if statements is None:
            statements = self.statements
        lines = []
        for entry in statements:
            if entry["group"]:
                if not self._group_can_fire(entry["members"], values):
                    continue
                lines.extend(self.render(values, entry["members"], indent))
                continue
            subj, pred, obj = entry["triple"]
            obj_text = self.render_term(obj, values)
            if obj_text is None:
                if entry["optional"]:
                    continue
                raise ValueError(f"required value missing for {obj}")
            subj_text = self.render_term(subj, values)
            pred_text = self.render_term(pred, values)
            lines.append(f"{subj_text} {pred_text} {obj_text} .")
        return lines
