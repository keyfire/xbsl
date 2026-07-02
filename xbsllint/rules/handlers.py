"""Тир D: обработчики форм ссылаются на существующие методы модуля.

В yaml-описании формы событие задаётся ключом-обработчиком, значение которого – имя метода
в парном модуле (`Имя.yaml` ↔ `Имя.xbsl`). Правило ловит рассинхрон "переименовал метод –
забыл поправить в форме" (и наоборот) до серверной компиляции при деплое.

Набор ключей-обработчиков выверен на реальном корпусе: у всех значение-идентификатор всегда
совпадает с методом парного модуля (0 ложных). Набор при необходимости расширяется. Значение
с точкой (FQN-ссылка на внешний модуль) и не-идентификатор не проверяются. Правило кросс-
файловое: без парного модуля обработчики не проверяются (не из чего резолвить).
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from xbsllint.diagnostics import Diagnostic, Severity
from xbsllint.engine import SourceFile, rule
from xbsllint.lexer import linemap, tokens

_HANDLER_KEYS = (
    "Обработчик", "ПриНажатии", "ПриИзменении", "ПриВыделенииСтроки",
    "ПослеЗагрузкиСодержимого", "ПриСменеСтраницы", "ПриВыбореЭлемента",
)
_HANDLER_RE = re.compile(
    r"(?m)^[ \t]*(?:" + "|".join(_HANDLER_KEYS) + r"):[ \t]*([^\s#][^\n#]*?)[ \t]*$"
)
_IDENT_RE = re.compile(r"^[^\W\d]\w*$", re.UNICODE)


def _module_methods(source: SourceFile) -> set[str]:
    """Имена методов и конструкторов, объявленных в модуле."""
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


@rule(
    "form/unknown-handler", "Обработчик формы не найден в модуле", "D",
    scope="project", severity=Severity.WARNING,
)
def unknown_handler(sources: list[SourceFile]) -> Iterable[Diagnostic]:
    modules = {str(s.path): s for s in sources if s.kind == "xbsl"}

    diags: list[Diagnostic] = []
    for s in sources:
        if s.kind != "yaml":
            continue
        module = modules.get(str(s.path.with_suffix(".xbsl")))
        if module is None:
            continue  # нет парного модуля – резолвить обработчики не из чего
        methods = _module_methods(module)
        lm = linemap(s)
        for m in _HANDLER_RE.finditer(s.text):
            name = m.group(1).strip()
            if not _IDENT_RE.match(name):
                continue  # FQN-ссылка на внешний модуль или не-идентификатор – не судим
            if name not in methods:
                line, col = lm.linecol(m.start(1))
                diags.append(Diagnostic(
                    s.rel, line, col, "form/unknown-handler", Severity.WARNING,
                    f"Обработчик '{name}' не найден как метод в модуле формы "
                    f"'{s.path.with_suffix('.xbsl').name}'.",
                ))
    return diags
