"""Tier D: the handler annotation on a method that overrides nothing.

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

Two rules, one per thing the sources prove.

code/bound-handler-annotation - a method under the annotation whose name the paired yaml
binds, as the value of an event of a component (the event names come from the interface
schema, in both spellings) or of a handler key (a command, a route). A bound method is a
handler of the yaml, not an override. A bound name that is also a known overridable handler is
left alone: whether a yaml may bind the base handler by its own name is not proven either way.

code/handler-overrides-nothing - a method of an interface component module, under the
annotation, bound by nothing and named like no handler the component's base declares. The
handlers of a component module are listed by the distribution itself - the description of
each component names the handlers of a module built on it, both spellings included (see
xbsl/modulehandlers.py) - and a component inherits those of its bases. The other modules (the
object module of a catalog, the record set of a register, the module of a scheduled job) have
no such description: the compiler declares their handlers in code, and the extractor reads that
code into the `element_module_handlers` section, by the kind of the element and the module its
file names (`Stock.Object.xbsl` is the Object module of the element `Stock.yaml`,
`Stock.xbsl` its own). A module whose handler names come from the element's own description at
build time - the operations of a processing, of a SOAP client - is not judged: any name may be a
handler there. Nor is a kind the data does not list, a chain of components ending outside the
project and the catalog, or data without the lists.

The own module of an entity is the exception: the one name it takes at build time is a
record-level security handler, the kind says which of them it declares, and the access settings
of its description (`AccessControl`) say which of those and of the permissions handler the
build uses (modulehandlers.access_slot). A probe on a server (2026-09) gave, for the
permissions handler of a catalog without access settings, a refusal of its own - "Handler X is
not used in this project item" - and took it once a privilege computed its permissions; so a
handler the element declares but its settings leave off gets that message, and a name it cannot
declare at all the usual one. A description whose settings cannot be read counts every handler
of the kind as used. The own module of an HTTP service, a SOAP service and a processing declares
the permissions handler alone, and the build uses it by the same test of their access settings
(the handler provider of access control sets `enabled` by it for every module with an
access-control target); below the mode the settings of a processing came in, the build does not
read them, and the handler is not judged there.

Three more answers of the compiler the rule follows. A module the data lists with no handler at
all - a common module, a data journal, localized strings, a fragment of the command interface,
a global client event - declares nothing, and any name under the annotation is refused there.
The object module of a catalog, a document, an exchange plan and an integrable application
declares `OnCreateOnBasis` once for each type the description lists under `CreateOnBasis`
(modulehandlers.PER_ITEM_PROPERTIES): without the list the handler is not found, and the message
says which property is missing. The module of the project (`Проект.xbsl` beside the project
description) declares `ComputeSystemAccessPermissions` in the project of an application alone;
the module of a library or an extension project declares nothing (`ProjectKind` of the
description, see modulehandlers.project_slot).

A handler may be there in some compatibility modes only (`from` and `to` of its row, a
half-open range - see modulehandlers.declared_in): the web chat handler of a client
application is gone from mode 8.0 on. Such a handler counts as declared only when the mode of
the project admits it, and an override of it in another mode gets a message of its own that
names both the modes of the handler and the mode of the project. The mode is the one the
project description declares, read the way the platform reads it (`typeinfer.project_modes`,
shared with code/deprecated-api and code/contract-parameter-name): a description that declares
no mode, a value that names none or a mode the platform does not support is refused by the
build, and the reader of the platform goes on in the newest mode - so does the rule, and the
message says the mode is assumed. A run with no project description knows no mode, and every
handler of the base counts.

Both fixes remove the annotation - with its line when nothing else stands there. When the name
is a near miss of a handler the base does declare, the second rule offers no fix: the author
more likely misspelled the override than put the annotation on the wrong method, and taking
the annotation away would quietly turn a broken override into a method nobody calls. Nor is
there a fix for a handler of other modes: the platform does not call such a method in the mode
of the project, with the annotation or without it.
"""

from __future__ import annotations

import difflib
from collections.abc import Iterable
from dataclasses import astuple
from functools import lru_cache
from pathlib import PurePosixPath

from xbsl import dataset, i18n, metamodel, modulehandlers, terms, typeinfer
from xbsl import parser as P
from xbsl.diagnostics import Diagnostic, Severity, TextEdit
from xbsl.engine import SourceFile, rule
from xbsl.layout import PROJECT_FILES
from xbsl.lexer import linemap
from xbsl.rules.component_since import _version
from xbsl.rules.handlers import _IDENT_RE, _event_names, _handler_pair_stem
from xbsl.rules.unused_methods import platform_handlers
from xbsl.rules.yaml_schema import (
    _HAVE_YAML,
    _composed,
    _mapping_nodes,
    _parsed,
    object_kind,
    object_kind_fast,
    value_of,
)

if _HAVE_YAML:
    import yaml

RULE = "code/bound-handler-annotation"
OVERRIDE_RULE = "code/handler-overrides-nothing"

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
    f"{OVERRIDE_RULE}.title": {
        "ru": "@Обработчик у метода, который ничего не переопределяет",
        "en": "@Handler on a method that overrides nothing",
    },
    f"{OVERRIDE_RULE}.found": {
        "ru": "Метод '{name}' помечен @{annotation}, но переопределять ему нечего: модуль "
              "компонента на базе {base} переопределяет только {handlers}, а парный yaml "
              "этот метод не привязывает. Сборка откажет: \"A handler associated with method "
              "\"{name}\" is not found\". Если метод подключается к событию в коде или "
              "вызывается из модуля, снимите аннотацию.",
        "en": "Method '{name}' carries @{annotation}, yet it has nothing to override: a module "
              "of a component built on {base} overrides only {handlers}, and the paired yaml "
              "does not bind the method. The build refuses it: \"A handler associated with "
              "method \"{name}\" is not found\". If the method is attached to an event in code "
              "or called from the module, remove the annotation.",
    },
    f"{OVERRIDE_RULE}.misspelled": {
        "ru": "Метод '{name}' помечен @{annotation}, но модуль компонента на базе {base} "
              "такого обработчика не переопределяет. Похоже на опечатку в {similar}: сборка "
              "откажет (\"A handler associated with method \"{name}\" is not found\"), а "
              "переименованный метод платформа будет вызывать как обработчик.",
        "en": "Method '{name}' carries @{annotation}, but a module of a component built on "
              "{base} overrides no such handler. It looks like a misspelled {similar}: the "
              "build refuses it (\"A handler associated with method \"{name}\" is not "
              "found\"), and once renamed the platform will call the method as the handler.",
    },
    f"{OVERRIDE_RULE}.mode": {
        "ru": "Метод '{name}' помечен @{annotation}, но переопределять ему нечего: модуль "
              "компонента на базе {base} переопределяет {handler} {modes}, а режим "
              "совместимости проекта – {mode}. Сборка откажет: \"A handler associated with "
              "method \"{name}\" is not found\". Снять аннотацию мало: в этом режиме платформа "
              "такой метод не вызывает.",
        "en": "Method '{name}' carries @{annotation}, yet it has nothing to override: a module "
              "of a component built on {base} overrides {handler} {modes}, and the project "
              "compatibility mode is {mode}. The build refuses it: \"A handler associated with "
              "method \"{name}\" is not found\". Removing the annotation is not enough: in this "
              "mode the platform does not call such a method.",
    },
    f"{OVERRIDE_RULE}.element-found": {
        "ru": "Метод '{name}' помечен @{annotation}, но переопределять ему нечего: {module} "
              "переопределяет только {handlers}, а парный yaml этот метод не привязывает. "
              "Сборка откажет: \"A handler associated with method \"{name}\" is not found\". "
              "Если метод вызывается из модуля, снимите аннотацию.",
        "en": "Method '{name}' carries @{annotation}, yet it has nothing to override: {module} "
              "overrides only {handlers}, and the paired yaml does not bind the method. The "
              "build refuses it: \"A handler associated with method \"{name}\" is not "
              "found\". If the method is called from the module, remove the annotation.",
    },
    f"{OVERRIDE_RULE}.element-misspelled": {
        "ru": "Метод '{name}' помечен @{annotation}, но {module} такого обработчика не "
              "переопределяет. Похоже на опечатку в {similar}: сборка откажет (\"A handler "
              "associated with method \"{name}\" is not found\"), а переименованный метод "
              "платформа будет вызывать как обработчик.",
        "en": "Method '{name}' carries @{annotation}, but {module} overrides no such handler. "
              "It looks like a misspelled {similar}: the build refuses it (\"A handler "
              "associated with method \"{name}\" is not found\"), and once renamed the "
              "platform will call the method as the handler.",
    },
    f"{OVERRIDE_RULE}.element-mode": {
        "ru": "Метод '{name}' помечен @{annotation}, но переопределять ему нечего: {module} "
              "переопределяет {handler} {modes}, а режим совместимости проекта – {mode}. "
              "Сборка откажет: \"A handler associated with method \"{name}\" is not "
              "found\". Снять аннотацию мало: в этом режиме платформа такой метод не вызывает.",
        "en": "Method '{name}' carries @{annotation}, yet it has nothing to override: {module} "
              "overrides {handler} {modes}, and the project compatibility mode is {mode}. The "
              "build refuses it: \"A handler associated with method \"{name}\" is not "
              "found\". Removing the annotation is not enough: in this mode the platform does "
              "not call such a method.",
    },
    f"{OVERRIDE_RULE}.element-nothing": {
        "ru": "Метод '{name}' помечен @{annotation}, но переопределять ему нечего: {module} "
              "такого обработчика не объявляет, а парный yaml этот метод не привязывает. "
              "Сборка откажет: \"A handler associated with method \"{name}\" is not found\". "
              "Если метод вызывается из модуля, снимите аннотацию.",
        "en": "Method '{name}' carries @{annotation}, yet it has nothing to override: {module} "
              "declares no such handler, and the paired yaml does not bind the method. The "
              "build refuses it: \"A handler associated with method \"{name}\" is not "
              "found\". If the method is called from the module, remove the annotation.",
    },
    f"{OVERRIDE_RULE}.element-per-item": {
        "ru": "Метод '{name}' помечен @{annotation}, но {module} объявляет обработчик {handler} "
              "только для типов, которые перечисляет свойство {property} описания элемента, а "
              "оно не перечисляет ни одного. Сборка откажет: \"A handler associated with method "
              "\"{name}\" is not found\".",
        "en": "Method '{name}' carries @{annotation}, but {module} declares the {handler} "
              "handler only for the types the {property} property of the element description "
              "lists, and it lists none. The build refuses it: \"A handler associated with "
              "method \"{name}\" is not found\".",
    },
    f"{OVERRIDE_RULE}.element-unused": {
        "ru": "Метод '{name}' помечен @{annotation}, но {module} обработчик {handler} при этих "
              "настройках доступа не использует: {reason}. Сборка откажет: \"Handler "
              "\"{name}\" is not used in this project item\".",
        "en": "Method '{name}' carries @{annotation}, but {module} does not use the {handler} "
              "handler with these access settings: {reason}. The build refuses it: \"Handler "
              "\"{name}\" is not used in this project item\".",
    },
    f"{OVERRIDE_RULE}.unused-computed": {
        "ru": "его вызывают, только когда настройки вычисляют разрешения "
              "(РазрешенияВычисляются или РазрешенияВычисляютсяДляКаждогоОбъекта)",
        "en": "it is called only when the settings compute permissions "
              "({n[РазрешенияВычисляются]} or {n[РазрешенияВычисляютсяДляКаждогоОбъекта]})",
    },
    f"{OVERRIDE_RULE}.unused-per-object": {
        "ru": "его вызывают, только когда настройки вычисляют разрешения для каждого объекта "
              "(РазрешенияВычисляютсяДляКаждогоОбъекта)",
        "en": "it is called only when the settings compute permissions for each object "
              "({n[РазрешенияВычисляютсяДляКаждогоОбъекта]})",
    },
    f"{OVERRIDE_RULE}.unused-standard": {
        "ru": "при стандартных разрешениях (СтандартныеРазрешения) обработчики доступа не "
              "вызываются",
        "en": "with the standard permissions ({n[СтандартныеРазрешения]}) no access handler is "
              "called",
    },
    f"{OVERRIDE_RULE}.unused-never": {
        "ru": "записи этого вида разрешения для каждого объекта не вычисляют",
        "en": "the records of this kind never compute permissions for each object",
    },
    f"{OVERRIDE_RULE}.own-module": {
        "ru": "модуль элемента вида {kind}",
        "en": "the module of an element of kind {kind}",
    },
    f"{OVERRIDE_RULE}.facet-module": {
        "ru": "модуль {kind}.{module}",
        "en": "the {kind}.{module} module",
    },
    f"{OVERRIDE_RULE}.project-module": {
        "ru": "модуль проекта вида {kind}",
        "en": "the module of a project of kind {kind}",
    },
    f"{OVERRIDE_RULE}.until": {
        "ru": "только в режимах ниже {until}",
        "en": "only in modes below {until}",
    },
    f"{OVERRIDE_RULE}.since": {
        "ru": "только начиная с режима {since}",
        "en": "only from mode {since} on",
    },
    f"{OVERRIDE_RULE}.between": {
        "ru": "только в режимах от {since} и ниже {until}",
        "en": "only in modes from {since} and below {until}",
    },
    f"{OVERRIDE_RULE}.assumed": {
        "ru": "{mode} (новейший: проект не указывает режим, который поддерживает платформа)",
        "en": "{mode} (the newest: the project states no mode the platform supports)",
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


def _reset() -> None:
    _annotations.cache_clear()
    _binding_keys.cache_clear()


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
            # A name some module overrides is left alone (see the module docstring).
            if name not in bound or name in platform_handlers():
                continue
            key, line = bound[name]
            yield Diagnostic(
                rel, method["line"], method["col"], RULE, Severity.ERROR,
                i18n.t(f"{RULE}.found", name=name, key=key, line=line,
                       annotation=method["annotation"]),
                fix=TextEdit(method["start"], method["end"], ""),
            )


# --- code/handler-overrides-nothing ------------------------------------------------------

#: The kind of the element whose module this rule judges.
_COMPONENT_KIND = "КомпонентИнтерфейса"
#: How close a written name must come to a handler of the base to read as its misspelling.
_NEAR_MISS = 0.8


def _base_head(data: dict, kind: str) -> str:
    """The base a component names (`Наследует.Тип`): no generic arguments, no package."""
    inherits = value_of(data, "Наследует", kind)
    written = value_of(inherits, "Тип") if isinstance(inherits, dict) else None
    return modulehandlers.base_head(written) if isinstance(written, str) else ""


def _component_fact(source: SourceFile) -> dict | None:
    """What the reduce needs of a component description: its name, base and bound methods."""
    if not _HAVE_YAML or object_kind_fast(source) != _COMPONENT_KIND:
        return None
    data, error = _parsed(source)
    kind = object_kind(data) if error is None else None
    if kind != _COMPONENT_KIND:
        return None
    name = value_of(data, "Имя", kind)
    bound = _yaml_fact(source)
    return {
        "k": "c",
        "stem": _handler_pair_stem(source.rel),
        "name": name if isinstance(name, str) else "",
        "head": _base_head(data, kind),
        "bound": sorted(bound["bound"]) if bound else [],
    }


def _element_fact(source: SourceFile) -> dict | None:
    """What the reduce needs of the description of any other element: its kind, bound names,
    for an element with access settings what they say (see _access_settings), and which of the
    collections some handler is declared once per item of it fills (see _given)."""
    if not _HAVE_YAML:
        return None
    kind = object_kind_fast(source)
    if not kind or kind == _COMPONENT_KIND:
        return None
    bound = _yaml_fact(source)
    fact = {
        "k": "e",
        "stem": _handler_pair_stem(source.rel),
        "kind": kind,
        "bound": sorted(bound["bound"]) if bound else [],
    }
    if modulehandlers.record_security_rows(kind, None) is not None or _access_control(kind):
        data, error = _parsed(source)
        settings = _access_settings(data, kind) if error is None else None
        fact["access"] = list(astuple(settings)) if settings is not None else None
    properties = modulehandlers.per_item_properties()
    if properties:
        given = _given(source, kind, properties)
        fact["given"] = sorted(given) if given is not None else None
    return fact


def _access_control(kind: str) -> dict:
    """The access settings property of the kind (`AccessControl`), {} for a kind without one."""
    return metamodel.properties(kind).get("КонтрольДоступа") or {}


def _given(source: SourceFile, kind: str, properties: frozenset[str]) -> set[str] | None:
    """The properties among `properties` the description fills with at least one item; None
    when the description cannot be read that far. A property the text never names is empty,
    and the file is not parsed for it."""
    def spellings(prop: str) -> set[str]:
        english = (metamodel.properties(kind).get(prop) or {}).get("en")
        return {*terms.key_forms(prop), *([english] if english else [])}

    named = [prop for prop in properties if any(key in source.text for key in spellings(prop))]
    if not named:
        return set()
    data, error = _parsed(source)
    if error is not None or not isinstance(data, dict):
        return None
    given = set()
    for prop in named:
        value = value_of(data, prop, kind)
        if (isinstance(value, (list, dict)) and value) or (isinstance(value, str)
                                                            and value.strip()):
            given.add(prop)
    return given


#: The values of a privilege that compute its permissions, for each object or not (the
#: `AccessControl` enumeration of the schema), and the value a privilege left out takes when the
#: description names no default.
_COMPUTED = "РазрешенияВычисляются"
_PER_OBJECT = "РазрешенияВычисляютсяДляКаждогоОбъекта"
_DEFAULT_VALUE = "РазрешеноАдминистраторам"
_TRUE = frozenset({True, "Истина", "True", "true"})


def _key_in(block, props: dict[str, dict], key: str):
    """The value of `key` of a yaml block, whichever spelling the file uses."""
    if not isinstance(block, dict):
        return None
    if key in block:
        return block[key]
    english = (props.get(key) or {}).get("en")
    return block.get(english) if english else None


def _access_value(value) -> str | None:
    """A privilege value in the Russian spelling, None for one the enumeration does not have."""
    if not isinstance(value, str):
        return None
    for russian in metamodel.enum_values("AccessControl") or (_COMPUTED, _PER_OBJECT,
                                                               _DEFAULT_VALUE):
        if value in (russian, terms.common_english(russian)):
            return russian
    return None


def _access_settings(data, kind: str) -> modulehandlers.AccessSettings | None:
    """What the access settings of an entity say, the way the build reads them; None when the
    description cannot be read that far.

    Each privilege of the kind takes the value the settings give it or else the default of the
    settings (`Default`, the administrators when unnamed): the build computes permissions
    when one of those values computes them, for each object when one computes them for each
    object. The privileges are the keys the schema gives the permissions block, the default
    aside. A settings storage may keep the standard permissions instead; an information register
    splits its keys by its periodicity.
    """
    if not isinstance(data, dict):
        return None
    periodicity = value_of(data, "Периодичность", kind)
    periodic = isinstance(periodicity, str) and periodicity not in (
        "Непериодический", terms.common_english("Непериодический"))
    control_record = metamodel.properties(kind).get("КонтрольДоступа") or {}
    control = value_of(data, "КонтрольДоступа", kind)
    if control is None:
        return modulehandlers.AccessSettings(periodic=periodic)
    control_props = metamodel.properties_of_class(control_record.get("type") or "")
    permissions_record = control_props.get("Разрешения") or {}
    permission_props = metamodel.properties_of_class(permissions_record.get("type") or "")
    if not isinstance(control, dict) or not permission_props:
        return None
    standard = _key_in(control, control_props, "СтандартныеРазрешения") in _TRUE
    permissions = _key_in(control, control_props, "Разрешения")
    if permissions is None:
        permissions = {}
    if not isinstance(permissions, dict):
        return None
    written = _key_in(permissions, permission_props, "ПоУмолчанию")
    default = _access_value(written) if written is not None else _DEFAULT_VALUE
    values = []
    for privilege in permission_props:
        if privilege == "ПоУмолчанию":
            continue
        given = _key_in(permissions, permission_props, privilege)
        values.append(_access_value(given) if given is not None else default)
    if None in values:
        return None  # a value the enumeration does not have: the build refuses it anyway
    return modulehandlers.AccessSettings(
        computed=any(value in (_COMPUTED, _PER_OBJECT) for value in values),
        per_object=_PER_OBJECT in values, standard=standard, periodic=periodic)


def _override_mapper(source: SourceFile) -> dict | None:
    components, elements = modulehandlers.available(), modulehandlers.element_available()
    if not components and not elements:
        return None
    if source.kind == "xbsl":
        return _module_fact(source)
    if source.kind == "yaml":
        if PurePosixPath(source.rel.replace("\\", "/")).name in PROJECT_FILES:
            # The folder of the project and the mode it declares: the fact the project typing
            # takes from the description, read once per source for every rule that asks. The
            # module of the project pairs with the description, and its kind picks the handlers.
            fact = typeinfer.project_fact(source)
            if fact is None or not elements \
                    or object_kind_fast(source) not in (None, modulehandlers.PROJECT_KIND):
                return fact  # an element that merely bears the name is no project description
            return {**fact, "stem": _handler_pair_stem(source.rel),
                    "project_kind": _project_kind(source)}
        if object_kind_fast(source) == _COMPONENT_KIND:
            return _component_fact(source) if components else None
        return _element_fact(source) if elements else None
    return None


def _project_kind(source: SourceFile) -> str | None:
    """The kind of the project a description declares (`ProjectKind`) in the Russian spelling:
    the application when it names none, None for a value the enumeration does not have or a
    description that cannot be read."""
    data, error = _parsed(source)
    if error is not None or not isinstance(data, dict):
        return None
    written = value_of(data, "ВидПроекта", modulehandlers.PROJECT_KIND)
    if written is None:
        return modulehandlers.APPLICATION_PROJECT
    if not isinstance(written, str):
        return None
    known = metamodel.enum_values("ProjectKindEnum") or (
        modulehandlers.APPLICATION_PROJECT, *sorted(modulehandlers.OTHER_PROJECTS))
    for russian in known:
        if written.strip() in (russian, terms.common_english(russian)):
            return russian
    return None


def _in_language(russian: str) -> str:
    """A value of the enumerations as the reader's language spells it."""
    return (terms.common_english(russian) or russian) if _language() == "en" else russian


def _mode_shown(mode: tuple[int, ...], assumed: bool) -> str:
    """The mode of the project as a message names it, with a word on where it comes from."""
    written = ".".join(str(part) for part in mode)
    return i18n.t(f"{OVERRIDE_RULE}.assumed", mode=written) if assumed else written


def _modes_shown(row: dict) -> str:
    """The modes a handler is there in, as a message words them."""
    since, until = str(row.get("from") or "").strip(), str(row.get("to") or "").strip()
    if since and until:
        return i18n.t(f"{OVERRIDE_RULE}.between", since=since, until=until)
    if until:
        return i18n.t(f"{OVERRIDE_RULE}.until", until=until)
    return i18n.t(f"{OVERRIDE_RULE}.since", since=since)


def _language() -> str:
    """The spelling a message names a handler in: the reader's language."""
    return "en" if i18n.current_lang() == "en" else "ru"


@rule(
    OVERRIDE_RULE, f"{OVERRIDE_RULE}.title", "D",
    scope="project", severity=Severity.ERROR, mapper=_override_mapper,
)
def handler_overrides_nothing(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    components: dict[str, list[str]] = {}
    by_stem: dict[str, dict] = {}
    for fact in facts.values():
        if fact["k"] == "c":
            components.setdefault(fact["name"], []).append(fact["head"])
            by_stem[fact["stem"]] = fact

    def project_base(name: str) -> str | None:
        heads = components.get(name)
        if heads is None:
            return None
        # Two components under one name: which one a base means cannot be told from here.
        return heads[0] if len(heads) == 1 else ""

    elements = {fact["stem"]: fact for fact in facts.values() if fact["k"] == "e"}
    projects = {fact["stem"]: fact for fact in facts.values()
                if fact["k"] == "project" and "stem" in fact}
    modes = typeinfer.project_modes(facts)
    for rel, fact in facts.items():
        if fact["k"] != "x":
            continue
        component = by_stem.get(fact["stem"])
        if component is None:
            project = projects.get(fact["stem"])
            if project is not None:
                yield from _project_overrides(rel, fact, project, modes)
            else:
                yield from _element_overrides(rel, fact, elements, modes)
            continue
        base = modulehandlers.platform_base(component["head"], project_base)
        rows = modulehandlers.rows_of(base) if base else ()
        if not rows:
            continue
        mode, assumed = modes.get(rel, (None, False))
        # {handler name in either spelling: its row}, in the mode of the project and out of it.
        present: dict[str, dict] = {}
        elsewhere: dict[str, dict] = {}
        shown: list[dict] = []
        for row in rows:
            if modulehandlers.declared_in(row, mode):
                shown.append(row)
                present.update(dict.fromkeys((row["ru"], row["en"]), row))
            else:
                elsewhere.update(dict.fromkeys((row["ru"], row["en"]), row))
        bound = set(component["bound"])
        for method in fact["annotated"]:
            name = method["name"]
            if name in bound or name in present:
                continue
            fields = {"name": name, "annotation": method["annotation"], "base": base}
            other = elsewhere.get(name)
            if other is not None and mode is not None:  # an unknown mode keeps every row
                yield Diagnostic(
                    rel, method["line"], method["col"], OVERRIDE_RULE, Severity.ERROR,
                    i18n.t(f"{OVERRIDE_RULE}.mode", handler=other[_language()],
                           modes=_modes_shown(other), mode=_mode_shown(mode, assumed), **fields),
                )
                continue
            near = difflib.get_close_matches(name, list(present), n=1, cutoff=_NEAR_MISS)
            if near:
                yield Diagnostic(
                    rel, method["line"], method["col"], OVERRIDE_RULE, Severity.ERROR,
                    i18n.t(f"{OVERRIDE_RULE}.misspelled", similar=present[near[0]][_language()],
                           **fields),
                )
                continue
            yield Diagnostic(
                rel, method["line"], method["col"], OVERRIDE_RULE, Severity.ERROR,
                i18n.t(f"{OVERRIDE_RULE}.found",
                       handlers=", ".join(row[_language()] for row in shown), **fields),
                fix=TextEdit(method["start"], method["end"], ""),
            )


def _element_overrides(rel: str, fact: dict, elements: dict[str, dict],
                       modes: dict) -> Iterable[Diagnostic]:
    """The findings of one module of an element other than a component (see the docstring)."""
    stem, module = modulehandlers.element_module(fact["stem"])
    element = elements.get(stem)
    if element is None:
        return
    kind = element["kind"]
    mode, assumed = modes.get(rel, (None, False))
    access = element.get("access")
    settings = modulehandlers.AccessSettings(*access) if access else None
    since = _version(_access_control(kind).get("since"))
    if since and mode is not None and mode < since:
        # Below the mode the settings came in, the build does not read them: which handler it
        # uses is not told here, and every handler counts as used.
        settings = None
    # The own module of an entity takes the record-level security handlers, and that of an
    # element with access settings the permissions handler: the settings say which the build
    # uses. Any other module takes the rows of its slot.
    split = modulehandlers.access_slot(kind, module, settings, controlled="access" in element)
    if split is not None:
        rows, off = split
    else:
        rows, off = modulehandlers.element_slot(kind, module), ()
        if rows is None:
            return  # nothing known of the module, or names taken at build time: not judged
    given = element.get("given")
    rows, absent = modulehandlers.per_item_split(
        rows, frozenset(given) if given is not None else None)
    where = (i18n.t(f"{OVERRIDE_RULE}.facet-module", kind=kind, module=module)
             if module else i18n.t(f"{OVERRIDE_RULE}.own-module", kind=kind))
    # The yaml binds the methods of the element's own module, not those of its other modules.
    bound = set() if module else set(element["bound"])
    yield from _judged(rel, fact, rows, where, bound, mode, assumed,
                       off=off, absent=absent, kind=kind, settings=settings)


def _project_overrides(rel: str, fact: dict, project: dict,
                       modes: dict) -> Iterable[Diagnostic]:
    """The findings of the module of the project: its kind picks the handlers (project_slot)."""
    project_kind = project.get("project_kind")
    rows = modulehandlers.project_slot(project_kind) if project_kind else None
    if rows is None:
        return  # the data knows no module of the project, or the kind is not one it has
    mode, assumed = modes.get(rel, (None, False))
    where = i18n.t(f"{OVERRIDE_RULE}.project-module", kind=_in_language(project_kind))
    yield from _judged(rel, fact, rows, where, set(), mode, assumed)


def _judged(rel: str, fact: dict, rows: tuple[dict, ...], where: str, bound: set[str],
            mode: tuple[int, ...] | None, assumed: bool, *, off: tuple[dict, ...] = (),
            absent: tuple[dict, ...] = (), kind: str = "",
            settings: modulehandlers.AccessSettings | None = None) -> Iterable[Diagnostic]:
    """The findings of the annotated methods of one module against what it declares.

    `rows` are the handlers the module declares, `off` those its access settings leave off, and
    `absent` those declared once per item of a collection the description leaves empty. A module
    that declares nothing at all is judged too: every name is wrong there.
    """
    unused = {name: row for row in off for name in (row["ru"], row["en"])}
    missing = {name: row for row in absent for name in (row["ru"], row["en"])}
    present: dict[str, dict] = {}
    elsewhere: dict[str, dict] = {}
    shown: list[dict] = []
    for row in rows:
        if modulehandlers.declared_in(row, mode):
            shown.append(row)
            present.update(dict.fromkeys((row["ru"], row["en"]), row))
        else:
            elsewhere.update(dict.fromkeys((row["ru"], row["en"]), row))
    for method in fact["annotated"]:
        name = method["name"]
        if name in bound or name in present:
            continue
        fields = {"name": name, "annotation": method["annotation"], "module": where}
        left_off = unused.get(name)
        if left_off is not None:
            reason = modulehandlers.unused_reason(kind, left_off, settings)
            yield Diagnostic(
                rel, method["line"], method["col"], OVERRIDE_RULE, Severity.ERROR,
                i18n.t(f"{OVERRIDE_RULE}.element-unused", handler=left_off[_language()],
                       reason=i18n.t(f"{OVERRIDE_RULE}.unused-{reason}"), **fields),
            )
            continue
        per_item = missing.get(name)
        if per_item is not None:
            prop = modulehandlers.per_item_property(per_item) or ""
            yield Diagnostic(
                rel, method["line"], method["col"], OVERRIDE_RULE, Severity.ERROR,
                i18n.t(f"{OVERRIDE_RULE}.element-per-item", handler=per_item[_language()],
                       property=_property_shown(kind, prop), **fields),
            )
            continue
        other = elsewhere.get(name)
        if other is not None and mode is not None:
            yield Diagnostic(
                rel, method["line"], method["col"], OVERRIDE_RULE, Severity.ERROR,
                i18n.t(f"{OVERRIDE_RULE}.element-mode", handler=other[_language()],
                       modes=_modes_shown(other), mode=_mode_shown(mode, assumed), **fields),
            )
            continue
        near = difflib.get_close_matches(name, list(present), n=1, cutoff=_NEAR_MISS)
        if near:
            yield Diagnostic(
                rel, method["line"], method["col"], OVERRIDE_RULE, Severity.ERROR,
                i18n.t(f"{OVERRIDE_RULE}.element-misspelled",
                       similar=present[near[0]][_language()], **fields),
            )
            continue
        # A module that declares nothing, or settings that leave every handler off, leave
        # nothing to list.
        message = (i18n.t(f"{OVERRIDE_RULE}.element-found",
                          handlers=", ".join(row[_language()] for row in shown), **fields)
                   if shown else i18n.t(f"{OVERRIDE_RULE}.element-nothing", **fields))
        yield Diagnostic(
            rel, method["line"], method["col"], OVERRIDE_RULE, Severity.ERROR, message,
            fix=TextEdit(method["start"], method["end"], ""),
        )


def _property_shown(kind: str, prop: str) -> str:
    """A property of an element description as the reader's language names it."""
    if _language() != "en":
        return prop
    return ((metamodel.properties(kind).get(prop) or {}).get("en")
            or terms.common_english(prop) or prop)
