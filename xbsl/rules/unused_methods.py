"""Tier D: a method declared in the project but referenced nowhere (dead code).

The check is deliberately built from exceptions – any doubt silences the finding. A method
is reported only when its name, apart from the declaration itself, occurs nowhere in the
project: neither in xbsl code (a call, a reference, a callback), nor in yaml descriptions
(handler keys, bindings), nor in string literals (HTML-container bridges call methods by
name inside strings), nor in comments. The mention search counts raw word tokens over the
FULL text of every project file, so a name inside a string or a comment also counts as a
use – deliberately conservative: better silence than a false positive.

Guards (such methods are never reported):

- a method with ANY annotation (@Обработчик, @ДоступноСКлиента, @НаСервере, ...) – these
  are called by the platform or from outside the module;
- names of the platform's own events (ПередЗаписью, ПослеСоздания, ...) – called by the
  platform even when the annotation was forgotten;
- object modules (`X.Объект.xbsl`) – object event handlers live there;
- modules paired with an `HttpСервис` yaml – their methods are wired to endpoints;
- a qualified use `Модуль.Метод` of a static manager method is an ordinary mention and is
  covered by the name search.

The rule is cross-file (scope=project): a single module cannot tell a dead method from one
called elsewhere. It is sound only when the linter sees the WHOLE project: on a subset of
files (a single directory, an editor buffer) a method used outside the subset would be a
false positive. That is why the rule is disabled by default (like style/line-length) and is
meant for full-project runs via `--select code/unused-method`.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable

from xbsl import i18n
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, rule
from xbsl.rules._syntax import code_tokens

MESSAGES = {
    "code/unused-method.title": {
        "ru": "Метод нигде не используется",
        "en": "Method is never referenced",
    },
    "code/unused-method.unreferenced": {
        "ru": "Метод '{name}' объявлен, но больше нигде в проекте не упоминается – "
              "ни в коде, ни в yaml, ни в строках.",
        "en": "Method '{name}' is declared but referenced nowhere else in the project – "
              "neither in code, nor in yaml, nor in strings.",
    },
}
i18n.register(MESSAGES)

_WORD_RE = re.compile(r"[^\W\d]\w*", re.UNICODE)
_HTTP_SERVICE_RE = re.compile(r"(?m)^ВидЭлемента:[ \t]*HttpСервис[ \t]*(?:#.*)?\r?$")

# Modifiers that may stand between the annotations and the `метод` keyword.
_MODIFIERS = ("STATIC", "ABSTRACT", "GLOBAL_EN", "GLOBAL_RU")

# Platform events: the platform calls these by name, a project-wide mention is not required.
# Collected from the 9.2 docs (catalog-types/document-types/exchange-plan-types,
# whats-new-in-5-0 "Переопределяемые обработчики") and the access-control contract.
_PLATFORM_EVENTS = frozenset({
    # object module: catalogs, documents, exchange plans
    "ПриЗаполнении", "ПередЗаписью", "ПослеЗаписи", "ПередУдалением",
    # overridable handlers of Компонент / Форма / ФормаОбъекта / КлиентскоеПриложение
    "ПослеСоздания", "ПриОбновлении", "ПослеЗакрытия", "ПередЗакрытием",
    "ПослеЧтения", "ПередЗаписьюОбъекта", "ПослеЗаписиОбъекта",
    "ПередУдалениемОбъекта", "ПослеУдаленияОбъекта",
    "ПриИзмененииИсторииПереходов", "ПриОткрытииПоСсылке",
    # access control and RLS
    "ВычислитьРазрешенияДоступа", "ВычислитьРазрешенияДоступаДляОбъектов",
    "ПроверитьНаличиеКлючейДоступа",
    # client work parameters
    "ВычислитьПараметрыРаботыКлиента",
})


def _is_annotated(toks: list, i: int) -> bool:
    """Any annotation (`@Имя`, possibly with arguments) before the method keyword at i.

    Walks back over modifiers (стат/абстрактный/глобальный) and annotation clusters;
    `toks` must be comment-free (code_tokens)."""
    j = i - 1
    while j >= 0:
        t = toks[j]
        if t.kind == "OP" and t.value == "@":
            return True
        if t.kind == "OP" and t.value == ")":
            # annotation arguments: skip the balanced parentheses back
            depth = 0
            while j >= 0:
                tk = toks[j]
                if tk.kind == "OP" and tk.value == ")":
                    depth += 1
                elif tk.kind == "OP" and tk.value == "(":
                    depth -= 1
                    if depth == 0:
                        break
                j -= 1
            j -= 1
            continue
        if t.kind in ("IDENT", "KEYWORD"):
            if t.kind == "KEYWORD" and t.canonical in _MODIFIERS:
                j -= 1
                continue
            # a possible annotation name: annotated when an `@` stands right before it
            return j > 0 and toks[j - 1].kind == "OP" and toks[j - 1].value == "@"
        return False
    return False


def _pair_stem(rel: str) -> str:
    slash = rel.replace("\\", "/")
    return slash[: slash.rfind(".")] if "." in slash.rsplit("/", 1)[-1] else slash


def _unused_mapper(source: SourceFile) -> dict | None:
    """The map phase. Every file contributes its word-mention counter slice; a yaml also
    flags an HTTP service pair, a module also lists its unannotated method declarations
    (positions included). The mention counting joins in the reduce."""
    fact: dict = {"k": source.kind, "stem": _pair_stem(source.rel)}
    # Every word-like token of every file (code, yaml, strings, comments) is a mention.
    fact["mentions"] = dict(Counter(_WORD_RE.findall(source.text)))
    if source.kind == "yaml":
        if _HTTP_SERVICE_RE.search(source.text) is not None:
            fact["http"] = True
        return fact
    if source.kind != "xbsl":
        return fact
    if source.path.stem.endswith(".Объект"):
        return fact  # object module – platform event handlers, no declarations to check
    decls: list[tuple[str, int, int]] = []
    toks = code_tokens(source)
    for i, t in enumerate(toks):
        if t.kind != "KEYWORD" or t.canonical != "METHOD" or not t.value[:1].islower():
            continue
        if i + 1 >= len(toks) or toks[i + 1].kind != "IDENT":
            continue
        name_tok = toks[i + 1]
        if name_tok.value in _PLATFORM_EVENTS:
            continue
        if _is_annotated(toks, i):
            continue
        decls.append((name_tok.value, name_tok.line, name_tok.col))
    if decls:
        fact["decls"] = decls
    return fact


@rule(
    "code/unused-method", "code/unused-method.title", "D",
    scope="project", severity=Severity.WARNING, enabled_by_default=False,
    mapper=_unused_mapper,
)
def unused_method(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    mentions: Counter = Counter()
    http_stems: set[str] = set()
    for fact in facts.values():
        mentions.update(fact["mentions"])
        if fact.get("http"):
            http_stems.add(fact["stem"])
    for rel, fact in facts.items():
        if fact["k"] != "xbsl" or "decls" not in fact:
            continue
        if fact["stem"] in http_stems:
            continue  # HTTP service module – methods are wired to endpoints
        for name, line, col in fact["decls"]:
            if mentions[name] <= 1:  # the declaration itself and nothing else
                yield Diagnostic(
                    rel, line, col, "code/unused-method", Severity.WARNING,
                    i18n.t("code/unused-method.unreferenced", name=name),
                )
