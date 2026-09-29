"""The handlers a module of an interface component overrides by name.

A component module may declare a method the platform itself calls: `AfterCreate` of every
component, `BeforeClose` of a form, `BeforeWrite` of an object form. Such a method is an
override - it carries the `@Handler` annotation, and its name is the platform's word, not the
project's: the compiler finds it by that name, in either spelling. A method under the same
annotation that overrides nothing is refused ("A handler associated with method X is not
found"), and a translated project has to spell the override the way the platform does.

The list comes from the distribution: each component description it ships names the
handlers of a module built on that component (`moduleHandlers`), both spellings included, and
the stdlib extractor keeps them in the `module_handlers` section of stdlib.json - each type
with its OWN handlers. A component inherits the handlers of its bases, so the lookup walks
`bases`, the way the member sets are expanded. A handler may be there in some compatibility
modes only - the description says which (see `declared_in`).

The handlers of the other modules (an object module, the record set of a register, the module
of a scheduled job) are declared by the compiler in code, not in a description; the extractor
reads that code (xbsl/extract/elementhandlers.py) and keeps the result in the
`element_module_handlers` section, by the kind of the element and its module: "" for the
element's own module, the Russian `Object`, `RecordSet`, `Record` for the others. Some of those modules
take handler names from the element's own description at build time - the operations of a
processing, the operations of a SOAP client, the record-level security handlers of an entity -
and their slot says `dynamic`: any name may be a handler there, and element_slot answers None.
Without the sections - a public checkout, or data extracted before they existed - every answer
is empty, and a caller judges nothing.

The record-level security handlers are the one dynamic source whose names are the platform's
and not the project's. The build picks the handler by the access settings of the element, so
the extractor sees a term read from metadata; the terms it picks from are three constants of the
distribution, listed in RECORD_SECURITY with their proof. element_rows adds them to a module
whose slot names that source, and handler_names to the names of the whole data.

Which of them an entity declares follows from its kind (record_security_rows), and whether the
compiler USES them - and the permissions handler beside them - from its access settings: a
handler the element declares but its settings leave off is refused with a message of its own
("Handler X is not used in this project item"). access_slot splits the handlers of such a module
into the ones the settings use and the ones they leave off.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from xbsl import dataset, terms

#: The section of stdlib.json this module reads.
SECTION = "module_handlers"
#: The section with the handlers of the modules of the other elements.
ELEMENT_SECTION = "element_module_handlers"

#: The record-level security handlers of an entity, both spellings. The build names the handler
#: by the access settings of the element (`PermissionsComputedForEachObject`): the permissions of
#: the objects for every entity, the access keys for read and for update apart for a periodic
#: register. The three terms are constants of the access-control constants class of the
#: distribution (`AccessControlCommonConstants`, the fields ending in `_NAME_TERM`), and the
#: producer of the access-control metadata (`AccessControlRtMetadataProducer`, the constants set
#: has one of its own) stores one of them as the handler term of the entity - the very value
#: the extractor meets as a term read at build time. The help names the same three handlers
#: (topics manage-access-control and rights-for-information-registers).
RECORD_SECURITY: tuple[dict, ...] = (
    {"ru": "ВычислитьРазрешенияДоступаДляОбъектов", "en": "ComputeAccessPermissionsForObjects"},
    {"ru": "ВычислитьКлючиДоступаДляЧтения", "en": "ComputeAccessKeysForRead"},
    {"ru": "ВычислитьКлючиДоступаДляИзменения", "en": "ComputeAccessKeysForUpdate"},
)
#: The place a slot names for them in `dynamic`: the handler term of the access-control
#: metadata of an entity, as the extractor writes it.
RECORD_SECURITY_SOURCE = "EntityAccessControlMetadata$HandlerMetadata.computeHandlerTerm"

_OBJECTS, _READ, _UPDATE = RECORD_SECURITY
#: The record-level security handlers each entity kind declares. The access-control metadata of
#: the entity lists them: an entity with objects takes the permissions for objects (the object
#: entity producer, `produceDefaultEntityAccessControlMetadata`); a register takes the access keys
#: for read and for update apart when it computes them separately (the register producer,
#: `shouldComputeAccessKeysSeparately`: always for an accumulation register, see _PERIODIC_KIND
#: for an information register); a constants set takes the keys apart, always (its own
#: producer).
_RECORD_SECURITY_BY_KIND: dict[str, tuple[dict, ...]] = {
    "Справочник": (_OBJECTS,),
    "Документ": (_OBJECTS,),
    "ПланОбмена": (_OBJECTS,),
    "ХранилищеНастроек": (_OBJECTS,),
    "ИнтегрируемоеПриложение": (_OBJECTS,),
    "РегистрНакопления": (_READ, _UPDATE),
    "НаборКонстант": (_READ, _UPDATE),
}
#: The information register computes the keys apart only when it is periodic (the register
#: producer asks `isPeriodic`: a periodicity other than the non-periodic one); a non-periodic
#: register takes the permissions for objects.
_PERIODIC_KIND = "РегистрСведений"
#: The kinds whose records never compute permissions for each object: the record type of a
#: constants set keeps the default of the entity type (`isRlsEnabled()` is false), so the
#: handlers it declares are never used.
_NO_PER_OBJECT = frozenset({"НаборКонстант"})

#: The handler the own module of an element with access settings computes permissions in. The
#: access-control provider of the compiler declares it beside the record-level security handlers
#: and uses it only when the settings compute some permission (`hasComputedPrivileges()`: a
#: privilege computed, for each object or not) and are not the standard ones of a settings
#: storage (`hasDefaultPrivileges()`); the record-level security handlers only when they compute
#: the permissions for each object (`isRlsEnabled()`) and are not the standard ones either.
ACCESS_PERMISSIONS = {"ru": "ВычислитьРазрешенияДоступа", "en": "ComputeAccessPermissions"}
#: The kind the data files the module of the project under - the kind of the project description.
PROJECT_KIND = "Проект"


@dataclass(frozen=True)
class AccessSettings:
    """What the access settings of an element say about its access handlers."""

    computed: bool = False     # some privilege computes its permissions, for each object or not
    per_object: bool = False   # some privilege computes them for each object
    standard: bool = False     # the standard permissions of a settings storage
    periodic: bool = False     # a periodic information register


def record_security_rows(kind: str, periodic: bool | None = False) -> tuple[dict, ...] | None:
    """The record-level security handlers an entity of `kind` declares, None for another kind.

    `periodic` matters for an information register only; None there - a periodicity that cannot
    be told - answers every handler the kind may declare.
    """
    if kind == _PERIODIC_KIND:
        if periodic is None:
            return RECORD_SECURITY
        return (_READ, _UPDATE) if periodic else (_OBJECTS,)
    return _RECORD_SECURITY_BY_KIND.get(kind)


def _catalog() -> dict:
    return dataset.load_optional("stdlib.json") or {}


@lru_cache(maxsize=1)
def _table() -> dict[str, tuple[dict, ...]]:
    """{type: its own handler rows} - both spellings of the type as keys, see dataset."""
    section = _catalog().get(SECTION)
    if not isinstance(section, dict):
        return {}
    return {
        str(owner): tuple(row for row in rows if isinstance(row, dict)
                          and isinstance(row.get("ru"), str) and isinstance(row.get("en"), str))
        for owner, rows in section.items() if isinstance(rows, list)
    }


def available() -> bool:
    """Whether the data carries the handler lists at all."""
    return bool(_table())


@lru_cache(maxsize=None)
def rows_of(type_name: str) -> tuple[dict, ...]:
    """The handler rows of a module built on `type_name`: its own and its bases', nearest first.

    Empty when the type is unknown to the catalog or the data carries no lists. A row is
    {"ru", "en"} plus the compatibility modes (`from`, `to`) where the description states them;
    which modes those admit is `declared_in`'s call.
    """
    table = _table()
    if not table:
        return ()
    bases = _catalog().get("bases") or {}
    if type_name not in table and type_name not in bases:
        return ()
    ancestors = bases.get(type_name) or ()
    owners = [type_name, *reversed(dataset.nearest_last(ancestors, bases))]
    rows: list[dict] = []
    seen: set[str] = set()
    for owner in owners:
        for row in table.get(owner, ()):
            if row["ru"] not in seen:
                seen.add(row["ru"])
                rows.append(row)
    return tuple(rows)


def declared_in(row: dict, mode: tuple[int, ...] | None) -> bool:
    """Whether a module declares the handler of `row` in compatibility mode `mode`.

    A description limits a handler to some modes by `from` and `to`, and the range is half-open:
    `from` is the first mode the handler is there in, `to` the first mode it is gone from. The
    compiler says so itself. The web chat handler of a client application, `to: 8.0` in the
    description, is declared by the handler provider of the compiler only while the mode is
    below 8.0 (`G5CompatibilityMode.lt(CMODE_8_0)`), under a term named for that range
    (`_00_80`); the web chat property of the newer modes is declared from 8.0 on, the mode
    itself included (`ge(CMODE_8_0)`, a term named `_80_00`). The descriptions of the components
    read the same way against the help: `to: 8.0` of the groups the help marks
    `Версия 7.0 и ниже`, and the `from` of a component is the mode its page marks "and above".

    An unknown mode (None) declares every row: which of them the project has cannot be told,
    and a row taken away on a guess would report an override the compiler accepts.
    """
    if mode is None:
        return True
    # The reader of a dotted version the rules share; imported here, since the rules import
    # this module.
    from xbsl.rules.component_since import _version

    first, last = _version(row.get("from")), _version(row.get("to"))
    return (first is None or first <= mode) and (last is None or mode < last)


@lru_cache(maxsize=1)
def all_names() -> frozenset[str]:
    """Both spellings of every handler a module of any component may override."""
    return frozenset(
        name for rows in _table().values() for row in rows for name in (row["ru"], row["en"])
    )


def base_head(written: str) -> str:
    """The name a base is looked up by: `ObjectForm<Tasks.Object>` -> `ObjectForm`.

    The generic arguments and the package (`Std::Interface::Forms::Form`) are dropped - the
    catalog keys a type by its head, and so does a project its components.
    """
    return written.split("<", 1)[0].strip().rpartition("::")[2].strip()


def platform_base(head: str, project_base, limit: int = 32) -> str:
    """The platform type a component module finally builds on, or "" when that cannot be told.

    `head` is the base the component's yaml names (`Наследует.Тип`, generic arguments and
    package already dropped). `project_base(name)` answers the base head of a component the
    PROJECT declares under that name, "" for a name the project has as something else, and
    None when the project has no element of that name: a component may build on another
    component of the project, and only the end of that chain is the platform's. A chain that
    loops, runs too deep or ends in a name neither side knows gives "".
    """
    seen: set[str] = set()
    while head and head not in seen and len(seen) < limit:
        seen.add(head)
        found = project_base(head)
        if found is None:
            return head if rows_of(head) else ""
        head = found
    return ""


@lru_cache(maxsize=1)
def _elements() -> dict[str, dict[str, dict]]:
    """{kind: {module: {"handlers": rows, "dynamic": sources}}} - the rows checked like above."""
    section = _catalog().get(ELEMENT_SECTION)
    if not isinstance(section, dict):
        return {}
    found: dict[str, dict[str, dict]] = {}
    for kind, modules in section.items():
        if not isinstance(modules, dict):
            continue
        for module, slot in modules.items():
            if not isinstance(slot, dict):
                continue
            rows = tuple(row for row in slot.get("handlers") or () if isinstance(row, dict)
                         and isinstance(row.get("ru"), str) and isinstance(row.get("en"), str))
            dynamic = tuple(str(item) for item in slot.get("dynamic") or ())
            found.setdefault(str(kind), {})[str(module)] = {"handlers": rows, "dynamic": dynamic}
    return found


def element_available() -> bool:
    """Whether the data carries the handlers of the modules of the other elements."""
    return bool(_elements())


def element_slot(kind: str, module: str) -> tuple[dict, ...] | None:
    """The handler rows of the module `module` of an element of `kind`, None when not to judge.

    `module` is "" for the element's own module, else the word its file adds (the Russian `Object`). None
    answers both "the data knows nothing of this module" and "its handler names are taken at
    build time" - in either case no name can be called wrong.
    """
    slot = _elements().get(kind, {}).get(module)
    if slot is None or slot["dynamic"]:
        return None
    return slot["handlers"]


def access_slot(kind: str, module: str, settings: AccessSettings | None
                ) -> tuple[tuple[dict, ...], tuple[dict, ...]] | None:
    """(the rows the settings use, the rows they leave off) of a module that takes the
    record-level security handlers, None for any other module or a kind not known here.

    The own module of an entity is dynamic only for those handlers (RECORD_SECURITY_SOURCE):
    the kind tells which of them it declares (record_security_rows), and `settings` - read from
    the description of the element - which of those and of the permissions handler the compiler
    uses. Without settings (a description that cannot be read) every handler counts as used:
    only a name the element cannot declare at all is then wrong.
    """
    slot = _elements().get(kind, {}).get(module)
    if slot is None or set(slot["dynamic"]) != {RECORD_SECURITY_SOURCE}:
        return None
    periodic = settings.periodic if settings is not None else None
    security = record_security_rows(kind, periodic)
    if security is None:
        return None
    rows = slot["handlers"]
    if settings is None:
        return rows + security, ()
    computed = settings.computed and not settings.standard
    per_object = (settings.per_object and not settings.standard
                  and kind not in _NO_PER_OBJECT)
    used = tuple(row for row in rows if computed or row["ru"] != ACCESS_PERMISSIONS["ru"])
    off = tuple(row for row in rows if row not in used)
    return (used + security, off) if per_object else (used, off + security)


def unused_reason(kind: str, row: dict, settings: AccessSettings | None) -> str:
    """Why the settings leave off the handler of `row` (one access_slot left off): the standard
    permissions, a kind that never computes permissions for each object, or the value missing
    from the settings - `computed` for the permissions handler, `per-object` for the rest."""
    if settings is not None and settings.standard:
        return "standard"
    if row["ru"] == ACCESS_PERMISSIONS["ru"]:
        return "computed"
    return "never" if kind in _NO_PER_OBJECT else "per-object"


def project_rows() -> tuple[dict, ...]:
    """The handlers the module of the project may override (`Проект.xbsl` beside the project
    description), () when the data does not list them.

    The compiler declares them for the project of an application only (the project kind of the
    description, the default one) and not in a mobile application; a library or an extension
    project declares none.
    """
    slot = _elements().get(PROJECT_KIND, {}).get("")
    return slot["handlers"] if slot is not None and not slot["dynamic"] else ()



def element_rows(kind: str, module: str) -> tuple[dict, ...]:
    """Every handler row known for the module `module` of an element of `kind`, () when none.

    Unlike element_slot, a module that takes more names at build time answers too - what the
    translator needs, not what a rule judges by. It answers the rows the compiler declares there
    whatever the element's description says and, where the slot takes the record-level security
    handlers (RECORD_SECURITY_SOURCE), those: all of them are the platform's words. The other
    names such a module takes - the operations of a processing, of a SOAP client - are the
    project's or the service's, and are not here.
    """
    slot = _elements().get(kind, {}).get(module)
    if slot is None:
        return ()
    rows = slot["handlers"]
    if RECORD_SECURITY_SOURCE in slot["dynamic"]:
        known = {row["ru"] for row in rows}
        rows = rows + tuple(row for row in RECORD_SECURITY if row["ru"] not in known)
    return rows


@lru_cache(maxsize=1)
def element_modules() -> frozenset[str]:
    """The module words the section names (the Russian `Object`, `RecordSet`), own module aside."""
    return frozenset(module for modules in _elements().values() for module in modules if module)


@lru_cache(maxsize=1)
def element_names() -> frozenset[str]:
    """Both spellings of every handler a module of any other element may override."""
    return frozenset(
        name for modules in _elements().values() for slot in modules.values()
        for row in slot["handlers"] for name in (row["ru"], row["en"])
    )


@lru_cache(maxsize=1)
def handler_names() -> frozenset[str]:
    """Both spellings of every handler the data lets some module override.

    The component lists, the element lists and, once some slot of the element lists takes them,
    the record-level security handlers (see element_rows). Empty without the sections.
    """
    names = set(all_names()) | element_names()
    if any(RECORD_SECURITY_SOURCE in slot["dynamic"]
           for modules in _elements().values() for slot in modules.values()):
        names.update(name for row in RECORD_SECURITY for name in (row["ru"], row["en"]))
    return frozenset(names)


@lru_cache(maxsize=1)
def module_words() -> dict[str, str]:
    """{the word a module file adds, in either spelling: the module as the data names it}."""
    words: dict[str, str] = {}
    for module in element_modules():
        words[module] = module
        english = terms.facet_suffix_english(module)
        if english:
            words[english] = module
    return words


def element_module(stem: str) -> tuple[str, str]:
    """(the stem of the element's yaml, the module) of a module file stem.

    `Stock.Object` gives (`Stock`, the Russian `Object`) - the file pairs with `Stock.yaml`; a
    stem without a module word the section names is the element's own module: (stem, "").
    """
    base, dot, word = stem.rpartition(".")
    if dot and "/" not in word and word in module_words():
        return base, module_words()[word]
    return stem, ""


def _reset() -> None:
    _table.cache_clear()
    rows_of.cache_clear()
    all_names.cache_clear()
    _elements.cache_clear()
    element_modules.cache_clear()
    element_names.cache_clear()
    handler_names.cache_clear()
    module_words.cache_clear()


dataset.register_reset(_reset)
# Answers read while the data was missing are empty; the recheck drops them with the rest.
dataset.register_recheck(_reset)
