"""Tier A: one and the same interface subtree, copied into another file.

A new form is often started by copying the neighbouring one, and the copy then drifts: the
fix goes into one file and misses the other. What the rule compares is the SHAPE of a subtree -
the keys, the nesting and the composition of the children - with the names and the texts
blanked out, because a copy is renamed and stays a copy.

Three decisions, each measured rather than guessed (four corpora, the threshold swept):

- **only across FILES.** Two mirrored pages of one form (the yearly and the monthly plan, the
  open and the closed state) are a layout idiom, not a copy to be pulled out, and they are the
  bulk of the within-file matches;
- **from 40 nodes.** At the four-node threshold the plan first proposed, a live project answers
  with 294 groups - every card, every button pair, every two-field row. At 40 it answers with
  the two copies that are really copies, and a foreign corpus with none;
- **the data SOURCE of a list is skipped.** The query and the field set of two lists of the same
  kind coincide by construction; without the exclusion half of the findings were those. A
  dictionary of localized strings is skipped whole for the same reason: its per-language twin
  repeats its shape by definition, and a project with two languages would answer with nothing
  else.

Only MAXIMAL groups are reported: a duplicated subtree duplicates its every branch too, and
naming them all says the same thing a dozen times.

Off by default, like `code/duplicate-method-body`: how much sameness is too much is a decision
of the project, not of the linter.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from functools import lru_cache

from xbsl import dataset, i18n, terms
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, rule
from xbsl.rules.yaml_schema import _composed, _parsed, object_kind

try:
    import yaml

    _HAVE_YAML = True
except ImportError:  # pragma: no cover
    _HAVE_YAML = False

MESSAGES = {
    "yaml/duplicate-subtree.title": {
        "ru": "Поддерево повторяет поддерево другого файла",
        "en": "The subtree repeats a subtree of another file",
    },
    "yaml/duplicate-subtree.copy": {
        "ru": "Поддерево из {nodes} узлов повторяет устройство поддерева в файле {other} "
              "(всего таких мест: {places}). Имена и тексты в счёт не идут – это копия, "
              "которую переименовали. Вынесите общий компонент, иначе правку придётся вносить "
              "в каждую копию.",
        "en": "This subtree of {nodes} nodes repeats the shape of a subtree in {other} "
              "({places} places in all). Names and texts do not count - a copy is a copy once "
              "renamed. Pull out a shared component, or the fix will have to go into every "
              "copy.",
    },
}
i18n.register(MESSAGES)

#: The size from which sameness stops being a coincidence of the layout - measured, see above.
_MIN_NODES = 40

#: A dictionary of localized strings: the translation file repeats its shape by definition.
_SKIPPED_KIND = "ЛокализованныеСтроки"


@lru_cache(maxsize=1)
def _blanked_keys() -> frozenset[str]:
    """Keys whose value carries a NAME or a TEXT: a copy differs there and stays a copy."""
    return frozenset(terms.key_forms(
        "Имя", "Ид", "Заголовок", "Подсказка", "Текст", "Представление",
    ))


@lru_cache(maxsize=1)
def _source_keys() -> frozenset[str]:
    """The data source of a list: two lists of one kind carry the same one by construction."""
    return frozenset(terms.key_forms("Источник"))


dataset.register_reset(lambda: (_blanked_keys.cache_clear(), _source_keys.cache_clear()))


def _shape(node) -> tuple[str, int]:
    """The shape of a node and how many nodes it holds."""
    if isinstance(node, yaml.MappingNode):
        parts, count = [], 1
        blanked = _blanked_keys()
        for key, value in sorted(node.value, key=lambda pair: str(getattr(pair[0], "value", ""))):
            name = str(getattr(key, "value", ""))
            if name in blanked:
                parts.append(name + ":*")
                continue
            child, held = _shape(value)
            parts.append(name + "=" + child)
            count += held
        return "{" + ",".join(parts) + "}", count
    if isinstance(node, yaml.SequenceNode):
        parts, count = [], 1
        for item in node.value:
            child, held = _shape(item)
            parts.append(child)
            count += held
        return "[" + ",".join(parts) + "]", count
    return "s", 1


def _walk(node, path: str, out: list) -> None:
    if isinstance(node, yaml.MappingNode):
        text, count = _shape(node)
        if count >= _MIN_NODES:
            digest = hashlib.blake2s(text.encode("utf-8"), digest_size=8).hexdigest()
            out.append([digest, count, node.start_mark.line + 1,
                        node.start_mark.column + 1, path])
        sources = _source_keys()
        for key, value in node.value:
            name = str(getattr(key, "value", ""))
            if name in sources:
                continue
            _walk(value, path + "/" + name, out)
    elif isinstance(node, yaml.SequenceNode):
        for index, item in enumerate(node.value):
            _walk(item, path + "[" + str(index) + "]", out)


def _duplicate_subtree_mapper(source: SourceFile) -> dict | None:
    if not _HAVE_YAML or source.kind != "yaml":
        return None
    data, err = _parsed(source)
    if err is None and object_kind(data) == _SKIPPED_KIND:
        return None
    root = _composed(source)
    if not isinstance(root, yaml.MappingNode):
        return None
    found: list = []
    _walk(root, "", found)
    return {"subtrees": found} if found else None


def _covered(places: list[tuple[str, str]], claimed: list[tuple[str, str]]) -> bool:
    """Whether every place of a group lies inside a place already claimed by a bigger one."""
    return all(
        any(rel == owner_rel and (path.startswith(owner + "/") or path.startswith(owner + "["))
            for owner_rel, owner in claimed)
        for rel, path in places
    )


@rule(
    "yaml/duplicate-subtree", "yaml/duplicate-subtree.title", "A",
    scope="project", severity=Severity.WARNING, enabled_by_default=False,
    off_reason="yaml/duplicate-subtree.off", mapper=_duplicate_subtree_mapper,
)
def duplicate_subtree(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    groups: dict[str, list] = {}
    for rel, fact in facts.items():
        for digest, count, line, col, path in fact.get("subtrees", ()):
            groups.setdefault(digest, []).append((rel, path, count, line, col))
    # The biggest first: a group nested inside a bigger one says the same thing again.
    ordered = sorted(groups.values(), key=lambda places: (-places[0][2], places[0][0]))
    claimed: list[tuple[str, str]] = []
    for places in ordered:
        if len({rel for rel, _p, _c, _l, _col in places}) < 2:
            continue  # within one file two mirrored branches are a layout, not a copy
        if _covered([(rel, path) for rel, path, _c, _l, _col in places], claimed):
            continue
        claimed.extend((rel, path) for rel, path, _c, _l, _col in places)
        ordered_places = sorted(places)
        for rel, _path, count, line, col in ordered_places:
            other = next(name for name, *_rest in ordered_places if name != rel)
            yield Diagnostic(
                rel, line, col, "yaml/duplicate-subtree", Severity.WARNING,
                i18n.t("yaml/duplicate-subtree.copy", nodes=count, other=other,
                       places=len(ordered_places)),
            )
