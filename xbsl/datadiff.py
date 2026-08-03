"""Diff of two language-data versions: what changed in the platform between releases.

    xbsl data-diff                  # the default version against the closest older one
    xbsl data-diff 1.2.3+4 1.3.0    # explicit versions
    xbsl data-diff --format md      # a full Markdown report (text is capped per list)

Reads the RAW versioned files (language/stdlib/metamodel/uischema/terms .json and the
docs.sqlite page index) from the same data root the linter uses. stdlib members are
compared in their stored OWN form: a member added to a base type is reported once for
the base, not for every descendant. Comparing datasets produced by different extractor
generations can report tooling changes as platform changes - regenerate both versions
with the current extractors for a clean diff.
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

from xbsl import dataset, i18n
from xbsl.dataset import MEMBER_KINDS

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
    "datadiff.section.stdlib": {"ru": "Типы stdlib", "en": "stdlib types"},
    "datadiff.section.metamodel": {"ru": "Метамодель конфигурации", "en": "Configuration metamodel"},
    "datadiff.section.uischema": {"ru": "Компоненты интерфейса", "en": "Interface components"},
    "datadiff.section.terms": {"ru": "Термины (ru/en пары)", "en": "Terms (ru/en pairs)"},
    "datadiff.section.docs": {"ru": "Документация", "en": "Documentation"},
    "datadiff.group.keywords": {"ru": "ключевые слова", "en": "keywords"},
    "datadiff.group.forms": {"ru": "формы ключевых слов", "en": "keyword forms"},
    "datadiff.group.operators": {"ru": "операторы", "en": "operators"},
    "datadiff.group.types": {"ru": "типы", "en": "types"},
    "datadiff.group.members": {"ru": "члены типов", "en": "type members"},
    "datadiff.group.member-types": {"ru": "типы членов", "en": "member result types"},
    "datadiff.group.globals": {"ru": "глобальные имена", "en": "global names"},
    "datadiff.group.object-members": {"ru": "порождаемые члены объектов", "en": "generated object members"},
    "datadiff.group.manager-members": {"ru": "члены менеджеров", "en": "manager members"},
    "datadiff.group.facets": {"ru": "фасеты", "en": "facets"},
    "datadiff.group.facet-members": {"ru": "члены фасетов", "en": "facet members"},
    "datadiff.group.classes": {"ru": "классы", "en": "classes"},
    "datadiff.group.props": {"ru": "свойства", "en": "properties"},
    "datadiff.group.enums": {"ru": "перечисления", "en": "enumerations"},
    "datadiff.group.enum-values": {"ru": "значения перечислений", "en": "enumeration values"},
    "datadiff.group.vid2class": {"ru": "виды элементов", "en": "element kinds"},
    "datadiff.group.components": {"ru": "компоненты", "en": "components"},
    "datadiff.group.flags": {"ru": "признаки компонентов", "en": "component flags"},
    "datadiff.group.pages": {"ru": "страницы", "en": "pages"},
    "datadiff.group.methods": {"ru": "методы", "en": "methods"},
    "datadiff.group.properties": {"ru": "свойства", "en": "properties"},
    "datadiff.term.types": {"ru": "типы", "en": "types"},
    "datadiff.term.facets": {"ru": "фасеты", "en": "facets"},
    "datadiff.term.properties": {"ru": "свойства", "en": "properties"},
    "datadiff.term.enums": {"ru": "значения перечислений", "en": "enumeration values"},
    "datadiff.term.query": {"ru": "язык запросов", "en": "query language"},
}
i18n.register(MESSAGES)

#: Sections of terms.json worth diffing (russian -> english pairs).
_TERM_SECTIONS = ("types", "facets", "properties", "enums", "query")
#: uischema property attributes that make a "changed" entry (doc texts excluded - noise).
_UISCHEMA_PROP_KEYS = ("types", "enum", "event", "slot", "readonly", "since", "default")
#: uischema component attributes compared as flags.
_UISCHEMA_FLAG_KEYS = ("abstract", "container", "since", "package")


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
    return json.loads(path.read_text(encoding="utf-8"))


def _load_doc_pages(root: Path, version: str) -> dict[str, tuple[str, str]] | None:
    path = root / version / "docs.sqlite"
    if not path.exists():
        return None
    con = sqlite3.connect(path)
    try:
        rows = con.execute("SELECT id, title, kind FROM pages").fetchall()
    finally:
        con.close()
    return {page_id: (title or "", kind or "") for page_id, title, kind in rows}


# --- Pure diffs ---------------------------------------------------------------------------


def _added_removed(old, new) -> dict:
    old_set, new_set = set(old or ()), set(new or ())
    out = {}
    if new_set - old_set:
        out["added"] = sorted(new_set - old_set)
    if old_set - new_set:
        out["removed"] = sorted(old_set - new_set)
    return out


def _prune(value):
    """Drop empty branches so an unchanged section renders as "no changes"."""
    if isinstance(value, dict):
        cleaned = {k: _prune(v) for k, v in value.items()}
        return {k: v for k, v in cleaned.items() if v not in ({}, [], None)}
    return value


def _diff_member_lists(old: dict, new: dict) -> dict:
    """Per-name diff of {"Имя": {"methods": [...], "properties": [...]}} sections."""
    out = {}
    for name in sorted(set(old) & set(new)):
        entry = {}
        for key in ("methods", "properties"):
            delta = _added_removed(old[name].get(key), new[name].get(key))
            if delta:
                entry[key] = delta
        if entry:
            out[name] = entry
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
    return _prune({
        "types": _added_removed(old_tm, new_tm),
        "members": members,
        "member_types": member_types,
        "globals": _added_removed(old.get("globals"), new.get("globals")),
        "object_members": _diff_name_sets(
            old.get("object_members") or {}, new.get("object_members") or {}),
        "manager_members": _diff_name_sets(
            old.get("manager_members") or {}, new.get("manager_members") or {}),
        "facets": _added_removed(old_fm, new_fm),
        "facet_members": _diff_member_lists(old_fm, new_fm),
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
        "enums": _added_removed(old_enums, new_enums),
        "enum_values": enum_values,
        "vid2class": vid,
    })


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
    old_enums, new_enums = old.get("enums") or {}, new.get("enums") or {}
    enum_values = {}
    for enum in sorted(set(old_enums) & set(new_enums)):
        delta = _added_removed(old_enums[enum], new_enums[enum])
        if delta:
            enum_values[enum] = delta
    return _prune({
        "components": _added_removed(old_comp, new_comp),
        "props": props,
        "flags": flags,
        "enums": _added_removed(old_enums, new_enums),
        "enum_values": enum_values,
    })


def diff_terms(old: dict, new: dict) -> dict:
    out = {}
    for section in _TERM_SECTIONS:
        old_map, new_map = old.get(section) or {}, new.get(section) or {}
        entry = _added_removed(old_map, new_map)
        changed = {name: [old_map[name], new_map[name]]
                   for name in sorted(set(old_map) & set(new_map))
                   if old_map[name] != new_map[name]}
        if changed:
            entry["changed"] = changed
        if entry:
            out[section] = entry
    return out


def diff_docs(old_pages: dict, new_pages: dict) -> dict:
    added = sorted(set(new_pages) - set(old_pages))
    removed = sorted(set(old_pages) - set(new_pages))
    retitled = {page_id: [old_pages[page_id][0], new_pages[page_id][0]]
                for page_id in sorted(set(old_pages) & set(new_pages))
                if old_pages[page_id][0] != new_pages[page_id][0]}
    return _prune({
        "pages": {
            "added": [[pid, *new_pages[pid]] for pid in added],
            "removed": [[pid, *old_pages[pid]] for pid in removed],
            "retitled": retitled,
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

_SECTIONS = ("language", "stdlib", "metamodel", "uischema", "terms", "docs")


def _cap(names: list, limit: int | None) -> tuple[list, str]:
    if limit is not None and len(names) > limit:
        return names[:limit], " " + i18n.t("datadiff.more", n=len(names) - limit)
    return names, ""


def _join(names: list[str], limit: int | None) -> str:
    shown, more = _cap(names, limit)
    return ", ".join(shown) + more


def _delta_head(title: str, delta: dict, changed_key: str = "changed") -> str:
    counts = [f"+{len(delta['added'])}" if delta.get("added") else "",
              f"-{len(delta['removed'])}" if delta.get("removed") else "",
              f"~{len(delta[changed_key])}" if delta.get(changed_key) else ""]
    joined = "/".join(part for part in counts if part)
    return f"{title} {joined}:" if joined else f"{title}:"


def _emit_delta(out: list, depth: int, title: str, delta: dict, limit: int | None) -> None:
    """A plain added/removed[/changed-pairs] group under one heading."""
    if not delta:
        return
    out.append((depth, _delta_head(title, delta)))
    if delta.get("added"):
        out.append((depth + 1, "+ " + _join(delta["added"], limit)))
    if delta.get("removed"):
        out.append((depth + 1, "- " + _join(delta["removed"], limit)))
    for name, pair in _cap(list((delta.get("changed") or {}).items()), limit)[0]:
        out.append((depth + 1, f"~ {name}: {pair[0]} -> {pair[1]}"))
    if delta.get("changed"):
        _, more = _cap(list(delta["changed"]), limit)
        if more:
            out.append((depth + 1, more.strip()))


def _members_line(entry: dict, limit: int | None) -> str:
    parts = []
    for key in ("methods", "properties"):
        delta = entry.get(key)
        if not delta:
            continue
        bits = []
        if delta.get("added"):
            bits.append("+" + _join(delta["added"], limit))
        if delta.get("removed"):
            bits.append("-" + _join(delta["removed"], limit))
        parts.append(i18n.t(f"datadiff.group.{key}") + " " + "; ".join(bits))
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


def _pair_line(pair: list) -> str:
    def fmt(value):
        if isinstance(value, list):
            return "[" + ", ".join(str(v) for v in value) + "]"
        return str(value)

    return f"{fmt(pair[0])} -> {fmt(pair[1])}"


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


def _group_title(key: str) -> str:
    return i18n.t("datadiff.group." + key.replace("_", "-"))


def _section_lines(section: str, body: dict, limit: int | None) -> list:
    out: list = []
    if section == "docs":
        _emit_pages(out, 0, body, limit)
        return out
    if section == "terms":
        for key in _TERM_SECTIONS:
            if key in body:
                _emit_delta(out, 0, i18n.t("datadiff.term." + key), body[key], limit)
        return out
    for key, payload in body.items():
        title = _group_title(key)
        if key in ("members", "facet_members"):
            _emit_named(out, 0, title, payload, lambda e: _members_line(e, limit), limit)
        elif key in ("props", "forms", "enum_values", "object_members", "manager_members"):
            _emit_named(out, 0, title, payload, lambda e: _props_line(e, limit), limit)
        elif key == "member_types":
            _emit_named(out, 0, title, payload, _pair_line, limit)
        elif key == "flags":
            _emit_named(out, 0, title, payload,
                        lambda e: "; ".join(f"{k} {_pair_line(v)}" for k, v in e.items()), limit)
        else:  # keywords, operators, types, globals, facets, classes, enums, components, vid2class
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
    except dataset.DatasetError as error:
        print(i18n.t("cli.data-error", error=error))
        return 2
    diff = build_diff(old_version, new_version)
    if args.format == "json":
        text = json.dumps(diff, ensure_ascii=False, indent=2) + "\n"
    elif args.format == "md":
        text = render_markdown(diff)
    else:
        text = render_text(diff, limit=(args.limit if args.limit > 0 else None))
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(i18n.t("datadiff.written", path=args.out))
    else:
        print(text, end="")
    return 0
