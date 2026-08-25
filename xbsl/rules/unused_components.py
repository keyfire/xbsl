"""Tier A: an interface component that nothing places and nothing creates.

A component is dead when no other file of the project names it: no yaml value puts it
anywhere (`Тип: X`, `Тип: Обёртка<X>`, `ТипКомпонентаСтроки: X`, `Форма: X` of an object,
`ТипФормы: X` of a section) and no module mentions it at all (`новый X(`, `Тип<X>`, a
parameter type, a static call `X.Метод()`). `code/unused-method` cannot see such a component
in principle: its methods are called by its OWN yaml, so every one of them looks used.

What counts as a use, and why the two sides are counted differently:

- in a YAML, only a scalar VALUE counts. A key does not (the localization dictionary and the
  translation dictionary both write names as KEYS - `Задачи: Tasks` - and counting those would
  silence every component of a bilingual project), and neither does a comment naming the
  component in prose;
- in a MODULE, any word of the text counts, a comment and a string literal included. That is
  deliberately lax, exactly as in `code/unused-method`: a component may be created by name
  from a string (an HTML container bridge), and doubt has to silence the finding.

Never reported:

- an ENTRY POINT - a component inheriting a client application (`CustomClientApplication`,
  `StandardClientApplicationWithSections`). Nothing refers to it by name: the address does,
  through the `Path` it declares;
- a component visible GLOBALLY (`VisibilityScope: Global`) - that is the public surface of a
  library, and its consumer is another project the linter does not see;
- a component whose name does not start with a capital letter. The mention search keeps only
  capitalized words (a component name is a type name), so a lower-case name would be judged
  against an incomplete set of uses.

The rule is cross-file (scope=project) and sound only when the linter sees the WHOLE project:
on a subset of files a component placed outside the subset would be a false positive. So the
run has to prove it covers a project - the project descriptor (the yaml with `Provider` and
`Version`) must be among the linted files. Without it the rule stays silent, which is what
keeps a single file, a directory or an editor buffer from being judged as a whole project.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from functools import lru_cache

from xbsl import dataset, formmodel, i18n, terms
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, rule
from xbsl.rules.project import _project
from xbsl.rules.yaml_schema import _HAVE_YAML, _composed, _parsed, object_kind, value_of, yaml

MESSAGES = {
    "yaml/unused-component.title": {
        "ru": "Компонент интерфейса нигде не используется",
        "en": "Interface component is never used",
    },
    "yaml/unused-component.unplaced": {
        "ru": "Компонент '{name}' нигде в проекте не размещён и не создан – ни в разметке "
              "другого компонента, ни в коде. Мёртвый компонент не виден правилу "
              "code/unused-method: его методы зовёт его же yaml.",
        "en": "Component '{name}' is placed nowhere in the project and created nowhere – "
              "neither in the markup of another component nor in code. A dead component is "
              "invisible to code/unused-method: its methods are called by its own yaml.",
    },
}
i18n.register(MESSAGES)

_WORD_RE = re.compile(r"[^\W\d]\w*", re.UNICODE)


@lru_cache(maxsize=1)
def _name_keys() -> frozenset[str]:
    return frozenset(terms.key_forms("Имя"))


@lru_cache(maxsize=1)
def _app_words() -> tuple[str, ...]:
    """Both spellings of the client application - the base type of an entry point.

    A substring is enough and is what the platform's own naming asks for: every application
    type is that word with a prefix (`Произвольное...`, `Стандартное...СРазделами`).
    """
    return terms.key_forms("КлиентскоеПриложение")


@lru_cache(maxsize=1)
def _global_scopes() -> frozenset[str]:
    return frozenset(terms.key_forms("Глобально"))


dataset.register_reset(_name_keys.cache_clear)
dataset.register_reset(_app_words.cache_clear)
dataset.register_reset(_global_scopes.cache_clear)


def _pair_stem(rel: str) -> str:
    slash = rel.replace("\\", "/")
    return slash[: slash.rfind(".")] if "." in slash.rsplit("/", 1)[-1] else slash


def _names(text: str) -> set[str]:
    """The capitalized words of a text - the shape of every type name."""
    return {w for w in _WORD_RE.findall(text) if w[:1].isupper()}


def _value_names(data) -> set[str]:
    """The names written in the scalar VALUES of a parsed yaml; keys are not uses."""
    out: set[str] = set()
    stack = [data]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            stack.extend(node.values())
        elif isinstance(node, (list, tuple)):
            stack.extend(node)
        elif isinstance(node, str):
            out |= _names(node)
    return out


def _name_position(source: SourceFile) -> tuple[int, int]:
    """Line and column of the component's own name, or the start of the file."""
    root = _composed(source)
    if isinstance(root, yaml.MappingNode):
        for key, value in root.value:
            if isinstance(key, yaml.ScalarNode) and key.value in _name_keys():
                return value.start_mark.line + 1, value.start_mark.column + 1
    return 1, 1


def _is_entry_point(data, kind: str | None) -> bool:
    """A component inheriting a client application: the address reaches it, no name does."""
    inherits = value_of(data, "Наследует", kind)
    base = value_of(inherits, "Тип") if isinstance(inherits, dict) else None
    return isinstance(base, str) and any(word in base for word in _app_words())


def _unused_component_mapper(source: SourceFile) -> dict | None:
    """The map phase: what each file USES, and what a component yaml DECLARES."""
    fact: dict = {"stem": _pair_stem(source.rel)}
    if source.kind == "yaml" and _project(source) is not None:
        fact["root"] = True  # the run covers a project, not a subset of one
    if source.kind != "yaml":
        fact["uses"] = sorted(_names(source.text))
        return fact
    if not _HAVE_YAML:
        return None
    data, _err = _parsed(source)
    fact["uses"] = sorted(_value_names(data))
    kind = object_kind(data)
    if kind != formmodel.COMPONENT_ELEMENT_KIND:
        return fact
    name = value_of(data, "Имя", kind)
    if not isinstance(name, str) or not name[:1].isupper():
        return fact
    scope = value_of(data, "ОбластьВидимости", kind)
    if isinstance(scope, str) and scope in _global_scopes():
        return fact  # the public surface of a library - the consumer is another project
    if _is_entry_point(data, kind):
        return fact
    line, col = _name_position(source)
    fact["decl"] = (name, line, col)
    return fact


@rule(
    "yaml/unused-component", "yaml/unused-component.title", "A",
    scope="project", severity=Severity.WARNING, mapper=_unused_component_mapper,
)
def unused_component(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    if not any(fact.get("root") for fact in facts.values()):
        return  # a subset run: a component placed outside it would be a false positive
    declared: dict[str, str] = {}  # name -> the stem of the pair that declares it
    for fact in facts.values():
        decl = fact.get("decl")
        if decl:
            declared[decl[0]] = fact["stem"]
    if not declared:
        return
    used: set[str] = set()
    for fact in facts.values():
        stem = fact["stem"]
        for name in fact.get("uses", ()):
            if name in declared and declared[name] != stem:
                used.add(name)
    for rel, fact in facts.items():
        decl = fact.get("decl")
        if decl and decl[0] not in used:
            name, line, col = decl
            yield Diagnostic(
                rel, line, col, "yaml/unused-component", Severity.WARNING,
                i18n.t("yaml/unused-component.unplaced", name=name),
            )
