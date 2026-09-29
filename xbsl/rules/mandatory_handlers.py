"""Tier D: a handler the compiler requires that the module of an element does not declare.

Some handlers are not optional: the compiler builds them `required`, and a module without one
is refused with "Mandatory handler X is not defined" - at the first line of the module, or at
the first line of the description when the element has no such module at all. A probe on a
server (2026-09) gave that answer for each source this rule reads.

- The data. The handler providers of the compiler build some handlers `required` wherever
  they declare them, and the extractor keeps the mark on the row (`required`, see
  xbsl/extract/elementhandlers.py): the handler of a command and of a command with a component
  (not of a switchable one), of a scheduled job, the computation of the client work
  parameters, the after-connection handler of a self-registration parameter and the
  permissions handler of an action privilege. A key granted by hand declares no handler in
  the newer modes, so the check of an access key is not required there and not marked at all.
- The creation on basis. `OnCreateOnBasis` of the object module of a catalog, a document, an
  exchange plan and an integrable application is required once for each type the description
  lists under `CreateOnBasis`: a module without the method is refused, and so is one with fewer
  overloads than the list has types. The overloads are counted only while none of them takes
  a union of types - one such method may serve several of them.
- The access settings. The access-control provider builds its handlers with one value for
  `enabled` and `required`: a handler the settings use (modulehandlers.access_slot) is the
  one the module has to declare - `ComputeAccessPermissions` once a privilege computes its
  permissions, the record-level security handlers once one computes them for each object.
  Settings that cannot be read, and the settings of a kind below the mode they came in, require
  nothing.
- The pairs. A handler built with `requiredHandlers` makes the handlers it names required once
  the module declares it: the computation of an external navigation link and the reference by
  one go together (`needs` of the row).

A method of the required name without the `@Handler` annotation gets another answer of the
compiler, "Handler method X is not marked with annotation @Handler", and the finding quotes
that one; the fix adds the annotation. A module with a syntax error is not judged, nor is a
module the run does not include while the disk has it. Without the handler lists of the data
the rule is silent.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import PurePosixPath

from xbsl import i18n, modulehandlers, terms, typeinfer
from xbsl import parser as P
from xbsl.diagnostics import Diagnostic, Severity, TextEdit
from xbsl.engine import SourceFile, rule
from xbsl.layout import PROJECT_FILES
from xbsl.lexer import linemap
from xbsl.rules.component_since import _version
from xbsl.rules.handler_annotation import (
    OVERRIDE_RULE,
    _access_control,
    _annotations,
    _element_fact,
    _language,
    _property_shown,
)
from xbsl.rules.handlers import _handler_pair_stem
from xbsl.rules.yaml_schema import _HAVE_YAML, _parsed, object_kind_fast, value_of

RULE = "code/mandatory-handler-missing"

MESSAGES = {
    f"{RULE}.title": {
        "ru": "Нет обязательного обработчика модуля",
        "en": "A mandatory handler of a module is missing",
    },
    f"{RULE}.missing": {
        "ru": "{where} обязан объявить обработчик {handler}: {reason}. Метода с этим именем "
              "под аннотацией @{annotation} в модуле нет, и сборка откажет: \"Mandatory "
              "handler \"{handler}\" is not defined\".",
        "en": "{where} has to declare the {handler} handler: {reason}. The module has no "
              "method of that name under the @{annotation} annotation, and the build refuses "
              "it: \"Mandatory handler \"{handler}\" is not defined\".",
    },
    f"{RULE}.no-module": {
        "ru": "Модуля {file} нет, а {where} обязан объявить обработчик {handler}: {reason}. "
              "Сборка откажет: \"Mandatory handler \"{handler}\" is not defined\". Добавьте "
              "модуль с методом {handler} под аннотацией @{annotation}.",
        "en": "There is no {file} module, yet {where} has to declare the {handler} handler: "
              "{reason}. The build refuses it: \"Mandatory handler \"{handler}\" is not "
              "defined\". Add the module with a {handler} method under the @{annotation} "
              "annotation.",
    },
    f"{RULE}.overloads": {
        "ru": "{where} обязан объявить обработчик {handler} на каждый тип из {property}: типов "
              "там {listed}, а методов {handler} под аннотацией @{annotation} в модуле "
              "{declared}. Сборка откажет: \"Mandatory handler \"{handler}\" is not defined\".",
        "en": "{where} has to declare a {handler} handler for each type {property} lists: it "
              "lists {listed}, and the module declares {declared} {handler} methods under the "
              "@{annotation} annotation. The build refuses it: \"Mandatory handler "
              "\"{handler}\" is not defined\".",
    },
    f"{RULE}.unmarked": {
        "ru": "Метод '{name}' – обязательный обработчик модуля: {reason}. Аннотации "
              "@{annotation} у него нет, и сборка откажет: \"Handler method \"{name}\" is not "
              "marked with annotation @{annotation}\".",
        "en": "Method '{name}' is a mandatory handler of the module: {reason}. It carries no "
              "@{annotation} annotation, and the build refuses it: \"Handler method \"{name}\" "
              "is not marked with annotation @{annotation}\".",
    },
    f"{RULE}.reason-kind": {
        "ru": "компилятор требует его в каждом таком модуле",
        "en": "the compiler requires it in every such module",
    },
    f"{RULE}.reason-computed": {
        "ru": "настройки доступа вычисляют разрешения (РазрешенияВычисляются или "
              "РазрешенияВычисляютсяДляКаждогоОбъекта)",
        "en": "the access settings compute permissions ({n[РазрешенияВычисляются]} or "
              "{n[РазрешенияВычисляютсяДляКаждогоОбъекта]})",
    },
    f"{RULE}.reason-per-object": {
        "ru": "настройки доступа вычисляют разрешения для каждого объекта "
              "(РазрешенияВычисляютсяДляКаждогоОбъекта)",
        "en": "the access settings compute permissions for each object "
              "({n[РазрешенияВычисляютсяДляКаждогоОбъекта]})",
    },
    f"{RULE}.reason-per-item": {
        "ru": "описание перечисляет типы в {property}, и на каждый нужен свой обработчик",
        "en": "the description lists types under {property}, and each needs a handler of "
              "its own",
    },
    f"{RULE}.reason-needs": {
        "ru": "модуль объявляет {other}, а компилятор требует его пару",
        "en": "the module declares {other}, and the compiler requires its pair",
    },
}
i18n.register(MESSAGES)


def _module_fact(source: SourceFile) -> dict:
    """The methods of a module: name, whether under the annotation, position, and whether the
    first parameter takes a union of types; a module with a syntax error is marked broken."""
    stem = _handler_pair_stem(source.rel)
    module, errors = P.parse(source)
    if errors:
        return {"k": "x", "stem": stem, "broken": True}
    lines = linemap(source)
    methods = []
    for member in module.members:
        if not isinstance(member, P.Method):
            continue
        annotated = any(annotation.name in _annotations() for annotation in member.annotations)
        first = member.params[0].type if member.params else None
        union = first is not None and len(first.names) > 1
        start = member.start
        if member.annotations:
            start = min(start, *(annotation.start for annotation in member.annotations))
        line, col = lines.linecol(start)
        line_start = source.text.rfind("\n", 0, start) + 1
        methods.append([member.name, annotated, line, col, union, line_start,
                        source.text[line_start:start]])
    return {"k": "x", "stem": stem, "methods": methods}


def _element_fact_with_counts(source: SourceFile) -> dict | None:
    """The element fact of code/handler-overrides-nothing, the number of items of each
    collection some handler is declared once per item of, and the module files on disk."""
    fact = _element_fact(source)
    if fact is None:
        return None
    kind = fact["kind"]
    counts: dict[str, int] = {}
    if fact.get("given"):
        data, error = _parsed(source)
        if error is None and isinstance(data, dict):
            for prop in fact["given"]:
                value = value_of(data, prop, kind)
                counts[prop] = len(value) if isinstance(value, (list, dict)) else 1
    fact["counts"] = counts
    fact["file"] = PurePosixPath(source.rel.replace("\\", "/")).name
    # The module files next to the description, whichever spelling of the module word: a module
    # the run does not include is not judged as missing.
    folder = source.path.parent if getattr(source, "path", None) else None
    stem = PurePosixPath(source.rel.replace("\\", "/")).stem
    on_disk = []
    if folder is not None:
        for word in ("", *modulehandlers.module_words()):
            name = f"{stem}.{word}.xbsl" if word else f"{stem}.xbsl"
            if (folder / name).is_file():
                on_disk.append(modulehandlers.module_words().get(word, word) if word else "")
    fact["on_disk"] = sorted(set(on_disk))
    return fact


def _mapper(source: SourceFile) -> dict | None:
    if not modulehandlers.element_available():
        return None
    if source.kind == "xbsl":
        return _module_fact(source)
    if source.kind != "yaml" or not _HAVE_YAML:
        return None
    if PurePosixPath(source.rel.replace("\\", "/")).name in PROJECT_FILES:
        return typeinfer.project_fact(source)  # the mode of the project
    if object_kind_fast(source) is None:
        return None
    return _element_fact_with_counts(source)


@rule(
    RULE, f"{RULE}.title", "D",
    scope="project", severity=Severity.ERROR, mapper=_mapper,
)
def mandatory_handler_missing(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    modules: dict[tuple[str, str], tuple[str, dict]] = {}
    for rel, fact in facts.items():
        if fact.get("k") == "x":
            modules[modulehandlers.element_module(fact["stem"])] = (rel, fact)
    modes = typeinfer.project_modes(facts)
    words = sorted({"", *modulehandlers.element_modules()})
    for rel, element in facts.items():
        if element.get("k") != "e":
            continue
        kind = element["kind"]
        mode, _assumed = modes.get(rel, (None, False))
        access = element.get("access")
        settings = modulehandlers.AccessSettings(*access) if access else None
        since = _version(_access_control(kind).get("since"))
        if since and (mode is None or mode < since):
            settings = None  # below the mode the settings came in the build does not read them
        given = element.get("given")
        for word in words:
            required = modulehandlers.required_rows(
                kind, word, settings, frozenset(given) if given is not None else None, mode,
                controlled="access" in element)
            needs = modulehandlers.needs_of(kind, word)
            if not required and not needs:
                continue
            found = modules.get((element["stem"], word))
            if found is None:
                if word in element["on_disk"] or not required:
                    continue  # a module outside the run, or no module to declare a pair in
                yield from _no_module(rel, element, kind, word, required)
                continue
            module_rel, module = found
            if module.get("broken"):
                continue
            yield from _judged(module_rel, module, element, kind, word, required, needs)


def _where(kind: str, word: str) -> str:
    return (i18n.t(f"{OVERRIDE_RULE}.facet-module", kind=kind, module=word) if word
            else i18n.t(f"{OVERRIDE_RULE}.own-module", kind=kind))


def _sentence(text: str) -> str:
    """A message that opens with the name of the module, from a capital letter."""
    return text[:1].upper() + text[1:]


def _reason(kind: str, row: dict, other: str = "") -> str:
    if other:
        return i18n.t(f"{RULE}.reason-needs", other=other)
    prop = modulehandlers.per_item_property(row)
    if row.get("per") and prop:
        return i18n.t(f"{RULE}.reason-per-item", property=_property_shown(kind, prop))
    if row.get("required"):
        return i18n.t(f"{RULE}.reason-kind")
    if row["ru"] == modulehandlers.ACCESS_PERMISSIONS["ru"]:
        return i18n.t(f"{RULE}.reason-computed")
    return i18n.t(f"{RULE}.reason-per-object")


def _annotation_shown(english: bool) -> str:
    """The annotation in the spelling of the project, told by the spelling of a method name."""
    forms = terms.key_forms("Обработчик")
    return next((form for form in forms if form.isascii()), forms[0]) if english else forms[0]


def _file_of(element: dict, word: str) -> str:
    stem = element["file"].rsplit(".", 1)[0]
    if not word:
        return f"{stem}.xbsl"
    english = terms.facet_suffix_english(word) if _language() == "en" else None
    return f"{stem}.{english or word}.xbsl"


def _no_module(rel: str, element: dict, kind: str, word: str,
               required: tuple[dict, ...]) -> Iterable[Diagnostic]:
    for row in required:
        handler = row[_language()]
        yield Diagnostic(
            rel, 1, 1, RULE, Severity.ERROR,
            i18n.t(f"{RULE}.no-module", file=_file_of(element, word), where=_where(kind, word),
                   handler=handler, reason=_reason(kind, row),
                   annotation=_annotation_shown(_language() == "en")),
        )


def _judged(rel: str, module: dict, element: dict, kind: str, word: str,
            required: tuple[dict, ...], needs: dict[str, tuple[dict, ...]]
            ) -> Iterable[Diagnostic]:
    annotated: dict[str, list] = {}
    bare: dict[str, list] = {}
    for method in module["methods"]:
        (annotated if method[1] else bare).setdefault(method[0], []).append(method)
    wanted: list[tuple[dict, str]] = [(row, "") for row in required]
    for name, rows in needs.items():
        if name in annotated:
            wanted.extend((row, name) for row in rows)
    seen: set[str] = set()
    for row, other in wanted:
        if row["ru"] in seen:
            continue
        seen.add(row["ru"])
        spellings = (row["ru"], row["en"])
        declared = [method for name in spellings for method in annotated.get(name, ())]
        reason = _reason(kind, row, other)
        if not declared:
            unmarked = next((method for name in spellings for method in bare.get(name, ())),
                            None)
            if unmarked is not None:
                name, _flag, line, col, _union, line_start, indent = unmarked
                annotation = _annotation_shown(name == row["en"] and name != row["ru"])
                yield Diagnostic(
                    rel, line, col, RULE, Severity.ERROR,
                    i18n.t(f"{RULE}.unmarked", name=name, reason=reason,
                           annotation=annotation),
                    fix=TextEdit(line_start, line_start,
                                 f"{indent if not indent.strip() else ''}@{annotation}\n"),
                )
                continue
            yield Diagnostic(
                rel, 1, 1, RULE, Severity.ERROR,
                _sentence(i18n.t(f"{RULE}.missing", where=_where(kind, word),
                                 handler=row[_language()], reason=reason,
                                 annotation=_annotation_shown(_language() == "en"))),
            )
            continue
        prop = modulehandlers.per_item_property(row)
        listed = element.get("counts", {}).get(prop or "", 0)
        if row.get("per") and prop and 0 < len(declared) < listed \
                and not any(method[4] for method in declared):
            yield Diagnostic(
                rel, 1, 1, RULE, Severity.ERROR,
                _sentence(i18n.t(f"{RULE}.overloads", where=_where(kind, word),
                                 handler=row[_language()], property=_property_shown(kind, prop),
                                 listed=listed, declared=len(declared),
                                 annotation=_annotation_shown(_language() == "en"))),
            )
