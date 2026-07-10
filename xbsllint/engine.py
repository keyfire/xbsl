"""Ядро линтера: загрузка исходников, реестр правил и их запуск.

Правила регистрируются декоратором @rule(...) с метаданными (id, тир, severity, scope).
Область (scope):
- 'file'    – пофайловое правило: (SourceFile) -> Iterable[Diagnostic];
- 'project' – кросс-файловое (напр. уникальность Ид): (list[SourceFile]) -> Iterable[Diagnostic].

Тиры: 'A' структура/YAML, 'B' текст/конвенции, 'C' парсер/структура кода, 'D' семантика.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

from xbsllint.diagnostics import Diagnostic, Severity

UTF8_BOM = b"\xef\xbb\xbf"


@dataclass
class SourceFile:
    path: Path
    kind: str  # 'xbsl' | 'yaml'
    data: bytes
    text: str
    had_bom: bool
    newline: str  # '\n', '\r\n', '\r', 'mixed' или '' если переводов строк нет
    decode_error: str | None = None
    # Кэш тяжёлых представлений (токены, AST, YAML) – заполняется по требованию
    cache: dict = field(default_factory=dict)

    @property
    def rel(self) -> str:
        return str(self.path)


def _detect_newline(data: bytes) -> str:
    crlf = data.count(b"\r\n")
    cr = data.count(b"\r") - crlf
    lf = data.count(b"\n") - crlf
    kinds = [k for k, n in (("\r\n", crlf), ("\r", cr), ("\n", lf)) if n]
    if not kinds:
        return ""
    if len(kinds) > 1:
        return "mixed"
    return kinds[0]


def make_source(path: Path, data: bytes) -> SourceFile:
    """Собрать SourceFile из пути и байтов (общий код для диска и памяти)."""
    kind = "xbsl" if path.suffix == ".xbsl" else "yaml"
    had_bom = data.startswith(UTF8_BOM)
    decode_error: str | None = None
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        decode_error = str(exc)
        text = data.decode("utf-8", errors="replace")
    return SourceFile(
        path=path,
        kind=kind,
        data=data,
        text=text,
        had_bom=had_bom,
        newline=_detect_newline(data),
        decode_error=decode_error,
    )


def load(path: Path) -> SourceFile:
    return make_source(path, path.read_bytes())


def load_text(name: str, content: str) -> SourceFile:
    """Собрать SourceFile из содержимого в памяти (для MCP lint_source)."""
    return make_source(Path(name), content.encode("utf-8"))


# --- Реестр правил -------------------------------------------------------------------

FileRuleFn = Callable[[SourceFile], Iterable[Diagnostic]]
ProjectRuleFn = Callable[[list[SourceFile]], Iterable[Diagnostic]]


@dataclass(frozen=True)
class RuleInfo:
    id: str
    title: str
    tier: str  # 'A' | 'B' | 'C' | 'D'
    scope: str  # 'file' | 'project'
    severity: Severity
    func: Callable
    enabled_by_default: bool = True

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "tier": self.tier,
            "scope": self.scope,
            "severity": self.severity.value,
            "enabled_by_default": self.enabled_by_default,
        }


RULES: list[RuleInfo] = []


def rule(
    rule_id: str,
    title: str,
    tier: str,
    *,
    scope: str = "file",
    severity: Severity = Severity.WARNING,
    enabled_by_default: bool = True,
) -> Callable[[Callable], Callable]:
    """Декоратор регистрации правила с метаданными."""

    def deco(fn: Callable) -> Callable:
        RULES.append(RuleInfo(rule_id, title, tier, scope, severity, fn, enabled_by_default))
        return fn

    return deco


def _is_selected(info: RuleInfo, select: set[str] | None, ignore: set[str] | None) -> bool:
    # select/ignore сопоставляются по id правила, по группе (часть id до '/')
    # или по букве тира ('A'..'D')
    group = info.id.split("/", 1)[0]

    def matches(keys: set[str]) -> bool:
        return info.id in keys or group in keys or info.tier in keys

    if ignore and matches(ignore):
        return False
    if select:
        # Явный выбор включает правило, даже если оно выключено по умолчанию
        return matches(select)
    return info.enabled_by_default


def active_rules(select: set[str] | None = None, ignore: set[str] | None = None) -> list[RuleInfo]:
    return [r for r in RULES if _is_selected(r, select, ignore)]


def run_sources(
    sources: list[SourceFile],
    *,
    select: set[str] | None = None,
    ignore: set[str] | None = None,
    scopes: tuple[str, ...] = ("file", "project"),
) -> list[Diagnostic]:
    diags: list[Diagnostic] = []
    active = active_rules(select, ignore)
    if "file" in scopes:
        file_rules = [r for r in active if r.scope == "file"]
        for src in sources:
            for r in file_rules:
                diags.extend(r.func(src))
    if "project" in scopes:
        for r in (r for r in active if r.scope == "project"):
            diags.extend(r.func(sources))
    return diags


def run(
    paths: list[Path],
    *,
    select: set[str] | None = None,
    ignore: set[str] | None = None,
) -> list[Diagnostic]:
    sources = [load(p) for p in paths]
    return run_sources(sources, select=select, ignore=ignore)


# Импорт пакета правил регистрирует их (декораторы выполняются при импорте модулей).
from xbsllint import rules as _rules  # noqa: E402,F401
from xbsllint import plugins as _plugins  # noqa: E402

# Правила внешних пакетов – после встроенных, чтобы порядок реестра был предсказуем.
_plugins.load_rules()
