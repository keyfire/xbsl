"""Read and edit documentation comments at metamodel-approved YAML node heads.

The editor applies returned character-offset edits to its live buffer. This module never
serializes YAML, so unrelated formatting, comments, and line endings stay intact.
"""

from __future__ import annotations

from dataclasses import dataclass

import yaml

from xbsl import i18n, metamodel
from xbsl.rules import yaml_doc_comments
from xbsl.rules.yaml_schema import object_kind

MESSAGES = {
    "doc-comment.invalid-offset": {
        "ru": "Некорректное смещение узла.", "en": "Invalid node offset.",
    },
    "doc-comment.invalid-yaml": {
        "ru": "Некорректный YAML.", "en": "Invalid YAML.",
    },
    "doc-comment.element-mapping": {
        "ru": "Ожидался узел элемента.", "en": "Expected an element mapping.",
    },
    "doc-comment.alias": {
        "ru": "YAML с псевдонимами недоступен для редактора документирующих комментариев.",
        "en": "YAML aliases are unavailable in the documentation comment editor.",
    },
    "doc-comment.unavailable": {
        "ru": "Документирующие комментарии недоступны для текущих данных технологии.",
        "en": "Documentation comments are unavailable for the current platform data.",
    },
    "doc-comment.element-kind": {
        "ru": "Вид элемента недоступен.", "en": "Element kind is unavailable.",
    },
    "doc-comment.node": {
        "ru": "Узел не найден.", "en": "Node is unavailable.",
    },
    "doc-comment.no-slot": {
        "ru": "У этого узла нет документирующего комментария.",
        "en": "This node has no documentation comment.",
    },
    "doc-comment.stale": {
        "ru": "Комментарий изменился в YAML. Проверьте текст и повторите сохранение.",
        "en": "The comment changed in YAML. Review it and try saving again.",
    },
    "doc-comment.invalid-character": {
        "ru": "Комментарий содержит недопустимый символ.",
        "en": "The comment contains an invalid character.",
    },
}
i18n.register(MESSAGES)


@dataclass(frozen=True)
class DocComment:
    supported: bool
    text: str = ""
    start: int = 0
    end: int = 0
    anchor: int = 0
    reason: str = ""

    def as_dict(self) -> dict:
        return {
            "supported": self.supported, "text": self.text,
            "start": self.start, "end": self.end, "anchor": self.anchor,
            "reason": self.reason, "offsetEncoding": "unicode-codepoint",
        }


def _line_start(text: str, offset: int) -> int:
    return text.rfind("\n", 0, offset) + 1


def _line_end(text: str, offset: int) -> int:
    end = text.find("\n", offset)
    return len(text) if end < 0 else end + 1


def _first_key(node) -> int:
    return node.value[0][0].start_mark.index


def _has_alias(root) -> bool:
    """Reject repeated YAML nodes, including cycles, before any unbounded tree walk."""
    seen: set[int] = set()
    stack = [root]
    while stack:
        node = stack.pop()
        identity = id(node)
        if identity in seen:
            return True
        seen.add(identity)
        if isinstance(node, yaml.MappingNode):
            for key, value in node.value:
                stack.extend((key, value))
        elif isinstance(node, yaml.SequenceNode):
            stack.extend(node.value)
    return False


def _node_at(root, text: str, offset: int):
    """Resolve an exact first-key line or the key/dash that owns a mapping value."""
    candidates = []
    stack = [(root, None)]
    while stack:
        node, parent_anchor = stack.pop()
        if isinstance(node, yaml.MappingNode):
            if node.value:
                first = _first_key(node)
                first_line = _line_start(text, first)
                anchors = {first, first_line}
                if node is root:
                    anchors.add(0)
                    if text.startswith("\ufeff"):
                        anchors.add(1)
                if parent_anchor is not None:
                    anchors.add(parent_anchor)
                    anchors.add(_line_start(text, parent_anchor))
                if offset in anchors:
                    candidates.append((0 if offset == first else 1, -first, node))
            for key, value in node.value:
                stack.append((value, key.start_mark.index))
        elif isinstance(node, yaml.SequenceNode):
            for item in node.value:
                anchor = item.start_mark.index
                if isinstance(item, yaml.MappingNode) and item.value:
                    first = _first_key(item)
                    line_start = _line_start(text, first)
                    prefix = text[line_start:first]
                    if prefix.strip() == "-":
                        anchor = line_start
                    else:
                        previous = line_start
                        while previous > 0:
                            previous = _line_start(text, previous - 1)
                            stripped = text[previous:_line_end(text, previous)].strip()
                            if stripped.startswith("#") or not stripped:
                                continue
                            if stripped == "-":
                                anchor = previous
                            break
                stack.append((item, anchor))
    if not candidates:
        return None
    return min(candidates, key=lambda item: (item[0], item[1]))[2]


def inspect(text: str, offset: int) -> DocComment:
    """Describe the documentation comment of one selected YAML mapping."""
    if offset < 0 or offset > len(text):
        return DocComment(False, reason=i18n.t("doc-comment.invalid-offset"))
    try:
        root = yaml.compose(text)
    except yaml.YAMLError:
        return DocComment(False, reason=i18n.t("doc-comment.invalid-yaml"))
    if not isinstance(root, yaml.MappingNode):
        return DocComment(False, reason=i18n.t("doc-comment.element-mapping"))
    if _has_alias(root):
        return DocComment(False, reason=i18n.t("doc-comment.alias"))
    if not yaml_doc_comments._documentable_known():
        return DocComment(False, reason=i18n.t("doc-comment.unavailable"))
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        return DocComment(False, reason=i18n.t("doc-comment.invalid-yaml"))
    if not isinstance(data, dict):
        return DocComment(False, reason=i18n.t("doc-comment.element-mapping"))
    kind = object_kind(data)
    if not kind or not metamodel.class_for_kind(kind):
        return DocComment(False, reason=i18n.t("doc-comment.element-kind"))
    node = _node_at(root, text, offset)
    if node is None:
        return DocComment(False, reason=i18n.t("doc-comment.node"))
    slots, _, _ = yaml_doc_comments._collect(root, kind)
    if id(node) not in slots:
        return DocComment(False, reason=i18n.t("doc-comment.no-slot"))
    key_start = _first_key(node)
    first_line = _line_start(text, key_start)
    prefix = text[first_line:key_start]
    # The key can share a line with the sequence dash. Its comment is inserted after the
    # dash; the first property then moves to a new line at its existing key indentation.
    inline_dash = prefix.strip() == "-" and node is not root
    indent = " " * (key_start - first_line) if inline_dash else prefix
    if node is root and first_line == 0 and text.startswith("\ufeff"):
        indent = ""
    block_start = first_line
    values: list[str] = []
    if not inline_dash:
        cursor = first_line
        while cursor > 0:
            previous = _line_start(text, cursor - 1)
            raw = text[previous:cursor].rstrip("\r\n").removeprefix("\ufeff")
            if not raw.startswith(indent + "##"):
                break
            values.insert(0, raw[len(indent) + 2:].removeprefix(" "))
            block_start = previous
            cursor = previous
    # Root comments at the very start follow an optional UTF-8 BOM.
    if node is root and block_start == 0 and text.startswith("\ufeff"):
        block_start = 1
    return DocComment(
        True, "\n".join(values), block_start, max(first_line, block_start), key_start,
    )


def plan(text: str, offset: int, value: str, expected: str | None = None) -> dict:
    """Return a single precise edit, refusing stale panel values."""
    current = inspect(text, offset)
    if not current.supported:
        return {"error": current.reason}
    if expected is not None and current.text != expected:
        return {"error": i18n.t("doc-comment.stale")}
    if "\x00" in value:
        return {"error": i18n.t("doc-comment.invalid-character")}
    normalized = value.replace("\r\n", "\n").replace("\r", "\n")
    if normalized == current.text:
        return {
            "edits": [], "comment": current.as_dict(),
            "offsetEncoding": "unicode-codepoint",
        }
    anchor_line = text[_line_start(text, current.anchor):_line_end(text, current.anchor)]
    eol = "\r\n" if anchor_line.endswith("\r\n") else "\n"
    first_line = _line_start(text, current.anchor)
    prefix = text[first_line:current.anchor]
    inline_dash = prefix.strip() == "-" and current.start == first_line
    indent = " " * len(prefix) if inline_dash else prefix.removeprefix("\ufeff")
    lines = normalized.split("\n") if normalized else []
    block = "".join(indent + "##" + (" " + line if line else "") + eol for line in lines)
    if inline_dash and block:
        replacement = prefix.rstrip() + eol + block + indent
        start, end = first_line, current.anchor
    else:
        replacement = block
        start, end = current.start, current.end
    return {
        "edits": [{"start": start, "end": end, "newText": replacement}],
        "nextOffset": current.anchor + len(replacement) - (end - start),
        "offsetEncoding": "unicode-codepoint",
    }
