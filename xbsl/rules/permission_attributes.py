"""Tier A: the attributes the permissions of objects are computed by (`ComputePermissionsBy`).

An entity whose access settings compute a permission for each object - a privilege set to
`PermissionsComputedForEachObject`, or the default set so and some privilege left out - reads
the permissions of an object from the attributes `ComputePermissionsBy` lists. The build checks
the list both ways (the processor of those attributes in the compiler, 2026-09; a probe on a
server gave both answers):

- `.missing`: the settings compute a permission for each object, and the list is absent or
  empty. The build refuses it with "Attributes for calculating object access permissions are
  missing" at the start of the `AccessControl` block. The standard permissions of a settings
  storage are the exception: the build takes the attributes of its own then.
- `.without-per-object`: the list is there, and no permission is computed for each object. The
  build refuses it with "It is not allowed to specify attributes for calculating access
  permissions without configuring access permissions calculation for each object", at the
  first attribute of the list.

A privilege takes the value the settings give it or else their default (the administrators
when the default is not written) - the reading code/handler-overrides-nothing shares. The kinds
judged are those whose access settings have the property at all: a catalog, a document, an
exchange plan, a settings storage, an integrable application and the registers. A description
that cannot be read that far is not judged.

yaml/compute-permissions-by-unknown reads the names of the list: each has to be a field of the
element, and the build answers any other with "Attribute "X" is not found" at that name. The
fields are what the element declares in its attributes (a standard attribute included), its
dimensions and resources, the service fields it has without a declaration and the built-in
fields of its kind (the numbers of the messages of an exchange plan node, the system attributes
of a settings storage); see the rule for what a probe settled. It judges every kind above.
"""

from __future__ import annotations

from collections.abc import Iterable
from functools import lru_cache

from xbsl import dataset, i18n, metamodel, terms
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, rule
from xbsl.querytypes import _SERVICE_FIELDS
from xbsl.rules.handler_annotation import _access_settings, _key_in
from xbsl.rules.yaml_schema import (
    _HAVE_YAML,
    _IDENTIFIER_RE,
    _composed,
    _parsed,
    object_kind,
    object_kind_fast,
    value_of,
)

if _HAVE_YAML:
    import yaml

RULE = "yaml/compute-permissions-by"

MESSAGES = {
    f"{RULE}.title": {
        "ru": "РасчетРазрешенийПо не согласован с расчетом разрешений для каждого объекта",
        "en": "ComputePermissionsBy does not match the permissions computed for each object",
    },
    f"{RULE}.missing": {
        "ru": "Настройки доступа вычисляют разрешения для каждого объекта "
              "(РазрешенияВычисляютсяДляКаждогоОбъекта), а реквизитов в РасчетРазрешенийПо "
              "нет. Сборка откажет: \"Attributes for calculating object access permissions "
              "are missing\". Перечислите в РасчетРазрешенийПо реквизиты, по которым "
              "вычисляются разрешения объекта.",
        "en": "The access settings compute permissions for each object "
              "({n[РазрешенияВычисляютсяДляКаждогоОбъекта]}), yet {n[РасчетРазрешенийПо]} "
              "lists no attribute. The build refuses it: \"Attributes for calculating object "
              "access permissions are missing\". List the attributes the permissions of an "
              "object are computed by under {n[РасчетРазрешенийПо]}.",
    },
    f"{RULE}.without-per-object": {
        "ru": "РасчетРазрешенийПо перечисляет реквизиты, а настройки доступа ни одно "
              "разрешение для каждого объекта не вычисляют. Сборка откажет: \"It is not "
              "allowed to specify attributes for calculating access permissions without "
              "configuring access permissions calculation for each object\". Уберите список "
              "или поставьте разрешению значение РазрешенияВычисляютсяДляКаждогоОбъекта.",
        "en": "{n[РасчетРазрешенийПо]} lists attributes, yet the access settings compute no "
              "permission for each object. The build refuses it: \"It is not allowed to "
              "specify attributes for calculating access permissions without configuring "
              "access permissions calculation for each object\". Remove the list, or set a "
              "permission to {n[РазрешенияВычисляютсяДляКаждогоОбъекта]}.",
    },
}
i18n.register(MESSAGES)

_CONTROL = "КонтрольДоступа"
_BY = "РасчетРазрешенийПо"


def _control_props(kind: str) -> dict[str, dict]:
    """The properties of the access settings of the kind, {} for a kind without them."""
    record = metamodel.properties(kind).get(_CONTROL) or {}
    return metamodel.properties_of_class(record.get("type") or "") if record else {}


def _node_of(root, keys: tuple[str, ...]):
    """The value node under a path of keys (each in either spelling given), or None."""
    node = root
    for spellings in keys:
        if not isinstance(node, yaml.MappingNode):
            return None
        node = next((value for key, value in node.value
                     if isinstance(key, yaml.ScalarNode) and key.value in spellings), None)
        if node is None:
            return None
    return node


@rule(RULE, f"{RULE}.title", "A", severity=Severity.ERROR)
def compute_permissions_by(source: SourceFile) -> Iterable[Diagnostic]:
    """`ComputePermissionsBy` against the permissions computed for each object - see the
    module docstring."""
    if source.kind != "yaml" or not _HAVE_YAML:
        return
    kind = object_kind_fast(source)
    if not kind:
        return
    props = _control_props(kind)
    if _BY not in props:
        return
    data, error = _parsed(source)
    if error is not None or object_kind(data) != kind:
        return
    control = value_of(data, _CONTROL, kind)
    if not isinstance(control, dict):
        return
    settings = _access_settings(data, kind)
    if settings is None:
        return
    listed = _key_in(control, props, _BY)
    if isinstance(listed, str):
        given = bool(listed.strip())
    elif isinstance(listed, (list, dict)):
        given = bool(listed)
    else:
        given = listed is not None
    root = _composed(source)
    if root is None:
        return
    control_keys = {_CONTROL, (metamodel.properties(kind).get(_CONTROL) or {}).get("en")}
    by_keys = {_BY, (props.get(_BY) or {}).get("en")}
    if settings.per_object and not settings.standard and not given:
        node = _node_of(root, (control_keys,))
        if node is None:
            return
        yield Diagnostic(source.rel, node.start_mark.line + 1, node.start_mark.column + 1, RULE,
                         Severity.ERROR, i18n.t(f"{RULE}.missing"))
    elif not settings.per_object and given:
        node = _node_of(root, (control_keys, by_keys))
        if isinstance(node, yaml.SequenceNode) and node.value:
            node = node.value[0]
        if node is None:
            return
        yield Diagnostic(source.rel, node.start_mark.line + 1, node.start_mark.column + 1, RULE,
                         Severity.ERROR, i18n.t(f"{RULE}.without-per-object"))


# --- A name the list gives that the element does not declare ------------------------------

UNKNOWN = "yaml/compute-permissions-by-unknown"

MESSAGES_UNKNOWN = {
    f"{UNKNOWN}.title": {
        "ru": "РасчетРазрешенийПо называет не реквизит элемента",
        "en": "ComputePermissionsBy names no attribute of the element",
    },
    f"{UNKNOWN}.unknown": {
        "ru": "РасчетРазрешенийПо называет '{name}', а элемент не объявляет такого реквизита. "
              "Сборка откажет: \"Attribute \"{name}\" is not found\". Стандартный реквизит "
              "(Наименование, Код, Номер) тоже объявляется в Реквизиты, а табличная часть "
              "здесь не подходит.",
        "en": "{n[РасчетРазрешенийПо]} names '{name}', and the element declares no such "
              "attribute. The build refuses it: \"Attribute \"{name}\" is not found\". A "
              "standard attribute ({n[Наименование]}, {n[Код]}, {n[Номер]}) is declared in "
              "{n[Реквизиты]} too, and a tabular section does not fit here.",
    },
    f"{UNKNOWN}.computed": {
        "ru": "РасчетРазрешенийПо называет '{name}' – это поле вычисляемое, по нему разрешения "
              "не рассчитать. Сборка не применится: сервер откажет в создании или обновлении "
              "приложения, ответив только \"Contact administrator for details\". Уберите поле "
              "из списка.",
        "en": "{n[РасчетРазрешенийПо]} names '{name}', a computed field the permissions cannot "
              "be calculated by. The build will not apply: the server refuses to create or "
              "update the application, answering nothing but \"Contact administrator for "
              "details\". Remove the field from the list.",
    },
}
i18n.register(MESSAGES_UNKNOWN)

#: The kinds whose fields a probe on a server settled: every kind whose access settings have
#: the list.
_UNKNOWN_KINDS = ("Справочник", "Документ", "РегистрСведений", "РегистрНакопления", "ПланОбмена",
                  "ХранилищеНастроек", "ИнтегрируемоеПриложение")
#: The fields a kind has without declaring them, beyond the service fields every entity has.
#: A probe on a server took each of them in the list with nothing declared: the code, the
#: numbers of the sent and the received message and the flag of this node of an exchange plan
#: (the four the documentation calls mandatory), the system attributes of a settings storage
#: (the documentation lists them, and its own example computes the permissions by the user
#: without a declaration) and the connection settings of an integrable application. The name
#: of an exchange plan and of an integrable application, their files and the code of an
#: integrable application are declared like those of a catalog: the same probe answered "not
#: found" for each of them left out.
_BUILT_IN_FIELDS = {
    "ПланОбмена": ("Код", "НомерОтправленного", "НомерПринятого", "ЭтотУзел"),
    "ХранилищеНастроек": ("Вариант", "Значение", "КлючНастройки", "КлючОбъекта", "Наименование",
                          "Общая", "Пользователь"),
    "ИнтегрируемоеПриложение": ("НастройкиПрямогоПодключения",),
}
#: Standard attributes the query tables know as service fields that a kind still has only when
#: it declares them: the number of a document. A probe answered "not found" for the number of
#: a document that does not declare it and took the number of one that does.
_DECLARED_ONLY = {"Документ": ("Номер",)}
#: Service fields a kind does not have at all: the build answered "not found" for the deletion
#: mark of a settings storage.
_ABSENT = {"ХранилищеНастроек": ("ПометкаУдаления",)}
#: The computed fields of the query tables. In the list they do not fail the compilation: the
#: apply of the build fails inside the server instead (a ClassCastException while it builds the
#: automatic list form), both when it creates the application and when it updates it, and the
#: application stays on the build it had. Probes gave that answer for each kind named here and
#: each field it lists; a kind is not judged for a field no probe tried with it.
_COMPUTED = {
    "Справочник": ("ПометкаУдаления", "Представление"),
    "Документ": ("ПометкаУдаления", "Представление"),
    "ПланОбмена": ("ПометкаУдаления", "Представление"),
    "ИнтегрируемоеПриложение": ("ПометкаУдаления", "Представление"),
    "ХранилищеНастроек": ("Представление",),
}
#: Service fields the query tables leave out that the element still has without a declaration:
#: the moment of the deletion mark, which a probe took in the list of a catalog and a document.
_MORE_SERVICE_FIELDS = ("МоментПометкиУдаления",)
#: The sections that declare the fields of an element: the attributes, and of a register its
#: dimensions and resources as well.
_FIELD_SECTIONS = ("Реквизиты", "Измерения", "Ресурсы")
#: The facets of the stdlib catalog whose properties are fields of an object or a record.
_RECORD_FACETS = ("Объект", "Запись", "КлючЗаписи", "КлючОсновногоФильтра")


@lru_cache(maxsize=1)
def _service_fields() -> frozenset[str]:
    """The fields an element has without declaring them, in every spelling the data knows.

    The service fields of the query tables and the properties of the object and record facets
    of the kinds judged: a probe on a server took the reference, the parent of a hierarchical
    catalog and the period of a periodic register without a declaration. Only a name outside
    them is reported, so the set errs on the wide side.
    """
    names = set(_SERVICE_FIELDS) | set(_MORE_SERVICE_FIELDS)
    catalog = dataset.load_optional("stdlib.json") or {}
    for facet, record in (catalog.get("facet_members") or {}).items():
        owner, _, part = facet.partition(".")
        if part in _RECORD_FACETS and (owner in _UNKNOWN_KINDS or owner == "Сущность"):
            names.update(record.get("properties") or ())
    spelled = set(names)
    for name in names:
        spelled.update(terms.key_forms(name))
        spelled.update(terms.member_spellings(name))
        english = terms.common_english(name)
        if english:
            spelled.add(english)
    return frozenset(spelled)


dataset.register_reset(_service_fields.cache_clear)


@lru_cache(maxsize=None)
def _built_in_fields(kind: str) -> frozenset[str]:
    """The fields the kind has without declaring them (_BUILT_IN_FIELDS), in every spelling the
    data knows. The set errs on the wide side like _service_fields: it only silences."""
    spelled: set[str] = set()
    for name in _BUILT_IN_FIELDS.get(kind, ()):
        spelled.add(name)
        spelled.update(terms.key_forms(name))
        spelled.update(terms.member_spellings(name))
        english = terms.common_english(name)
        if english:
            spelled.add(english)
    return frozenset(spelled)


def _precise_forms(name: str) -> frozenset[str]:
    """Both spellings of a platform name, the term pair and nothing else: the forms a name is
    reported by must not reach past it, as the wide silencing sets may."""
    return frozenset({name, *terms.key_forms(name), terms.common_english(name) or name})


@lru_cache(maxsize=None)
def _declared_only(kind: str) -> tuple[frozenset[str], ...]:
    """The spellings of each standard attribute the kind has only when it declares it
    (_DECLARED_ONLY): a name that matches is reported unless declared."""
    return tuple(_precise_forms(name) for name in _DECLARED_ONLY.get(kind, ()))


@lru_cache(maxsize=None)
def _absent(kind: str) -> frozenset[str]:
    """The spellings of the service fields the kind does not have (_ABSENT)."""
    return frozenset(form for name in _ABSENT.get(kind, ()) for form in _precise_forms(name))


@lru_cache(maxsize=None)
def _computed(kind: str) -> frozenset[str]:
    """The spellings of the computed fields that fail the apply for the kind (_COMPUTED)."""
    return frozenset(form for name in _COMPUTED.get(kind, ()) for form in _precise_forms(name))


dataset.register_reset(_built_in_fields.cache_clear)
dataset.register_reset(_declared_only.cache_clear)
dataset.register_reset(_absent.cache_clear)
dataset.register_reset(_computed.cache_clear)


def _declared_fields(data: dict, kind: str) -> set[str] | None:
    """The names the element declares for its fields; None for a section of an unexpected shape."""
    names: set[str] = set()
    name_keys = terms.key_forms("Имя")
    for section in _FIELD_SECTIONS:
        items = value_of(data, section, kind)
        if items is None:
            continue
        if not isinstance(items, list):
            return None
        for item in items:
            if isinstance(item, dict):
                names.update(item[key] for key in name_keys
                             if isinstance(item.get(key), str))
    return names


def _known(name: str, declared: set[str], kind: str) -> bool:
    """Whether the name is a field of the element, in either spelling of a platform word."""
    if name in declared:
        return True
    for forms in _declared_only(kind):
        if name in forms:
            return bool(forms & declared)
    if name in _absent(kind):
        return False
    if name in _service_fields() or name in _built_in_fields(kind):
        return True
    russian, english = terms.common_russian(name), terms.common_english(name)
    return bool(russian and (russian in declared or russian in _service_fields()
                             or russian in _built_in_fields(kind))
                or english and english in declared)


@rule(UNKNOWN, f"{UNKNOWN}.title", "A", severity=Severity.ERROR)
def compute_permissions_by_unknown(source: SourceFile) -> Iterable[Diagnostic]:
    """A name in `ComputePermissionsBy` that is no field of the element.

    A probe on a server answered `Attribute "X" is not found` at the name in the list for an
    attribute nobody declared (a misspelt name), for a standard attribute left out of the
    attributes (the name of a catalog, the number of a document), for the identifier and for
    the name of a tabular section; a declared attribute, a dimension, a resource and an
    attribute of a register compiled. The standard attributes are declared in the attributes
    like any other (the metamodel dispatches the item by its name), so the declared names are
    the fields - together with the service fields the element has without a declaration
    (_service_fields) and the built-in fields of its kind (_BUILT_IN_FIELDS). The service set
    is wide on purpose and costs findings; it makes three exceptions. The number of a document
    is known to the query tables as a service field, yet the document has it only when it
    declares it (_DECLARED_ONLY); a settings storage has no deletion mark (_ABSENT); and the
    deletion mark and the presentation are computed fields, which the compiler takes and the
    apply of the build then fails on inside the server (_COMPUTED, reported apart as
    `.computed`).
    """
    if source.kind != "yaml" or not _HAVE_YAML:
        return
    kind = object_kind_fast(source)
    if kind not in _UNKNOWN_KINDS or _BY not in _control_props(kind):
        return
    data, error = _parsed(source)
    if error is not None or object_kind(data) != kind:
        return
    declared = _declared_fields(data, kind)
    if declared is None:
        return
    root = _composed(source)
    if root is None:
        return
    props = _control_props(kind)
    control_keys = {_CONTROL, (metamodel.properties(kind).get(_CONTROL) or {}).get("en")}
    by_keys = {_BY, (props.get(_BY) or {}).get("en")}
    listed = _node_of(root, (control_keys, by_keys))
    if not isinstance(listed, yaml.SequenceNode):
        return
    for item in listed.value:
        if not isinstance(item, yaml.ScalarNode) or item.tag != "tag:yaml.org,2002:str":
            continue
        # Only a plain name is judged: no probe has asked the build about a path through a
        # reference, and a guess about it would be a finding on a list the build may take.
        if not _IDENTIFIER_RE.fullmatch(item.value):
            continue
        if item.value in _computed(kind) and item.value not in declared:
            key = f"{UNKNOWN}.computed"
        elif _known(item.value, declared, kind):
            continue
        else:
            key = f"{UNKNOWN}.unknown"
        yield Diagnostic(source.rel, item.start_mark.line + 1, item.start_mark.column + 1,
                         UNKNOWN, Severity.ERROR, i18n.t(key, name=item.value))
