"""Tier D: a module constant read by a method compiled for an environment it does not exist in.

The code/constant-unavailable rule. A constant, like a method or a structure, exists in the
environment of its module unless environment annotations name its own (docs
topics/module-execution: the environment "for a method, a structure, an exception, an
enumeration, a constant can be set explicitly"). The module of an interface component or a
command lives in `Client`, so a constant declared there without an annotation is a client
name, and a method annotated `@OnServer` in the same module is compiled where that name does
not exist. The apply refuses the project with `<Server> Variable "X" is not defined` and the
application rolls back - after every rule of the linter had said nothing.

The verdict comes from the compiler, not from a reading of the page: one probe project held
every combination of a component, a command and a common module with `Environment:
ClientAndServer`, each module with a control name that certainly does not exist. The environment
of a constant is its annotations - `@OnServer`, `@OnClient` or both - or else the environment of
the module, and a method is compiled for the environments its own annotations name, or else the
module's: `@OnServer` (with `@AvailableFromClient`, with `@Contextual`, or alone) is the server,
an unannotated method of a module of both environments is compiled for both, and so is a method
carrying both annotations. Every reference whose method is compiled for a side the constant
lacks was refused - a bare name, a name inside a lambda and the short interpolation `%NAME` of
a string alike - and every other one compiled, the mirror included: a constant declared
`@OnServer` in a component module, read by an unannotated (client) method, got
`<Client> Variable "X" is not defined`.

Judged are the modules whose environment the pair settles and where both annotations are
legal: the client kinds of the documentation table (an interface component, the commands, a
storable structure) and a common module, a structure or an enumeration of both environments. A
module of the server alone never meets the case, and a common module of the client alone
refuses `@OnServer` by itself (code/server-annotation-in-client-module says so). The
environment is read from the yaml beside the module on the disk, the way
code/unknown-form-component reads its markup: the check then stays a file rule, answering on
every keystroke of the module it is about. A name a method declares for itself (a parameter, a
local, a loop or catch variable, a lambda parameter) hides the constant in that whole method,
and a module that does not parse is not judged.

The fix gives the constant the side it lacks, never taking one away: an unannotated constant of
a client module gets `@OnServer @OnClient` on a line of its own (`@OnServer` alone would take
it off the client, where other code may read it), and an annotated one gets the missing
annotation beside the one it has. A constant misses at most one side, so every finding of one
constant carries the same edit.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path

from xbsl import dataset, i18n, terms
from xbsl import parser as P
from xbsl.diagnostics import Diagnostic, Severity, TextEdit
from xbsl.engine import SourceFile, is_query_file, make_source, rule
from xbsl.lexer import linemap
from xbsl.parser import parse
from xbsl.rules._syntax import code_tokens
from xbsl.rules.environment import (
    _CLIENT_ENV_KINDS,
    _both_env_forms,
    _on_client_forms,
    _on_server_forms,
    _parsed_object,
)
from xbsl.rules.undefined_names import _interpolations
from xbsl.rules.yaml_imports import _interpolation_bodies
from xbsl.rules.yaml_schema import _HAVE_YAML, object_kind, value_of
from xbsl.typeinfer import _method_names, walk_nodes

RULE = "code/constant-unavailable"

MESSAGES = {
    f"{RULE}.title": {
        "ru": "Константа модуля вне своего окружения",
        "en": "A module constant outside its environment",
    },
    f"{RULE}.module-client": {
        "ru": "Константа '{name}' объявлена без аннотации окружения и существует там же, где "
              "модуль, – на клиенте, а метод '{method}' компилируется для сервера: применение "
              "отвечает \"Переменная {name} не определена\". Поставьте константе {annotations}: "
              "так она будет и на сервере, и на клиенте.",
        "en": "Constant '{name}' carries no environment annotation and exists where its module "
              "does, on the client, while method '{method}' is compiled for the server: the "
              "apply answers \"Variable {name} is not defined\". Annotate the constant "
              "{annotations}, and it exists on both the server and the client.",
    },
    f"{RULE}.client-only": {
        "ru": "Константа '{name}' объявлена @НаКлиенте, а метод '{method}' компилируется для "
              "сервера: применение отвечает \"Переменная {name} не определена\". Добавьте "
              "константе {annotations}.",
        "en": "Constant '{name}' is declared @{n[НаКлиенте]}, while method '{method}' is "
              "compiled for the server: the apply answers \"Variable {name} is not defined\". "
              "Add {annotations} to the constant.",
    },
    f"{RULE}.server-only": {
        "ru": "Константа '{name}' объявлена @НаСервере, а метод '{method}' компилируется для "
              "клиента: применение отвечает \"Переменная {name} не определена\". Добавьте "
              "константе {annotations}.",
        "en": "Constant '{name}' is declared @{n[НаСервере]}, while method '{method}' is "
              "compiled for the client: the apply answers \"Variable {name} is not defined\". "
              "Add {annotations} to the constant.",
    },
}
i18n.register(MESSAGES)

_SERVER, _CLIENT = "server", "client"
_BOTH = frozenset({_SERVER, _CLIENT})
#: The kind of an element whose module belongs to both environments by the documentation table.
_ENUM_KIND = "Перечисление"
#: The kinds whose module takes its environment from the `Environment` of the element.
_OWN_ENVIRONMENT_KINDS = ("ОбщийМодуль", "Структура")
#: The declaring keyword in either spelling: the cheap gate before the pair and the parse.
_CONST_WORD_RE = re.compile(r"(?<![\w])(?:конст|const)(?![\w])")
#: A name of a full interpolation that is a root: no dot and no namespace before it.
_ROOT_WORD_RE = re.compile(r"(?<![\w.:$%&])([^\W\d]\w*)(?!\s*::)")


@lru_cache(maxsize=1)
def _annotation_forms() -> tuple[frozenset[str], frozenset[str]]:
    """Both spellings of the server and of the client annotation."""
    return _on_server_forms(), _on_client_forms()


dataset.register_reset(_annotation_forms.cache_clear)


def _module_sides(pair: Path) -> frozenset[str] | None:
    """The environments the module of the element described by `pair` exists in, or None when
    the rule does not judge that module (see the module docstring)."""
    try:
        if not pair.is_file():
            return None
        source = make_source(pair, pair.read_bytes())
    except OSError:
        return None
    data = _parsed_object(source)
    if data is None:
        return None
    kind = object_kind(data)
    if kind in _CLIENT_ENV_KINDS:
        return frozenset({_CLIENT})
    if kind == _ENUM_KIND:
        return _BOTH
    if kind in _OWN_ENVIRONMENT_KINDS and value_of(data, "Окружение", kind) in _both_env_forms():
        return _BOTH
    return None


def _sides(annotations: list[P.Annotation], default: frozenset[str]) -> frozenset[str]:
    """The environments a declaration exists in: its own annotations, else the module's."""
    server_forms, client_forms = _annotation_forms()
    names = {annotation.name for annotation in annotations}
    on_server, on_client = bool(names & server_forms), bool(names & client_forms)
    if not on_server and not on_client:
        return default
    return frozenset(side for side, on in ((_SERVER, on_server), (_CLIENT, on_client)) if on)


def _uses(nodes: list, names: frozenset[str]) -> list[tuple[int, str]]:
    """(offset, name) of every read of one of `names` among the nodes of a method body.

    A bare name, and a name inside a string: the short interpolation `%NAME` (the compiler
    points at the name, one past the sign) and a root word of the full one, `%{...}`.
    """
    found: list[tuple[int, str]] = []
    for node in nodes:
        if isinstance(node, P.Name):
            if node.name in names:
                found.append((node.start, node.name))
        elif isinstance(node, P.Literal) and node.kind == "STRING":
            for offset, _sign, name in _interpolations(node.text):
                if name in names:
                    found.append((node.start + offset + 1, name))
            for offset, body in _interpolation_bodies(node.text):
                for match in _ROOT_WORD_RE.finditer(body):
                    if match.group(1) in names:
                        found.append((node.start + offset + match.start(1), match.group(1)))
    return sorted(found)


def _spelled(forms: frozenset[str], english: bool) -> str:
    """The spelling of an annotation for a file of that language."""
    ordered = sorted(forms, key=lambda form: form.isascii() != english)
    return ordered[0]


def _fix(source: SourceFile, member: P.ObjectField, missing: str) -> TextEdit | None:
    """The edit that gives the constant the side it lacks, keeping the one it has.

    The edit replaces a span rather than inserting at a point: every finding of the constant
    carries the same one, and the fixer keeps a single edit of a span while two insertions at
    one point would both be applied.
    """
    server_forms, client_forms = _annotation_forms()
    keyword = next((token for token in code_tokens(source)
                    if member.start <= token.start < member.end and token.canonical == "CONST"),
                   None)
    if keyword is None:
        return None
    english = keyword.value.isascii()
    environment = [annotation for annotation in member.annotations
                   if annotation.name in server_forms or annotation.name in client_forms]
    if environment:
        last = environment[-1]
        added = _spelled(server_forms if missing == _SERVER else client_forms, english)
        return TextEdit(last.start, last.end, f"{source.text[last.start:last.end]} @{added}")
    both = f"@{_spelled(server_forms, english)} @{_spelled(client_forms, english)}"
    text = source.text
    line_start = text.rfind("\n", 0, keyword.start) + 1
    indent = text[line_start:keyword.start]
    if indent.strip():
        # Something else stands before the keyword on its line (another annotation): the pair
        # goes there too.
        return TextEdit(keyword.start, keyword.end, f"{both} {keyword.value}")
    newline = "\r\n" if source.newline == "\r\n" else "\n"
    return TextEdit(keyword.start, keyword.end, f"{both}{newline}{indent}{keyword.value}")


def _shown(missing: str, annotated: bool) -> str:
    """The annotations the message names, in the language of the message."""
    english = i18n.current_lang() == "en"
    server_forms, client_forms = _annotation_forms()
    if not annotated:
        return f"@{_spelled(server_forms, english)} @{_spelled(client_forms, english)}"
    return "@" + _spelled(server_forms if missing == _SERVER else client_forms, english)


@rule(RULE, f"{RULE}.title", "D", severity=Severity.ERROR)
def constant_unavailable(source: SourceFile) -> Iterable[Diagnostic]:
    """A module constant read by a method compiled for a side the constant lacks."""
    if source.kind != "xbsl" or not _HAVE_YAML or is_query_file(Path(source.path)):
        return
    if not _CONST_WORD_RE.search(source.text):
        return
    module_sides = _module_sides(Path(source.path).with_suffix(".yaml"))
    if module_sides is None:
        return
    module, errors = parse(source)
    if errors:
        return
    constants: dict[str, tuple[P.ObjectField, frozenset[str]]] = {}
    for member in module.members:
        if isinstance(member, P.ObjectField) and member.kind == "CONST":
            constants[member.name] = (member, _sides(member.annotations, module_sides))
    if not constants:
        return
    lines = linemap(source)
    environment_forms = _annotation_forms()[0] | _annotation_forms()[1]
    fixes: dict[str, TextEdit | None] = {}
    for method in module.members:
        if not isinstance(method, P.Method):
            continue
        method_sides = _sides(method.annotations, module_sides)
        nodes = walk_nodes(method.body)
        visible = frozenset(constants) - _method_names(method, nodes)
        for offset, name in _uses(nodes, visible):
            member, constant_sides = constants[name]
            lacking = method_sides - constant_sides
            if not lacking:
                continue
            # A constant lacks one side at most: it exists on the other one.
            missing = _SERVER if _SERVER in lacking else _CLIENT
            annotated = any(annotation.name in environment_forms
                            for annotation in member.annotations)
            if not annotated:
                key = f"{RULE}.module-client"
            elif missing == _SERVER:
                key = f"{RULE}.client-only"
            else:
                key = f"{RULE}.server-only"
            if name not in fixes:
                fixes[name] = _fix(source, member, missing)
            line, col = lines.linecol(offset)
            yield Diagnostic(
                source.rel, line, col, RULE, Severity.ERROR,
                i18n.t(key, name=name, method=method.name,
                       annotations=_shown(missing, annotated)),
                fix=fixes[name],
            )
