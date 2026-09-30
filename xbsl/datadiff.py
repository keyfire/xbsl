"""Diff of two language-data versions: what changed in the platform between releases.

    xbsl data-diff                  # the default version against the closest older one
    xbsl data-diff 1.2.3+4 1.3.0    # explicit versions
    xbsl data-diff --format md      # a full Markdown report (text is capped per list)
    xbsl data-diff --limit 0        # the text report with every list in full

Reads the RAW versioned files (language/stdlib/metamodel/uischema/terms/uiterms/terms_full
.json and the docs.sqlite page index) from the same data root the linter uses. Every section of
every file is compared. The sections that need it have a comparison of their own; any other one
- a section a newer extractor adds included - is compared entry by entry, so a change cannot
stay silent merely because nobody taught the diff where to look. Only `meta` (the version, the
counts and the notes of an extraction) and the token numbering of the grammar are left out.

stdlib members are compared with the inheritance expanded, and a change is reported at the type
that makes it rather than at every descendant (see _diff_expanded_members); the other sections
kept per type in the same own or fully expanded form - signatures, method type parameters,
deprecations, checked results, component properties, bases - are lifted the same way.
Documentation pages are compared by a hash of their HTML besides their ids and titles.
Comparing datasets produced by different extractor generations can report tooling changes as
platform changes - regenerate both versions with the current extractors for a clean diff.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from pathlib import Path

from xbsl import dataset, i18n
from xbsl.dataset import MEMBER_KINDS, nearest_last

MESSAGES = {
    "datadiff.description": {
        "ru": "Сравнение двух версий данных Элемента: что изменилось в платформе между релизами.",
        "en": "Compare two Element data versions: what changed in the platform between releases.",
    },
    "datadiff.header": {
        "ru": "Данные 1С:Элемент: {old} -> {new}",
        "en": "1C:Element data: {old} -> {new}",
    },
    "datadiff.missing": {
        "ru": "Нет файлов для сравнения (пропущено): {files}",
        "en": "Files absent on one side (skipped): {files}",
    },
    "datadiff.no-changes": {
        "ru": "изменений нет",
        "en": "no changes",
    },
    "datadiff.no-older": {
        "ru": "Не с чем сравнивать: у версии '{version}' нет более старой среди доступных ({available}). "
              "Укажите версии явно: xbsl data-diff <старая> <новая>.",
        "en": "Nothing to compare against: no version older than '{version}' among the available "
              "ones ({available}). Pass the versions explicitly: xbsl data-diff <old> <new>.",
    },
    "datadiff.more": {
        "ru": "... и ещё {n}",
        "en": "... and {n} more",
    },
    "datadiff.written": {
        "ru": "Записано: {path}",
        "en": "Written: {path}",
    },
    "datadiff.pages": {
        "ru": "страниц: {old} -> {new}",
        "en": "pages: {old} -> {new}",
    },
    "datadiff.help.old": {
        "ru": "старая версия данных (по умолчанию – ближайшая младше новой)",
        "en": "the old data version (default: the closest one older than the new)",
    },
    "datadiff.help.new": {
        "ru": "новая версия данных (по умолчанию – версия по умолчанию из индекса)",
        "en": "the new data version (default: the index default)",
    },
    "datadiff.help.format": {
        "ru": "вид отчёта: text (списки ограничены --limit), md (полный Markdown), json",
        "en": "report format: text (lists capped by --limit), md (full Markdown), json",
    },
    "datadiff.help.out": {
        "ru": "записать отчёт в файл вместо вывода на экран",
        "en": "write the report to a file instead of stdout",
    },
    "datadiff.help.limit": {
        "ru": "сколько имён показывать в каждом списке text-отчёта (0 – без ограничения)",
        "en": "how many names to show per list in the text report (0 - unlimited)",
    },
    "datadiff.help.data-dir": {
        "ru": "корень данных (по умолчанию – тот же, что у линтера; также env XBSL_DATA_DIR)",
        "en": "the data root (default: same as the linter; also env XBSL_DATA_DIR)",
    },
    # Section and group titles.
    "datadiff.section.language": {"ru": "Язык", "en": "Language"},
    "datadiff.section.stdlib": {"ru": "Каталог stdlib", "en": "stdlib catalog"},
    "datadiff.section.metamodel": {"ru": "Метамодель конфигурации", "en": "Configuration metamodel"},
    "datadiff.section.uischema": {"ru": "Компоненты интерфейса", "en": "Interface components"},
    "datadiff.section.terms": {"ru": "Термины (ru/en пары)", "en": "Terms (ru/en pairs)"},
    "datadiff.section.uiterms": {"ru": "Написания интерфейса (ru/en)",
                                 "en": "Interface spellings (ru/en)"},
    "datadiff.section.terms_full": {"ru": "Словарь компилятора (ru/en)",
                                    "en": "Compiler dictionary (ru/en)"},
    "datadiff.section.docs": {"ru": "Документация", "en": "Documentation"},
    "datadiff.group.keywords": {"ru": "ключевые слова", "en": "keywords"},
    "datadiff.group.forms": {"ru": "формы ключевых слов", "en": "keyword forms"},
    "datadiff.group.operators": {"ru": "операторы", "en": "operators"},
    "datadiff.group.types": {"ru": "типы", "en": "types"},
    "datadiff.group.members": {"ru": "члены типов", "en": "type members"},
    "datadiff.group.member-types": {"ru": "типы членов", "en": "member result types"},
    "datadiff.group.globals": {"ru": "глобальные имена", "en": "global names"},
    "datadiff.group.object-members": {"ru": "порождаемые члены объектов", "en": "generated object members"},
    "datadiff.group.object-kinds": {"ru": "виды объектов с порождаемыми членами",
                                    "en": "object kinds with generated members"},
    "datadiff.group.managers": {"ru": "виды с членами менеджера", "en": "kinds with manager members"},
    "datadiff.group.manager-members": {"ru": "члены менеджеров", "en": "manager members"},
    "datadiff.group.facets": {"ru": "фасеты", "en": "facets"},
    "datadiff.group.facet-members": {"ru": "члены фасетов", "en": "facet members"},
    "datadiff.group.generated-types": {"ru": "порождаемые типы", "en": "generated types"},
    "datadiff.group.generated-members": {"ru": "члены порождаемых типов",
                                        "en": "members of generated types"},
    "datadiff.group.names": {"ru": "имена символов", "en": "symbol names"},
    "datadiff.group.component-props": {"ru": "свойства компонентов", "en": "component properties"},
    "datadiff.group.retired-components": {"ru": "снятые компоненты", "en": "retired components"},
    "datadiff.group.component-from": {"ru": "режим совместимости компонентов",
                                      "en": "compatibility modes of components"},
    "datadiff.group.module-handlers": {"ru": "обработчики модулей компонентов",
                                       "en": "component module handlers"},
    "datadiff.group.element-module-handlers": {"ru": "обработчики модулей элементов",
                                               "en": "element module handlers"},
    "datadiff.group.global-availability": {"ru": "доступность глобальных имен",
                                           "en": "availability of global names"},
    "datadiff.group.type-availability": {"ru": "доступность типов", "en": "type availability"},
    "datadiff.group.manager-member-types": {"ru": "типы членов менеджеров",
                                            "en": "manager member result types"},
    "datadiff.group.checked-return-methods": {"ru": "методы с проверяемым результатом",
                                              "en": "methods with a checked result"},
    "datadiff.group.member-signatures": {"ru": "сигнатуры методов", "en": "method signatures"},
    "datadiff.group.bases": {"ru": "базовые типы", "en": "base types"},
    "datadiff.group.generic-bases": {"ru": "аргументы обобщенных баз", "en": "generic base arguments"},
    "datadiff.group.type-ctors": {"ru": "конструкторы типов", "en": "type constructors"},
    "datadiff.group.type-params": {"ru": "параметры типов", "en": "type parameters"},
    "datadiff.group.type-param-variance": {"ru": "вариантность параметров типов",
                                           "en": "type parameter variance"},
    "datadiff.group.member-type-params": {"ru": "параметры типов методов",
                                          "en": "method type parameters"},
    "datadiff.group.deprecated-members": {"ru": "устаревшие члены", "en": "deprecated members"},
    "datadiff.group.classes": {"ru": "классы", "en": "classes"},
    "datadiff.group.class-attrs": {"ru": "признаки классов", "en": "class attributes"},
    "datadiff.group.props": {"ru": "свойства", "en": "properties"},
    "datadiff.group.enums": {"ru": "перечисления", "en": "enumerations"},
    "datadiff.group.enum-values": {"ru": "значения перечислений", "en": "enumeration values"},
    "datadiff.group.enum-packages": {"ru": "пакеты перечислений", "en": "enumeration packages"},
    "datadiff.group.vid2class": {"ru": "виды элементов", "en": "element kinds"},
    "datadiff.group.components": {"ru": "компоненты", "en": "components"},
    "datadiff.group.flags": {"ru": "признаки компонентов", "en": "component flags"},
    "datadiff.group.yaml-props": {"ru": "ключи yaml компонентов", "en": "component yaml keys"},
    "datadiff.group.pages": {"ru": "страницы", "en": "pages"},
    "datadiff.group.pages-changed": {"ru": "содержимое страниц", "en": "page content"},
    "datadiff.group.methods": {"ru": "методы", "en": "methods"},
    "datadiff.group.properties": {"ru": "свойства", "en": "properties"},
    "datadiff.group.events": {"ru": "события", "en": "events"},
    "datadiff.group.moved": {"ru": "перенесены", "en": "moved"},
    # data that does not say whether a name is a property or a method (see _as_member_lists)
    "datadiff.group.any-members": {"ru": "члены без разделения", "en": "members, undivided"},
    # Titles a section names its own way; a group without one falls back to datadiff.group.*.
    "datadiff.metamodel.vetted": {"ru": "проверенные виды", "en": "vetted kinds"},
    "datadiff.metamodel.common": {"ru": "свойства всех элементов", "en": "properties of every element"},
    "datadiff.uiterms.packages": {"ru": "пакеты", "en": "packages"},
    "datadiff.uiterms.member-names": {"ru": "имена членов", "en": "member names"},
    "datadiff.uiterms.resource-paths": {"ru": "пути ресурсов", "en": "resource paths"},
    "datadiff.terms-full.common": {"ru": "общий словарь", "en": "common dictionary"},
    "datadiff.terms-full.manager-owners": {"ru": "владельцы менеджеров", "en": "manager owners"},
    "datadiff.term.types": {"ru": "типы", "en": "types"},
    "datadiff.term.facets": {"ru": "фасеты", "en": "facets"},
    "datadiff.term.properties": {"ru": "свойства", "en": "properties"},
    "datadiff.term.enums": {"ru": "значения перечислений", "en": "enumeration values"},
    "datadiff.term.query": {"ru": "язык запросов", "en": "query language"},
    "datadiff.term.kinds": {"ru": "виды элементов", "en": "element kinds"},
    "datadiff.term.query-reserved": {"ru": "зарезервированные слова языка запросов",
                                     "en": "reserved words of the query language"},
    "datadiff.term.query-reserved-english-only": {
        "ru": "зарезервированные слова языка запросов только по-английски",
        "en": "reserved words of the query language in English only"},
    "datadiff.term.query-reserved-types": {"ru": "типы литералов языка запросов",
                                           "en": "types of the query language literals"},
}
i18n.register(MESSAGES)

#: Sections of terms.json worth diffing: pairs keyed by the Russian name (its English spelling,
#: or the type of a literal of the query language), and the list of the English-only reserved
#: words. They come first, in this order; a section the list does not know follows them.
_TERM_SECTIONS = ("types", "facets", "properties", "enums", "query", "kinds", "query_reserved",
                  "query_reserved_english_only", "query_reserved_types")
#: uischema property attributes that make a "changed" entry (doc texts excluded - noise).
_UISCHEMA_PROP_KEYS = ("types", "enum", "event", "slot", "nullable", "readonly", "since", "default")
#: uischema component attributes compared as flags.
_UISCHEMA_FLAG_KEYS = ("abstract", "container", "since", "package", "retired", "until", "source")
#: Sections no file is compared by: the version, counts and notes of the extraction itself, and
#: the numbering of the grammar tokens - it moves with any rule of the grammar, and the engine
#: reads the keywords and operators, never the numbers.
_NOT_COMPARED = {"meta", "token_ids"}
#: The fields that name an item of a list of records, tried in this order (see _keyed).
_IDENTITY_FIELDS = ("ru", "signature", "name", "id", "term")


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", version))


def previous_version(new: str, available: list[str]) -> str | None:
    """The closest version older than `new` by numeric ordering, or None."""
    older = [v for v in available if v != new and _version_key(v) < _version_key(new)]
    return max(older, key=_version_key) if older else None


# --- Loading ------------------------------------------------------------------------------


def _load_json(root: Path, version: str, name: str) -> dict | None:
    path = root / version / name
    if not path.exists():
        return None
    return dataset.read_json(path)


def _digest(html: str | None) -> str:
    return hashlib.sha256((html or "").encode("utf-8")).hexdigest()


def _load_doc_pages(root: Path, version: str) -> dict[str, tuple[str, str, str]] | None:
    """{page id: (title, kind, hash of the HTML)} of the documentation index, or None without one."""
    path = root / version / "docs.sqlite"
    if not path.exists():
        return None
    # Read-only: the diff must not touch a data root it only reads. A file URI needs an
    # absolute path, and --data-dir may be a relative one.
    con = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        rows = con.execute("SELECT id, title, kind, html FROM pages").fetchall()
    finally:
        con.close()
    return {page_id: (title or "", kind or "", _digest(html)) for page_id, title, kind, html in rows}


# --- Pure diffs ---------------------------------------------------------------------------


def _order(values) -> list:
    """Values sorted for a report: names as they sort, a value of another type beside them."""
    return sorted(values, key=lambda value: (value is None, str(value)))


def _added_removed(old, new) -> dict:
    old_set, new_set = set(old or ()), set(new or ())
    out = {}
    if new_set - old_set:
        out["added"] = _order(new_set - old_set)
    if old_set - new_set:
        out["removed"] = _order(old_set - new_set)
    return out


def _prune(value):
    """Drop empty branches so an unchanged section renders as "no changes"."""
    if isinstance(value, dict):
        cleaned = {k: _prune(v) for k, v in value.items()}
        return {k: v for k, v in cleaned.items() if v not in ({}, [], None)}
    return value


def _plain(values: list) -> bool:
    return all(value is None or isinstance(value, (str, int, float, bool)) for value in values)


def _identity(item: dict, field: str):
    value = item.get(field)
    if field == "term" and isinstance(value, dict):
        return value.get("ru") or value.get("en")
    return value


def _keyed(items: list) -> dict | None:
    """A list of records as {name: record}, or None when no field names every record once.

    Handler rows are named by `ru`, the forms of a member by `signature`, the properties of a
    retired component by `term` - comparing such lists by name says which record came, went
    or changed, where comparing them whole could only say that the list is different.
    """
    if not all(isinstance(item, dict) for item in items):
        return None
    for field in _IDENTITY_FIELDS:
        names = [_identity(item, field) for item in items]
        if all(isinstance(name, str) and name for name in names) and len(set(names)) == len(names):
            return dict(zip(names, items))
    return None


def _delta(old, new, ordered: bool = False):
    """What changed between two values of the data, or None when nothing did.

    Two mappings give a keyed delta: the keys that came and went and the delta of every key
    they share. Two lists of records named by a field (see _keyed) compare the same way. Two
    lists of names give the names that came and went. The order of a list counts only where
    `ordered` says it is the point (type parameters, generic arguments): then, as for anything
    else that differs, the delta is the pair [old, new]; elsewhere a list that merely came in
    another order is no change - the extractors sort what has no order of its own.
    """
    if old == new:
        return None
    if isinstance(old, dict) and isinstance(new, dict):
        return _keyed_delta(old, new, ordered)
    if isinstance(old, list) and isinstance(new, list):
        old_keyed, new_keyed = _keyed(old), _keyed(new)
        if old_keyed is not None and new_keyed is not None:
            return _keyed_delta(old_keyed, new_keyed, ordered) or ([old, new] if ordered else None)
        if not ordered and _plain(old) and _plain(new):
            return _added_removed(old, new) or None
    return [old, new]


def _keyed_delta(old: dict | None, new: dict | None, ordered: bool = False,
                 skip=frozenset()) -> dict:
    """{"added": [keys], "removed": [keys], "changed": {key: delta}} of two mappings.

    `skip` names keys left out on both sides: a type that came or went is named once, among the
    types, rather than again in every section keyed by type.
    """
    old = {k: v for k, v in (old or {}).items() if k not in skip}
    new = {k: v for k, v in (new or {}).items() if k not in skip}
    out = _added_removed(old, new)
    changed = {}
    for key in _order(set(old) & set(new)):
        delta = _delta(old[key], new[key], ordered)
        if delta is not None:
            changed[key] = delta
    if changed:
        out["changed"] = changed
    return out


def _section_delta(old, new, ordered: bool = False) -> dict:
    """The delta of one top-level section of any shape; a side that lacks it counts as empty."""
    if isinstance(old, dict) or isinstance(new, dict):
        return _keyed_delta(old if isinstance(old, dict) else {},
                            new if isinstance(new, dict) else {}, ordered)
    if isinstance(old, list) or isinstance(new, list):
        old_list = old if isinstance(old, list) else []
        new_list = new if isinstance(new, list) else []
        old_keyed, new_keyed = _keyed(old_list), _keyed(new_list)
        if old_keyed is not None and new_keyed is not None and (old_list or new_list):
            return _keyed_delta(old_keyed, new_keyed, ordered)
        if _plain(old_list) and _plain(new_list):
            return _added_removed(old_list, new_list)
    return {} if old == new else {"changed": {"value": [old, new]}}


def _other_sections(old: dict, new: dict, known) -> dict:
    """Sections of a file that no dedicated comparison reads, compared entry by entry.

    This is what keeps the diff from going blind to a section: the one a newer extractor adds
    (or one the list above forgot) is reported like any other instead of being passed over.
    """
    out = {}
    for section in _order(set(old) | set(new)):
        if section in known or section in _NOT_COMPARED:
            continue
        out[section] = _section_delta(old.get(section), new.get(section))
    return out


def _diff_member_lists(old: dict, new: dict) -> dict:
    """Per-name diff of {name: {"methods": [...], "properties": [...]}} sections."""
    out = {}
    for name in sorted(set(old) & set(new)):
        entry = {}
        for key in ("methods", "properties", "events", "members"):
            delta = _added_removed(old[name].get(key), new[name].get(key))
            if delta:
                entry[key] = delta
        if entry:
            out[name] = entry
    return out


def _as_member_lists(section) -> dict:
    """A section of member lists brought to one shape, whichever vintage the data is.

    manager_members keeps properties and methods apart; data generated before the split is a
    plain list of names per kind, and comparing the two shapes head-on would report every kind
    as changed. Such a list is put under a bucket of its own, so an old-to-new comparison says
    what it honestly is: the names moved from an undivided list into the divided one.
    """
    out: dict = {}
    for name, entry in (section or {}).items():
        out[name] = entry if isinstance(entry, dict) else {"members": list(entry or ())}
    return out


def _diff_name_sets(old: dict, new: dict) -> dict:
    """Per-name diff of {"Имя": ["член", ...]} sections (object/manager members)."""
    out = {}
    for name in sorted(set(old) & set(new)):
        delta = _added_removed(old[name], new[name])
        if delta:
            out[name] = delta
    return out


def diff_language(old: dict, new: dict) -> dict:
    old_kw, new_kw = old.get("keywords") or {}, new.get("keywords") or {}
    forms = {}
    for group in sorted(set(old_kw) & set(new_kw)):
        delta = _added_removed(old_kw[group].get("forms"), new_kw[group].get("forms"))
        if delta:
            forms[group] = delta
    return _prune({
        "keywords": _added_removed(old_kw, new_kw),
        "forms": forms,
        "operators": _added_removed(old.get("operators"), new.get("operators")),
        **_other_sections(old, new, {"keywords", "operators"}),
    })


def _expand_members(data: dict) -> dict[str, dict[str, set[str]]]:
    """Full member sets per type: own plus every ancestor's own (`bases` is transitively closed).

    The diff MUST compare expanded sets: how members are split between a type and its bases
    is an artifact of how well the extractor resolved the hierarchy of that distribution,
    and comparing the stored own-form reports that artifact as a platform change.
    """
    bases = data.get("bases") or {}
    own = data.get("type_members") or {}
    full = {}
    for name, entry in own.items():
        merged = {kind: set(entry.get(kind) or ()) for kind in MEMBER_KINDS}
        for base in bases.get(name, ()):
            base_entry = own.get(base) or {}
            for kind in MEMBER_KINDS:
                merged[kind] |= set(base_entry.get(kind) or ())
        full[name] = merged
    return full


def _expand_member_types(data: dict) -> dict[str, dict[str, str]]:
    bases = data.get("bases") or {}
    own = data.get("member_types") or {}
    full = {}
    for name, members in own.items():
        merged: dict[str, str] = {}
        for base in bases.get(name, ()):
            merged.update(own.get(base) or {})
        merged.update(members)
        full[name] = merged
    return full


def _expand_own(data: dict, section: str) -> dict[str, dict]:
    """{type: {member: value}} of a section kept in the own form, with the ancestors merged in.

    The same merge the loader does (dataset._expand_inherited): every ancestor's entries, the
    nearest one last, then the type's own - an overridden member keeps its own value.
    """
    bases = data.get("bases") or {}
    own = data.get(section) or {}
    full = {}
    for name in set(own) | set(bases):
        merged: dict = {}
        for base in nearest_last(bases.get(name, ()), bases):
            merged.update(own.get(base) or {})
        merged.update(own.get(name) or {})
        if merged:
            full[name] = merged
    return full


def _as_marks(section) -> dict[str, dict[str, bool]]:
    """{owner: [names]} as {owner: {name: True}} - a set of names compared like a mapping."""
    return {owner: {name: True for name in names or ()} for owner, names in (section or {}).items()}


def _canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _touched(delta: dict) -> list:
    return [*delta.get("added", ()), *delta.get("removed", ()), *(delta.get("changed") or {})]


def _restricted(delta: dict, keys: set) -> dict:
    out = {sign: [k for k in delta.get(sign, ()) if k in keys] for sign in ("added", "removed")}
    out["changed"] = {k: v for k, v in (delta.get("changed") or {}).items() if k in keys}
    return {sign: part for sign, part in out.items() if part}


def _diff_lifted(old_map: dict, new_map: dict, old_bases: dict, new_bases: dict,
                 ordered: bool = False, skip=frozenset()) -> dict:
    """Keyed delta of {owner: {name: value}} maps, each change kept at the owner that makes it.

    A section stored per type fully expanded (or expanded here from its own form) repeats a
    change of a base in every descendant. A change is kept only at an owner none of whose bases
    - in either version - carries the very same change, the way the members above are lifted,
    so the report stays the size of the platform change.
    """
    old_map = {k: v for k, v in old_map.items() if k not in skip}
    new_map = {k: v for k, v in new_map.items() if k not in skip}
    out = _added_removed(old_map, new_map)
    deltas: dict[str, dict] = {}
    marks: dict[tuple[str, str, str], set[str]] = {}

    def mark(owner: str, name: str) -> tuple[str, str, str]:
        return (name, _canonical(old_map[owner].get(name)), _canonical(new_map[owner].get(name)))

    for owner in set(old_map) & set(new_map):
        delta = _keyed_delta(old_map[owner], new_map[owner], ordered)
        if delta:
            deltas[owner] = delta
            for name in _touched(delta):
                marks.setdefault(mark(owner, name), set()).add(owner)
    changed = {}
    for owner in _order(deltas):
        bases = set(old_bases.get(owner) or ()) | set(new_bases.get(owner) or ())
        own = {name for name in _touched(deltas[owner])
               if not any(base in marks.get(mark(owner, name), ()) for base in bases)}
        if own:
            changed[owner] = _restricted(deltas[owner], own)
    if changed:
        out["changed"] = changed
    return out


def _diff_expanded_members(old_full: dict, new_full: dict,
                           old_bases: dict, new_bases: dict) -> dict:
    """Per-type diff of the expanded sets, lifted to the inheritance root.

    A member added to a base reappears in every descendant's expanded set; reporting it
    once - at the type none of whose bases carries the same change - keeps the report the
    size of the actual platform change.
    """
    deltas: dict[str, dict[str, dict[str, list[str]]]] = {}
    marks: dict[tuple[str, str, str], set[str]] = {}
    moves: dict[str, dict[str, list[str]]] = {}
    for name in set(old_full) & set(new_full):
        entry = {}
        for kind in MEMBER_KINDS:
            delta = _added_removed(old_full[name].get(kind, set()),
                                   new_full[name].get(kind, set()))
            if delta:
                entry[kind] = delta
        # A member that LEFT one kind and JOINED another did not disappear - the document was
        # rebuilt around it. Reporting the two halves apart is how a whole shelf of events read
        # as "removed" when the documents gave them a section of their own; a move says what happened.
        moved = _moved_between_kinds(entry)
        if moved:
            moves[name] = moved
            entry = _without_moved(entry, moved)
        for kind, delta in entry.items():
            for sign, members in delta.items():
                for member in members:
                    marks.setdefault((kind, member, sign), set()).add(name)
        if entry:
            deltas[name] = entry
    lifted = {}
    for name in sorted(deltas):
        # Both hierarchies together: either one may know an ancestor the other failed to
        # resolve, and the change is still the ancestor's, not the descendant's.
        bases = set(old_bases.get(name) or ()) | set(new_bases.get(name) or ())
        entry = {}
        for kind, delta in deltas[name].items():
            kept = {}
            for sign, members in delta.items():
                stays = [m for m in members
                         if not any(b in marks.get((kind, m, sign), ()) for b in bases)]
                if stays:
                    kept[sign] = stays
            if kept:
                entry[kind] = kept
        if entry:
            lifted[name] = entry
    for name, moved in moves.items():
        lifted.setdefault(name, {})["moved"] = moved
    return lifted


def _moved_between_kinds(entry: dict) -> dict[str, list[str]]:
    """{member: [where it was, where it is now]} for members that changed kind, not existence."""
    gone = {m: kind for kind, delta in entry.items() for m in delta.get("removed", ())}
    moved: dict[str, list[str]] = {}
    for kind, delta in entry.items():
        for member in delta.get("added", ()):
            was = gone.get(member)
            if was is not None and was != kind:
                moved[member] = [was, kind]
    return moved


def _without_moved(entry: dict, moved: dict[str, list[str]]) -> dict:
    """The same delta with the moved members taken out of both halves."""
    out: dict[str, dict[str, list[str]]] = {}
    for kind, delta in entry.items():
        kept = {sign: [m for m in members if m not in moved] for sign, members in delta.items()}
        kept = {sign: members for sign, members in kept.items() if members}
        if kept:
            out[kind] = kept
    return out


def _rows_by_name(rows) -> dict[str, dict]:
    """Handler rows as {name: row}: a handler is known by its Russian name, the English one
    standing in for a row that has none."""
    out = {}
    for row in rows or ():
        name = row.get("ru") or row.get("en")
        if name:
            out[name] = row
    return out


def _component_handlers(section) -> dict[str, dict]:
    """module_handlers ({type: [rows]}) as {type: {handler: row}}."""
    return {owner: _rows_by_name(rows) for owner, rows in (section or {}).items()}


def _element_handlers(section) -> dict[str, dict]:
    """element_module_handlers as {"<kind>.<module>": {handler: row}}; the own module of an
    element is named by the kind alone.

    One level per module keeps a change readable as "the module lost a handler" instead of a
    path through the kind, the module and the list. A place the module takes handler names
    from at build time (`dynamic`) is an entry of its own, `dynamic:<place>`.
    """
    out: dict[str, dict] = {}
    for kind, modules in (section or {}).items():
        for module, slot in (modules or {}).items():
            entries: dict = dict(_rows_by_name(slot.get("handlers")))
            for place in slot.get("dynamic") or ():
                entries[f"dynamic:{place}"] = True
            out[f"{kind}.{module}" if module else kind] = entries
    return out


#: stdlib sections kept per type in the own form: expanded by `bases`, then lifted to the type
#: that makes a change - (section, whether a list value is a sequence rather than a set).
_STDLIB_OWN_FORM = (
    ("member_signatures", False),
    ("member_type_params", True),
    ("deprecated_members", False),
)
#: stdlib sections compared key by key: (section, whether a list value is a sequence, whether
#: the section is keyed by type - then a type that came or went is left to the "types" group).
_STDLIB_KEYED = (
    ("retired_components", False, False),
    ("component_from", False, False),
    ("global_availability", False, False),
    ("type_availability", False, True),
    ("manager_member_types", False, False),
    ("generic_bases", True, True),
    ("type_ctors", False, True),
    ("type_params", True, True),
    ("type_param_variance", True, True),
)
#: stdlib sections a dedicated part of diff_stdlib reads; the rest go to _other_sections.
_STDLIB_KNOWN = {
    "names", "object_members", "component_props", "module_handlers", "element_module_handlers",
    "type_members", "globals", "manager_members", "facet_members", "generated_members",
    "member_types", "checked_return_methods", "bases",
    *(section for section, _ in _STDLIB_OWN_FORM),
    *(section for section, _, _ in _STDLIB_KEYED),
}


def diff_stdlib(old: dict, new: dict) -> dict:
    old_tm, new_tm = old.get("type_members") or {}, new.get("type_members") or {}
    old_bases, new_bases = old.get("bases") or {}, new.get("bases") or {}
    members = _diff_expanded_members(_expand_members(old), _expand_members(new),
                                     old_bases, new_bases)
    old_mt, new_mt = _expand_member_types(old), _expand_member_types(new)
    mt_marks: dict[tuple[str, str, str], set[str]] = {}
    mt_deltas: dict[str, dict[str, list[str]]] = {}
    for type_name in set(old_mt) & set(new_mt):
        for member, old_type in old_mt[type_name].items():
            new_type = new_mt[type_name].get(member)
            if new_type is not None and new_type != old_type:
                mt_deltas.setdefault(type_name, {})[member] = [old_type, new_type]
                mt_marks.setdefault((member, old_type, new_type), set()).add(type_name)
    member_types = {}
    for type_name in sorted(mt_deltas):
        bases = (new_bases.get(type_name) or []) + (old_bases.get(type_name) or [])
        for member, (old_type, new_type) in mt_deltas[type_name].items():
            if any(b in mt_marks.get((member, old_type, new_type), ()) for b in bases):
                continue
            member_types[f"{type_name}.{member}"] = [old_type, new_type]
    old_fm, new_fm = old.get("facet_members") or {}, new.get("facet_members") or {}
    # A type that came or went is named once, in "types"; the sections keyed by type say
    # what changed about the types both versions have.
    came_or_went = set(old_tm) ^ set(new_tm)
    return _prune({
        "types": _added_removed(old_tm, new_tm),
        "members": members,
        "member_types": member_types,
        "globals": _added_removed(old.get("globals"), new.get("globals")),
        "object_kinds": _added_removed(old.get("object_members"), new.get("object_members")),
        "object_members": _diff_name_sets(
            old.get("object_members") or {}, new.get("object_members") or {}),
        # A member list is compared for the names both versions have; a kind or a generated
        # type that came or went is named apart, the way facets are.
        "managers": _added_removed(old.get("manager_members"), new.get("manager_members")),
        "manager_members": _diff_member_lists(
            _as_member_lists(old.get("manager_members")),
            _as_member_lists(new.get("manager_members")),
        ),
        "facets": _added_removed(old_fm, new_fm),
        "facet_members": _diff_member_lists(old_fm, new_fm),
        "generated_types": _added_removed(old.get("generated_members"), new.get("generated_members")),
        "generated_members": _diff_member_lists(
            old.get("generated_members") or {}, new.get("generated_members") or {}),
        "names": _added_removed(old.get("names"), new.get("names")),
        "module_handlers": _keyed_delta(_component_handlers(old.get("module_handlers")),
                                        _component_handlers(new.get("module_handlers"))),
        "element_module_handlers": _keyed_delta(
            _element_handlers(old.get("element_module_handlers")),
            _element_handlers(new.get("element_module_handlers"))),
        # Stored fully expanded, so a change of a base repeats in every heir - lifted like members.
        "component_props": _diff_lifted(
            _as_marks(old.get("component_props")), _as_marks(new.get("component_props")),
            old_bases, new_bases, skip=came_or_went),
        "checked_return_methods": _diff_lifted(
            _as_marks(old.get("checked_return_methods")),
            _as_marks(new.get("checked_return_methods")),
            old_bases, new_bases, skip=came_or_went),
        # The chain is transitively closed: an ancestor that gains a base passes it to every heir.
        "bases": _diff_lifted(_as_marks(old_bases), _as_marks(new_bases),
                              old_bases, new_bases, skip=came_or_went),
        **{section: _diff_lifted(_expand_own(old, section), _expand_own(new, section),
                                 old_bases, new_bases, ordered, skip=came_or_went)
           for section, ordered in _STDLIB_OWN_FORM},
        **{section: _keyed_delta(old.get(section), new.get(section), ordered,
                                 skip=came_or_went if by_type else frozenset())
           for section, ordered, by_type in _STDLIB_KEYED},
        **_other_sections(old, new, _STDLIB_KNOWN),
    })


def diff_metamodel(old: dict, new: dict) -> dict:
    old_cls, new_cls = old.get("classes") or {}, new.get("classes") or {}
    props = {}
    for cls in sorted(set(old_cls) & set(new_cls)):
        old_props = old_cls[cls].get("props") or {}
        new_props = new_cls[cls].get("props") or {}
        entry = _added_removed(old_props, new_props)
        changed = {}
        for prop in sorted(set(old_props) & set(new_props)):
            if old_props[prop] != new_props[prop]:
                attrs = set(old_props[prop]) ^ set(new_props[prop])
                attrs |= {k for k in set(old_props[prop]) & set(new_props[prop])
                          if old_props[prop][k] != new_props[prop][k]}
                changed[prop] = sorted(attrs)
        if changed:
            entry["changed"] = changed
        if entry:
            props[cls] = entry
    # Whatever else a class states besides its properties (the classes it extends, how it is
    # presented) is compared too, for the classes both versions have.
    common = set(old_cls) & set(new_cls)
    class_attrs = _keyed_delta(
        {cls: {k: v for k, v in old_cls[cls].items() if k != "props"} for cls in common},
        {cls: {k: v for k, v in new_cls[cls].items() if k != "props"} for cls in common})
    old_enums, new_enums = old.get("enums") or {}, new.get("enums") or {}
    enum_values = {}
    for enum in sorted(set(old_enums) & set(new_enums)):
        delta = _added_removed(old_enums[enum], new_enums[enum])
        if delta:
            enum_values[enum] = delta
    old_vid, new_vid = old.get("vid2class") or {}, new.get("vid2class") or {}
    vid = _added_removed(old_vid, new_vid)
    changed_vid = {v: [old_vid[v], new_vid[v]]
                   for v in sorted(set(old_vid) & set(new_vid)) if old_vid[v] != new_vid[v]}
    if changed_vid:
        vid["changed"] = changed_vid
    return _prune({
        "classes": _added_removed(old_cls, new_cls),
        "props": props,
        "class_attrs": class_attrs,
        "enums": _added_removed(old_enums, new_enums),
        "enum_values": enum_values,
        "vid2class": vid,
        **_other_sections(old, new, {"classes", "enums", "vid2class"}),
    })


def _enum_values(entry) -> list:
    """The values of a ui-schema enumeration: {"package", "values"}, or a plain list of old."""
    return list(entry.get("values") or ()) if isinstance(entry, dict) else list(entry or ())


def diff_uischema(old: dict, new: dict) -> dict:
    old_comp, new_comp = old.get("components") or {}, new.get("components") or {}
    props, flags = {}, {}
    for comp in sorted(set(old_comp) & set(new_comp)):
        old_props = old_comp[comp].get("props") or {}
        new_props = new_comp[comp].get("props") or {}
        entry = _added_removed(old_props, new_props)
        changed = {}
        for prop in sorted(set(old_props) & set(new_props)):
            diff_keys = [key for key in _UISCHEMA_PROP_KEYS
                         if (old_props[prop].get(key) or None) != (new_props[prop].get(key) or None)]
            if diff_keys:
                changed[prop] = diff_keys
        if changed:
            entry["changed"] = changed
        if entry:
            props[comp] = entry
        flag_delta = {key: [old_comp[comp].get(key), new_comp[comp].get(key)]
                      for key in _UISCHEMA_FLAG_KEYS
                      if (old_comp[comp].get(key) or None) != (new_comp[comp].get(key) or None)}
        if flag_delta:
            flags[comp] = flag_delta
    common = set(old_comp) & set(new_comp)
    # The yaml keys a source may write on a component beyond its properties.
    yaml_props = _keyed_delta({comp: old_comp[comp].get("yaml_props") or [] for comp in common},
                              {comp: new_comp[comp].get("yaml_props") or [] for comp in common})
    old_enums, new_enums = old.get("enums") or {}, new.get("enums") or {}
    enum_values = {}
    enum_packages = {}
    for enum in sorted(set(old_enums) & set(new_enums)):
        # An enumeration of the schema is {"package", "values"}: comparing the two records as
        # key sets said "no change" whatever happened to the values.
        delta = _added_removed(_enum_values(old_enums[enum]), _enum_values(new_enums[enum]))
        if delta:
            enum_values[enum] = delta
        old_package = old_enums[enum].get("package") if isinstance(old_enums[enum], dict) else None
        new_package = new_enums[enum].get("package") if isinstance(new_enums[enum], dict) else None
        if old_package != new_package:
            enum_packages[enum] = [old_package, new_package]
    return _prune({
        "components": _added_removed(old_comp, new_comp),
        "props": props,
        "flags": flags,
        "yaml_props": yaml_props,
        "enums": _added_removed(old_enums, new_enums),
        "enum_values": enum_values,
        "enum_packages": {"changed": enum_packages},
        "type_params": _keyed_delta(old.get("type_params"), new.get("type_params"), ordered=True),
        **_other_sections(old, new, {"components", "enums", "type_params"}),
    })


def diff_terms(old: dict, new: dict) -> dict:
    """Pairs keyed by the Russian name, compared by name: a new, a gone and a changed spelling."""
    sections = [*_TERM_SECTIONS,
                *_order((set(old) | set(new)) - set(_TERM_SECTIONS) - _NOT_COMPARED)]
    out = {}
    for section in sections:
        entry = _section_delta(old.get(section), new.get(section))
        if entry:
            out[section] = entry
    return out


def diff_pairs(old: dict, new: dict) -> dict:
    """Any file of ru/en pairs (uiterms.json, terms_full.json): every section compared by name."""
    return _prune(_other_sections(old, new, ()))


def diff_docs(old_pages: dict, new_pages: dict) -> dict:
    """Pages that came, went, got another title or another content.

    A page is (title, kind) or (title, kind, hash of the HTML). The four lists do not overlap:
    a retitled page is listed among the retitled only, although its HTML - which carries the
    heading - changed as well.
    """
    added = sorted(set(new_pages) - set(old_pages))
    removed = sorted(set(old_pages) - set(new_pages))
    shared = sorted(set(old_pages) & set(new_pages))
    retitled = {page_id: [old_pages[page_id][0], new_pages[page_id][0]]
                for page_id in shared if old_pages[page_id][0] != new_pages[page_id][0]}
    changed = [[page_id, *new_pages[page_id][:2]] for page_id in shared
               if page_id not in retitled and len(old_pages[page_id]) > 2
               and len(new_pages[page_id]) > 2 and old_pages[page_id][2] != new_pages[page_id][2]]
    return _prune({
        "pages": {
            "added": [[pid, *new_pages[pid][:2]] for pid in added],
            "removed": [[pid, *old_pages[pid][:2]] for pid in removed],
            "retitled": retitled,
            "changed": changed,
        },
        "counts": {"old": len(old_pages), "new": len(new_pages)},
    })


# --- Assembly -----------------------------------------------------------------------------

#: (diff section, file, pure diff function) - docs is separate (sqlite, not json).
_JSON_SECTIONS = (
    ("language", "language.json", diff_language),
    ("stdlib", "stdlib.json", diff_stdlib),
    ("metamodel", "metamodel.json", diff_metamodel),
    ("uischema", "uischema.json", diff_uischema),
    ("terms", "terms.json", diff_terms),
    ("uiterms", "uiterms.json", diff_pairs),
    ("terms_full", "terms_full.json", diff_pairs),
)


def build_diff(old_version: str, new_version: str) -> dict:
    root = Path(dataset.data_root())
    result: dict = {"meta": {"old": old_version, "new": new_version, "root": str(root)}}
    missing: list[str] = []
    for section, file_name, differ in _JSON_SECTIONS:
        old_data = _load_json(root, old_version, file_name)
        new_data = _load_json(root, new_version, file_name)
        if old_data is None or new_data is None:
            missing.append(file_name)
            continue
        result[section] = differ(old_data, new_data)
    old_pages = _load_doc_pages(root, old_version)
    new_pages = _load_doc_pages(root, new_version)
    if old_pages is None or new_pages is None:
        missing.append("docs.sqlite")
    else:
        result["docs"] = diff_docs(old_pages, new_pages)
    if missing:
        result["meta"]["missing"] = missing
    return result


# --- Rendering ----------------------------------------------------------------------------
#
# Both renderers work off the same (depth, text) line list; text caps every list at --limit,
# markdown emits everything as nested bullet lists.

_SECTIONS = ("language", "stdlib", "metamodel", "uischema", "terms", "uiterms", "terms_full",
             "docs")
#: Groups of the four original sections that keep a shape of their own; every other group -
#: the ones added since and the pair files - is a keyed delta and renders through _emit_delta.
_OWN_SHAPE_SECTIONS = ("language", "stdlib", "metamodel", "uischema")
_MEMBER_GROUPS = ("members", "facet_members", "manager_members", "generated_members")
_NAME_SET_GROUPS = ("props", "forms", "enum_values", "object_members")
#: The i18n prefix a section keeps its own titles under (terms.json predates the rest).
_TITLE_PREFIX = {"terms": "datadiff.term."}


def _cap(names: list, limit: int | None) -> tuple[list, str]:
    if limit is not None and len(names) > limit:
        return names[:limit], " " + i18n.t("datadiff.more", n=len(names) - limit)
    return names, ""


def _join(names: list, limit: int | None) -> str:
    shown, more = _cap(names, limit)
    return ", ".join(str(name) for name in shown) + more


def _delta_head(title: str, delta: dict, changed_key: str = "changed") -> str:
    counts = [f"+{len(delta['added'])}" if delta.get("added") else "",
              f"-{len(delta['removed'])}" if delta.get("removed") else "",
              f"~{len(delta[changed_key])}" if delta.get(changed_key) else ""]
    joined = "/".join(part for part in counts if part)
    return f"{title} {joined}:" if joined else f"{title}:"


def _value(value) -> str:
    if isinstance(value, list):
        return "[" + ", ".join(_value(v) for v in value) + "]"
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _pair_line(pair: list) -> str:
    return f"{_value(pair[0])} -> {_value(pair[1])}"


def _detail(delta, limit: int | None) -> str:
    """One line for the delta of an entry: a pair, or what came, went and changed inside it."""
    if isinstance(delta, list):
        return _pair_line(delta)
    parts = []
    if delta.get("added"):
        parts.append("+" + _join(delta["added"], limit))
    if delta.get("removed"):
        parts.append("-" + _join(delta["removed"], limit))
    changed = delta.get("changed") or {}
    if changed:
        shown, more = _cap(list(changed.items()), limit)
        parts.append("~" + ", ".join(f"{name} ({_detail(sub, limit)})" for name, sub in shown)
                     + more)
    return "; ".join(parts)


def _emit_delta(out: list, depth: int, title: str, delta: dict, limit: int | None) -> None:
    """A keyed delta under one heading: what came, what went, and a line per changed entry."""
    if not delta:
        return
    out.append((depth, _delta_head(title, delta)))
    if delta.get("added"):
        out.append((depth + 1, "+ " + _join(delta["added"], limit)))
    if delta.get("removed"):
        out.append((depth + 1, "- " + _join(delta["removed"], limit)))
    shown, more = _cap(list((delta.get("changed") or {}).items()), limit)
    for name, detail in shown:
        out.append((depth + 1, f"~ {name}: {_detail(detail, limit)}"))
    if more:
        out.append((depth + 1, more.strip()))


def _members_line(entry: dict, limit: int | None) -> str:
    parts = []
    for key, label in (
        ("methods", "datadiff.group.methods"),
        ("properties", "datadiff.group.properties"),
        ("events", "datadiff.group.events"),
        ("members", "datadiff.group.any-members"),
    ):
        delta = entry.get(key)
        if not delta:
            continue
        bits = []
        if delta.get("added"):
            bits.append("+" + _join(delta["added"], limit))
        if delta.get("removed"):
            bits.append("-" + _join(delta["removed"], limit))
        parts.append(i18n.t(label) + " " + "; ".join(bits))
    moved = entry.get("moved") or {}
    if moved:
        shown, more = _cap(list(moved.items()), limit)
        kinds = [(member, [i18n.t("datadiff.group." + kind) for kind in pair])
                 for member, pair in shown]
        parts.append(i18n.t("datadiff.group.moved") + " "
                     + ", ".join(f"{member} ({was} -> {now})" for member, (was, now) in kinds)
                     + more)
    return "; ".join(parts)


def _props_line(entry: dict, limit: int | None) -> str:
    parts = []
    if entry.get("added"):
        parts.append("+" + _join(entry["added"], limit))
    if entry.get("removed"):
        parts.append("-" + _join(entry["removed"], limit))
    changed = entry.get("changed") or {}
    if changed:
        shown, more = _cap(list(changed.items()), limit)
        rendered = ", ".join(f"{prop} ({', '.join(attrs)})" for prop, attrs in shown)
        parts.append("~" + rendered + more)
    return "; ".join(parts)


def _emit_named(out: list, depth: int, title: str, entries: dict, line, limit: int | None) -> None:
    """A per-name group: one line per name, `line(entry)` renders the payload."""
    if not entries:
        return
    out.append((depth, f"{title} ~{len(entries)}:"))
    shown, more = _cap(list(entries.items()), limit)
    for name, entry in shown:
        out.append((depth + 1, f"{name}: {line(entry)}"))
    if more:
        out.append((depth + 1, more.strip()))


def _emit_pages(out: list, depth: int, body: dict, limit: int | None) -> None:
    counts = body.get("counts") or {}
    if counts:
        out.append((depth, i18n.t("datadiff.pages", old=counts.get("old"), new=counts.get("new"))))
    pages = body.get("pages") or {}
    title = i18n.t("datadiff.group.pages")
    for key, sign in (("added", "+"), ("removed", "-")):
        rows = pages.get(key) or []
        if not rows:
            continue
        out.append((depth, f"{title} {sign}{len(rows)}:"))
        shown, more = _cap(rows, limit)
        for _pid, page_title, kind in shown:
            out.append((depth + 1, f"{sign} {page_title}" + (f"  [{kind}]" if kind else "")))
        if more:
            out.append((depth + 1, more.strip()))
    retitled = pages.get("retitled") or {}
    if retitled:
        out.append((depth, f"{title} ~{len(retitled)}:"))
        shown, more = _cap(list(retitled.items()), limit)
        for _pid, (old_title, new_title) in shown:
            out.append((depth + 1, f"~ {old_title} -> {new_title}"))
        if more:
            out.append((depth + 1, more.strip()))
    changed = pages.get("changed") or []
    if changed:
        # The id goes along: titles repeat across the tree, and the id is what opens the page.
        out.append((depth, f"{i18n.t('datadiff.group.pages-changed')} ~{len(changed)}:"))
        shown, more = _cap(changed, limit)
        for pid, page_title, kind in shown:
            out.append((depth + 1, f"~ {page_title}" + (f"  [{kind}]" if kind else "") + f"  {pid}"))
        if more:
            out.append((depth + 1, more.strip()))


def _group_title(section: str, key: str) -> str:
    """The title of a group: the section's own, the shared one, or the key itself.

    A section a newer extractor adds has no title yet - it is shown under its own key rather
    than hidden for the want of one.
    """
    prefixes = (_TITLE_PREFIX.get(section) or f"datadiff.{section.replace('_', '-')}.",
                "datadiff.group.")
    for prefix in prefixes:
        name = prefix + key.replace("_", "-")
        title = i18n.t(name)
        if title != name:
            return title
    return key


def _section_lines(section: str, body: dict, limit: int | None) -> list:
    out: list = []
    if section == "docs":
        _emit_pages(out, 0, body, limit)
        return out
    own_shape = section in _OWN_SHAPE_SECTIONS
    for key, payload in body.items():
        title = _group_title(section, key)
        if own_shape and key in _MEMBER_GROUPS:
            _emit_named(out, 0, title, payload, lambda e: _members_line(e, limit), limit)
        elif own_shape and key in _NAME_SET_GROUPS:
            _emit_named(out, 0, title, payload, lambda e: _props_line(e, limit), limit)
        elif own_shape and key == "member_types":
            _emit_named(out, 0, title, payload, _pair_line, limit)
        elif own_shape and key == "flags":
            _emit_named(out, 0, title, payload,
                        lambda e: "; ".join(f"{k} {_pair_line(v)}" for k, v in e.items()), limit)
        else:  # a keyed delta: names that came and went, a line per changed entry
            _emit_delta(out, 0, title, payload, limit)
    return out


def _render(diff: dict, limit: int | None, markdown: bool) -> str:
    meta = diff["meta"]
    head = i18n.t("datadiff.header", old=meta["old"], new=meta["new"])
    lines = [("# " + head) if markdown else head, ""]
    if meta.get("missing"):
        lines += [i18n.t("datadiff.missing", files=", ".join(meta["missing"])), ""]
    for section in _SECTIONS:
        body = diff.get(section)
        if body is None:
            continue
        title = i18n.t("datadiff.section." + section)
        lines.append(("## " + title) if markdown else (title + ":"))
        rows = _section_lines(section, body, limit)
        if not rows:
            lines.append(("" if markdown else "  ") + i18n.t("datadiff.no-changes"))
        for depth, text in rows:
            if markdown:
                lines.append("  " * depth + "- " + text)
            else:
                lines.append("  " * (depth + 1) + text)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_text(diff: dict, limit: int | None = 15) -> str:
    return _render(diff, limit, markdown=False)


def render_markdown(diff: dict) -> str:
    return _render(diff, None, markdown=True)


# --- CLI ----------------------------------------------------------------------------------


def _build_parser():
    parser = i18n.ArgumentParser(prog="xbsl data-diff", description=i18n.t("datadiff.description"))
    parser.add_argument("old", nargs="?", help=i18n.t("datadiff.help.old"))
    parser.add_argument("new", nargs="?", help=i18n.t("datadiff.help.new"))
    parser.add_argument("--format", choices=("text", "md", "json"), default="text",
                        help=i18n.t("datadiff.help.format"))
    parser.add_argument("--out", help=i18n.t("datadiff.help.out"))
    parser.add_argument("--limit", type=int, default=15, help=i18n.t("datadiff.help.limit"))
    parser.add_argument("--data-dir", help=i18n.t("datadiff.help.data-dir"))
    return parser


def cli_main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.data_dir:
        dataset.set_data_root(args.data_dir)
    try:
        available = dataset.available_versions()
        new_version = dataset.resolve_version(args.new)
        old_version = args.old or previous_version(new_version, available)
        if not old_version:
            print(i18n.t("datadiff.no-older", version=new_version,
                         available=", ".join(available) or "-"))
            return 2
        old_version = dataset.resolve_version(old_version)
        diff = build_diff(old_version, new_version)
    except dataset.DatasetError as error:
        print(i18n.t("cli.data-error", error=error))
        return 2
    if args.format == "json":
        text = json.dumps(diff, ensure_ascii=False, indent=2) + "\n"
    elif args.format == "md":
        text = render_markdown(diff)
    else:
        text = render_text(diff, limit=(args.limit if args.limit > 0 else None))
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8", newline="")
        print(i18n.t("datadiff.written", path=args.out))
    else:
        print(text, end="")
    return 0
