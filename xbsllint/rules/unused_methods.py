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
meant for full-project runs via `--select code/unused-method`. Verified on the real corpus
(the single finding audited by hand and confirmed dead).
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable

from xbsllint import i18n
from xbsllint.diagnostics import Diagnostic, Severity
from xbsllint.engine import SourceFile, rule
from xbsllint.rules._syntax import code_tokens

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
_HTTP_SERVICE_RE = re.compile(r"(?m)^ВидЭлемента:[ \t]*HttpСервис[ \t\r]*$")

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


def _is_http_service_module(source: SourceFile, yamls: dict[str, SourceFile]) -> bool:
    pair = yamls.get(str(source.path.with_suffix(".yaml")))
    return pair is not None and _HTTP_SERVICE_RE.search(pair.text) is not None


@rule(
    "code/unused-method", "code/unused-method.title", "D",
    scope="project", severity=Severity.WARNING, enabled_by_default=False,
)
def unused_method(sources: list[SourceFile]) -> Iterable[Diagnostic]:
    modules = [s for s in sources if s.kind == "xbsl"]
    if not modules:
        return []
    yamls = {str(s.path): s for s in sources if s.kind == "yaml"}

    # Every word-like token of every file (code, yaml, strings, comments) is a mention.
    mentions: Counter = Counter()
    for s in sources:
        mentions.update(_WORD_RE.findall(s.text))

    diags: list[Diagnostic] = []
    for s in modules:
        if s.path.stem.endswith(".Объект"):
            continue  # object module – platform event handlers
        if _is_http_service_module(s, yamls):
            continue  # HTTP service module – methods are wired to endpoints
        toks = code_tokens(s)
        for i, t in enumerate(toks):
            if t.kind != "KEYWORD" or t.canonical != "METHOD" or not t.value[:1].islower():
                continue
            if i + 1 >= len(toks) or toks[i + 1].kind != "IDENT":
                continue
            name_tok = toks[i + 1]
            name = name_tok.value
            if name in _PLATFORM_EVENTS:
                continue
            if _is_annotated(toks, i):
                continue
            if mentions[name] <= 1:  # the declaration itself and nothing else
                diags.append(Diagnostic(
                    s.rel, name_tok.line, name_tok.col,
                    "code/unused-method", Severity.WARNING,
                    i18n.t("code/unused-method.unreferenced", name=name),
                ))
    return diags
