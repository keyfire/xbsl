"""A short project type may resolve to multiple visible package namespaces.

Only written type positions in code and YAML are considered. Qualified names choose
an owner explicitly; values, imports alone and unresolved external libraries are not
guessed. Root and package declarations in the same subsystem have equal priority.
"""
from pathlib import Path
import re
from xbsl import dataset, i18n, parser as P
from xbsl.lexer import linemap, tokenize
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import rule
from xbsl.rules import yaml_imports as Y

MESSAGES = {
    "ambiguous-type.title": {
        "ru": "Неоднозначное короткое имя типа",
        "en": "Ambiguous short type name",
    },
    "ambiguous-type.found": {
        "ru": "Тип '{name}' доступен из нескольких пространств имён: {namespaces}. Укажите пространство имён явно.",
        "en": "Type '{name}' is available from multiple namespaces: {namespaces}. Qualify the type with its namespace.",
    },
}
i18n.register(MESSAGES)

# Validate YAML type grammar after removing namespace prefixes. The shared parser
# accepts generic/union types but intentionally leaves bindings and arbitrary text alone.
_QUALIFIER = re.compile(r"(?<![\w.])(?:[^\W\d]\w*\s*::\s*)+")

def _type_roots(written):
    try:
        significant = [token for token in tokenize(written)
                       if token.kind not in ("COMMENT", "NEWLINE", "EOF")]
    except dataset.DatasetError:
        return  # YAML-only installations need not have language data.
    for index, token in enumerate(significant):
        if token.kind not in ("IDENT", "KEYWORD"):
            continue
        before = significant[index - 1].value if index else ""
        after = significant[index + 1].value if index + 1 < len(significant) else ""
        if before not in (".", "::") and after != "::":
            yield token.value, token.start

def _mapper(source):
    fact = (Y._yaml_import_mapper(source) if source.kind == "yaml"
            else Y._missing_import_mapper(source))
    if fact is None or fact["k"] not in ("el", "mod"):
        return fact
    # Missing-import deliberately removes stdlib names. Ambiguity cannot: the
    # project's own namespaces take priority over a platform namesake. Likewise a
    # qualified member of a union must not erase its unqualified sibling.
    candidates = []
    if source.kind == "yaml":
        data, error = Y._parsed(source)
        if error is not None:
            return fact
        for key in Y._REFERENCE_KEYS:
            for value in dict.fromkeys(Y._type_values(data, key)):
                if not Y._parse_type_string(_QUALIFIER.sub("", value)):
                    continue
                positions = Y._value_positions(source, value, key) or [(1, 1)]
                for name, _offset in _type_roots(value):
                    for line, col in positions:
                        candidates.append((name, name, line, col))
    else:
        module, errors = P.parse(source)
        if errors:
            return fact
        lines = linemap(source)
        for node in Y._nodes(module):
            if isinstance(node, P.TypeRef):
                written, start = node.text, node.start
            elif isinstance(node, P.Literal) and node.kind == "TYPE":
                raw = source.text[node.start:node.end]
                begin, end = raw.find("<") + 1, raw.rfind(">")
                if not begin or end < begin:
                    continue
                written, start = raw[begin:end], node.start + begin
            else:
                continue
            for name, offset in _type_roots(written):
                line, col = lines.linecol(start + offset)
                candidates.append((name, name, line, col))
    return {**fact, "cands": candidates}

def _findings(facts, kind, rule_id):
    layout = Y._layout_from(facts)
    if not layout.known:
        return
    elements = {}
    paired_types = {}
    for fact in facts.values():
        if fact["k"] == "mod":
            paired_types.setdefault(fact["stem"], set()).update(fact.get("local_types", []))
        if fact["k"] != "el" or not fact.get("name"):
            continue
        place = layout.place(Path(fact["path"]))
        if place:
            elements.setdefault((place.project_dir, fact["name"]), {})[place.key] = fact["vis"]
    for rel, fact in facts.items():
        if fact["k"] != kind:
            continue
        place = layout.place(Path(fact["path"]))
        if place is None:
            continue
        imports = {layout.local_name(name, place.project_dir) for name in fact["imports"]}
        local = paired_types.get(fact["stem"], ())
        reported = set()
        for name, written, line, col in fact.get("cands", []):
            if "::" in written or name in local:
                continue
            candidates = elements.get((place.project_dir, name), {})
            own = [key for key in candidates if Y.subsystem_of_key(key) == place.subsystem]
            visible = sorted(own or [key for key, vis in candidates.items()
                                     if key in imports and vis in Y._public_scopes()])
            if len(visible) < 2 or (name, line, col) in reported:
                continue
            reported.add((name, line, col))
            yield Diagnostic(rel, line, col, rule_id, Severity.ERROR,
                             i18n.t("ambiguous-type.found", name=written,
                                    namespaces=", ".join(visible)),
                             data={"namespaces": visible, "name": name})

@rule("code/ambiguous-type", "ambiguous-type.title", "D", severity=Severity.ERROR,
      scope="project", mapper=_mapper)
def ambiguous_code_type(facts):
    yield from _findings(facts, "mod", "code/ambiguous-type")

@rule("yaml/ambiguous-type", "ambiguous-type.title", "D", severity=Severity.ERROR,
      scope="project", mapper=_mapper)
def ambiguous_yaml_type(facts):
    yield from _findings(facts, "el", "yaml/ambiguous-type")
