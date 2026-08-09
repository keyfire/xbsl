"""Tier D: a method declared in the project but referenced nowhere (dead code).

The check is deliberately built from exceptions – any doubt silences the finding. A method
is reported only when its name, apart from the declaration itself, occurs nowhere in the
project: neither in xbsl code (a call, a reference, a callback), nor in yaml descriptions
(handler keys, bindings), nor in string literals (HTML-container bridges call methods by
name inside strings), nor in comments. The mention search counts raw word tokens over the
FULL text of every project file, so a name inside a string or a comment also counts as a
use – deliberately conservative: better silence than a false positive.

Guards (such methods are never reported):

- a method with an annotation that means a call from OUTSIDE the project code: the
  platform calls it itself (@Handler, @Subscription, @ProjectUpdate, @ApplicationSetup),
  a contract calls it through the base type (@Implementation, @Override), or the method is
  deliberately kept for compatibility (@Deprecated). An annotation the dictionary does not
  know is treated the same way – a project may declare its own, and doubt silences the
  finding;
- names of the platform's own events (ПередЗаписью, ПослеСоздания, ...) – called by the
  platform even when the annotation was forgotten;
- object modules (`X.Объект.xbsl`) – object event handlers live there;
- modules paired with an `HttpСервис` yaml – their methods are wired to endpoints;
- a qualified use `Модуль.Метод` of a static manager method is an ordinary mention and is
  covered by the name search.

The annotations of VISIBILITY (@InProject, @InSubsystem, @InType, @Global, @Local) and of the
ENVIRONMENT (@OnServer, @OnClient, @AvailableFromClient, @Contextual) do NOT silence the
rule, and this is the whole point of the guard being a list rather than "any annotation".
Both say WHO may call the method and WHERE it runs, not that anybody outside the project
does: the caller is the project's own code, so a mention has to be somewhere among its
files. Silencing them left the public API of the common modules – exactly where dead code
piles up – unjudged: on a 400-file corpus the rule saw 1540 declarations and reported none,
while a manual count of the callers found seven declarations with no caller at all.

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
from functools import lru_cache

from xbsl import dataset, i18n, terms
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, rule
from xbsl.rules._syntax import annotations_before, code_tokens

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


@lru_cache(maxsize=1)
def _internal_annotations() -> frozenset[str]:
    """Both spellings of the annotations that leave the caller INSIDE the project.

    Everything else – the platform's own (@Handler, @Subscription, @ProjectUpdate,
    @ApplicationSetup), a contract's (@Implementation, @Override), compatibility
    (@Deprecated) and any annotation the dictionary does not know (a project may declare
    its own) – means a caller the mention search cannot see, and silences the method.
    Without the data file only the Russian spellings are known, so an English project
    degrades into silence rather than into false findings.
    """
    return frozenset(terms.key_forms(
        # Std::Annotations::VisibilityScopes – WHO may call the method
        "Локально", "ВПодсистеме", "ВПроекте", "ВТипе", "Глобально",
        # Std::Annotations::Environments and Contextual – WHERE the method runs
        "НаКлиенте", "НаСервере", "ДоступноСКлиента", "Контекстный",
        # the call form and a compiler check – neither says anything about the caller
        "ИменованныеПараметры", "ПроверятьИспользованиеЗначения",
    ))


dataset.register_reset(_internal_annotations.cache_clear)

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


def _silenced_by_annotation(toks: list, i: int) -> bool:
    """An annotation above the method at i names a caller outside the project code."""
    return any(name not in _internal_annotations() for name in annotations_before(toks, i))


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
        if _silenced_by_annotation(toks, i):
            continue
        decls.append((name_tok.value, name_tok.line, name_tok.col))
    if decls:
        fact["decls"] = decls
    return fact


@rule(
    "code/unused-method", "code/unused-method.title", "D",
    scope="project", severity=Severity.WARNING, enabled_by_default=False, off_reason="code/unused-method.off",
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
