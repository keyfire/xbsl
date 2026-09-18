"""Tier A: a comment of an element description that the visual editor will not keep.

The rules yaml/plain-comment and yaml/doc-comment-misplaced.

The development environment of the platform does not edit a yaml file in place. A change made
in the visual editor (the component designer, the properties panel) is applied to the MODEL of
the element, and the file is then written out again from that model as a whole: the properties
of a node come out in the model's order and every `#` comment of the file is gone, because a
plain comment has no place in the model.

What the model does keep is a DOCUMENTATION comment: lines that start with `##`. The reader
takes them from the head of a yaml mapping - after the `-` of a list item, before the first
key - and only for a node whose class is documentable (the metamodel interface
`IDocumentable`); the environment shows the text as the "Documentation comment" property of
that node and renders it as Markdown. So a `##` line has a slot in exactly these places:

- the first lines of the file - the element itself (any kind, and also the project and the
  subsystem descriptions);
- the first lines of an interface component node, before its `Type` - the platform components
  the ui schema knows and the components a project or a library declares;
- the first lines of a list item whose class is documentable: a property or an event of a
  component, a URL template, a tabular section and its attributes, a dimension or a resource
  of a register, an index, a structure field, an enumeration item, a constant, a parameter of
  a global client event, of a virtual table, of a scheduled job.

And in these it has none, however it is spelled: a single property of a node (a scalar has no
head to hold it), an item of a collection that dispatches by name (the attributes of a
catalog, a document or a register - the built-in ones have no slot at all, and the writer
rebuilds the rest), a command of a command interface, a structural value of the interface (a
dynamic list field, a filter item, layout settings, a font) and an item of `Import`.

yaml/plain-comment reports every `#` comment; yaml/doc-comment-misplaced reports a `##` block
that stands where the reader does not look. Both carry an autofix when the text is already
next to a slot and only has to be spelled or stepped inside: the block at the head of the
file, the block before the first key of a slot node, the block before the `-` of a slot item
and the block before the key that holds a component (a key of the element itself excepted:
what stands above `Inherits` describes the element, not the component under it). Anything
else needs an author - the text
goes into the comment of the nearest enclosing slot and has to name what it is about - so it
is reported without a fix, and the message says where that slot is.

Both rules are off by default: a project written before it knew about the editor has such a
comment on every other node. The data gates them as well - a platform version whose metamodel
has no `IDocumentable` keeps no comments at all, and there is nothing to advise.
"""

from __future__ import annotations

from collections.abc import Iterable
from functools import lru_cache
from typing import NamedTuple

from xbsl import dataset, i18n, metamodel, uischema
from xbsl.diagnostics import Diagnostic, Severity, TextEdit
from xbsl.engine import SourceFile, rule
from xbsl.rules import _comments
from xbsl.rules.semantics import _stdlib_names
from xbsl.rules.yaml_schema import (
    _composed,
    _HAVE_YAML,
    _parsed,
    is_translation_dictionary,
    object_kind,
)

if _HAVE_YAML:
    import yaml

MESSAGES = {
    "yaml/plain-comment.title": {
        "ru": "Комментарий `#` не переживёт визуальный редактор",
        "en": "A `#` comment does not survive the visual editor",
    },
    "yaml/plain-comment.off": {
        "ru": "в проекте, написанном до знакомства с редактором, срабатывает на каждом втором узле",
        "en": "fires on every other node of a project written before it knew about the editor",
    },
    "yaml/plain-comment.here": {
        "ru": "Комментарий `#` пропадёт при первой правке файла в визуальном редакторе: среда "
              "разработки пишет файл заново из модели, а в модели есть место только "
              "документирующему комментарию. Здесь это место есть – замените `#` на `##`.",
        "en": "A `#` comment is lost on the first edit of the file in the visual editor: the "
              "environment writes the file out again from the model, and the model keeps a "
              "documentation comment only. This place holds one - write `##` instead of `#`.",
    },
    "yaml/plain-comment.inside": {
        "ru": "Комментарий `#` пропадёт при первой правке файла в визуальном редакторе. "
              "Документирующий комментарий узла читается с его первых строк: перенесите текст "
              "внутрь узла, перед первым ключом, и замените `#` на `##`.",
        "en": "A `#` comment is lost on the first edit of the file in the visual editor. The "
              "documentation comment of a node is read from its first lines: move the text "
              "inside the node, before its first key, and write `##` instead of `#`.",
    },
    "yaml/plain-comment.nearest": {
        "ru": "Комментарий `#` пропадёт при первой правке файла в визуальном редакторе, а у "
              "этого места своего документирующего комментария нет. Перенесите пояснение в "
              "комментарий `##` {where} и назовите в нём, к чему оно относится.",
        "en": "A `#` comment is lost on the first edit of the file in the visual editor, and "
              "this place has no documentation comment of its own. Move the note into the `##` "
              "comment {where} and name there what it is about.",
    },
    "yaml/doc-comment-misplaced.title": {
        "ru": "Документирующий комментарий `##` стоит не на месте",
        "en": "A `##` documentation comment stands where it is not read",
    },
    "yaml/doc-comment-misplaced.off": {
        "ru": "парное правило к yaml/plain-comment, включается вместе с ним",
        "en": "the companion of yaml/plain-comment, turned on together with it",
    },
    "yaml/doc-comment-misplaced.inside": {
        "ru": "Строки `##` читаются документирующим комментарием только с первых строк узла: "
              "после `-` и перед первым ключом. Здесь среда разработки их не прочтёт и при "
              "записи файла потеряет – перенесите блок внутрь узла.",
        "en": "`##` lines are read as a documentation comment only from the first lines of a "
              "node: after the `-` and before the first key. Here the environment does not "
              "read them and loses them when it writes the file - move the block inside the "
              "node.",
    },
    "yaml/doc-comment-misplaced.nearest": {
        "ru": "У этого места документирующего комментария нет, строки `##` пропадут при записи "
              "файла визуальным редактором. Перенесите пояснение в комментарий `##` {where} и "
              "назовите в нём, к чему оно относится.",
        "en": "This place has no documentation comment, the `##` lines are lost when the visual "
              "editor writes the file. Move the note into the `##` comment {where} and name "
              "there what it is about.",
    },
    "yaml/doc-comment.where-file": {
        "ru": "элемента – в первые строки файла",
        "en": "of the element - the first lines of the file",
    },
    "yaml/doc-comment.where-node": {
        "ru": "узла, который начинается в строке {line}",
        "en": "of the node that starts on line {line}",
    },
}
i18n.register(MESSAGES)

#: The interface of the metamodel a documentable class extends.
_DOCUMENTABLE = "IDocumentable"
_TYPE_KEYS = ("Тип", "Type")
_NAME_KEYS = ("Имя", "Name")


class _Slot(NamedTuple):
    """A mapping that holds a documentation comment, and the line its first key stands on."""

    node: object
    first_line: int  # 1-based line of the first key
    is_root: bool


@lru_cache(maxsize=1)
def _documentable_known() -> bool:
    """Whether the metamodel of the chosen version knows documentation comments at all."""
    return metamodel.available() and metamodel.has_class(_DOCUMENTABLE)


@lru_cache(maxsize=1)
def _components() -> frozenset[str]:
    """The component names of the ui schema, as the schema spells them."""
    schema = dataset.load_ui_schema() or {}
    return frozenset((schema.get("components") or {}).keys())


dataset.register_reset(_documentable_known.cache_clear)
dataset.register_reset(_components.cache_clear)


def _is_component_type(written: str) -> bool:
    """Whether a `Type` value names an interface component.

    A platform component is told by the ui schema. A platform type the schema does not list
    is a value, not a component: a command, a dynamic list field, a font. A name the platform
    does not know at all is a component a project or a library declares - a file rule cannot
    look it up, and nothing else is written as the `Type` of a node with properties of its
    own. A facet (`Catalog.Reference`) and a nullable type only occur as the type of a
    declared property, never as a node.
    """
    head = written.split("<", 1)[0].strip()
    if not head or head.endswith("?") or head[0] in "=%":
        return False
    if "::" in head:
        head = head.rsplit("::", 1)[1]
    if "." in head:
        return False
    canonical = uischema.canonical_component(head)
    if canonical in _components():
        return True
    return head not in _stdlib_names() and canonical not in _stdlib_names()


def _scalar(mapping, keys: tuple[str, ...]) -> str | None:
    for key_node, value_node in mapping.value:
        if (isinstance(key_node, yaml.ScalarNode) and key_node.value in keys
                and isinstance(value_node, yaml.ScalarNode)):
            return value_node.value
    return None


def _section_record(props: dict[str, dict], key: str) -> tuple[str, dict] | None:
    """(the collection as the metamodel names it, its record) for a key of the file."""
    record = props.get(key)
    if record is not None:
        return (key, record) if record.get("kind") == "list" else None
    for name, candidate in props.items():
        if candidate.get("kind") == "list" and candidate.get("en") == key:
            return name, candidate
    return None


def _first_line(mapping) -> int:
    return mapping.value[0][0].start_mark.line + 1 if mapping.value else mapping.start_mark.line + 1


def _collect(root, kind: str | None) -> tuple[dict[int, _Slot], dict[int, object]]:
    """(slots by the id of their mapping, every mapping by the line of its first key)."""
    slots: dict[int, _Slot] = {id(root): _Slot(root, _first_line(root), True)}
    judged: set[int] = {id(root)}  # mappings the metamodel has an opinion about
    cls = metamodel.class_for_kind(kind) if kind else None

    def by_metamodel(owner: str, mapping) -> None:
        props = metamodel.properties_of_class(owner)
        for key_node, value_node in mapping.value:
            if not isinstance(key_node, yaml.ScalarNode) or not isinstance(value_node, yaml.SequenceNode):
                continue
            found = _section_record(props, key_node.value)
            if found is None:
                continue
            section, record = found
            for item in value_node.value:
                if not isinstance(item, yaml.MappingNode):
                    continue
                child = metamodel.collection_item_class(owner, section, _scalar(item, _NAME_KEYS))
                if not child:
                    continue
                judged.add(id(item))
                # A collection that dispatches by the item name rebuilds its items on write.
                if not record.get("dispatch") and metamodel.inherits(child, _DOCUMENTABLE):
                    slots[id(item)] = _Slot(item, _first_line(item), False)
                by_metamodel(child, item)

    if cls:
        by_metamodel(cls, root)

    firsts: dict[int, object] = {}
    stack = [root]
    while stack:
        node = stack.pop()
        if isinstance(node, yaml.MappingNode):
            if node.value:
                firsts.setdefault(_first_line(node), node)
            if id(node) not in judged:
                written = _scalar(node, _TYPE_KEYS)
                if written is not None and _is_component_type(written):
                    slots[id(node)] = _Slot(node, _first_line(node), False)
            for key_node, value_node in node.value:
                stack.append(value_node)
        elif isinstance(node, yaml.SequenceNode):
            stack.extend(node.value)
    return slots, firsts


class _Block(NamedTuple):
    lines: list  # CommentLine, consecutive, one marker kind
    doc: bool


def _blocks(source: SourceFile) -> list[_Block]:
    """Own-line comment lines grouped into blocks of one marker kind."""
    text_lines = source.text.split("\n")
    out: list[_Block] = []
    for line in _comments.lines(source):
        if text_lines[line.line - 1][: line.column - 1].strip():
            # A trailing comment after a value: a block of its own, never a slot.
            out.append(_Block([line], line.text.startswith("##")))
            continue
        doc = line.text.startswith("##")
        last = out[-1] if out else None
        if (last and last.doc == doc and last.lines[-1].line == line.line - 1
                and not text_lines[last.lines[-1].line - 1][: last.lines[-1].column - 1].strip()):
            last.lines.append(line)
        else:
            out.append(_Block([line], doc))
    return out


def _enclosing_slot(slots: dict[int, _Slot], line: int) -> _Slot:
    """The innermost slot mapping whose span holds the line; the root when none does."""
    best = None
    for slot in slots.values():
        node = slot.node
        start, end = node.start_mark.line + 1, node.end_mark.line + 1
        if slot.is_root or start <= line <= end:
            if best is None or (not slot.is_root and (best.is_root or start >= best.node.start_mark.line + 1)):
                best = slot
    return best


def _where(slot: _Slot) -> str:
    if slot.is_root:
        return i18n.t("yaml/doc-comment.where-file")
    return i18n.t("yaml/doc-comment.where-node", line=slot.first_line)


def _as_doc(text: str) -> str:
    """The comment line spelled as a documentation one: `#  x` -> `##  x`, `## x` kept."""
    return text if text.startswith("##") else "#" + text


def _moved(source: SourceFile, block: _Block, anchor_line: int, slot: _Slot) -> TextEdit | None:
    """The edit that steps a block over its anchor line into the node that starts after it.

    The anchor is the `-` of a list item standing on its own line, or the key whose value is
    the node. The block is cut from above the anchor and written right below it, indented as
    the first key of the node. Nothing is offered when the anchor carries a value of its own
    (`- Name: x`): there the first key stands on the anchor line.
    """
    text_lines = source.text.split("\n")
    if slot.first_line <= anchor_line:
        return None
    first_key = text_lines[slot.first_line - 1]
    indent = first_key[: len(first_key) - len(first_key.lstrip())]
    between = text_lines[anchor_line:slot.first_line - 1]
    if any(part.strip() and not part.strip().startswith("#") for part in between):
        return None
    start_line = block.lines[0].line
    start = block.lines[0].offset - (block.lines[0].column - 1)
    anchor_text = text_lines[anchor_line - 1]
    end = sum(len(part) + 1 for part in text_lines[: anchor_line - 1]) + len(anchor_text)
    if any(part.strip() for part in text_lines[block.lines[-1].line:anchor_line - 1]):
        return None  # something other than blank lines between the block and its anchor
    eol = "\r\n" if anchor_text.endswith("\r") else "\n"
    moved = eol.join(indent + _as_doc(line.text.rstrip("\r")) for line in block.lines)
    new = anchor_text.rstrip("\r") + eol + moved + ("\r" if eol == "\r\n" else "")
    if start_line >= anchor_line:
        return None
    return TextEdit(start, end, new)


def _respelled(source: SourceFile, block: _Block) -> TextEdit:
    """The edit that turns every `#` of a block standing in its slot into `##`."""
    start = block.lines[0].offset
    last = block.lines[-1]
    end = last.offset + len(last.text.rstrip("\r"))
    text = source.text[start:end]
    parts = text.split("\n")
    out = []
    for index, part in enumerate(parts):
        if index == 0:
            out.append(_as_doc(part))
            continue
        lead = len(part) - len(part.lstrip())
        out.append(part[:lead] + _as_doc(part[lead:]))
    return TextEdit(start, end, "\n".join(out))


def _judge(source: SourceFile, want_doc: bool) -> Iterable[Diagnostic]:
    if source.kind != "yaml" or not _HAVE_YAML or "#" not in source.text:
        return
    if not _documentable_known() or is_translation_dictionary(source):
        return
    data, err = _parsed(source)
    if err is not None or not isinstance(data, dict):
        return
    root = _composed(source)
    if root is None or not isinstance(root, yaml.MappingNode) or not root.value:
        return
    blocks = [block for block in _blocks(source) if block.doc == want_doc]
    if not blocks:
        return
    rule_id = "yaml/doc-comment-misplaced" if want_doc else "yaml/plain-comment"
    slots, firsts = _collect(root, object_kind(data))
    text_lines = source.text.split("\n")
    key_lines: dict[int, object] = {}
    stack = [root]
    while stack:
        node = stack.pop()
        if isinstance(node, yaml.MappingNode):
            for key_node, value_node in node.value:
                # A key of the element itself is left out: a block above `Inherits` describes
                # the element, and its place is the head of the file, not the component below.
                if node is not root:
                    key_lines.setdefault(key_node.start_mark.line + 1, value_node)
                stack.append(value_node)
        elif isinstance(node, yaml.SequenceNode):
            stack.extend(node.value)

    for block in blocks:
        head = block.lines[0]
        own_line = not text_lines[head.line - 1][: head.column - 1].strip()
        fix = None
        key = "nearest"
        where_slot = None
        if own_line:
            index = block.lines[-1].line  # 0-based index of the line after the block
            while index < len(text_lines) and (
                    not text_lines[index].strip() or text_lines[index].strip().startswith("#")):
                index += 1
            anchor_line = index + 1
            anchor = text_lines[index].strip() if index < len(text_lines) else ""
            node = firsts.get(anchor_line)
            dash = anchor == "-" or anchor.startswith("- ")
            if node is not None and id(node) in slots and not dash:
                if want_doc:
                    continue  # a `##` block at the head of a slot node is where it belongs
                key, fix = "here", _respelled(source, block)
            elif anchor == "-":
                follow = index + 1
                while follow < len(text_lines) and (
                        not text_lines[follow].strip() or text_lines[follow].strip().startswith("#")):
                    follow += 1
                item = firsts.get(follow + 1)
                if item is not None and id(item) in slots:
                    key, fix = "inside", _moved(source, block, anchor_line, slots[id(item)])
            elif dash:
                item = firsts.get(anchor_line)
                if item is not None and id(item) in slots:
                    key = "inside"
            else:
                value = key_lines.get(anchor_line)
                if isinstance(value, yaml.MappingNode) and id(value) in slots:
                    key, fix = "inside", _moved(source, block, anchor_line, slots[id(value)])
        if key == "nearest":
            where_slot = _enclosing_slot(slots, head.line)
        message_key = f"{rule_id}.{key}"
        if want_doc and key == "here":  # pragma: no cover - filtered above
            continue
        yield Diagnostic(
            source.rel, head.line, head.column, rule_id, Severity.WARNING,
            i18n.t(message_key, where=_where(where_slot)) if where_slot else i18n.t(message_key),
            fix=fix,
        )


@rule(
    "yaml/plain-comment", "yaml/plain-comment.title", "A",
    severity=Severity.WARNING, enabled_by_default=False, off_reason="yaml/plain-comment.off",
)
def plain_comment(source: SourceFile) -> Iterable[Diagnostic]:
    """A `#` comment of an element description - see the module docstring."""
    yield from _judge(source, want_doc=False)


@rule(
    "yaml/doc-comment-misplaced", "yaml/doc-comment-misplaced.title", "A",
    severity=Severity.WARNING, enabled_by_default=False,
    off_reason="yaml/doc-comment-misplaced.off",
)
def doc_comment_misplaced(source: SourceFile) -> Iterable[Diagnostic]:
    """A `##` block outside the head of a documentable node - see the module docstring."""
    yield from _judge(source, want_doc=True)
