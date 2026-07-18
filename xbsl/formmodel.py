"""Form model of a 1C:Element interface component: a node tree with source spans.

Parses a `ВидЭлемента: КомпонентИнтерфейса` yaml into a tree of components and slots
(`Наследует` and its child-bearing keys) for the visual designer (docs/DESIGNER.md,
stage 0, track B). The model is read-only; the edit operations that consume it live in
formedits.py. Three surfaces expose the pair, like the meta_* family: the LSP requests
`xbsl/formTree` / `xbsl/formNodeAt` / `xbsl/formEdit` (lsp.py), the MCP tools
`meta_component_tree` / `meta_*_component` (mcp_server.py) and the CLI subcommands
`form-tree` / `form-edit` (cli.py).

Parsing strategy: PyYAML `compose()` with the pure-python SafeLoader supplies the node
structure and precise START marks (`Mark.index` is a character offset). END marks of
block collections are NOT trusted - the composer extends them to the token that closed
the block (verified empirically: the end of a sequence item points at the next "-") -
so every block end here is computed textually, from line indentation. This module never
serializes yaml back: edits are precise text splices computed by formedits.py, so the
untouched formatting, comments and key order survive by construction.

Model conventions (documented decisions):
    - Children live only under the slot keys in CHILD_SLOTS; every other nested mapping
      (`Шрифт`, `Фон`, `ОсновнаяКоманда`, `Источник`) or sequence (`Элементы`) is a
      COMPOSITE PROPERTY, not a child. A slot whose value is written in flow style
      (`Содержимое: {...}`) is treated as a composite property too - flow collections
      are out of scope for line-based edits.
    - A slot holds children either as a "-" list (list_style=True) or as one nested
      mapping (list_style=False); both spellings occur in real forms and are preserved
      as written.
    - `Тип` and `Имя` are surfaced as node fields (`type`/`type_full`, `name`), not as
      properties; the properties list carries everything else.
    - A property whose key starts with При/После/Перед followed by a capital letter and
      whose value is a scalar is an event handler (kind "handler"); `Приоритет` and the
      like do not match because the next letter is lowercase.
    - `#` comments directly above a node at the node's own indent (no blank line in
      between) belong to the node: they are part of its span and travel with it on
      move/duplicate/remove.
    - Spans are half-open [start, end) character offsets. Node and property spans cover
      whole lines, including the trailing newline of the last line; the exact scalar
      value span (`value_span`) comes from the composer marks.
    - Node ids are slash paths from the root: "Наследует", "Наследует/Содержимое" (a
      slot), "Наследует/Содержимое[0]" (a component). Ids are positional and stay valid
      only until the next edit; clients re-read the tree after every change.
    - The top-level `Свойства:` section (the component's own properties: a "-" list of
      {Имя, Тип} records) is NOT part of the node tree - it is modelled separately as
      Form.properties_section and serialized as the "componentProperties" top field of
      the tree surfaces. The corpus rule: the section follows the Наследует block (the
      dominant spelling by a wide margin), which is where property_add creates it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import yaml

from xbsl.scaffold import ScaffoldError

#: Slot keys whose values hold child components. A provisional whitelist: once track A
#: (the ui schema extracted from the platform docs) lands, the per-component schema
#: becomes the source of truth for what each property accepts. The list is checked
#: against the wireframe preview traversal (editors/vscode/src/formPreviewCore.ts walks
#: Содержимое, Страницы, Колонки) and the form generators in scaffold.py, which also
#: emit Команды and КомандыСтроки as component-bearing slots; Шапка and Подвал are the
#: header/footer slots of layout components.
CHILD_SLOTS = (
    "Содержимое",
    "Страницы",
    "Колонки",
    "Команды",
    "КомандыСтроки",
    "Шапка",
    "Подвал",
)

COMPONENT_ELEMENT_KIND = "КомпонентИнтерфейса"
ROOT_KEY = "Наследует"
PROPERTIES_KEY = "Свойства"

_HANDLER_KEY_RE = re.compile(r"^(?:При|После|Перед)[А-ЯЁA-Z]")
_INDENT_RE = re.compile(r"^[ \t]*")
_PREVIEW_LIMIT = 60


class FormModelError(ScaffoldError):
    """Form model/operation error; the text is shown to the user as is."""


# --- spans and lines ----------------------------------------------------------------------


@dataclass(frozen=True)
class Span:
    start: int
    end: int

    def as_dict(self) -> dict:
        return {"start": self.start, "end": self.end}

    def contains(self, offset: int) -> bool:
        return self.start <= offset < self.end

    def encloses(self, other: "Span") -> bool:
        return self.start <= other.start and other.end <= self.end


class _Lines:
    """Line table over the text: offsets, indents, blank/comment tests."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.starts = [0]
        pos = text.find("\n")
        while pos != -1:
            self.starts.append(pos + 1)
            pos = text.find("\n", pos + 1)

    def __len__(self) -> int:
        return len(self.starts)

    def start(self, i: int) -> int:
        return self.starts[i]

    def after(self, i: int) -> int:
        """Offset just past line i (past its newline; len(text) on the last line)."""
        return self.starts[i + 1] if i + 1 < len(self.starts) else len(self.text)

    def content(self, i: int) -> str:
        end = self.after(i)
        text = self.text[self.starts[i]: end]
        return text.rstrip("\r\n")

    def indent(self, i: int) -> int:
        return len(_INDENT_RE.match(self.content(i)).group(0))

    def is_blank(self, i: int) -> bool:
        return self.content(i).strip() == ""

    def is_comment(self, i: int) -> bool:
        return self.content(i).strip().startswith("#")

    def index_at(self, offset: int) -> int:
        """Index of the line containing the offset."""
        lo, hi = 0, len(self.starts) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if self.starts[mid] <= offset:
                lo = mid
            else:
                hi = mid - 1
        return lo

    def block_last_line(self, anchor_line: int, min_indent: int) -> int:
        """Last content line of the block opened at anchor_line.

        The block continues over blank lines and lines indented at least min_indent;
        trailing blank lines are not part of the block.
        """
        last = anchor_line
        i = anchor_line + 1
        while i < len(self.starts):
            if self.is_blank(i):
                i += 1
                continue
            if self.indent(i) < min_indent:
                break
            last = i
            i += 1
        return last

    def attach_comments(self, anchor_line: int, indent: int) -> int:
        """First line of the comment run directly above anchor_line at the same indent."""
        first = anchor_line
        while (
            first - 1 >= 0
            and self.is_comment(first - 1)
            and not self.is_blank(first - 1)
            and self.indent(first - 1) == indent
        ):
            first -= 1
        return first


# --- model --------------------------------------------------------------------------------


@dataclass
class Property:
    key: str
    kind: str  # "scalar" | "binding" | "composite" | "handler"
    value_preview: str
    span: Span  # whole lines: key line .. end of the value block
    value_span: Span | None  # exact scalar value span (marks), None for composites

    def as_dict(self, spans: bool = True) -> dict:
        d = {"key": self.key, "kind": self.kind, "valuePreview": self.value_preview}
        if spans:
            d["span"] = self.span.as_dict()
            d["valueSpan"] = self.value_span.as_dict() if self.value_span else None
        return d


@dataclass
class Pair:
    """A raw mapping entry of a component (including Тип/Имя and slot keys)."""

    key: str
    value: object  # the composed yaml value node
    key_line: int
    key_col: int
    span: Span  # whole lines: key line .. end of the nested block
    scalar_span: Span | None


@dataclass
class Node:
    id: str
    kind: str  # "component" | "slot"
    span: Span  # includes the attached comments above
    content_span: Span  # without the attached comments
    parent_id: str | None = None
    children: list["Node"] = field(default_factory=list)
    properties: list[Property] = field(default_factory=list)
    type_full: str | None = None
    name: str | None = None
    slot: str | None = None  # component: the parent slot name
    list_style: bool | None = None  # slot: children are written as a "-" list
    # geometry for edit computation
    anchor_line: int = 0  # dash line (list item) / first key line (mapping) / key line (slot)
    body_col: int | None = None  # column of the mapping keys (component) or None
    dash_col: int | None = None  # list item: column of its dash; slot: column of item dashes

    @property
    def type(self) -> str | None:
        if not self.type_full:
            return None
        angle = self.type_full.find("<")
        return self.type_full[:angle].strip() if angle > 0 else self.type_full

    # populated for components only
    pairs: dict[str, Pair] = field(default_factory=dict)
    pair_list: list[Pair] = field(default_factory=list)


@dataclass
class ComponentProperty:
    """One record of the top-level Свойства section ({Имя, Тип} with comments)."""

    name: str | None
    type_full: str | None
    span: Span  # whole lines: the attached comments above the dash .. end of the record
    content_span: Span  # without the attached comments
    name_span: Span | None  # exact scalar span of the Имя value
    type_span: Span | None  # exact scalar span of the Тип value
    anchor_line: int  # the dash line of the record
    body_col: int | None  # column of the record's keys (None for an opaque scalar item)

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "type": self.type_full,
            "span": self.span.as_dict(),
            "nameSpan": self.name_span.as_dict() if self.name_span else None,
            "typeSpan": self.type_span.as_dict() if self.type_span else None,
        }


@dataclass
class PropertiesSection:
    """The top-level Свойства section of the component file.

    supported=False marks a spelling the line-based operations do not edit (a flow
    collection or a non-list value); the entries are empty then.
    """

    span: Span  # whole lines: comments above the key .. end of the section block
    content_span: Span  # the key line .. end of the section block
    key_line: int
    key_col: int
    dash_col: int | None  # None for an empty section ("Свойства:" with no items)
    entries: list[ComponentProperty] = field(default_factory=list)
    supported: bool = True


@dataclass
class Form:
    text: str
    root: Node
    nodes: dict[str, Node]
    lines: _Lines
    nl: str
    step: int  # indentation step detected from the file itself
    properties_section: PropertiesSection | None = None

    @property
    def component_properties(self) -> list[ComponentProperty]:
        return self.properties_section.entries if self.properties_section else []


# --- parsing ------------------------------------------------------------------------------


def _dominant_nl(text: str) -> str:
    from xbsl import fixer

    return fixer._dominant_newline(text) if text else "\n"


def _detect_step(lines: _Lines) -> int:
    """Indentation step sampled from the first key that opens a deeper block."""
    for i in range(len(lines) - 1):
        content = lines.content(i).strip()
        if not content or content.startswith("#") or not content.endswith(":"):
            continue
        j = i + 1
        while j < len(lines) and lines.is_blank(j):
            j += 1
        if j < len(lines) and lines.indent(j) > lines.indent(i):
            return lines.indent(j) - lines.indent(i)
    return 4


def _is_block_collection(node: object) -> bool:
    return isinstance(node, (yaml.MappingNode, yaml.SequenceNode)) and not node.flow_style


def _mapping_pairs(node: yaml.MappingNode) -> list[tuple[yaml.ScalarNode, object]]:
    return [(k, v) for k, v in node.value if isinstance(k, yaml.ScalarNode)]


def _scalar_of(node: yaml.MappingNode, key: str) -> str | None:
    for k, v in _mapping_pairs(node):
        if k.value == key and isinstance(v, yaml.ScalarNode) and v.value:
            return str(v.value)
    return None


def _one_line(value: str) -> str:
    value = " ".join(value.split())
    if len(value) > _PREVIEW_LIMIT:
        value = value[: _PREVIEW_LIMIT - 3] + "..."
    return value


def _classify_property(key: str, value: object) -> tuple[str, str]:
    """(kind, value_preview) of a non-slot mapping entry."""
    if isinstance(value, yaml.ScalarNode):
        raw = str(value.value) if value.value is not None else ""
        if raw.startswith("=") or raw.startswith("$"):
            return "binding", _one_line(raw)
        if _HANDLER_KEY_RE.match(key):
            return "handler", _one_line(raw)
        return "scalar", _one_line(raw)
    if isinstance(value, yaml.MappingNode):
        type_name = _scalar_of(value, "Тип")
        return "composite", type_name or "{...}"
    return "composite", "[...]"


def _find_dash_line(lines: _Lines, content_line: int, dash_col: int) -> int:
    """The "-" line introducing the sequence item whose content starts at content_line."""
    content = lines.content(content_line)
    if lines.indent(content_line) == dash_col and content.strip().startswith("-"):
        return content_line  # inline item: "- Ключ: значение"
    i = content_line - 1
    while i >= 0:
        stripped = lines.content(i).strip()
        if stripped.startswith("-") and lines.indent(i) == dash_col:
            return i
        if stripped.startswith("#") or stripped == "":
            i -= 1
            continue
        break
    return content_line  # defensive fallback: treat the content line as the anchor


class _Builder:
    def __init__(self, text: str) -> None:
        self.lines = _Lines(text)
        self.text = text
        self.nodes: dict[str, Node] = {}

    def _line_span(self, first_line: int, last_line: int) -> Span:
        return Span(self.lines.start(first_line), self.lines.after(last_line))

    def _pairs_of(self, map_node: yaml.MappingNode) -> tuple[dict[str, Pair], list[Pair]]:
        pairs: dict[str, Pair] = {}
        order: list[Pair] = []
        for k, v in _mapping_pairs(map_node):
            key_line = k.start_mark.line
            key_col = k.start_mark.column
            last = self.lines.block_last_line(key_line, key_col + 1)
            scalar_span = None
            if isinstance(v, yaml.ScalarNode) and v.end_mark.index > v.start_mark.index:
                scalar_span = Span(v.start_mark.index, v.end_mark.index)
            pair = Pair(
                key=str(k.value), value=v, key_line=key_line, key_col=key_col,
                span=self._line_span(key_line, last), scalar_span=scalar_span,
            )
            order.append(pair)
            pairs.setdefault(pair.key, pair)
        return pairs, order

    def build_component(
        self,
        value_node: object,
        node_id: str,
        parent_id: str | None,
        slot_name: str | None,
        anchor_line: int,
        min_indent: int,
        comment_indent: int,
        dash_col: int | None,
    ) -> Node:
        last = self.lines.block_last_line(anchor_line, min_indent)
        first = self.lines.attach_comments(anchor_line, comment_indent)
        node = Node(
            id=node_id, kind="component",
            span=self._line_span(first, last),
            content_span=self._line_span(anchor_line, last),
            parent_id=parent_id, slot=slot_name,
            anchor_line=anchor_line, dash_col=dash_col,
        )
        self.nodes[node_id] = node
        if not isinstance(value_node, yaml.MappingNode):
            return node  # an opaque scalar item keeps only its span
        node.body_col = value_node.start_mark.column
        node.pairs, node.pair_list = self._pairs_of(value_node)
        node.type_full = _scalar_of(value_node, "Тип")
        node.name = _scalar_of(value_node, "Имя")
        for pair in node.pair_list:
            if pair.key in CHILD_SLOTS and (
                _is_block_collection(pair.value)
                or (isinstance(pair.value, yaml.ScalarNode) and not pair.value.value)
            ):
                node.children.append(self.build_slot(pair, node))
            elif pair.key not in ("Тип", "Имя"):
                kind, preview = _classify_property(pair.key, pair.value)
                node.properties.append(Property(
                    key=pair.key, kind=kind, value_preview=preview,
                    span=pair.span, value_span=pair.scalar_span,
                ))
        return node

    def build_slot(self, pair: Pair, parent: Node) -> Node:
        slot_id = f"{parent.id}/{pair.key}"
        first = self.lines.attach_comments(pair.key_line, pair.key_col)
        last = self.lines.block_last_line(pair.key_line, pair.key_col + 1)
        slot = Node(
            id=slot_id, kind="slot", name=pair.key,
            span=self._line_span(first, last),
            content_span=self._line_span(pair.key_line, last),
            parent_id=parent.id, anchor_line=pair.key_line,
            body_col=pair.key_col, list_style=False,
        )
        self.nodes[slot_id] = slot
        value = pair.value
        if isinstance(value, yaml.SequenceNode):
            slot.list_style = True
            slot.dash_col = value.start_mark.column
            for i, item in enumerate(value.value):
                content_line = item.start_mark.line
                dash_line = _find_dash_line(self.lines, content_line, slot.dash_col)
                slot.children.append(self.build_component(
                    item, f"{slot_id}[{i}]", slot_id, pair.key,
                    anchor_line=dash_line, min_indent=slot.dash_col + 1,
                    comment_indent=slot.dash_col, dash_col=slot.dash_col,
                ))
        elif isinstance(value, yaml.MappingNode):
            slot.children.append(self.build_component(
                value, f"{slot_id}[0]", slot_id, pair.key,
                anchor_line=value.start_mark.line, min_indent=value.start_mark.column,
                comment_indent=value.start_mark.column, dash_col=None,
            ))
        # an empty scalar value ("Слот:" with nothing nested) keeps zero children
        return slot

    def build_properties(self, key_node: yaml.ScalarNode, value: object) -> PropertiesSection:
        key_line = key_node.start_mark.line
        key_col = key_node.start_mark.column
        first = self.lines.attach_comments(key_line, key_col)
        last = self.lines.block_last_line(key_line, key_col + 1)
        section = PropertiesSection(
            span=self._line_span(first, last),
            content_span=self._line_span(key_line, last),
            key_line=key_line, key_col=key_col, dash_col=None,
        )
        if isinstance(value, yaml.ScalarNode) and not value.value:
            return section  # "Свойства:" with an empty value - a section with no records
        if not isinstance(value, yaml.SequenceNode) or value.flow_style:
            section.supported = False
            return section
        section.dash_col = value.start_mark.column
        for item in value.value:
            content_line = item.start_mark.line
            dash_line = _find_dash_line(self.lines, content_line, section.dash_col)
            item_last = self.lines.block_last_line(dash_line, section.dash_col + 1)
            item_first = self.lines.attach_comments(dash_line, section.dash_col)
            name = type_full = None
            name_span = type_span = None
            body_col = None
            if isinstance(item, yaml.MappingNode):
                body_col = item.start_mark.column
                name = _scalar_of(item, "Имя")
                type_full = _scalar_of(item, "Тип")
                for k, v in _mapping_pairs(item):
                    if not isinstance(v, yaml.ScalarNode) or v.end_mark.index <= v.start_mark.index:
                        continue
                    if k.value == "Имя":
                        name_span = Span(v.start_mark.index, v.end_mark.index)
                    elif k.value == "Тип":
                        type_span = Span(v.start_mark.index, v.end_mark.index)
            section.entries.append(ComponentProperty(
                name=name, type_full=type_full,
                span=self._line_span(item_first, item_last),
                content_span=self._line_span(dash_line, item_last),
                name_span=name_span, type_span=type_span,
                anchor_line=dash_line, body_col=body_col,
            ))
        return section


def parse_form(text: str) -> Form:
    """Parse an interface component yaml into the node tree.

    Raises FormModelError for anything that is not a well-formed КомпонентИнтерфейса
    with a Наследует block (the message is user-facing, in Russian).
    """
    try:
        root_yaml = yaml.compose(text, Loader=yaml.SafeLoader)
    except yaml.MarkedYAMLError as exc:
        mark = exc.problem_mark
        where = f" (строка {mark.line + 1})" if mark is not None else ""
        raise FormModelError(f"Ошибка разбора yaml: {exc.problem}{where}") from exc
    except yaml.YAMLError as exc:
        raise FormModelError(f"Ошибка разбора yaml: {exc}") from exc
    if not isinstance(root_yaml, yaml.MappingNode):
        raise FormModelError("Файл не является yaml-описанием элемента (нет маппинга верхнего уровня)")
    element_kind = _scalar_of(root_yaml, "ВидЭлемента")
    if element_kind != COMPONENT_ELEMENT_KIND:
        raise FormModelError(
            f"Файл не является компонентом интерфейса (ВидЭлемента: {element_kind or 'не задан'})"
        )
    inherit_pair = next(
        ((k, v) for k, v in _mapping_pairs(root_yaml) if k.value == ROOT_KEY), None
    )
    if inherit_pair is None or not isinstance(inherit_pair[1], yaml.MappingNode):
        raise FormModelError("В компоненте нет блока Наследует – дерево формы отсутствует")
    key_node, inherit = inherit_pair
    if inherit.flow_style:
        raise FormModelError("Блок Наследует записан во flow-стиле – он не поддерживается")

    builder = _Builder(text)
    root = builder.build_component(
        inherit, ROOT_KEY, None, None,
        anchor_line=key_node.start_mark.line, min_indent=key_node.start_mark.column + 1,
        comment_indent=key_node.start_mark.column, dash_col=None,
    )
    props_pair = next(
        ((k, v) for k, v in _mapping_pairs(root_yaml) if k.value == PROPERTIES_KEY), None
    )
    section = builder.build_properties(*props_pair) if props_pair is not None else None
    return Form(
        text=text, root=root, nodes=builder.nodes, lines=builder.lines,
        nl=_dominant_nl(text), step=_detect_step(builder.lines),
        properties_section=section,
    )


# --- queries ------------------------------------------------------------------------------


def node_at(form: Form, offset: int) -> Node | None:
    """The deepest node (component or slot) whose span contains the offset."""
    if not form.root.span.contains(offset):
        return None
    node = form.root
    descended = True
    while descended:
        descended = False
        for child in node.children:
            if child.span.contains(offset):
                node = child
                descended = True
                break
    return node


def get_node(form: Form, node_id: str) -> Node:
    node = form.nodes.get(node_id or "")
    if node is None:
        raise FormModelError(f"Узел не найден: {node_id}")
    return node


def get_component(form: Form, node_id: str) -> Node:
    node = get_node(form, node_id)
    if node.kind != "component":
        raise FormModelError(f"Узел не является компонентом: {node_id}")
    return node


def parent_component(form: Form, node: Node) -> Node | None:
    """The nearest ancestor COMPONENT of the node, slots skipped; None for the root.

    A slot resolves to its owner component, a component to the component above its slot.
    Serialized (without children) into the "parent" field of the one-node surfaces
    (LSP xbsl/formNodeAt, CLI form-tree --at) so the properties panel can show the owner
    of a slot the cursor landed on.
    """
    current = node.parent_id
    while current is not None:
        parent = form.nodes.get(current)
        if parent is None:
            return None
        if parent.kind == "component":
            return parent
        current = parent.parent_id
    return None


def node_dict(node: Node, *, property_spans: bool = True, deep: bool = True) -> dict:
    """Serializable node for the LSP/MCP/CLI surfaces (camelCase keys for clients).

    "contentSpan" is the span without the leading comments attached to the node (equal
    to "span" when there are none): clients move the cursor to contentSpan.start, while
    moves/copies keep operating on the full span.
    """
    d: dict = {
        "id": node.id,
        "kind": node.kind,
        "span": node.span.as_dict(),
        "contentSpan": node.content_span.as_dict(),
    }
    if node.kind == "component":
        d["type"] = node.type
        d["typeFull"] = node.type_full
        d["name"] = node.name
        d["slot"] = node.slot
        d["properties"] = [p.as_dict(spans=property_spans) for p in node.properties]
    else:
        d["name"] = node.name
        d["list"] = bool(node.list_style)
    if deep:
        d["children"] = [
            node_dict(c, property_spans=property_spans, deep=True) for c in node.children
        ]
    return d


def component_properties_dicts(form: Form) -> list[dict]:
    """The Свойства records for the tree surfaces ("componentProperties" - not tree nodes)."""
    return [p.as_dict() for p in form.component_properties]
