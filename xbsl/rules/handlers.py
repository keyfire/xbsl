"""Tier D: form handlers reference methods that exist in the module.

In a form's yaml description an event is given by a handler key whose value is a method name
in the paired module (`Name.yaml` ↔ `Name.xbsl`). The rule catches the "renamed a method –
forgot to fix the form" drift (and vice versa) before the server-side compilation on deploy.

For every handler key of the set the identifier value must match a method of the paired
module. The set is extended when needed. A value with a dot (an FQN reference to an external module) and a non-identifier are
not checked. The rule is cross-file: without the paired module handlers are not checked
(nothing to resolve against).
"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Iterable
from functools import lru_cache

from xbsl import dataset, i18n, uischema
from xbsl import parser as P
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, rule
from xbsl.lexer import linemap, tokens
from xbsl.parser import parse
from xbsl.rules._syntax import code_tokens

MESSAGES = {
    "form/unknown-handler.title": {
        "ru": "Обработчик формы не найден в модуле",
        "en": "Form handler not found in the module",
    },
    "form/unknown-handler.not-found": {
        "ru": "Обработчик '{name}' не найден как метод в модуле формы '{module}'.",
        "en": "Handler '{name}' is not found as a method in the form module '{module}'.",
    },
    "code/close-in-before-close.title": {
        "ru": "Закрыть() внутри ПередЗакрытием",
        "en": "{n[Закрыть]}() inside {n[ПередЗакрытием]}",
    },
    "code/close-in-before-close.nested": {
        "ru": "Вызов {name}() внутри обработчика {n[ПередЗакрытием]} платформа игнорирует, а "
              "процесс закрытия остаётся незавершённым – после этого форму не закрывает уже "
              "ничто. Вынесите закрытие за пределы обработчика разовым таймером: "
              "{n[ПодключитьОбработчикТаймера]}(() -> {name}(...), 0с, {n[Истина]}).",
        "en": "A {name}() call inside the {n[ПередЗакрытием]} handler is ignored by the platform "
              "while the closing stays unfinished – after that nothing closes the form at all. "
              "Move the closing out of the handler with a one-shot timer: "
              "{n[ПодключитьОбработчикТаймера]}(() -> {name}(...), 0с, {n[Истина]}).",
    },
}
i18n.register(MESSAGES)

_HANDLER_KEYS = (
    "Обработчик", "ПриНажатии", "ПриИзменении", "ПриВыделенииСтроки",
    "ПослеЗагрузкиСодержимого", "ПриСменеСтраницы", "ПриВыбореЭлемента",
)


@lru_cache(maxsize=1)
def _handler_re() -> re.Pattern[str]:
    """The event keys above in both spellings - a form may be written in English.

    The English name of every key comes from the component schema, never from a guess; a
    key the schema pairs with nothing keeps its Russian spelling alone.
    """
    keys: list[str] = []
    for key in _HANDLER_KEYS:
        for form in (key, uischema.english_property(key)):
            if form and form not in keys:
                keys.append(form)
    return re.compile(  # a trailing comment and CRLF are allowed after the value
        r"(?m)^[ \t]*(?:" + "|".join(keys) + r"):[ \t]*([^\s#][^\n#]*?)[ \t]*(?:#.*)?\r?$"
    )


dataset.register_reset(_handler_re.cache_clear)

_IDENT_RE = re.compile(r"^[^\W\d]\w*$", re.UNICODE)


def _module_methods(source: SourceFile) -> set[str]:
    """Names of the methods and constructors declared in the module."""
    toks = tokens(source)
    names: set[str] = set()
    for i, t in enumerate(toks):
        if t.kind == "KEYWORD" and t.canonical in ("METHOD", "CONSTRUCTOR") and t.value[:1].islower():
            j = i + 1
            while j < len(toks) and toks[j].kind == "COMMENT":
                j += 1
            if j < len(toks) and toks[j].kind == "IDENT":
                names.add(toks[j].value)
    return names


def _handler_pair_stem(rel: str) -> str:
    slash = rel.replace("\\", "/")
    return slash[: slash.rfind(".")] if "." in slash.rsplit("/", 1)[-1] else slash


def _handler_mapper(source: SourceFile) -> dict | None:
    """The map phase: a yaml contributes its handler references with positions, a module
    the set of its method names - the reduce joins the pair."""
    if source.kind == "xbsl":
        # Even an empty method set matters: a paired module WITHOUT the referenced
        # method is exactly what the rule flags.
        methods = _module_methods(source)
        return {"k": "x", "stem": _handler_pair_stem(source.rel), "methods": sorted(methods)}
    if source.kind != "yaml":
        return None
    refs: list[tuple[str, int, int]] = []
    lm = None
    for m in _handler_re().finditer(source.text):
        name = m.group(1).strip()
        if not _IDENT_RE.match(name):
            continue  # FQN reference to an external module or a non-identifier – skip
        if lm is None:
            lm = linemap(source)
        line, col = lm.linecol(m.start(1))
        refs.append((name, line, col))
    if not refs:
        return None
    return {
        "k": "y",
        "stem": _handler_pair_stem(source.rel),
        "module_file": source.path.with_suffix(".xbsl").name,
        "refs": refs,
    }


@rule(
    "form/unknown-handler", "form/unknown-handler.title", "D",
    scope="project", severity=Severity.WARNING, mapper=_handler_mapper,
)
def unknown_handler(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    methods_by_stem: dict[str, set[str]] = {}
    for fact in facts.values():
        if fact["k"] == "x":
            methods_by_stem[fact["stem"]] = set(fact["methods"])
    for rel, fact in facts.items():
        if fact["k"] != "y":
            continue
        methods = methods_by_stem.get(fact["stem"])
        if methods is None:
            continue  # no paired module – nothing to resolve handlers against
        for name, line, col in fact["refs"]:
            if name not in methods:
                yield Diagnostic(
                    rel, line, col, "form/unknown-handler", Severity.WARNING,
                    i18n.t(
                        "form/unknown-handler.not-found",
                        name=name, module=fact["module_file"],
                    ),
                )


# The handler the platform runs while the form is closing, in both spellings.
_BEFORE_CLOSE = frozenset({"ПередЗакрытием", "BeforeClose"})

# The call that the platform ignores inside that handler.
_CLOSE_NAMES = frozenset({"Закрыть", "Close"})


def _lambda_spans(method: P.Method) -> list[tuple[int, int]]:
    """[start, end) of every lambda inside the method - a deferred call is not the handler's.

    The AST has no generic walker, and the nodes are dataclasses, so the children are the
    field values: a node, or a sequence holding nodes. The sequence may hold TUPLES rather
    than nodes - the branches of `если` are (condition, body) pairs - so a walker that only
    descends into lists of nodes silently misses everything inside a condition.
    """
    spans: list[tuple[int, int]] = []

    def walk(node) -> None:
        if isinstance(node, (list, tuple)):
            for item in node:
                walk(item)
            return
        if not isinstance(node, P.Node):
            return
        if isinstance(node, P.Lambda):
            spans.append((node.start, node.end))
            return  # a lambda inside a lambda is inside this span anyway
        for f in dataclasses.fields(node):
            walk(getattr(node, f.name, None))

    walk(method.body)
    return spans


@rule(
    "code/close-in-before-close", "code/close-in-before-close.title", "C",
    severity=Severity.WARNING,
)
def close_in_before_close(source: SourceFile) -> Iterable[Diagnostic]:
    """`Закрыть(...)` in the body of `ПередЗакрытием` - the platform ignores it and the form sticks.

    The pattern "ask on closing, Yes = save and close" cannot be written as a nested call: the
    platform ignores it, the closing process stays unfinished, and afterwards even the cross
    does nothing (the symptom is "the form can no longer be closed"). The cure is to save
    synchronously in the handler and close outside it with a one-shot timer - so a call inside
    a LAMBDA is exactly the cure and stays silent; only a call made in the handler's own flow
    is reported. A call through an intermediate method breaks the form just as badly, but a
    file rule cannot see through the call - that half stays with the deploy.
    """
    if source.kind != "xbsl":
        return
    if not any(name in source.text for name in _CLOSE_NAMES):
        return
    module, errors = parse(source)
    if errors:
        return  # a broken file is code/parse-error territory
    toks = code_tokens(source)
    lm = linemap(source)
    for member in module.members:
        if not isinstance(member, P.Method) or member.name not in _BEFORE_CLOSE:
            continue
        spans = _lambda_spans(member)
        for i, t in enumerate(toks):
            if t.start < member.start:
                continue
            if t.start >= member.end:
                break
            if t.kind != "IDENT" or t.value not in _CLOSE_NAMES:
                continue
            following = toks[i + 1] if i + 1 < len(toks) else None
            if following is None or following.kind != "OP" or following.value != "(":
                continue
            previous = toks[i - 1] if i else None
            if previous is not None and previous.kind == "OP" and previous.value == ".":
                continue  # a member call on a value, not the form's own Закрыть
            if any(start <= t.start < end for start, end in spans):
                continue  # inside a lambda - that is the recommended deferred closing
            line, col = lm.linecol(t.start)
            yield Diagnostic(
                source.rel, line, col, "code/close-in-before-close", Severity.WARNING,
                i18n.t("code/close-in-before-close.nested", name=t.value),
            )
