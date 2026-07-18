"""Editing operations of the form designer: precise text edits over the form model.

Every operation is a pure function `text + arguments -> [TextEdit]` (plus the id/span of
the resulting node): the file is never rewritten wholesale, so the formatting, comments
and key order of untouched lines survive by construction - the same philosophy as
scaffold.py. The operations are consumed by three surfaces (lsp.py, mcp_server.py,
cli.py) through the shared dispatcher `apply_operation`; `op_component_edit` wraps an
operation into a ScaffoldResult for the surfaces that write to disk.

Conventions (documented decisions):
    - Every result is validated: the edits are applied to a scratch copy and the file is
      re-parsed; the resulting node is located by its span start. An unparseable result
      (e.g. a bad value_yaml fragment) is an error, not a broken write.
    - A node moves/duplicates/deletes together with the comments attached above it (see
      formmodel). wrap/unwrap leave the attached comments of the wrapped/unwrapped node
      in place, so wrap followed by unwrap is byte-identical.
    - Inserting into a slot that holds a single nested mapping converts the slot to the
      "-" list form (the existing child is reindented one step deeper under its own
      dash); removing down to one child does NOT convert back - the designer never
      re-normalizes what it does not touch.
    - Inserting into a missing or empty slot writes the single-mapping form, matching
      how the platform generators spell a singleton child.
    - Removing the last child of a slot removes the slot key line as well ("Слот:" with
      an empty value does not compile); the slot's own attached comments go with it.
    - The indentation step is detected from the file itself (formmodel._detect_step);
      list-item geometry is taken from the existing siblings of the target slot.
    - insert_fragment pastes a READY yaml block of one component (what the structure
      panel copied): the fragment is dedented to its margin and re-indented to the
      destination; the internal relative indentation is preserved as pasted. Blank lines
      inside the run of leading comments are dropped so the comments stay attached to
      the inserted node (the formmodel attachment rule).
    - The property_* operations edit the top-level Свойства section only. The section is
      created right after the Наследует block - the corpus spelling (49 of 50 files put
      Свойства immediately after Наследует). property_rename does NOT rewrite the
      bindings that use the property (=Имя...): the result carries a note with the usage
      count so the client can warn.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from xbsl import engine
from xbsl.formmodel import (
    CHILD_SLOTS,
    PROPERTIES_KEY,
    ROOT_KEY,
    Form,
    FormModelError,
    Node,
    PropertiesSection,
    Span,
    get_component,
    get_node,
    node_at,
    parse_form,
)
from xbsl.scaffold import FileChange, ScaffoldResult, TextEdit

_NAME_RE = re.compile(r"^[A-Za-zА-Яа-яЁё_][A-Za-zА-Яа-яЁё0-9_]*$")
_TYPE_RE = re.compile(r"^[A-Za-zА-Яа-яЁё_][A-Za-zА-Яа-яЁё0-9_.<>,: ?-]*$")
#: Types of the Свойства records additionally allow unions ("Накладная.Ссылка|?").
_PROPERTY_TYPE_RE = re.compile(r"^[A-Za-zА-Яа-яЁё_][A-Za-zА-Яа-яЁё0-9_.<>,:| ?-]*$")
_NUMBER_RE = re.compile(r"^-?\d+(?:\.\d+)?$")
_BARE_SCALAR_RE = re.compile(r"^[=$A-Za-zА-Яа-яЁё0-9_][A-Za-zА-Яа-яЁё0-9_.,()<> =/-]*$")
#: Plain spellings YAML would read as a non-string type - always quoted.
_YAML_AMBIGUOUS = {"true", "false", "yes", "no", "on", "off", "null", "~"}

OPERATIONS = (
    "insert", "insert_fragment", "move", "remove", "wrap", "unwrap",
    "duplicate", "rename", "set_property", "reset_property",
    "property_add", "property_retype", "property_remove", "property_rename",
)


@dataclass
class EditResult:
    edits: list[TextEdit]  # ascending, non-overlapping, offsets in the SOURCE text
    new_text: str  # the text with the edits applied
    node_id: str | None  # the resulting node in the NEW text (None for remove)
    node_span: Span | None
    # Warnings for the client (e.g. the binding-usage count on property_rename); the
    # file-level wrapper copies them into ScaffoldResult.notes.
    notes: list[str] = field(default_factory=list)

    def edits_dicts(self) -> list[dict]:
        return [{"start": e.start, "end": e.end, "newText": e.new_text} for e in self.edits]

    def node_dict(self) -> dict | None:
        if self.node_id is None:
            return None
        return {"id": self.node_id, "span": self.node_span.as_dict()}


def apply_edits(text: str, edits: list[TextEdit]) -> str:
    """Apply non-overlapping edits; zero-width inserts at a removal start apply cleanly."""
    ordered = sorted(edits, key=lambda e: (e.start, e.end))
    for a, b in zip(ordered, ordered[1:]):
        if a.end > b.start:
            raise FormModelError("внутренняя ошибка: правки пересекаются")
    for e in reversed(ordered):
        text = text[: e.start] + e.new_text + text[e.end :]
    return text


# --- text-shaping helpers -----------------------------------------------------------------


def _reindent(block: str, delta: int) -> str:
    """Shift every non-blank line of the block by delta spaces (negative - dedent)."""
    if delta == 0 or not block:
        return block
    out = []
    for line in block.split("\n"):
        body = line.rstrip("\r")
        tail = line[len(body):]
        if body.strip() == "":
            out.append(line)
        elif delta > 0:
            out.append(" " * delta + body + tail)
        else:
            if body[:-delta].strip() != "":
                raise FormModelError("внутренняя ошибка: недостаточный отступ переносимого блока")
            out.append(body[-delta:] + tail)
    return "\n".join(out)


def _split_payload(form: Form, node: Node) -> tuple[str, str]:
    """(attached comments, content) slices of the node, both made of whole lines."""
    comments = form.text[node.span.start : node.content_span.start]
    content = form.text[node.content_span.start : node.content_span.end]
    if content and not content.endswith("\n"):
        content += form.nl  # the node closed the file without a trailing newline
    return comments, content


def _item_content_to_mapping(form: Form, node: Node, content: str, dest_col: int) -> str:
    """List-item content (the dash line + body) rendered as a plain nested mapping."""
    if node.body_col is None:
        raise FormModelError(
            "Элемент без блока свойств нельзя разместить одиночным значением слота"
        )
    first, _, rest = content.partition("\n")
    delta = dest_col - node.body_col
    stripped = first.strip()
    if stripped == "-":
        return _reindent(rest, delta)
    # inline item "- Ключ: значение": the first key moves onto its own line
    head = " " * dest_col + stripped[1:].lstrip() + first[len(first.rstrip("\r")):]
    return head + "\n" + _reindent(rest, delta)


def _as_item(form: Form, node: Node, dest_dash: int) -> str:
    """The node (with its attached comments) rendered as a list item at dest_dash."""
    comments, content = _split_payload(form, node)
    if node.dash_col is not None:
        return _reindent(comments + content, dest_dash - node.dash_col)
    if node.body_col is None:
        raise FormModelError("внутренняя ошибка: у узла нет ни маркера списка, ни блока свойств")
    dash_line = " " * dest_dash + "-" + form.nl
    return (
        _reindent(comments, dest_dash - node.body_col)
        + dash_line
        + _reindent(content, dest_dash + form.step - node.body_col)
    )


def _as_mapping(form: Form, node: Node, dest_col: int) -> str:
    """The node (with its attached comments) rendered as a slot's single nested mapping."""
    comments, content = _split_payload(form, node)
    if node.dash_col is None:
        return _reindent(comments + content, dest_col - node.body_col)
    if node.body_col is None:
        raise FormModelError(
            "Элемент без блока свойств нельзя разместить одиночным значением слота"
        )
    return (
        _reindent(comments, dest_col - node.dash_col)
        + _item_content_to_mapping(form, node, content, dest_col)
    )


def _convert_child_to_item(form: Form, child: Node, removal: Span | None) -> str:
    """The single nested-mapping child rewritten as a list item under its own dash.

    The dash lands at the child's former body column and the body goes one step deeper -
    the reverse of how the platform spells a singleton. removal, when given, is a span
    INSIDE the child's content that must disappear in the same edit (a node being moved
    out of this child while the slot is converting).
    """
    if child.body_col is None:
        raise FormModelError("Слот содержит скалярный элемент – преобразование не поддерживается")
    comments, content = _split_payload(form, child)
    if removal is not None:
        rel_s = removal.start - child.content_span.start
        rel_e = removal.end - child.content_span.start
        if rel_s < 0 or rel_e > len(content):
            raise FormModelError("внутренняя ошибка: удаляемый диапазон вне преобразуемого блока")
        content = content[:rel_s] + content[rel_e:]
    dash_line = " " * child.body_col + "-" + form.nl
    return comments + dash_line + _reindent(content, form.step)


# --- validation helpers -------------------------------------------------------------------


def _check_slot(slot: str) -> str:
    if slot not in CHILD_SLOTS:
        raise FormModelError(
            f"Слот не поддерживается: {slot} (доступны: {', '.join(CHILD_SLOTS)})"
        )
    return slot


def _check_name(name: str) -> str:
    if not _NAME_RE.match(name):
        raise FormModelError(
            f"Недопустимое имя компонента: '{name}' (нужен идентификатор: буквы, цифры, подчёркивание)"
        )
    return name


def _check_type(type_: str) -> str:
    if not _TYPE_RE.match(type_) or ": " in type_ or type_.endswith(":") or type_ != type_.strip():
        raise FormModelError(f"Недопустимый тип компонента: '{type_}'")
    return type_


def _check_property_key(key: str) -> str:
    if key in CHILD_SLOTS:
        raise FormModelError(
            f"Ключ {key} – слот дочерних компонентов; используйте операции insert/move/remove"
        )
    if not _NAME_RE.match(key):
        raise FormModelError(f"Недопустимое имя свойства: '{key}'")
    return key


def _encode_scalar(value: str) -> str:
    """A yaml spelling of the value: bare where unambiguous, JSON double quotes otherwise."""
    if _NUMBER_RE.match(value):
        return value
    if (
        value
        and value == value.strip()
        and value.lower() not in _YAML_AMBIGUOUS
        and _BARE_SCALAR_RE.match(value)
    ):
        return value
    return json.dumps(value, ensure_ascii=False)


def _not_root(node: Node, действие: str) -> Node:
    if node.id == ROOT_KEY:
        raise FormModelError(f"Корневой узел формы нельзя {действие}")
    return node


def _resolve_sibling(form: Form, slot_node: Node, sib_id: str | None) -> Node | None:
    if sib_id is None:
        return None
    sib = get_node(form, sib_id)
    if sib.parent_id != slot_node.id:
        raise FormModelError(f"Узел {sib_id} не находится в слоте {slot_node.name}")
    return sib


# --- the shared insertion planner ---------------------------------------------------------


@dataclass
class _Plan:
    edits: list[TextEdit]
    anchor: int  # offset of the resulting node's span start in the NEW text
    removal_consumed: bool = False


def _plan_insert(form, parent, slot_name, item_fn, map_fn, before, after,
                 removal: Span | None) -> _Plan:
    """Where and how a new/moved block lands in the parent's slot.

    item_fn(dash_col) renders the payload as a "-" list item; map_fn(body_col) renders
    it as a slot's single nested mapping (both end with a newline). removal is the span
    the caller is deleting in the same operation (move) - it offsets the reported anchor
    and, when it falls inside the child of a converting slot, is folded into the
    conversion edit (removal_consumed=True).
    """
    if before is not None and after is not None:
        raise FormModelError("Укажите только один из параметров before и after")
    text, nl, step = form.text, form.nl, form.step
    slot_node = next(
        (c for c in parent.children if c.kind == "slot" and c.name == slot_name), None
    )

    def shift(pos: int) -> int:
        if removal is not None and removal.end <= pos:
            return -(removal.end - removal.start)
        return 0

    def eof_fix(pos: int, fragment: str) -> tuple[str, int]:
        if pos == len(text) and text and not text.endswith("\n"):
            return nl + fragment, len(nl)
        return fragment, 0

    if slot_node is None:
        if slot_name in parent.pairs:
            raise FormModelError(
                f"Свойство {slot_name} задано не блочным значением – операция невозможна"
            )
        if before is not None or after is not None:
            raise FormModelError(
                f"В слоте {slot_name} нет узлов – позиционирование before/after невозможно"
            )
        col = parent.body_col
        pos = parent.content_span.end
        key_line = " " * col + slot_name + ":" + nl
        fragment, lead = eof_fix(pos, key_line + map_fn(col + step))
        return _Plan([TextEdit(pos, pos, fragment)], pos + shift(pos) + lead + len(key_line))

    if slot_node.list_style:
        sib_before = _resolve_sibling(form, slot_node, before)
        sib_after = _resolve_sibling(form, slot_node, after)
        if sib_before is not None:
            pos = sib_before.span.start
        elif sib_after is not None:
            pos = sib_after.span.end
        else:
            pos = slot_node.content_span.end
        fragment, lead = eof_fix(pos, item_fn(slot_node.dash_col))
        return _Plan([TextEdit(pos, pos, fragment)], pos + shift(pos) + lead)

    if not slot_node.children:  # "Слот:" with an empty value
        if before is not None or after is not None:
            raise FormModelError(
                f"В слоте {slot_name} нет узлов – позиционирование before/after невозможно"
            )
        pos = slot_node.content_span.end
        fragment, lead = eof_fix(pos, map_fn(slot_node.body_col + step))
        return _Plan([TextEdit(pos, pos, fragment)], pos + shift(pos) + lead)

    # a single nested mapping: the slot converts to the "-" list form
    child = slot_node.children[0]
    _resolve_sibling(form, slot_node, before)
    _resolve_sibling(form, slot_node, after)
    removal_inside = removal is not None and child.content_span.encloses(removal)
    converted = _convert_child_to_item(form, child, removal if removal_inside else None)
    item = item_fn(child.body_col)
    new_first = before == child.id
    replacement = item + converted if new_first else converted + item
    region = child.span
    anchor = region.start + shift(region.start) + (0 if new_first else len(converted))
    return _Plan(
        [TextEdit(region.start, region.end, replacement)], anchor,
        removal_consumed=removal_inside,
    )


def _finish(text: str, edits: list[TextEdit], anchor: int | None) -> EditResult:
    """Validate the edits by applying and re-parsing; locate the resulting node."""
    new_text = apply_edits(text, edits)
    try:
        form = parse_form(new_text)
    except FormModelError as exc:
        raise FormModelError(f"Правка делает файл неразборным: {exc}") from exc
    ordered = sorted(edits, key=lambda e: (e.start, e.end))
    if anchor is None:
        return EditResult(ordered, new_text, None, None)
    node = node_at(form, anchor)
    # The anchor points at the first line the operation wrote (or kept) for the node.
    # span.start may sit ABOVE the anchor when neighbouring comments got attached to the
    # node - the payload's own comments, the wrapped node's comments now describing the
    # wrapper, or a stray trailing comment adopted by an insertion below it - so the
    # anchor is only required to fall between the comments and the first content line.
    if (
        node is None
        or node.kind != "component"
        or not node.span.start <= anchor <= node.content_span.start
    ):
        raise FormModelError("внутренняя ошибка: узел-результат не найден после правки")
    return EditResult(ordered, new_text, node.id, node.span)


# --- operations ---------------------------------------------------------------------------


def insert_component(text: str, parent_id: str, slot: str, type_: str | None = None,
                     name: str | None = None, before: str | None = None,
                     after: str | None = None) -> EditResult:
    """A minimal new component (Тип and/or Имя) into the parent's slot."""
    form = parse_form(text)
    parent = get_component(form, parent_id)
    if parent.body_col is None:
        raise FormModelError(f"У узла {parent_id} нет блока свойств – вставка невозможна")
    _check_slot(slot)
    if not type_ and not name:
        raise FormModelError("Укажите хотя бы тип или имя нового компонента")
    lines0 = []
    if type_:
        lines0.append(f"Тип: {_check_type(type_)}")
    if name:
        lines0.append(f"Имя: {_check_name(name)}")
    nl, step = form.nl, form.step

    def item_fn(dash: int) -> str:
        return " " * dash + "-" + nl + "".join(" " * (dash + step) + l + nl for l in lines0)

    def map_fn(col: int) -> str:
        return "".join(" " * col + l + nl for l in lines0)

    plan = _plan_insert(form, parent, slot, item_fn, map_fn, before, after, removal=None)
    return _finish(text, plan.edits, plan.anchor)


def _fragment_component_lines(fragment: str) -> tuple[list[str], int]:
    """The pasted component fragment as dedented lines: (lines, leading comment count).

    The fragment must be ONE yaml mapping with a top-level Тип key (what the structure
    panel copies), optionally with attached comments above. A list, several components
    or a scalar raise a user-facing error; the component type is deliberately NOT
    checked against any catalog - project components are as valid as platform ones.
    """
    if not fragment or not fragment.strip():
        raise FormModelError("Пустой yaml-фрагмент компонента")
    try:
        composed = yaml.compose(fragment, Loader=yaml.SafeLoader)
    except yaml.YAMLError as exc:
        raise FormModelError(f"Фрагмент не является корректным yaml: {exc}") from exc
    if isinstance(composed, yaml.SequenceNode):
        raise FormModelError(
            "Фрагмент содержит список элементов – вставляйте компоненты по одному, "
            "без маркера списка \"-\""
        )
    if not isinstance(composed, yaml.MappingNode):
        raise FormModelError(
            "Фрагмент не является yaml-блоком компонента (ожидается маппинг с ключом Тип)"
        )
    keys = [k.value for k, _v in composed.value if isinstance(k, yaml.ScalarNode)]
    type_count = keys.count("Тип")
    if type_count > 1:
        raise FormModelError(
            f"Во фрагменте несколько компонентов (ключ Тип встречается {type_count} раза) – "
            "вставляйте по одному"
        )
    if type_count == 0:
        raise FormModelError("Во фрагменте нет верхнеуровневого ключа Тип")

    lines = [ln.rstrip() for ln in fragment.replace("\r\n", "\n").split("\n")]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    common = min(len(ln) - len(ln.lstrip(" ")) for ln in lines if ln.strip())
    lines = [ln[common:] if ln.strip() else "" for ln in lines]
    # The leading comments become the node's attached comments: blank lines inside the
    # run would detach them (the formmodel rule), so they are dropped from the run.
    comments: list[str] = []
    rest = list(lines)
    while rest and (not rest[0].strip() or rest[0].lstrip().startswith("#")):
        line = rest.pop(0)
        if line.strip():
            comments.append(line)
    return comments + rest, len(comments)


def insert_fragment(text: str, parent_id: str, slot: str, fragment: str,
                    before: str | None = None, after: str | None = None) -> EditResult:
    """Paste a copied component subtree (a ready yaml block) into the parent's slot.

    The fragment is re-indented to the destination (the file's own step decides where
    the body lands); its internal relative indentation survives as pasted. The slot
    rules are the same as insert_component: a missing slot is created, a single-mapping
    slot converts to the "-" list form.
    """
    form = parse_form(text)
    parent = get_component(form, parent_id)
    if parent.body_col is None:
        raise FormModelError(f"У узла {parent_id} нет блока свойств – вставка невозможна")
    _check_slot(slot)
    lines0, n_comments = _fragment_component_lines(fragment)
    nl, step = form.nl, form.step

    def render(prefix_col: int, body_col: int, dash: bool) -> str:
        out = []
        for line in lines0[:n_comments]:
            out.append(" " * prefix_col + line + nl)
        if dash:
            out.append(" " * prefix_col + "-" + nl)
        for line in lines0[n_comments:]:
            out.append((" " * body_col + line if line else "") + nl)
        return "".join(out)

    def item_fn(dash_col: int) -> str:
        return render(dash_col, dash_col + step, dash=True)

    def map_fn(col: int) -> str:
        return render(col, col, dash=False)

    plan = _plan_insert(form, parent, slot, item_fn, map_fn, before, after, removal=None)
    return _finish(text, plan.edits, plan.anchor)


def move_node(text: str, node_id: str, new_parent_id: str, slot: str,
              before: str | None = None, after: str | None = None) -> EditResult:
    """Move a node (with its attached comments) into another - or the same - slot."""
    form = parse_form(text)
    node = _not_root(get_component(form, node_id), "переместить")
    new_parent = get_component(form, new_parent_id)
    if new_parent.body_col is None:
        raise FormModelError(f"У узла {new_parent_id} нет блока свойств – вставка невозможна")
    _check_slot(slot)
    if new_parent_id == node_id or new_parent_id.startswith(node_id + "/"):
        raise FormModelError("Нельзя переместить узел внутрь его собственного поддерева")
    if node_id in (before, after):
        raise FormModelError("Нельзя позиционировать узел относительно самого себя")
    src_slot = get_node(form, node.parent_id)
    dest_slot = next(
        (c for c in new_parent.children if c.kind == "slot" and c.name == slot), None
    )
    if dest_slot is src_slot and len(src_slot.children) == 1:
        raise FormModelError("Узел – единственный в слоте, перемещать некуда")
    removal = node.span if len(src_slot.children) > 1 else src_slot.span
    plan = _plan_insert(
        form, new_parent, slot,
        lambda dash: _as_item(form, node, dash),
        lambda col: _as_mapping(form, node, col),
        before, after, removal=removal,
    )
    edits = list(plan.edits)
    if not plan.removal_consumed:
        edits.append(TextEdit(removal.start, removal.end, ""))
    return _finish(text, edits, plan.anchor)


def remove_node(text: str, node_id: str) -> EditResult:
    """Remove a node; the last child takes the slot key line down with it."""
    form = parse_form(text)
    node = _not_root(get_component(form, node_id), "удалить")
    src_slot = get_node(form, node.parent_id)
    removal = node.span if len(src_slot.children) > 1 else src_slot.span
    return _finish(text, [TextEdit(removal.start, removal.end, "")], None)


def wrap_node(text: str, node_id: str, container_type: str,
              name: str | None = None) -> EditResult:
    """Wrap a node in a new container; the node becomes its single Содержимое child.

    The attached comments of the node stay in place (above the new container), which
    keeps wrap followed by unwrap byte-identical.
    """
    form = parse_form(text)
    node = _not_root(get_component(form, node_id), "обернуть")
    _check_type(container_type)
    if name:
        _check_name(name)
    nl, step = form.nl, form.step
    region = node.content_span
    _, content = _split_payload(form, node)
    if node.dash_col is not None:
        dash, body = node.dash_col, node.dash_col + step
        head = " " * dash + "-" + nl + " " * body + f"Тип: {container_type}" + nl
        if name:
            head += " " * body + f"Имя: {name}" + nl
        head += " " * body + "Содержимое:" + nl
        replacement = head + _item_content_to_mapping(form, node, content, body + step)
    else:
        body = node.body_col
        head = " " * body + f"Тип: {container_type}" + nl
        if name:
            head += " " * body + f"Имя: {name}" + nl
        head += " " * body + "Содержимое:" + nl
        replacement = head + _reindent(content, step)
    return _finish(text, [TextEdit(region.start, region.end, replacement)], region.start)


def unwrap_node(text: str, node_id: str) -> EditResult:
    """Replace a container with its children (the container's comments stay in place)."""
    form = parse_form(text)
    node = _not_root(get_component(form, node_id), "распаковать")
    filled = [s for s in node.children if s.kind == "slot" and s.children]
    if not filled:
        raise FormModelError("У контейнера нет вложенных компонентов – распаковывать нечего")
    if len(filled) > 1:
        names = ", ".join(s.name for s in filled)
        raise FormModelError(
            f"У контейнера несколько слотов с содержимым ({names}) – распаковка неоднозначна"
        )
    kids = filled[0].children
    region = node.content_span
    if node.dash_col is not None:
        replacement = "".join(_as_item(form, kid, node.dash_col) for kid in kids)
    elif len(kids) == 1 and kids[0].body_col is not None:
        replacement = _as_mapping(form, kids[0], node.body_col)
    else:  # several children replace a single-mapping node: the parent slot becomes a list
        replacement = "".join(_as_item(form, kid, node.body_col) for kid in kids)
    return _finish(text, [TextEdit(region.start, region.end, replacement)], region.start)


def duplicate_node(text: str, node_id: str) -> EditResult:
    """Copy a node (comments included) right after the original, uniquifying every Имя."""
    form = parse_form(text)
    node = _not_root(get_component(form, node_id), "дублировать")
    src_slot = get_node(form, node.parent_id)
    payload = form.text[node.span.start : node.span.end]
    if payload and not payload.endswith("\n"):
        payload += form.nl
    renamed = _uniquify_names(form, node, payload)
    comments_len = node.content_span.start - node.span.start
    if src_slot.list_style:
        pos = node.span.end
        fragment, lead = renamed, 0
        if pos == len(text) and text and not text.endswith("\n"):
            fragment, lead = form.nl + fragment, len(form.nl)
        return _finish(text, [TextEdit(pos, pos, fragment)], pos + lead)
    # a single nested mapping: converting the slot, the copy becomes the second item
    converted = _convert_child_to_item(form, node, None)
    copy_item = (
        renamed[:comments_len]
        + " " * node.body_col + "-" + form.nl
        + _reindent(renamed[comments_len:], form.step)
    )
    region = node.span
    edits = [TextEdit(region.start, region.end, converted + copy_item)]
    return _finish(text, edits, region.start + len(converted))


def _unique_name(base: str, used: set[str]) -> str:
    m = re.match(r"^(.*?)(\d+)$", base)
    stem, n = (m.group(1), int(m.group(2)) + 1) if m else (base, 2)
    while f"{stem}{n}" in used:
        n += 1
    return f"{stem}{n}"


def _uniquify_names(form: Form, node: Node, payload: str) -> str:
    """Fresh Имя values for the copied subtree - a duplicate must not clash by name."""
    used = {n.name for n in form.nodes.values() if n.kind == "component" and n.name}
    replacements: list[tuple[int, int, str]] = []
    for desc_id, desc in form.nodes.items():
        if desc_id != node.id and not desc_id.startswith(node.id + "/"):
            continue
        if desc.kind != "component" or not desc.name:
            continue
        pair = desc.pairs.get("Имя")
        if pair is None or pair.scalar_span is None:
            continue
        fresh = _unique_name(desc.name, used)
        used.add(fresh)
        replacements.append(
            (pair.scalar_span.start - node.span.start,
             pair.scalar_span.end - node.span.start, fresh)
        )
    for start, end, fresh in sorted(replacements, reverse=True):
        payload = payload[:start] + fresh + payload[end:]
    return payload


def rename_node(text: str, node_id: str, new_name: str | None) -> EditResult:
    """Set, change or (new_name=None) remove the node's Имя."""
    form = parse_form(text)
    node = get_component(form, node_id)
    if node.id == ROOT_KEY:
        raise FormModelError(
            "У корневого узла формы нет свойства Имя – имя компонента задаёт верхнеуровневый ключ Имя"
        )
    if node.body_col is None:
        raise FormModelError(f"У узла {node_id} нет блока свойств")
    pair = node.pairs.get("Имя")
    if not new_name:
        if pair is None:
            raise FormModelError("Свойство Имя не задано – удалять нечего")
        if len(node.pair_list) == 1:
            raise FormModelError("Нельзя удалить единственное свойство узла")
        edits = [TextEdit(pair.span.start, pair.span.end, "")]
    else:
        _check_name(new_name)
        if pair is not None and pair.scalar_span is not None:
            edits = [TextEdit(pair.scalar_span.start, pair.scalar_span.end, new_name)]
        elif pair is not None:  # "Имя:" spelled with an empty value
            line = " " * pair.key_col + "Имя: " + new_name + form.nl
            edits = [TextEdit(pair.span.start, pair.span.end, line)]
        else:
            edits = [_insert_property_edit(form, node, [f"Имя: {new_name}"])]
    return _finish(text, edits, node.span.start)


def _insert_property_edit(form: Form, node: Node, lines0: list[str]) -> TextEdit:
    """A new property block right after Тип (or after the node's first key)."""
    anchor = node.pairs.get("Тип") or (node.pair_list[0] if node.pair_list else None)
    if anchor is None:
        raise FormModelError("У узла нет свойств – некуда добавить новое")
    pos = anchor.span.end
    fragment = "".join(" " * anchor.key_col + l + form.nl for l in lines0)
    if pos == len(form.text) and form.text and not form.text.endswith("\n"):
        fragment = form.nl + fragment
    return TextEdit(pos, pos, fragment)


def _fragment_lines(value_yaml: str) -> list[str]:
    """The composite fragment as dedented lines; must parse as yaml on its own."""
    if not value_yaml or not value_yaml.strip():
        raise FormModelError("Пустой yaml-фрагмент значения")
    try:
        composed = yaml.compose(value_yaml, Loader=yaml.SafeLoader)
    except yaml.YAMLError as exc:
        raise FormModelError(f"Фрагмент значения не является корректным yaml: {exc}") from exc
    if isinstance(composed, yaml.ScalarNode):
        raise FormModelError(
            "Фрагмент значения – скаляр; для скалярных значений используйте параметр value"
        )
    lines = [ln.rstrip() for ln in value_yaml.replace("\r\n", "\n").split("\n")]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    common = min(len(ln) - len(ln.lstrip(" ")) for ln in lines if ln.strip())
    return [ln[common:] if ln.strip() else "" for ln in lines]


def set_property(text: str, node_id: str, key: str, value: str | None = None,
                 value_yaml: str | None = None) -> EditResult:
    """Set or replace a property: a scalar/binding via value, a composite via value_yaml.

    A single-line value_yaml (a flow collection) is written inline after the key; a
    multi-line one becomes a nested block one indentation step deeper.
    """
    form = parse_form(text)
    node = get_component(form, node_id)
    if node.body_col is None:
        raise FormModelError(f"У узла {node_id} нет блока свойств")
    _check_property_key(key)
    if (value is None) == (value_yaml is None):
        raise FormModelError("Укажите ровно один из параметров value и value_yaml")
    nl, step = form.nl, form.step
    pair = node.pairs.get(key)
    if value is not None:
        if pair is not None and pair.scalar_span is not None:
            edits = [TextEdit(pair.scalar_span.start, pair.scalar_span.end, _encode_scalar(value))]
        else:
            lines0 = [f"{key}: {_encode_scalar(value)}"]
            if pair is not None:
                line = " " * pair.key_col + lines0[0] + nl
                edits = [TextEdit(pair.span.start, pair.span.end, line)]
            else:
                edits = [_insert_property_edit(form, node, lines0)]
    else:
        frag = _fragment_lines(value_yaml)
        if len(frag) == 1:
            lines0 = [f"{key}: {frag[0]}"]
        else:
            lines0 = [f"{key}:"] + [" " * step + ln if ln else "" for ln in frag]
        if pair is not None:
            block = "".join((" " * pair.key_col + ln if ln else "") + nl for ln in lines0)
            edits = [TextEdit(pair.span.start, pair.span.end, block)]
        else:
            edits = [_insert_property_edit(form, node, lines0)]
    return _finish(text, edits, node.span.start)


def reset_property(text: str, node_id: str, key: str) -> EditResult:
    """Remove a property key (a composite value goes together with its whole block)."""
    form = parse_form(text)
    node = get_component(form, node_id)
    if node.body_col is None:
        raise FormModelError(f"У узла {node_id} нет блока свойств")
    if key in CHILD_SLOTS:
        raise FormModelError(
            f"Ключ {key} – слот дочерних компонентов; используйте операции insert/move/remove"
        )
    pair = node.pairs.get(key)
    if pair is None:
        raise FormModelError(f"Свойство {key} не задано")
    if len(node.pair_list) == 1:
        raise FormModelError("Нельзя удалить единственное свойство узла")
    return _finish(text, [TextEdit(pair.span.start, pair.span.end, "")], node.span.start)


# --- the Свойства section (the component's own properties) ---------------------------------
#
# The records feed the "Data" panel (docs/DESIGNER.md, hook 2). The operations edit ONLY
# the top-level Свойства section; pseudo node ids "Свойства/<Имя>" in the results are
# NOT tree node ids - they only carry the record span for the cursor jump.


def _check_component_property_type(type_: str) -> str:
    if (
        not _PROPERTY_TYPE_RE.match(type_)
        or ": " in type_
        or type_.endswith(":")
        or type_ != type_.strip()
    ):
        raise FormModelError(f"Недопустимый тип свойства: '{type_}'")
    return type_


def _properties_section(form: Form) -> PropertiesSection | None:
    section = form.properties_section
    if section is not None and not section.supported:
        raise FormModelError(
            "Секция Свойства записана не блочным списком – операция невозможна"
        )
    return section


def _property_entry(form: Form, name: str):
    section = _properties_section(form)
    entry = next(
        (e for e in (section.entries if section else []) if e.name == name), None
    )
    if entry is None:
        raise FormModelError(f"Свойство {name} не найдено в секции Свойства")
    return section, entry


def _finish_property(text: str, edits: list[TextEdit], name: str | None,
                     notes: list[str] | None = None) -> EditResult:
    """Validate the edits by applying and re-parsing; locate the resulting record."""
    new_text = apply_edits(text, edits)
    try:
        form = parse_form(new_text)
    except FormModelError as exc:
        raise FormModelError(f"Правка делает файл неразборным: {exc}") from exc
    ordered = sorted(edits, key=lambda e: (e.start, e.end))
    if name is None:
        return EditResult(ordered, new_text, None, None, notes=notes or [])
    entry = next((e for e in form.component_properties if e.name == name), None)
    if entry is None:
        raise FormModelError("внутренняя ошибка: свойство не найдено после правки")
    return EditResult(
        ordered, new_text, f"{PROPERTIES_KEY}/{name}", entry.span, notes=notes or [],
    )


def property_add(text: str, name: str, type_: str) -> EditResult:
    """Append a {Имя, Тип} record to the Свойства section, creating the section if absent.

    A new section lands right after the Наследует block - the spelling of the corpus
    (Свойства immediately follows Наследует).
    """
    form = parse_form(text)
    _check_name(name)
    _check_component_property_type(type_)
    section = _properties_section(form)
    if section is not None and any(e.name == name for e in section.entries):
        raise FormModelError(f"Свойство {name} уже есть в секции Свойства")
    nl, step = form.nl, form.step

    def record(dash_col: int) -> str:
        body = " " * (dash_col + step)
        return (
            " " * dash_col + "-" + nl
            + body + f"Имя: {name}" + nl
            + body + f"Тип: {type_}" + nl
        )

    if section is None:
        key_col = form.lines.indent(form.root.anchor_line)
        pos = form.root.span.end
        fragment = " " * key_col + PROPERTIES_KEY + ":" + nl + record(key_col + step)
    elif section.dash_col is None:  # "Свойства:" with an empty value
        pos = section.content_span.end
        fragment = record(section.key_col + step)
    else:
        pos = section.content_span.end
        fragment = record(section.dash_col)
    if pos == len(text) and text and not text.endswith("\n"):
        fragment = nl + fragment
    return _finish_property(text, [TextEdit(pos, pos, fragment)], name)


def property_retype(text: str, name: str, new_type: str) -> EditResult:
    """Change the Тип of a Свойства record (a record without Тип gets the key added)."""
    form = parse_form(text)
    _check_component_property_type(new_type)
    _section, entry = _property_entry(form, name)
    if entry.type_span is not None:
        edits = [TextEdit(entry.type_span.start, entry.type_span.end, new_type)]
    else:
        if entry.body_col is None or entry.name_span is None:
            raise FormModelError(f"У свойства {name} нет блока ключей – правка невозможна")
        line = form.lines.index_at(entry.name_span.start)
        pos = form.lines.after(line)
        edits = [TextEdit(pos, pos, " " * entry.body_col + f"Тип: {new_type}" + form.nl)]
    return _finish_property(text, edits, name)


def property_remove(text: str, name: str) -> EditResult:
    """Remove a Свойства record; the last record takes the whole section with it."""
    form = parse_form(text)
    section, entry = _property_entry(form, name)
    removal = entry.span if len(section.entries) > 1 else section.span
    return _finish_property(text, [TextEdit(removal.start, removal.end, "")], None)


def _binding_usage_count(text: str, name: str) -> int:
    """Occurrences of the property name inside binding values (=... to the line end).

    An approximation for the rename warning: a line's value part that starts with "="
    (after "Ключ: " or a "- " list marker) is scanned for the name as a whole word.
    Multi-line scalars are out of scope.
    """
    word = re.compile(rf"(?<![\wА-Яа-яЁё]){re.escape(name)}(?![\wА-Яа-яЁё])")
    count = 0
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("- "):
            stripped = stripped[2:].lstrip()
        _key, sep, value = stripped.partition(": ")
        if not sep:
            value = stripped
        value = value.strip().strip('"')
        if value.startswith("="):
            count += len(word.findall(value))
    return count


def property_rename(text: str, old: str, new: str) -> EditResult:
    """Rename a Свойства record - the record ONLY.

    The bindings that use the property (=Имя, =не Имя, =Метод(Имя) ...) and the paired
    module code are NOT rewritten; the result's notes carry the number of binding
    usages left behind so the client can warn the user.
    """
    form = parse_form(text)
    _check_name(new)
    section, entry = _property_entry(form, old)
    if new != old and any(e.name == new for e in section.entries):
        raise FormModelError(f"Свойство {new} уже есть в секции Свойства")
    if entry.name_span is None:
        raise FormModelError(f"У свойства {old} не задано Имя – переименование невозможно")
    uses = _binding_usage_count(text, old)
    notes = []
    if uses:
        notes.append(
            f"Использования свойства в биндингах не переписаны: вхождений =...{old}... – {uses}"
        )
    edits = [TextEdit(entry.name_span.start, entry.name_span.end, new)]
    return _finish_property(text, edits, new, notes=notes)


# --- the shared dispatcher (parity of the three surfaces) ---------------------------------


_CAMEL_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def apply_operation(text: str, op: str, args: dict | None) -> EditResult:
    """One entry point for LSP/MCP/CLI: an operation name plus its arguments.

    Argument keys: parent, slot, type, name, before, after, node, new_parent,
    container, new_name, key, value, value_yaml, fragment, new_type (camelCase
    spellings are accepted, for the operation name too).
    """
    op_norm = _CAMEL_RE.sub("_", op or "").lower().replace("-", "_")
    raw = args or {}
    a = {_CAMEL_RE.sub("_", str(k)).lower(): v for k, v in raw.items()}

    def need(param: str) -> str:
        v = a.get(param)
        if v is None or v == "":
            raise FormModelError(f"Операция {op_norm}: не задан параметр {param}")
        return str(v)

    def opt(param: str) -> str | None:
        v = a.get(param)
        return str(v) if v not in (None, "") else None

    if op_norm == "insert":
        return insert_component(text, need("parent"), need("slot"), type_=opt("type"),
                                name=opt("name"), before=opt("before"), after=opt("after"))
    if op_norm == "insert_fragment":
        return insert_fragment(text, need("parent"), need("slot"), need("fragment"),
                               before=opt("before"), after=opt("after"))
    if op_norm == "move":
        return move_node(text, need("node"), need("new_parent"), need("slot"),
                         before=opt("before"), after=opt("after"))
    if op_norm == "remove":
        return remove_node(text, need("node"))
    if op_norm == "wrap":
        return wrap_node(text, need("node"), need("container"), name=opt("name"))
    if op_norm == "unwrap":
        return unwrap_node(text, need("node"))
    if op_norm == "duplicate":
        return duplicate_node(text, need("node"))
    if op_norm == "rename":
        return rename_node(text, need("node"), opt("new_name"))
    if op_norm == "set_property":
        value = a.get("value")
        return set_property(text, need("node"), need("key"),
                            value=str(value) if value is not None else None,
                            value_yaml=opt("value_yaml"))
    if op_norm == "reset_property":
        return reset_property(text, need("node"), need("key"))
    if op_norm == "property_add":
        return property_add(text, need("name"), need("type"))
    if op_norm == "property_retype":
        return property_retype(text, need("name"), need("new_type"))
    if op_norm == "property_remove":
        return property_remove(text, need("name"))
    if op_norm == "property_rename":
        return property_rename(text, need("name"), need("new_name"))
    raise FormModelError(f"Неизвестная операция: {op} (доступны: {', '.join(OPERATIONS)})")


# --- the file-level wrappers for the surfaces (MCP, CLI, LSP) -----------------------------


def load_form(yaml_path: Path, *, reader=None) -> Form:
    """Parse a component file (or its dirty buffer when a reader is injected)."""
    if not yaml_path.is_file():
        raise FormModelError(f"Файл не найден: {yaml_path}")
    text = reader(yaml_path) if reader is not None else engine.load(yaml_path).text
    return parse_form(text)


@dataclass
class FormEditOutcome:
    result: ScaffoldResult  # one FileChange with the full new text; caller applies
    node: dict | None  # {"id", "span"} of the resulting node in the new text
    edits: list[TextEdit]


def op_component_edit(yaml_path: Path, op: str, args: dict | None, *,
                      reader=None) -> FormEditOutcome:
    """Run an operation against a file (or its dirty buffer) as a ScaffoldResult."""
    if not yaml_path.is_file():
        raise FormModelError(f"Файл не найден: {yaml_path}")
    text = reader(yaml_path) if reader is not None else engine.load(yaml_path).text
    res = apply_operation(text, op, args)
    cursor = None
    if res.node_span is not None:
        start = res.node_span.start
        line = res.new_text.count("\n", 0, start)
        cursor = (line, start - (res.new_text.rfind("\n", 0, start) + 1))
    result = ScaffoldResult(changes=[
        FileChange(path=yaml_path, content=res.new_text, created=False, cursor=cursor)
    ], notes=list(res.notes))
    return FormEditOutcome(result=result, node=res.node_dict(), edits=res.edits)
