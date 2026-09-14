"""Module constants referenced nowhere in a whole-project check.

Like unused methods, constants may be read by yaml or by a string-based bridge. Any
word mention in a project source therefore keeps a constant alive. A translation
dictionary only describes the source and contributes no uses. Global constants are
a library API; their callers may live outside the checked project.
"""

from __future__ import annotations

from bisect import bisect_left
from collections import Counter
from collections.abc import Iterable
from functools import lru_cache

from xbsl import dataset, i18n, parser as P, terms
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, rule
from xbsl.rules._syntax import code_tokens
from xbsl.rules.unused_methods import _WORD_RE, _internal_annotations
from xbsl.rules.yaml_schema import is_translation_dictionary

RULE = "code/unused-constant"
i18n.register({
    f"{RULE}.title": {
        "ru": "Константа модуля нигде не используется",
        "en": "Module constant is never referenced",
    },
    f"{RULE}.unreferenced": {
        "ru": "Константа '{name}' объявлена, но больше нигде в проекте не упоминается.",
        "en": "Constant '{name}' is declared but referenced nowhere else in the project.",
    },
    f"{RULE}.off": {
        "ru": "нужен весь проект: при проверке отдельных файлов использование константы может остаться за их пределами",
        "en": "requires the whole project: a use outside the checked files would otherwise be missed",
    },
})


@lru_cache(maxsize=1)
def _constant_annotations() -> frozenset[str]:
    return _internal_annotations() - frozenset(terms.key_forms("Глобально"))


dataset.register_reset(_constant_annotations.cache_clear)


def _constant_mapper(source: SourceFile) -> dict | None:
    if source.kind == "yaml" and is_translation_dictionary(source):
        return None
    fact: dict = {"mentions": dict(Counter(_WORD_RE.findall(source.text)))}
    if source.kind != "xbsl":
        return fact
    module, errors = P.parse(source)
    if errors:
        return fact
    tokens = code_tokens(source)
    starts = [t.start for t in tokens]
    internal = _constant_annotations()
    declarations = []
    for member in module.members:
        if not isinstance(member, P.ObjectField) or member.kind != "CONST":
            continue
        if any(a.name not in internal for a in member.annotations):
            continue
        index = bisect_left(starts, member.start)
        while index < len(tokens) and tokens[index].start < member.end:
            token = tokens[index]
            if token.canonical == "CONST" and index + 1 < len(tokens):
                name = tokens[index + 1]
                declarations.append((member.name, name.line, name.col))
                break
            index += 1
    fact["decls"] = declarations
    return fact


@rule(RULE, f"{RULE}.title", "D", scope="project", severity=Severity.WARNING,
      enabled_by_default=False, off_reason=f"{RULE}.off", mapper=_constant_mapper)
def unused_constant(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    mentions: Counter = Counter()
    for fact in facts.values():
        mentions.update(fact["mentions"])
    for path, fact in facts.items():
        for name, line, col in fact.get("decls", ()):
            if mentions[name] <= 1:
                yield Diagnostic(path, line, col, RULE, Severity.WARNING,
                                 i18n.t(f"{RULE}.unreferenced", name=name))
