"""Folding the comments of an element description into the documentation comment of their node.

The development environment keeps a comment of an element description in one place only: a
`##` block at the head of a node that has room for a description. A plain `#` comment is dropped
by the visual editor the first time it writes the file, and a `##` block anywhere else is never
shown. The rules `yaml/plain-comment` and `yaml/doc-comment-misplaced` find such blocks and fix
the mechanical cases themselves - a marker changed in place, a block moved under the dash of its
item. What is left is a comment about a node that has no room of its own: a property of a
component, an item of a list without a description, a key of the element. This module moves it
into the description of the nearest node that has room, as an item of a list that names the
subject:

    ## * `HorizontalStretch`:
    ##   The width is set in pixels: without the stretch the column does not share the room.

The name of the subject stands on a line of its own, so the lines of the comment keep their text
and a translation dictionary keeps its pairs for them; only the new lines with the names need
pairs of their own.

A block is moved only when the move is unambiguous. A block that may be read two ways - the
first block of the file above a key that is not a part of the head (it may describe the element
or only that key), a heading of a group of strings in a localization file, an item of a list
without a name - is proposed and applied only on request. A note at the end of the file has no
owner and is left where it is.

A file is written only when the result passes the audit: the yaml parses to the same data, every
line of every comment is still there, the rules find nothing but the blocks left on purpose, and
a second pass has nothing to move. The byte order mark and the line ends of the file are kept.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from functools import lru_cache

from xbsl import dataset, i18n, terms
from xbsl.diagnostics import TextEdit

MESSAGES = {
    "fold.kind.property": {"ru": "свойство узла", "en": "a property of a node"},
    "fold.kind.item": {"ru": "элемент списка", "en": "an item of a list"},
    "fold.kind.mapping": {"ru": "узел без описания", "en": "a node without a description"},
    "fold.kind.element-key": {"ru": "ключ элемента", "en": "a key of the element"},
    "fold.kind.description": {"ru": "описание элемента", "en": "a description of the element"},
    "fold.kind.trailing": {"ru": "комментарий после значения", "en": "a comment after a value"},
    "fold.kind.end": {"ru": "конец файла", "en": "the end of the file"},
    "fold.kind.fix": {"ru": "исправление правила", "en": "a fix of the rule"},
    "fold.action.applied": {"ru": "перенесено", "en": "moved"},
    "fold.action.proposed": {"ru": "предложено", "en": "proposed"},
    "fold.action.left": {"ru": "оставлено", "en": "left"},
    "fold.summary.dry": {
        "ru": "файлов: {files}; перенести: {applied}, предложено: {proposed}, оставлено: {left}. "
              "Ничего не записано: записать - ключ --write",
        "en": "files: {files}; to move: {applied}, proposed: {proposed}, left: {left}. Nothing "
              "written: --write writes",
    },
    "fold.summary.written": {
        "ru": "файлов: {files}, записано: {written}; перенесено: {applied}, предложено: "
              "{proposed}, оставлено: {left}",
        "en": "files: {files}, written: {written}; moved: {applied}, proposed: {proposed}, "
              "left: {left}",
    },
    "fold.reason.first-block": {
        "ru": "первый блок файла стоит над ключом, который не входит в шапку: это может быть и "
              "описание элемента, и заметка к ключу",
        "en": "the first block of the file stands above a key outside the head: it may describe "
              "the element or only that key",
    },
    "fold.reason.localization": {
        "ru": "в файле локализации блок обычно подписывает группу строк, а не одну строку",
        "en": "in a localization file a block usually heads a group of strings, not one string",
    },
    "fold.reason.separator": {
        "ru": "блок похож на заголовок раздела, а не на пояснение к одному узлу",
        "en": "the block looks like the heading of a section, not a note about one node",
    },
    "fold.reason.unlabeled": {
        "ru": "у элемента списка нет имени: пункт назван номером, а номер меняется при перестановке",
        "en": "the item of the list has no name: it is named by its number, which changes when "
              "the items move",
    },
    "fold.reason.collection": {
        "ru": "блок стоит над списком, а не над одним его элементом",
        "en": "the block stands above a list, not above one of its items",
    },
    "fold.reason.end": {
        "ru": "после блока нет ни одного узла: у заметки нет хозяина, возможно, она устарела",
        "en": "no node follows the block: the note has no owner and may be stale",
    },
    "fold.note.place-words": {
        "ru": "строка {line}: текст ссылается на место (\"ниже\", \"здесь\"), а после переноса "
              "места рядом не будет",
        "en": "line {line}: the text points at a place (\"below\", \"here\"), and after the move "
              "that place is gone",
    },
    "fold.audit.data": {
        "ru": "после свертки yaml разбирается в другие данные",
        "en": "after the fold the yaml parses to other data",
    },
    "fold.audit.lines": {
        "ru": "после свертки пропали строки комментариев: {lines}",
        "en": "after the fold lines of the comments are missing: {lines}",
    },
    "fold.audit.rules": {
        "ru": "после свертки правила комментариев нашли новое: {found}",
        "en": "after the fold the comment rules found something new: {found}",
    },
    "fold.audit.again": {
        "ru": "второй проход свертки нашел, что еще перенести",
        "en": "a second pass of the fold found more to move",
    },
    "fold.audit.parse": {
        "ru": "после свертки yaml не разбирается",
        "en": "after the fold the yaml does not parse",
    },
}
i18n.register(MESSAGES)

#: A line of a comment that looks like the heading of a section: `--- Раздел ---`, `===`.
_SEPARATOR = re.compile(r"^(?:[-=─_]{3,}|.*\s[-=─]{3,})\s*$")
#: Words that point at a place in the file: after the move the place is somewhere else.
_PLACE_WORDS = re.compile(r"(?i)\b(?:ниже|выше|здесь|следующ\w*|below|above|here)\b")
#: The marker and the one space after it: what a line of a comment starts with.
_MARKER = re.compile(r"^#+ ?")


@lru_cache(maxsize=1)
def _spellings() -> dict[str, frozenset[str]]:
    """The keys the fold reads, in both spellings of the project."""

    def forms(*names: str) -> frozenset[str]:
        return frozenset(form for name in names for form in terms.key_forms(name))

    return {
        "head": forms("ВидЭлемента", "Ид", "Имя", "ОбластьВидимости", "Представление", "Окружение"),
        "inherits": forms("Наследует"),
        "labels": ("Имя", "Name", "Обработчик", "Handler", "Представление", "Presentation"),
        "type": forms("Тип"),
        "localization": forms("Строки", "Шаблоны"),
    }


dataset.register_reset(_spellings.cache_clear)


@dataclass
class Move:
    """One block of a file and what the fold does with it."""

    line: int
    kind: str
    #: "applied" - moved; "proposed" - a move is offered, applied only on request; "left" - the
    #: block has no place to go and stays where it is.
    action: str
    target_line: int | None = None
    subject: str | None = None
    reason: str = ""
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "line": self.line,
            "kind": self.kind,
            "action": self.action,
            "target_line": self.target_line,
            "subject": self.subject,
            "reason": i18n.t(self.reason) if self.reason else "",
            "notes": list(self.notes),
        }


@dataclass
class FileFold:
    """The fold of one file: the moves, the new text and what the audit found."""

    rel: str
    moves: list[Move] = field(default_factory=list)
    text: str | None = None
    audit: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return self.text is not None and not self.audit

    def as_dict(self) -> dict:
        return {
            "file": self.rel,
            "changed": self.changed,
            "moves": [move.as_dict() for move in self.moves],
            "audit": list(self.audit),
        }


def fold_text(text: str, rel: str = "file.yaml", *, take_proposed: bool = False) -> FileFold:
    """Fold the comments of one element description; nothing is written here.

    `take_proposed` applies the proposed moves as well. The result carries the new text only
    when something moved and the audit passed.
    """
    from xbsl import engine
    from xbsl.rules import yaml_doc_comments as rules

    result = FileFold(rel)
    if "#" not in text or not rules._documentable_known():
        return result
    bom = text.startswith("﻿")
    body = text[1:] if bom else text
    source = engine.load_text(rel, body)
    if source.kind != "yaml":
        return result
    fixed, fix_moves = _apply_rule_fixes(rel, body)
    folded, moves = _fold_blocks(rel, fixed, take_proposed)
    result.moves = fix_moves + moves
    if folded == body:
        return result
    result.audit = _audit(rel, body, folded, result.moves, take_proposed)
    result.text = ("﻿" if bom else "") + folded
    return result


def _apply_rule_fixes(rel: str, text: str) -> tuple[str, list[Move]]:
    """The fixes the two rules offer themselves, applied until none is left."""
    from xbsl import engine
    from xbsl.rules import yaml_doc_comments as rules

    moves: list[Move] = []
    for _pass in range(20):
        source = engine.load_text(rel, text)
        fixes = [
            (diagnostic.line, diagnostic.fix)
            for want_doc in (False, True)
            for diagnostic in rules._judge(source, want_doc)
            if diagnostic.fix is not None
        ]
        if not fixes:
            break
        # One pass takes the fixes that do not overlap, the last first so the offsets hold.
        chosen: list[tuple[int, TextEdit]] = []
        for line, fix in sorted(fixes, key=lambda item: item[1].start):
            if chosen and fix.start < chosen[-1][1].end:
                continue
            chosen.append((line, fix))
        for line, fix in reversed(chosen):
            text = text[:fix.start] + fix.new + text[fix.end:]
            moves.append(Move(line, "fix", "applied"))
    return text, moves


def _misplaced_lines(rel: str, text: str) -> set[int]:
    """The first lines of the blocks the rules still report."""
    from xbsl import engine
    from xbsl.rules import yaml_doc_comments as rules

    source = engine.load_text(rel, text)
    return {
        diagnostic.line
        for want_doc in (False, True)
        for diagnostic in rules._judge(source, want_doc)
    }


def _fold_blocks(rel: str, text: str, take_proposed: bool) -> tuple[str, list[Move]]:
    """Fold every block the rules still report into the description of its node."""
    import yaml

    from xbsl import engine
    from xbsl.rules import yaml_doc_comments as rules
    from xbsl.rules.yaml_schema import _composed, _parsed, object_kind

    reported = _misplaced_lines(rel, text)
    if not reported:
        return text, []
    source = engine.load_text(rel, text)
    data, err = _parsed(source)
    root = _composed(source)
    if err is not None or not isinstance(data, dict) or not isinstance(root, yaml.MappingNode):
        return text, []
    slots, firsts, _refused = rules._collect(root, object_kind(data))
    spell = _spellings()
    eol = "\r\n" if "\r\n" in text else "\n"
    lines = [line[:-1] if line.endswith("\r") else line for line in text.split("\n")]
    localization = any(key.value in spell["localization"] for key, _value in root.value)

    steps_of: dict[int, list] = {id(root): []}
    key_at: dict[int, tuple] = {}
    items_at: dict[int, object] = {}
    stack = [root]
    while stack:
        node = stack.pop()
        here = steps_of[id(node)]
        if isinstance(node, yaml.MappingNode):
            for index, (key, value) in enumerate(node.value):
                key_at[key.start_mark.line + 1] = (index, node, value)
                steps_of[id(value)] = here + [("k", index)]
                stack.append(value)
        elif isinstance(node, yaml.SequenceNode):
            for index, item in enumerate(node.value):
                steps_of[id(item)] = here + [("i", index)]
                items_at.setdefault(item.start_mark.line + 1, item)
                stack.append(item)
    node_by_steps = {tuple(steps): node_id for node_id, steps in steps_of.items()}

    def target_of(steps: list, leaf) -> tuple:
        depth = len(steps) if leaf is not None else len(steps) - 1
        while depth >= 0:
            node_id = node_by_steps.get(tuple(steps[:depth]))
            if node_id in slots:
                return slots[node_id], depth
            depth -= 1
        return slots[id(root)], 0

    moves: list[Move] = []
    removals: set[int] = set()
    trailing: dict[int, int] = {}
    entries: dict[int, list] = {}
    first_top_block = True

    for block in rules._blocks(source):
        head = block.lines[0]
        if head.line not in reported:
            continue
        texts = [_MARKER.sub("", line.text.rstrip("\r")).rstrip() for line in block.lines]
        own = not lines[head.line - 1][: head.column - 1].strip()
        move = Move(head.line, "property", "applied")
        steps: list = []
        leaf = None
        description = False
        if not own:
            found = key_at.get(head.line)
            if found is None:
                move.kind, move.action, move.reason = "trailing", "left", "fold.reason.end"
                moves.append(move)
                continue
            index, parent, _value = found
            steps, leaf, move.kind = steps_of[id(parent)], index, "trailing"
        else:
            index_line = block.lines[-1].line
            while index_line < len(lines) and (
                    not lines[index_line].strip() or lines[index_line].strip().startswith("#")):
                index_line += 1
            anchor_line = index_line + 1
            anchor = lines[index_line].strip() if index_line < len(lines) else ""
            if not anchor:
                move.kind, move.action, move.reason = "end", "left", "fold.reason.end"
                moves.append(move)
                continue
            dash = anchor == "-" or anchor.startswith("- ")
            item = None
            if anchor == "-":
                follow = index_line + 1
                while follow < len(lines) and (
                        not lines[follow].strip() or lines[follow].strip().startswith("#")):
                    follow += 1
                item = firsts.get(follow + 1) or items_at.get(follow + 1)
            elif dash:
                item = items_at.get(anchor_line)
            node = firsts.get(anchor_line)
            if item is not None:
                steps, move.kind = steps_of[id(item)], "item"
            elif anchor_line in key_at:
                index, parent, value = key_at[anchor_line]
                if node is not None and node is parent and id(parent) not in slots and index == 0 \
                        and parent is not root:
                    steps, move.kind = steps_of[id(parent)], "mapping"
                else:
                    steps, leaf = steps_of[id(parent)], index
                    if parent is root:
                        key_name = parent.value[index][0].value
                        before = [key.value for key, _value in root.value[:index]]
                        if key_name in spell["inherits"] or (
                                first_top_block and all(key in spell["head"] for key in before)):
                            description = True
                            move.kind = "description"
                        else:
                            move.kind = "element-key"
                            if first_top_block:
                                move.reason = "fold.reason.first-block"
                                description = True
                        first_top_block = False
                    # Above a list the block may be about the whole list or about its first
                    # item; a description of the element is neither.
                    if isinstance(value, yaml.SequenceNode) and not description:
                        move.reason = move.reason or "fold.reason.collection"
            else:
                move.kind, move.action, move.reason = "end", "left", "fold.reason.end"
                moves.append(move)
                continue
        slot, depth = target_of(steps, leaf) if (steps or leaf is not None) else (slots[id(root)], 0)
        subject = None if description else _names_along(root, steps, depth, leaf, spell)
        if subject is not None and subject.startswith("#"):
            subject = subject[1:]
            move.reason = move.reason or "fold.reason.unlabeled"
        if localization and not move.reason:
            move.reason = "fold.reason.localization"
        if not move.reason and any(_SEPARATOR.match(text_line) for text_line in texts if text_line):
            move.reason = "fold.reason.separator"
        move.target_line = slot.first_line
        move.subject = subject
        for offset, text_line in enumerate(texts):
            if _PLACE_WORDS.search(text_line):
                move.notes.append(i18n.t("fold.note.place-words", line=head.line + offset))
        if move.reason and move.reason != "fold.reason.end" and not take_proposed:
            move.action = "proposed"
            moves.append(move)
            continue
        if own:
            removals.update(line.line for line in block.lines)
        else:
            trailing[head.line] = head.column
        entries.setdefault(id(slot.node), []).append((head.line, subject, texts))
        moves.append(move)

    if not entries:
        return text, moves
    for number, column in trailing.items():
        lines[number - 1] = lines[number - 1][: column - 1].rstrip()
    replaced: dict[int, tuple[int, list[str]]] = {}
    for node_id, items in entries.items():
        slot = slots[node_id]
        start, block = _merged(lines, slot.first_line, removals, items)
        replaced[slot.first_line] = (start, block)
    out: list[str] = []
    skip_until = 0
    starts = {start: (first, block) for first, (start, block) in replaced.items()}
    for number, line in enumerate(lines, 1):
        if number in starts:
            first, block = starts[number]
            out.extend(block)
            skip_until = first - 1
        if number <= skip_until:
            continue
        if number in removals:
            continue
        out.append(line)
    return eol.join(out), moves


def _names_along(root, steps: list, start: int, leaf, spell: dict) -> str | None:
    """The path of the subject from the target down: keys as written, items by their name.

    An item without a name is named by its number, with a `#` in front that the caller reads
    as "unlabeled".
    """
    import yaml

    names: list[str] = []
    node = root
    unlabeled = False
    for kind, index in steps[:start]:
        node = node.value[index][1] if kind == "k" else node.value[index]
    for kind, index in steps[start:]:
        if kind == "k":
            names.append(node.value[index][0].value)
            node = node.value[index][1]
        else:
            item = node.value[index]
            label = _label(item, spell)
            if not label:
                unlabeled = True
            names.append(label or str(index + 1))
            node = item
    if leaf is not None:
        if not isinstance(node, yaml.MappingNode) or leaf >= len(node.value):
            return None
        names.append(node.value[leaf][0].value)
    path = ".".join(name for name in names if name)
    if not path:
        return None
    return ("#" if unlabeled else "") + path


def _label(item, spell: dict) -> str | None:
    """The name an item of a list goes by: its name, handler or presentation, or its type."""
    import yaml

    if isinstance(item, yaml.ScalarNode):
        value = item.value.strip().lstrip("=$").split("(")[0]
        return value or None
    if not isinstance(item, yaml.MappingNode):
        return None
    values = {
        key.value: value.value for key, value in item.value
        if isinstance(key, yaml.ScalarNode) and isinstance(value, yaml.ScalarNode)
    }
    for key in spell["labels"]:
        value = (values.get(key) or "").strip().lstrip("=$")
        if value:
            return value
    for key in spell["type"]:
        value = (values.get(key) or "").strip()
        if value:
            return value.split("<")[0].split("(")[0].rsplit(".", 1)[-1]
    return None


def _merged(lines: list[str], first: int, removals: set[int], items: list) -> tuple[int, list[str]]:
    """The documentation block of a node with the new entries merged in.

    Returns the first line the block takes and its lines. The paragraphs of the description go
    first - the old ones, then the new ones - and the list of subjects after them: the old items,
    then the new ones in the order of the file.
    """
    key_line = lines[first - 1]
    indent = key_line[: len(key_line) - len(key_line.lstrip())]
    start = first
    while start > 1 and (start - 1) not in removals and lines[start - 2].strip().startswith("##"):
        start -= 1
    old = [line.strip() for line in lines[start - 1:first - 1]]
    split = next((index for index, line in enumerate(old) if line.startswith("## * ")), len(old))
    paragraphs = _trimmed(old[:split])
    listed = _trimmed(old[split:])
    new_paragraphs: list[str] = []
    new_items: list[str] = []
    for _line, subject, texts in sorted(items, key=lambda entry: entry[0]):
        body = list(texts)
        while body and not body[0]:
            body.pop(0)
        while body and not body[-1]:
            body.pop()
        if subject is None:
            if new_paragraphs:
                new_paragraphs.append("##")
            new_paragraphs.extend("## " + line if line else "##" for line in body)
        else:
            new_items.append(f"## * `{subject}`:")
            new_items.extend("##   " + line if line else "##" for line in body)
    head = paragraphs + (["##"] if paragraphs and new_paragraphs else []) + new_paragraphs
    tail = listed + new_items
    block = head + (["##"] if head and tail else []) + tail
    return start, [indent + line for line in block]


def _trimmed(block: list[str]) -> list[str]:
    """A part of a documentation block without the empty `##` lines at its edges."""
    out = list(block)
    while out and out[0] == "##":
        out.pop(0)
    while out and out[-1] == "##":
        out.pop()
    return out


def _comment_texts(text: str) -> Counter:
    """Every line of every comment of the text, without markers and indentation - the audit."""
    out: Counter = Counter()
    for line in text.split("\n"):
        stripped = line.strip().rstrip("\r")
        at = stripped.find("#")
        if at < 0:
            continue
        if at > 0 and not stripped.startswith("#"):
            # A comment after a value: the part after ` #`.
            found = re.search(r"\s#", stripped)
            if found is None:
                continue
            stripped = stripped[found.start() + 1:]
        body = _MARKER.sub("", stripped).strip()
        if body.startswith("* `") and body.endswith("`:"):
            continue  # a name line the fold writes itself
        if body:
            out[body] += 1
    return out


def _audit(rel: str, before: str, after: str, moves: list[Move], take_proposed: bool) -> list[str]:
    """What is wrong with the result; a file with a finding is not written."""
    import yaml

    problems: list[str] = []
    try:
        same = yaml.safe_load(before) == yaml.safe_load(after)
    except yaml.YAMLError:
        return [i18n.t("fold.audit.parse")]
    if not same:
        problems.append(i18n.t("fold.audit.data"))
    lost = _comment_texts(before) - _comment_texts(after)
    if lost:
        problems.append(i18n.t("fold.audit.lines", lines="; ".join(sorted(lost)[:3])))
    left = sum(1 for move in moves if move.action != "applied")
    found = len(_misplaced_lines(rel, after))
    if found > left:
        problems.append(i18n.t("fold.audit.rules", found=found - left))
    again = _fold_blocks(rel, after, take_proposed)[1]
    if any(move.action == "applied" for move in again):
        problems.append(i18n.t("fold.audit.again"))
    return problems


def fold_paths(paths: Iterable, *, take_proposed: bool = False) -> list[FileFold]:
    """The fold of every element description among the paths, in the order of the paths."""
    from pathlib import Path

    out: list[FileFold] = []
    for path in paths:
        path = Path(path)
        if path.suffix.lower() != ".yaml":
            continue
        raw = path.read_bytes()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
        result = fold_text(text, str(path), take_proposed=take_proposed)
        if result.moves:
            out.append(result)
    return out
