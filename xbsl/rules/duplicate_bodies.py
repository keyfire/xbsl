"""Tier D: one method body written twice in DIFFERENT files.

Copy-paste between modules is the kind of duplication that survives review: each file reads
fine on its own, and the second copy is found only when a fix has to be applied twice. The
rule compares the NORMALIZED body - comments and blank lines dropped, indentation collapsed -
so a reformatted copy is still a copy, and it judges only bodies of at least five such lines:
below that the coincidence of two short bodies (a guard clause, a one-line delegation) is
ordinary.

Two narrowings, both measured:

- a PLATFORM HOOK is left alone, and it is told apart by its `@Handler` annotation rather
  than by a list of names. The platform calls such a method itself in every object that
  declares it, and the same body in every object is the normal shape of that contract; a
  hand-written wrapper of the same name carries no annotation and is judged as any other
  method (on a live project the annotation covered 73 of 73 `AfterCreation` hooks and none
  of the 24 hand-written `PerformWrite` wrappers);
- copies inside ONE file are not reported. There the duplication is visible while reading the
  file, and the cure is local; the class this rule is about is the copy that hides in another
  module.

Off by default, like the other rules whose finding is a refactoring proposal rather than a
defect: whether two identical bodies should become one method is a design decision, and on a
subset of files the rule cannot see the other copy at all.
"""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from collections.abc import Iterable
from functools import lru_cache

from xbsl import dataset, i18n, terms
from xbsl import parser as P
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, rule
from xbsl.lexer import linemap
from xbsl.parser import parse

MESSAGES = {
    "code/duplicate-method-body.title": {
        "ru": "Тело метода повторяется в другом файле",
        "en": "The method body is repeated in another file",
    },
    "code/duplicate-method-body.copy": {
        "ru": "Тело метода '{name}' ({lines} строк) дословно повторяет '{other}' в {path}"
              "{more}. Вынесите общий код в один метод – иначе правку придётся вносить в "
              "каждую копию.",
        "en": "The body of '{name}' ({lines} lines) repeats '{other}' in {path}{more} word for "
              "word. Move the shared code into one method - otherwise every copy has to be "
              "fixed on its own.",
    },
    "code/duplicate-method-body.more": {
        "ru": " и ещё в {count} местах",
        "en": " and in {count} more places",
    },
}
i18n.register(MESSAGES)

#: The shortest body worth reporting, in normalized lines.
MIN_LINES = 5
_COMMENT_RE = re.compile(r"//.*")


@lru_cache(maxsize=1)
def _handler_forms() -> frozenset[str]:
    """Both spellings of the annotation that marks a platform hook."""
    return frozenset(terms.key_forms("Обработчик"))


dataset.register_reset(_handler_forms.cache_clear)


def _normalized(text: str) -> list[str]:
    """The body without comments, blank lines and indentation - the shape that is compared."""
    out: list[str] = []
    for raw in text.splitlines():
        line = _COMMENT_RE.sub("", raw).strip()
        if line:
            out.append(" ".join(line.split()))
    return out


def _duplicate_mapper(source: SourceFile) -> dict | None:
    """The map phase: the fingerprint of every body long enough to be worth comparing."""
    if source.kind != "xbsl":
        return None
    module, errors = parse(source)
    if errors:
        return None  # a broken file is code/parse-error territory
    handler = _handler_forms()
    lm = linemap(source)
    bodies: list[tuple[str, str, int, int]] = []  # (digest, name, line, line count)
    for member in module.members:
        if not isinstance(member, P.Method) or not member.body:
            continue
        if {a.name for a in member.annotations} & handler:
            continue  # the platform calls it in every object that declares it
        lines = _normalized(source.text[member.body[0].start:member.body[-1].end])
        if len(lines) < MIN_LINES:
            continue
        digest = hashlib.sha1("\n".join(lines).encode("utf-8")).hexdigest()
        bodies.append((digest, member.name, lm.linecol(member.start)[0], len(lines)))
    return {"bodies": bodies} if bodies else None


@rule(
    "code/duplicate-method-body", "code/duplicate-method-body.title", "D",
    scope="project", severity=Severity.WARNING, enabled_by_default=False,
    off_reason="code/duplicate-method-body.off", mapper=_duplicate_mapper,
)
def duplicate_method_body(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    places: dict[str, list[tuple[str, str, int, int]]] = defaultdict(list)
    for rel, fact in facts.items():
        for digest, name, line, count in fact["bodies"]:
            places[digest].append((rel, name, line, count))
    for group in places.values():
        if len({rel for rel, _name, _line, _count in group}) < 2:
            continue  # a copy inside one file is visible while reading it
        for rel, name, line, count in group:
            others = [(r, n) for r, n, _l, _c in group if (r, n) != (rel, name)]
            first_path, first_name = others[0]
            more = ("" if len(others) == 1
                    else i18n.t("code/duplicate-method-body.more", count=len(others) - 1))
            yield Diagnostic(
                rel, line, 1, "code/duplicate-method-body", Severity.WARNING,
                i18n.t("code/duplicate-method-body.copy", name=name, lines=count,
                       other=first_name, path=first_path, more=more),
            )
