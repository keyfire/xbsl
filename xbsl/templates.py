"""Code templates: an EDT-compatible store, expanded into editor snippets.

A template is a short trigger plus a code pattern; the editor offers it on Ctrl+Space ahead of
the other completions, and inserting it drops a ready construct with edit points at the cursor.
This mirrors the 1C:EDT template mechanism (Параметры - Шаблоны), the file format included -
it is a shape proven in practice, and it makes the mechanism familiar to whoever used EDT.

The templates themselves are ours: an EDT dump carries BSL code (`Если ... Тогда ...
КонецЕсли`), which XBSL does not compile, so such a file is rejected by its contexts rather
than imported into something that would silently insert broken code.

The store is a JSON envelope:

    {"templates": [{"type": "xbsl.template",
                    "name": "мет[од] - Метод",
                    "description": "/Стандартные/Объявления/Метод",
                    "context": {"moduleEnvironments": [...], "moduleContexts": [...]},
                    "pattern": "метод ${Редактировать(\"Имя\")}()\\n    ${Редактировать(\"\")}\\n;",
                    "isAutoinsertable": false}]}

`name` is `<trigger> - <title>`, where the trigger may carry an optional tail in brackets -
`мет[од]` means "мет" is enough to type. Without " - " the whole name is both trigger and title.

`pattern` holds the code with variables (the EDT set, minus what BSL has and XBSL does not):

    ${Редактировать("подсказка")}          an edit point, a placeholder in snippet terms
    ${Выбрать("а", "б")}                   a choice between fixed variants
    ${ИмяОбъектаМетаданного(Справочник)}   a choice over the objects of that kind in the project
    ${ПолноеИмяОбъектаМетаданного("...")}  the same, inserted as <Вид>.<Имя>

`expand()` turns a pattern into an LSP snippet: variables become numbered tab stops, and the
literal text around them is escaped, which matters here - `$` is string interpolation in XBSL
and `{}` are collection literals, so unescaped code would be read as snippet syntax.

Objects of the project are supplied by a resolver, so the core stays free of the index: the LSP
server passes a lookup-backed one, the CLI passes none and the variable degrades to a plain edit
point with the kind as its text.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Iterator, Optional, Sequence

from xbsl import i18n

TEMPLATE_TYPE = "xbsl.template"

#: Where a template may be offered. XBSL has no "conditional compilation" or "invocation
#: params" context of its own, so this list is shorter than the BSL one of the same shape.
STATEMENT_CONTEXT = "STATEMENT_CONTEXT"      # inside a method body
DECLARATION_CONTEXT = "DECLARATION_CONTEXT"  # at module level: methods, structures, enums
QUERY_CONTEXT = "QUERY_CONTEXT"              # inside a Запрос{...} block
CONTEXTS = (STATEMENT_CONTEXT, DECLARATION_CONTEXT, QUERY_CONTEXT)

#: Where the code runs. A template that only makes sense on one side says so; most say both.
SERVER_ENVIRONMENT = "SERVER_ENVIRONMENT"
CLIENT_ENVIRONMENT = "CLIENT_ENVIRONMENT"
ENVIRONMENTS = (SERVER_ENVIRONMENT, CLIENT_ENVIRONMENT)


MESSAGES = {
    "templates.bad-json": {
        "ru": "Файл шаблонов '{path}' не читается как JSON: {error}",
        "en": "The template file '{path}' does not read as JSON: {error}",
    },
    "templates.bad-envelope": {
        "ru": "В файле шаблонов '{path}' нет списка 'templates'",
        "en": "The template file '{path}' has no 'templates' list",
    },
    "templates.bad-item": {
        "ru": "Шаблон №{index} в '{path}': {error}",
        "en": "Template #{index} in '{path}': {error}",
    },
    "templates.no-name": {
        "ru": "не задано имя ('name')",
        "en": "no name ('name') given",
    },
    "templates.no-pattern": {
        "ru": "не задан текст шаблона ('pattern')",
        "en": "no template text ('pattern') given",
    },
    "templates.bad-context": {
        "ru": "неизвестный контекст '{value}'; допустимы: {allowed}",
        "en": "unknown context '{value}'; allowed: {allowed}",
    },
    "templates.bad-environment": {
        "ru": "неизвестное окружение '{value}'; допустимы: {allowed}",
        "en": "unknown environment '{value}'; allowed: {allowed}",
    },
    "templates.duplicate-trigger": {
        "ru": "Шаблон '{name}' повторяет аббревиатуру шаблона '{other}'",
        "en": "Template '{name}' repeats the trigger of template '{other}'",
    },
}
i18n.register(MESSAGES)


class TemplateError(RuntimeError):
    """A template file that cannot be read, or a template that cannot be understood."""


# `мет[од] - Метод` -> trigger `мет` + optional tail `од`, title `Метод`. The separator is
# " - " with spaces: a title itself may hold a dash (`Метод - с параметрами`), the first
# separator wins, and a name without one is a trigger that needs no shortening (`Возврат`).
_NAME_RE = re.compile(r"^\s*(?P<head>[^\[]*?)\s*(?:\[(?P<tail>[^\]]*)\])?\s*(?: - (?P<title>.*))?$")


@dataclass(frozen=True)
class Template:
    """One template: how it is typed, where it is offered, and what it inserts."""

    name: str
    pattern: str
    description: str = ""
    contexts: tuple[str, ...] = CONTEXTS
    environments: tuple[str, ...] = ENVIRONMENTS
    autoinsertable: bool = False

    @property
    def _parts(self) -> tuple[str, str, str]:
        m = _NAME_RE.match(self.name)
        if not m:  # pragma: no cover - the regex matches any string
            return self.name, "", self.name
        head = (m.group("head") or "").strip()
        tail = (m.group("tail") or "").strip()
        title = (m.group("title") or "").strip()
        return head, tail, title or (head + tail)

    @property
    def prefix(self) -> str:
        """The shortest text that has to be typed: `мет` of `мет[од]`."""
        return self._parts[0]

    @property
    def trigger(self) -> str:
        """The full trigger with the optional tail: `метод` of `мет[од]`."""
        head, tail, _ = self._parts
        return head + tail

    @property
    def title(self) -> str:
        """The human-readable half of the name: `Метод` of `мет[од] - Метод`."""
        return self._parts[2]

    @property
    def category(self) -> str:
        """The tree path of `description`, without the leaf: `/Стандартные/Управляющие`."""
        parts = [p for p in self.description.split("/") if p]
        return "/" + "/".join(parts[:-1]) if len(parts) > 1 else ""

    def matches(self, typed: str) -> bool:
        """Does `typed` reach this template? Case-insensitively, as the editor filters."""
        return bool(typed) and self.trigger.lower().startswith(typed.lower())

    def offered_in(self, contexts: Iterable[str]) -> bool:
        """Is any of these contexts one the template declares?"""
        return any(c in self.contexts for c in contexts)

    def to_dict(self) -> dict:
        """The EDT-shaped record, ready to be dumped."""
        return {
            "type": TEMPLATE_TYPE,
            "name": self.name,
            "description": self.description,
            "context": {
                "moduleEnvironments": list(self.environments),
                "moduleContexts": list(self.contexts),
            },
            "pattern": self.pattern,
            "isAutoinsertable": self.autoinsertable,
        }


# ---------------------------------------------------------------------------- variables

#: A variable opens with `${Имя(` and closes with `)}`; the arguments are scanned by hand
#: rather than by a regex, because an argument may itself hold brackets and quotes -
#: `${Редактировать("Массив(0)")}` has to survive.
_VAR_START = re.compile(r"\$\{(?P<name>[A-Za-zА-Яа-яЁё_][A-Za-zА-Яа-яЁё0-9_]*)\(")

EDIT_VAR = "Редактировать"
CHOICE_VAR = "Выбрать"
OBJECT_NAME_VAR = "ИмяОбъектаМетаданного"
OBJECT_FULL_NAME_VAR = "ПолноеИмяОбъектаМетаданного"

#: (variable, argument) -> the variants to choose from. Returning an empty list means "the
#: project has none / there is no index", and the variable falls back to an edit point.
Resolver = Callable[[str, str], Sequence[str]]


@dataclass(frozen=True)
class Variable:
    """A `${Имя(аргументы)}` occurrence: its name, its raw arguments and its span."""

    name: str
    args: tuple[str, ...]
    start: int
    end: int


def _split_args(raw: str) -> tuple[str, ...]:
    """`"а", "б"` -> ("а", "б"); a bare word stays as it is: `Справочник` -> ("Справочник",).

    A quoted argument keeps its spaces ("Имя метода"), an unquoted one is stripped: the
    separating spaces of `"а", "б"` belong to the syntax, not to the second variant.
    """
    args: list[str] = []
    buf: list[str] = []
    quoted = False    # this argument was given in quotes - keep it verbatim
    in_quotes = False
    i = 0
    while i < len(raw):
        ch = raw[i]
        if in_quotes:
            if ch == '"':
                if raw[i + 1:i + 2] == '"':  # "" inside a quoted argument is one quote
                    buf.append('"')
                    i += 2
                    continue
                in_quotes = False
            else:
                buf.append(ch)
        elif ch == '"':
            in_quotes = True
            quoted = True
            buf = []  # spaces ahead of the quote are syntax
        elif ch == ",":
            args.append("".join(buf) if quoted else "".join(buf).strip())
            buf, quoted = [], False
        elif quoted and ch.isspace():
            pass  # spaces after the closing quote are syntax too
        else:
            buf.append(ch)
        i += 1
    tail = "".join(buf) if quoted else "".join(buf).strip()
    args.append(tail)
    # `${Редактировать()}` - no arguments at all, not one empty argument.
    if len(args) == 1 and not quoted and not args[0]:
        return ()
    return tuple(args)


def parse_variables(pattern: str) -> list[Variable]:
    """Every `${Имя(...)}` of the pattern, in order of appearance."""
    found: list[Variable] = []
    pos = 0
    while True:
        m = _VAR_START.search(pattern, pos)
        if not m:
            return found
        i = m.end()
        depth, in_quotes = 1, False
        while i < len(pattern):
            ch = pattern[i]
            if in_quotes:
                if ch == '"':
                    in_quotes = pattern[i + 1:i + 2] == '"'
                    i += 1 if not in_quotes else 2
                    continue
            elif ch == '"':
                in_quotes = True
            elif ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        # An unbalanced `${Имя(` is not a variable - leave it as literal text.
        if i >= len(pattern) or pattern[i:i + 2] != ")}":
            pos = m.end()
            continue
        found.append(Variable(
            name=m.group("name"),
            args=_split_args(pattern[m.end():i]),
            start=m.start(),
            end=i + 2,
        ))
        pos = i + 2


# ---------------------------------------------------------------------------- expansion

def escape_snippet(text: str) -> str:
    r"""Escape literal text for an LSP snippet.

    `$` is interpolation in XBSL strings ("Здравствуйте, $Имя") and `}` closes collection
    literals - both are snippet syntax and would be swallowed on insert.
    """
    return text.replace("\\", "\\\\").replace("$", "\\$").replace("}", "\\}")


def _escape_choice(text: str) -> str:
    """Inside `${1|а,б|}` a comma and a pipe separate the variants, so they escape too."""
    return escape_snippet(text).replace(",", "\\,").replace("|", "\\|")


def _choice(stop: int, variants: Sequence[str]) -> str:
    return "${%d|%s|}" % (stop, ",".join(_escape_choice(v) for v in variants))


def _placeholder(stop: int, text: str) -> str:
    return "${%d:%s}" % (stop, escape_snippet(text)) if text else "${%d}" % stop


def expand(pattern: str, resolver: Optional[Resolver] = None) -> str:
    """Compile a pattern into an LSP snippet: variables to tab stops, the rest escaped.

    Tab stops are numbered by appearance. An unknown variable becomes an edit point named
    after itself, so a template written for a newer version still inserts readable code.
    """
    out: list[str] = []
    stop = 0
    pos = 0
    for var in parse_variables(pattern):
        out.append(escape_snippet(pattern[pos:var.start]))
        pos = var.end
        stop += 1
        out.append(_expand_variable(var, stop, resolver))
    out.append(escape_snippet(pattern[pos:]))
    return "".join(out)


def _expand_variable(var: Variable, stop: int, resolver: Optional[Resolver]) -> str:
    if var.name == EDIT_VAR:
        return _placeholder(stop, var.args[0] if var.args else "")
    if var.name == CHOICE_VAR:
        variants = [a for a in var.args if a]
        return _choice(stop, variants) if variants else _placeholder(stop, "")
    if var.name in (OBJECT_NAME_VAR, OBJECT_FULL_NAME_VAR):
        kind = var.args[0] if var.args else ""
        variants = list(resolver(var.name, kind)) if resolver else []
        # No index, or the project has no such objects: an edit point prompting for the kind
        # beats a choice with nothing to choose - the latter cannot be typed into at all.
        return _choice(stop, variants) if variants else _placeholder(stop, kind)
    return _placeholder(stop, var.name)


def preview(pattern: str) -> str:
    """The pattern as plain code: variables shown by their prompt, for a list or a tooltip."""
    out: list[str] = []
    pos = 0
    for var in parse_variables(pattern):
        out.append(pattern[pos:var.start])
        pos = var.end
        if var.name == EDIT_VAR:
            out.append(var.args[0] if var.args else "")
        elif var.args:
            out.append(var.args[0])
        else:
            out.append(var.name)
    out.append(pattern[pos:])
    return "".join(out)


# ---------------------------------------------------------------------------- the store

def _normalize(
    values: object,
    allowed: tuple[str, ...],
    fail: Callable[[str], Exception],
) -> tuple[str, ...]:
    """The declared values, deduplicated. An empty or absent list means "everywhere"."""
    if not isinstance(values, list) or not values:
        return allowed
    out: list[str] = []
    for value in values:
        if value not in allowed:
            raise fail(str(value))
        if value not in out:
            out.append(str(value))
    return tuple(out)


def _as_template(item: dict, path: str, index: int) -> Template:
    def fail(key: str, **fields) -> TemplateError:
        return TemplateError(i18n.t(
            "templates.bad-item", index=index + 1, path=path, error=i18n.t(key, **fields),
        ))

    name = (item.get("name") or "").strip()
    if not name:
        raise fail("templates.no-name")
    pattern = item.get("pattern")
    if not pattern:
        raise fail("templates.no-pattern")
    ctx = item.get("context") or {}
    contexts = _normalize(
        ctx.get("moduleContexts"), CONTEXTS,
        lambda v: fail("templates.bad-context", value=v, allowed=", ".join(CONTEXTS)),
    )
    environments = _normalize(
        ctx.get("moduleEnvironments"), ENVIRONMENTS,
        lambda v: fail("templates.bad-environment", value=v, allowed=", ".join(ENVIRONMENTS)),
    )
    return Template(
        name=name,
        pattern=str(pattern),
        description=str(item.get("description") or ""),
        contexts=contexts,
        environments=environments,
        autoinsertable=bool(item.get("isAutoinsertable")),
    )


def loads(text: str, *, path: str = "<текст>") -> list[Template]:
    """Read the envelope. Accepts our own dump and an EDT one (the type is ignored)."""
    try:
        data = json.loads(text)
    except ValueError as e:
        raise TemplateError(i18n.t("templates.bad-json", path=path, error=e)) from e
    items = data.get("templates") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise TemplateError(i18n.t("templates.bad-envelope", path=path))
    return [_as_template(x, path, i) for i, x in enumerate(items) if isinstance(x, dict)]


def load_file(path: Path) -> list[Template]:
    return loads(path.read_text(encoding="utf-8"), path=str(path))


def dumps(templates: Iterable[Template]) -> str:
    """The envelope as text, shaped like an EDT dump (which is one line of JSON)."""
    return json.dumps({"templates": [t.to_dict() for t in templates]}, ensure_ascii=False)


def load_builtin() -> list[Template]:
    """The templates shipped with the toolkit (xbsl/templates_builtin.py)."""
    from xbsl.templates_builtin import BUILTIN

    return list(BUILTIN)


def merge(builtin: Iterable[Template], custom: Iterable[Template]) -> list[Template]:
    """Custom templates win over builtin ones with the same name; the rest are appended."""
    result = {t.name: t for t in builtin}
    for t in custom:
        result[t.name] = t
    return list(result.values())


#: Outside a query both are possible: telling "inside a method body" from "at module level"
#: needs a parse of half-typed code, and guessing it wrong would hide the template the author
#: is reaching for. EDT does not narrow this either - its templates are all offered everywhere.
CODE_CONTEXTS = (STATEMENT_CONTEXT, DECLARATION_CONTEXT)


def offered(
    templates: Iterable[Template],
    *,
    typed: str = "",
    contexts: Iterable[str] = CODE_CONTEXTS,
) -> Iterator[Template]:
    """The templates the editor should show here.

    `typed` is optional: an editor filters the returned list by the typed prefix on its own,
    and a caller that does not (a CLI listing, a test) passes it to get the same choice.
    """
    contexts = tuple(contexts)
    for t in templates:
        if not t.offered_in(contexts):
            continue
        if typed and not t.matches(typed):
            continue
        yield t
