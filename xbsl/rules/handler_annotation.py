"""Tier D: the handler annotation on a method the paired yaml binds.

`@Обработчик` marks an OVERRIDE: a handler the base type of the module declares and the
platform calls by its name - the after-create handler of a form, the before-write handler of
an object module, the handler of a scheduled job. The documentation of the annotation says
it is put on the overridable handler methods, and the compiler holds to that: a method that
overrides nothing is refused at the line of the annotation with "A handler associated with
method X is not found". A probe on a server (2026-09, both compatibility modes) gave that
refusal for a command handler, a component event handler and an HTTP route handler named in
the yaml, and for a method nobody binds; the form's own after-create handler under the same
annotation compiled. Without the annotation the bound methods compiled as well - the yaml
binds them, nothing else is needed.

The rule reports the case the sources prove: a method under the annotation whose name the
paired yaml binds - as the value of an event of a component (the event names come from the
interface schema, in both spellings) or of a handler key (a command, a route). A bound method
is a handler of the yaml, not an override. A method nobody binds is refused too, but telling
it from an override takes the complete list of the overridable handlers of every kind of
module, and the data does not carry one: the list kept for code/unused-method misses five
names the corpora override (the handler of a scheduled job, two handlers of an object module,
two of a self-registration parameter) and knows no English spelling at all. A rule built on
it would call legal overrides errors, so that half is not judged.

A bound name that is also a known overridable handler is left alone: whether a yaml may bind
the base handler by its own name is not proven either way.

The fix removes the annotation - with its line when nothing else stands there.
"""

from __future__ import annotations

from collections.abc import Iterable
from functools import lru_cache

from xbsl import dataset, i18n, terms
from xbsl import parser as P
from xbsl.diagnostics import Diagnostic, Severity, TextEdit
from xbsl.engine import SourceFile, rule
from xbsl.lexer import linemap
from xbsl.rules.handlers import _IDENT_RE, _event_names, _handler_pair_stem
from xbsl.rules.unused_methods import _PLATFORM_EVENTS
from xbsl.rules.yaml_schema import _HAVE_YAML, _composed, _mapping_nodes

if _HAVE_YAML:
    import yaml

RULE = "code/bound-handler-annotation"

MESSAGES = {
    f"{RULE}.title": {
        "ru": "@Обработчик у метода, который привязывает yaml",
        "en": "@Handler on a method the yaml binds",
    },
    f"{RULE}.found": {
        "ru": "Метод '{name}' – обработчик '{key}' из парного yaml (строка {line}), а стоит "
              "под аннотацией @{annotation}. Она нужна только переопределяемым обработчикам "
              "базового типа модуля, таким как ПослеСоздания или ПослеЗаписи, и сборка "
              "откажет: \"A handler associated with method \"{name}\" is not found\". Снимите "
              "аннотацию: метод и так связан с событием через yaml.",
        "en": "Method '{name}' is the '{key}' handler of the paired yaml (line {line}), yet "
              "it carries @{annotation}. The annotation belongs only to the overridable "
              "handlers of the module's base type, such as {n[ПослеСоздания]} or "
              "{n[ПослеЗаписи]}, and the build refuses it: \"A handler associated with method "
              "\"{name}\" is not found\". Remove the annotation: the yaml binds the method "
              "to its event already.",
    },
}
i18n.register(MESSAGES)

#: The annotation, the catalog name.
_ANNOTATION = "Обработчик"

#: The key that names the method of a command or of a route, besides the component events.
_HANDLER_KEY = "Обработчик"


@lru_cache(maxsize=1)
def _annotations() -> frozenset[str]:
    """Both spellings of the annotation."""
    return frozenset(terms.key_forms(_ANNOTATION))


@lru_cache(maxsize=1)
def _binding_keys() -> frozenset[str]:
    """The yaml keys whose value is a method of the paired module: the events, the handler."""
    return frozenset({*_event_names(), *terms.key_forms(_HANDLER_KEY)})


@lru_cache(maxsize=1)
def _overridable() -> frozenset[str]:
    """Names some base type overrides - both spellings; a bound one of them is not judged."""
    names: set[str] = set()
    for name in _PLATFORM_EVENTS:
        names.add(name)
        english = terms.common_english(name)
        if english:
            names.add(english)
    return frozenset(names)


def _reset() -> None:
    _annotations.cache_clear()
    _binding_keys.cache_clear()
    _overridable.cache_clear()


dataset.register_reset(_reset)


def _removal(text: str, start: int, end: int) -> tuple[int, int]:
    """The span that takes the annotation out: its whole line when it stands alone there,
    else the annotation with the blanks after it (or before it, at the end of a line)."""
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", end)
    line_end = len(text) if line_end < 0 else line_end
    if not text[line_start:start].strip() and not text[end:line_end].strip():
        return line_start, min(line_end + 1, len(text))
    after = end
    while after < line_end and text[after] in " \t":
        after += 1
    if after < line_end:
        return start, after
    before = start
    while before > line_start and text[before - 1] in " \t":
        before -= 1
    return before, end


def _module_fact(source: SourceFile) -> dict | None:
    if not any("@" + name in source.text for name in _annotations()):
        return None
    module, errors = P.parse(source)
    if errors:
        return None  # a broken module is code/parse-error territory
    lines = linemap(source)
    annotated = []
    for member in module.members:
        if not isinstance(member, P.Method):
            continue
        for annotation in member.annotations:
            if annotation.name in _annotations():
                line, col = lines.linecol(annotation.start)
                start, end = _removal(source.text, annotation.start, annotation.end)
                annotated.append({
                    "name": member.name, "annotation": annotation.name,
                    "line": line, "col": col, "start": start, "end": end,
                })
                break
    if not annotated:
        return None
    return {"k": "x", "stem": _handler_pair_stem(source.rel), "annotated": annotated}


def _yaml_fact(source: SourceFile) -> dict | None:
    if not _HAVE_YAML or not any(key in source.text for key in _binding_keys()):
        return None
    root = _composed(source)
    if root is None:
        return None
    bound: dict[str, list] = {}
    for mapping in _mapping_nodes(root):
        for key, value in mapping.value:
            if not isinstance(key, yaml.ScalarNode) or key.value not in _binding_keys():
                continue
            if not isinstance(value, yaml.ScalarNode) or not isinstance(value.value, str):
                continue
            name = value.value.strip()
            if _IDENT_RE.match(name) and name not in bound:
                bound[name] = [key.value, value.start_mark.line + 1]
    if not bound:
        return None
    return {"k": "y", "stem": _handler_pair_stem(source.rel), "bound": bound}


def _mapper(source: SourceFile) -> dict | None:
    if source.kind == "xbsl":
        return _module_fact(source)
    if source.kind == "yaml":
        return _yaml_fact(source)
    return None


@rule(
    RULE, f"{RULE}.title", "D",
    scope="project", severity=Severity.ERROR, mapper=_mapper,
)
def bound_handler_annotation(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    bound_by_stem = {fact["stem"]: fact["bound"] for fact in facts.values() if fact["k"] == "y"}
    for rel, fact in facts.items():
        if fact["k"] != "x":
            continue
        bound = bound_by_stem.get(fact["stem"])
        if not bound:
            continue
        for method in fact["annotated"]:
            name = method["name"]
            if name not in bound or name in _overridable():
                continue
            key, line = bound[name]
            yield Diagnostic(
                rel, method["line"], method["col"], RULE, Severity.ERROR,
                i18n.t(f"{RULE}.found", name=name, key=key, line=line,
                       annotation=method["annotation"]),
                fix=TextEdit(method["start"], method["end"], ""),
            )
