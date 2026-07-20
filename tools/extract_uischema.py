#!/usr/bin/env python3
"""Extract the interface component ui schema from the DOCUMENTATION dataset (docs.sqlite).

Unlike the other extractors this one does not read the distribution: it reads the pages
already extracted by tools/extract_docs.py (via xbsl.docs) and derives a machine schema
for the visual designer - the component palette and the typed properties panel. The
result is uischema.json written NEXT to stdlib.json in the same versioned data folder.

What is derived from where:

- The component set is the same as component_props in extract_stdlib.py: every type page
  whose "Иерархия типа" lists Стд::Интерфейс::Компонент among the bases, plus the page
  of Компонент itself. The bases list on a page is the full ancestor chain, so a direct
  membership test suffices.
- The declarative property list of a constructible component is the parameter list of its
  current @ИменованныеПараметры constructor (the docs guarantee it includes inherited
  properties). Blocks struck out with <del> ("Версия N и ниже") are ignored.
- A component with no current @ИменованныеПараметры constructor is marked
  "abstract": true - there is nothing to map yaml keys onto, so it cannot be inserted
  from the palette; its properties are collected from the "Свойства" sections of the
  page and its ancestors instead (may include runtime-only members, which carry
  "readonly": true when the docs mark them with ТолькоЧтение).
- Property docs, since-versions, read-only markers and defaults come from the property
  sections of the page and its ancestors (nearest ancestor wins, the page itself wins
  over all).
- Enum values are the OWN property headings of the enumeration's page ("Свойства"
  section). The service members (Индекс, ВСтроку, ПолучитьТип, Представление) live only
  in the inherited-members sections, so taking own headings IS the filter - no name
  blacklist involved.

The shape of uischema.json (optional keys are omitted when false/unknown - a consumer
treats an absent key as false/null):

    { "meta": {"source": "docs", "element_version": "...", "tool": "extract_uischema",
               "count": N},
      "components": {
        "СтандартнаяКарточка": {
          "package": "Стд::Интерфейс::ОбщиеКомпоненты",
          "doc": "Представляет собой карточку с предопределенной структурой.",
          "abstract": true,            # only when there is no current constructor
          "container": true,           # only when the props carry a slot Содержимое
          "since": "9.0",              # only when the docs state a version
          "conflicts": ["Пакет::Имя"], # only for same-named losers (see below)
          "props": {
            "ВидОтображения": {"types": ["Авто", "ВидОтображенияСтандартнойКарточки"],
                               "enum": ["Карточка", "Баннер"], "doc": "...",
                               "default": "Карточка"},
            "ПриНажатии":     {"event": "(Карточка, СобытиеПриНажатии)->ничто", "doc": "..."},
            "Картинка":       {"types": ["Картинка"], "nullable": true, "slot": true},
            "Содержимое":     {"types": ["Компонент", "Строка"], "slot": true}
          } } },
      "enums": {"ВидОтображенияСтандартнойКарточки": {
          "package": "Стд::Интерфейс::ОбщиеКомпоненты",
          "values": ["Карточка", "Баннер"]}} }

Conventions of the property records:

- "types" is the value type union split on top-level "|" (bracket-aware: "|" inside
  generic arguments does not split). "Авто" stays a regular member - the editors treat
  it as the tri-state/auto marker.
- Nullable encoding: a trailing "?" - both the whole-union form ("Url|Ссылка|?") and the
  single-type form ("Картинка?") - is NOT kept in "types"; it becomes "nullable": true.
  A "?" inside generic arguments (conditional types) is left alone.
- "event" replaces "types" for handler properties - a functional type "(...)->...";
  the signature is kept as one normalized string.
- "slot": true marks properties that accept components or command-interface items
  (future nodes of the designer's structure tree): some type referenced by the union -
  generic arguments included, Тип<...> type literals excluded - is an interface
  component or a non-enum type of the Стд::Интерфейс::Команды package.
- "container": true on a component means its properties include Содержимое with
  "slot": true. Exactly Содержимое: the designer wraps into and drops onto that slot,
  so other component-bearing slots (Команды, Шапка, Подвал, Страницы, Колонки) do not
  make a component a container in this sense. The flag is what lets the palette and
  the structure view take the container list straight from the catalog instead of
  fetching every full record.
- "enum" is resolved only when the union has exactly one real member (ignoring "Авто"
  and the nullable marker), that member has no generic arguments and its name is an
  enumeration page title. The top-level "enums" map carries every enumeration
  referenced by ANY member of ANY property union - members beyond the single-member
  "enum" case included - so the paired Type+Value editor can offer values for an
  enumeration member of a wider union.
- "default" is a best-effort extraction of the documented auto-value ("При Авто
  выбирается X"); when the docs do not state one, the key is absent - never guessed.
- "since" of a component: the page-level "Версия N и выше" marker when present;
  otherwise the marker of its only-ever constructor (no deleted overloads - the
  component appeared together with it). A deleted overload proves the component
  predates the current constructor, so no since is emitted.

Same-named components (or enumerations) in different packages, should a version bring
them: the bare name stays the key; the winner is chosen by (an Стд::Интерфейс package
first, then the shorter qualified name, then alphabetically) and lists the losers'
qualified names under "conflicts". Version 9.2.8+11 has no such name clashes.

The docs dataset of the chosen version must exist (tools/extract_docs.py); the root is
picked the standard way (--data-dir / env XBSL_DATA_DIR / the clone default) and the
output goes into the same root - never a hardcoded machine path.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from html import unescape
from pathlib import Path

_TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(_TOOLS))
sys.path.insert(0, str(_TOOLS.parent))  # the local xbsl package wins over an installed copy
import _distro  # noqa: E402
from xbsl import dataset, docs  # noqa: E402

COMPONENT_BASE_QUALIFIED = "Стд::Интерфейс::Компонент"
ENUM_BASE_QUALIFIED = "Стд::Перечисление"
COMMANDS_PACKAGE = "Стд::Интерфейс::Команды"

_H2_RE = re.compile(r'<h2 id="[^"]*">(.*?)</h2>', re.S)
_H3_RE = re.compile(r'<h3 id="[^"]*">(.*?)</h3>', re.S)
_P_RE = re.compile(r"<p>(.*?)</p>", re.S)
_PRE_CODE_RE = re.compile(r"<pre><code>(.*?)</code></pre>", re.S)
_BASES_RE = re.compile(r"<p><em>Базовые типы:</em>(.*?)</p>", re.S)
_LINK_RE = re.compile(r'<a href="#([^"#]+)(?:#[^"]*)?">(.*?)</a>', re.S)
_TAG_RE = re.compile(r"<[^>]+>")
_CODE_SPAN_RE = re.compile(r"<code>.*?</code>", re.S)
_WS_RE = re.compile(r"\s+")
_NAME_RE = re.compile(r"^[А-ЯЁA-Z][0-9A-Za-zА-Яа-яЁё_]*$")
_SINCE_RE = re.compile(r"<code>Версия ([\d.]+) и выше</code>")
_READONLY_RE = re.compile(r"<code>Доступность:[^<]*</code>\s*<code>ТолькоЧтение</code>")
_DEFAULT_RE = re.compile(
    r"При <code>Авто</code>\s*(?:выбирается|используется)\s*(?:<a[^>]*>|<code>)?\s*"
    r"([А-ЯЁA-Z][0-9A-Za-zА-Яа-яЁё_]*)"
)
_NAMED_PARAMS = "@ИменованныеПараметры"
#: A referenced type name inside a type expression: the head identifier with optional
#: dotted facets (ДвоичныйОбъект.Ссылка, ТипИсточника.ItemDataType stay one token).
_TYPE_REF_RE = re.compile(r"[А-ЯЁA-Z][0-9A-Za-zА-Яа-яЁё_]*(?:\.[0-9A-Za-zА-Яа-яЁё_]+)*")
_TYPE_LITERAL_RE = re.compile(r"(?<![0-9A-Za-zА-Яа-яЁё_])Тип<")
#: Boilerplate paragraphs of the page header that are not the description.
_NOT_DOC = ("Сравнение", "Ссылочное", "Значимое")


def _plain(html: str) -> str:
    """Tag-free single-space text of an HTML fragment.

    Tags are replaced with spaces (so adjacent elements do not glue together), which
    leaves a stray space before punctuation after inline markup ("<code>Истина</code>,")
    - the final substitution folds it back.
    """
    text = _WS_RE.sub(" ", unescape(_TAG_RE.sub(" ", html))).strip()
    return re.sub(r"\s+([,.;:!?)])", r"\1", text)


def first_sentence(text: str) -> str:
    """The first sentence of a doc paragraph (best effort - a plain '. ' boundary)."""
    m = re.match(r"(.+?[.!?])(?:\s|$)", text)
    return (m.group(1) if m else text).strip()


def normalize_type(raw: str) -> str:
    """A type expression as one canonical line: collapsed whitespace, tight brackets.

    The docs wrap long signatures over lines; this folds them back:
    spaces vanish around "|", "<", ">", "(", ")" and "->", a comma becomes ", ".
    Spaces inside conditional types (`X это Y ? A : B`) survive - only the listed
    structural characters are touched.
    """
    t = _WS_RE.sub(" ", unescape(raw)).strip()
    t = re.sub(r"\s*->\s*", "->", t)
    t = re.sub(r"\s*\|\s*", "|", t)
    t = re.sub(r"<\s+", "<", t)
    t = re.sub(r"\s+>", ">", t)
    t = re.sub(r"\(\s+", "(", t)
    t = re.sub(r"\s+\)", ")", t)
    t = re.sub(r"\s*,\s*", ", ", t)
    return t


def _split_top(text: str, sep: str) -> list[str]:
    """Split on a separator at zero bracket depth ("()" and "<>"; "->" is an arrow,
    not a closing angle bracket)."""
    parts: list[str] = []
    depth = 0
    start = 0
    for i, ch in enumerate(text):
        if ch in "(<":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == ">" and (i == 0 or text[i - 1] != "-"):
            depth -= 1
        elif ch == sep and depth == 0:
            parts.append(text[start:i])
            start = i + 1
    parts.append(text[start:])
    return parts


def split_union(type_str: str) -> tuple[list[str], bool]:
    """Union members of a value type and the nullable flag.

    The trailing "?" - a bare "|?" member or a "?" suffix of a member - marks the
    property nullable and is stripped from the members (see the module docstring).
    """
    members: list[str] = []
    nullable = False
    for member in _split_top(type_str, "|"):
        member = member.strip()
        if member == "?":
            nullable = True
            continue
        if member.endswith("?"):
            nullable = True
            member = member[:-1].strip()
        if member:
            members.append(member)
    return members, nullable


def _strip_type_literals(text: str) -> str:
    """Remove Тип<...> spans: a type literal references types, it does not nest components."""
    while True:
        m = _TYPE_LITERAL_RE.search(text)
        if not m:
            return text
        depth = 0
        end = len(text)
        for i in range(m.end() - 1, len(text)):
            ch = text[i]
            if ch == "<":
                depth += 1
            elif ch == ">" and text[i - 1] != "-":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        text = text[:m.start()] + text[end:]


def type_refs(type_str: str) -> set[str]:
    """Type names referenced by a value type expression, generic arguments included."""
    return set(_TYPE_REF_RE.findall(_strip_type_literals(type_str)))


def is_event(type_str: str) -> bool:
    """Whether the type is a handler signature - a functional type "(...)->..."."""
    return type_str.startswith("(") and "->" in type_str


def parse_ctor_params(sig_text: str) -> list[tuple[str, str]]:
    """(name, normalized type) pairs of an @ИменованныеПараметры constructor signature.

    The parameter list is taken between the first "(" at zero angle depth (skipping the
    generic arguments of the component name) and its matching ")"; parameters split on
    top-level commas - the docs put them one per line, but not always.
    """
    text = normalize_type(sig_text.split(_NAMED_PARAMS, 1)[-1])
    depth = 0
    start = -1
    for i, ch in enumerate(text):
        if ch == "<":
            depth += 1
        elif ch == ">" and (i == 0 or text[i - 1] != "-"):
            depth -= 1
        elif ch == "(" and depth == 0:
            start = i
            break
    if start < 0:
        return []
    depth = 0
    inner = text[start + 1:]
    for i in range(start, len(text)):
        ch = text[i]
        if ch in "(<":
            depth += 1
        elif ch == ")" or (ch == ">" and text[i - 1] != "-"):
            depth -= 1
            if depth == 0:
                inner = text[start + 1:i]
                break
    out: list[tuple[str, str]] = []
    for part in _split_top(inner, ","):
        name, sep, typ = part.partition(":")
        name = name.strip()
        if sep and _NAME_RE.match(name):
            out.append((name, typ.strip()))
    return out


def _h3_blocks(section: str):
    """(name, deleted, body) triples of the H3 blocks of a section."""
    parts = _H3_RE.split(section)
    for k in range(1, len(parts) - 1, 2):
        heading, body = parts[k], parts[k + 1]
        yield _plain(heading), "<del>" in heading, body


def _first_doc_paragraph(html: str) -> str | None:
    """The first paragraph that carries text (markers like availability are code-only)."""
    for m in _P_RE.finditer(html):
        para = m.group(1)
        if not _plain(_CODE_SPAN_RE.sub("", para)):
            continue  # only <code> markers inside
        text = _plain(para)
        if text.startswith(_NOT_DOC):
            continue  # the comparison boilerplate of the page header
        return text
    return None


class PageInfo:
    """The parsed skeleton of one type page (see parse_page)."""

    def __init__(self, rec: dict) -> None:
        self.id: str = rec["id"]
        self.title: str = rec["title"]
        self.qualified: str = unescape(rec.get("qualified") or "")
        self.base_ids: list[str] = []
        self.base_texts: list[str] = []
        self.doc: str | None = None
        self.since: str | None = None  # the page-level marker
        #: Own property sections: name -> {"type", "doc", "since", "readonly", "default"}.
        self.own_props: dict[str, dict] = {}
        #: Values of an enumeration page = its own property headings, page order.
        self.value_names: list[str] = []
        self.ctor_params: list[tuple[str, str]] | None = None  # the current constructor
        self.ctor_since: str | None = None
        self.has_deleted_ctor: bool = False

    @property
    def package(self) -> str | None:
        return self.qualified.rsplit("::", 1)[0] if "::" in self.qualified else None


def parse_page(rec: dict) -> PageInfo:
    """Parse a cleaned docs page (the docs.sqlite html) into a PageInfo."""
    info = PageInfo(rec)
    parts = _H2_RE.split(rec["html"])
    head = parts[0]
    doc = _first_doc_paragraph(head)
    info.doc = first_sentence(doc) if doc else None
    m = _SINCE_RE.search(head)
    info.since = m.group(1) if m else None
    for heading, body in zip(parts[1::2], parts[2::2]):
        heading = _plain(heading)
        if heading.startswith("Иерархия типа"):
            mb = _BASES_RE.search(body)
            if mb:
                for pid, text in _LINK_RE.findall(mb.group(1)):
                    info.base_ids.append(pid)
                    info.base_texts.append(_plain(text))
        elif heading.startswith("Конструкторы"):
            _parse_ctors(info, body)
        elif heading.startswith("Свойства"):
            _parse_props(info, body)
    return info


def _parse_ctors(info: PageInfo, section: str) -> None:
    for _name, deleted, body in _h3_blocks(section):
        if deleted:
            info.has_deleted_ctor = True  # any struck-out overload proves pre-existence
            continue
        named = next(
            (m.group(1) for m in _PRE_CODE_RE.finditer(body) if _NAMED_PARAMS in m.group(1)),
            None,
        )
        if named is not None and info.ctor_params is None:
            info.ctor_params = parse_ctor_params(named)
            m = _SINCE_RE.search(body)
            info.ctor_since = m.group(1) if m else None


def _parse_props(info: PageInfo, section: str) -> None:
    for name, deleted, body in _h3_blocks(section):
        if deleted or not _NAME_RE.match(name):
            continue
        entry: dict = {"type": None, "doc": None, "since": None, "readonly": False,
                       "default": None}
        sig = _PRE_CODE_RE.search(body)
        if sig:
            line = normalize_type(sig.group(1))
            head, sep, typ = line.partition(":")
            if sep and head.strip() == name:
                entry["type"] = typ.strip()
        m = _SINCE_RE.search(body)
        entry["since"] = m.group(1) if m else None
        entry["readonly"] = bool(_READONLY_RE.search(body))
        doc = _first_doc_paragraph(body)
        entry["doc"] = first_sentence(doc) if doc else None
        md = _DEFAULT_RE.search(body)
        entry["default"] = md.group(1) if md else None
        info.own_props[name] = entry
        info.value_names.append(name)


def _pick_namesake(infos: list[PageInfo]) -> PageInfo:
    """The winner among same-named pages: Стд::Интерфейс first, shorter name, alphabet."""
    return min(
        infos,
        key=lambda p: (
            not (p.package or "").startswith("Стд::Интерфейс"),
            len(p.qualified),
            p.qualified,
        ),
    )


def _merged_props(info: PageInfo, by_id: dict[str, PageInfo]) -> dict[str, dict]:
    """Property info of the page and its ancestors: nearest wins, the page itself last."""
    merged: dict[str, dict] = {}
    for pid in info.base_ids:
        base = by_id.get(pid)
        if base:
            merged.update(base.own_props)
    merged.update(info.own_props)
    return merged


def _prop_record(
    type_str: str,
    known: dict | None,
    components: set[str],
    commands: set[str],
    enum_values: dict[str, list[str]],
) -> dict:
    """One property record of the schema (see the module docstring for the shape)."""
    rec: dict = {}
    if is_event(type_str):
        rec["event"] = type_str
    else:
        members, nullable = split_union(type_str)
        rec["types"] = members
        if nullable:
            rec["nullable"] = True
        real = [m for m in members if m != "Авто"]
        if len(real) == 1 and "<" not in real[0] and real[0] in enum_values:
            rec["enum"] = enum_values[real[0]]
        refs = set()
        for member in members:
            refs |= type_refs(member)
        if refs & (components | commands):
            rec["slot"] = True
    if known:
        for key in ("doc", "since", "default"):
            if known.get(key):
                rec[key] = known[key]
        if known.get("readonly"):
            rec["readonly"] = True
    return rec


def build_schema(pages: list[dict], element_version: str) -> dict:
    """The full uischema dictionary from the type pages of the documentation dataset."""
    infos = [parse_page(rec) for rec in pages]
    by_id = {p.id: p for p in infos}
    component_base_ids = {p.id for p in infos if p.qualified == COMPONENT_BASE_QUALIFIED}
    enum_base_ids = {p.id for p in infos if p.qualified == ENUM_BASE_QUALIFIED}

    def is_component(p: PageInfo) -> bool:
        if p.qualified == COMPONENT_BASE_QUALIFIED:
            return True
        return bool(component_base_ids.intersection(p.base_ids)) or (
            COMPONENT_BASE_QUALIFIED in p.base_texts
        )

    def is_enum(p: PageInfo) -> bool:
        return bool(enum_base_ids.intersection(p.base_ids)) or (
            "Перечисление" in p.base_texts or ENUM_BASE_QUALIFIED in p.base_texts
        )

    comp_groups: dict[str, list[PageInfo]] = {}
    enum_groups: dict[str, list[PageInfo]] = {}
    commands: set[str] = set()
    for p in infos:
        if is_component(p):
            comp_groups.setdefault(p.title, []).append(p)
        elif is_enum(p):
            enum_groups.setdefault(p.title, []).append(p)
        elif p.package == COMMANDS_PACKAGE:
            commands.add(p.title)

    enum_pages = {name: _pick_namesake(group) for name, group in enum_groups.items()}
    enum_values = {name: p.value_names for name, p in enum_pages.items() if p.value_names}
    component_names = set(comp_groups)

    components: dict[str, dict] = {}
    used_enums: set[str] = set()
    for name in sorted(comp_groups):
        page = _pick_namesake(comp_groups[name])
        merged = _merged_props(page, by_id)
        abstract = page.ctor_params is None
        props: dict[str, dict] = {}
        if abstract:
            source = [(n, e["type"]) for n, e in merged.items() if e["type"]]
        else:
            source = page.ctor_params or []
        for prop_name, type_str in source:
            props[prop_name] = _prop_record(
                type_str, merged.get(prop_name), component_names, commands, enum_values
            )
            if "types" in props[prop_name]:
                for member in props[prop_name]["types"]:
                    used_enums |= type_refs(member) & set(enum_values)
        rec: dict = {"package": page.package}
        if abstract:
            rec["abstract"] = True
        content = props.get("Содержимое")
        if content is not None and content.get("slot"):
            rec["container"] = True  # only the Содержимое slot counts (see the docstring)
        since = page.since
        if since is None and not abstract and not page.has_deleted_ctor:
            since = page.ctor_since
        if since:
            rec["since"] = since
        if page.doc:
            rec["doc"] = page.doc
        losers = sorted(p.qualified for p in comp_groups[name] if p is not page)
        if losers:
            rec["conflicts"] = losers
        rec["props"] = props
        components[name] = rec

    enums = {
        name: {"package": enum_pages[name].package, "values": enum_values[name]}
        for name in sorted(used_enums)
    }
    return {
        "meta": {
            "source": "docs",
            "element_version": element_version,
            "tool": "extract_uischema",
            "count": len(components),
        },
        "components": components,
        "enums": enums,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Извлечь ui-схему компонентов интерфейса из датасета документации"
    )
    ap.add_argument(
        "--element-version",
        help="версия данных (по умолчанию – версия default из индекса корня данных)",
    )
    ap.add_argument("--out", help="переопределить путь uischema.json")
    _distro.add_data_dir_arg(ap)
    args = ap.parse_args(argv)
    _distro.set_data_root(args.data_dir)
    root = _distro.data_root()
    dataset.set_data_root(root)  # read the docs from the same root the output goes to

    try:
        version = dataset.resolve_version(args.element_version)
    except dataset.DatasetError as exc:
        raise SystemExit(str(exc))
    if not docs.available(version):
        raise SystemExit(
            f"Нет docs.sqlite для версии {version} в {root} – сначала запустите "
            "tools/extract_docs.py"
        )

    schema = build_schema(docs.type_pages(version), version)
    out = Path(args.out) if args.out else _distro.version_dir(version) / "uischema.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    # newline="\n": keep the generated file LF on every platform (git-friendly data).
    out.write_text(
        json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )

    comps = schema["components"]
    props = [p for c in comps.values() for p in c["props"].values()]
    print(f"Записано: {out} (версия {version})")
    print(f"  компонентов интерфейса: {len(comps)}"
          f" (абстрактных: {sum(1 for c in comps.values() if c.get('abstract'))})")
    print(f"  свойств: {len(props)}"
          f" (событий: {sum(1 for p in props if 'event' in p)},"
          f" слотов: {sum(1 for p in props if p.get('slot'))},"
          f" с перечислением: {sum(1 for p in props if 'enum' in p)},"
          f" с описанием: {sum(1 for p in props if 'doc' in p)})")
    print(f"  перечислений со значениями: {len(schema['enums'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
