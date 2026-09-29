"""Tier D: a declaration of a module used by a method compiled for an environment it lacks.

Three rules share the reading of the environments: code/constant-unavailable for a constant,
code/module-type-unavailable for a structure, an exception and an enumeration of the same
module, and code/qualified-member-unavailable for those declarations reached from anywhere by
the qualified name of a common module.

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

The code/module-type-unavailable rule reads a structure, an exception and an enumeration the
same way: probe projects held them in a component, a command and a common module of both
environments. A method compiled for a side the type lacks was refused with `Type "X" is
unavailable in the current environment` wherever it named the type - a variable, a parameter,
a result, a constructor, `throw`, a catch clause, a type check, a generic argument, a lambda -
and with `Variable "X" is not defined` for an enumeration read as a value, in the code or as
the root word of a full interpolation. The fix is the one of a constant, offered only where
the whole declaration exists on both sides (see _widenable): a structure widened while a field
of it had a client-only type was refused at that field.

The code/qualified-member-unavailable rule is a project rule: the declaration lives in one
module, the use in another. A probe declared constants, structures and enumerations for one
side in a common module of both environments and reached them as `Module.NAME` from a server
common module, an HTTP service, a component, a command and the declaring module itself: a
constant or an enumeration read as a value got `Unknown property "Module.NAME"`, a type
position `Type "Module.Name" is unavailable in the current environment`, under the tag of the
side the declaration lacks. A declaration without a visibility annotation fails outside its
module on the visibility first, so only the open ones are judged there.
"""

from __future__ import annotations

import re
from bisect import bisect_left
from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path

from xbsl import dataset, i18n, terms
from xbsl import parser as P
from xbsl.diagnostics import Diagnostic, Severity, TextEdit
from xbsl.engine import SourceFile, is_query_file, make_source, rule
from xbsl.lexer import Token, linemap
from xbsl.parser import parse
from xbsl.rules._syntax import code_tokens
from xbsl.rules.environment import (
    _CLIENT_ENV_KINDS,
    _SERVER_ENV_KINDS,
    _both_env_forms,
    _environment_forms,
    _on_client_forms,
    _on_server_forms,
    _pair_stem,
    _parsed_object,
    _type_availability,
)
from xbsl.rules.undefined_names import _interpolations
from xbsl.rules.yaml_imports import _interpolation_bodies
from xbsl.rules.yaml_schema import _HAVE_YAML, element_own_names, object_kind, value_of
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


def _fix(source: SourceFile, member: P.ObjectField | P.Structure | P.Enum, missing: str,
         declaring: str = "CONST") -> TextEdit | None:
    """The edit that gives the declaration the side it lacks, keeping the one it has.

    `declaring` is the canonical keyword of the declaration: `CONST`, `STRUCTURE`, `EXCEPTION`
    or `ENUMERATION`. The edit replaces a span rather than inserting at a point: every finding
    of the declaration carries the same one, and the fixer keeps a single edit of a span while
    two insertions at one point would both be applied.
    """
    server_forms, client_forms = _annotation_forms()
    keyword = next((token for token in code_tokens(source)
                    if member.start <= token.start < member.end and token.canonical == declaring),
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


# --- A type of the module outside its environment ------------------------------------------

TYPE_RULE = "code/module-type-unavailable"

MESSAGES_TYPE = {
    f"{TYPE_RULE}.title": {
        "ru": "Тип модуля вне своего окружения",
        "en": "A module type outside its environment",
    },
    f"{TYPE_RULE}.module-client": {
        "ru": "Тип '{name}' объявлен без аннотации окружения и существует там же, где модуль, "
              "– на клиенте, а метод '{method}' компилируется для сервера: применение отвечает "
              "\"{answer}\". Поставьте типу {annotations}, и он будет и на сервере, и на "
              "клиенте, либо уберите обращение из серверного метода.",
        "en": "Type '{name}' carries no environment annotation and exists where its module "
              "does, on the client, while method '{method}' is compiled for the server: the "
              "apply answers \"{answer}\". Annotate the type {annotations} to have it on both "
              "the server and the client, or take the reference out of the server method.",
    },
    f"{TYPE_RULE}.client-only": {
        "ru": "Тип '{name}' объявлен @НаКлиенте, а метод '{method}' компилируется для сервера: "
              "применение отвечает \"{answer}\". Добавьте типу {annotations} либо уберите "
              "обращение из серверного кода.",
        "en": "Type '{name}' is declared @{n[НаКлиенте]}, while method '{method}' is compiled "
              "for the server: the apply answers \"{answer}\". Add {annotations} to the type, "
              "or take the reference out of the server code.",
    },
    f"{TYPE_RULE}.server-only": {
        "ru": "Тип '{name}' объявлен @НаСервере, а метод '{method}' компилируется для клиента: "
              "применение отвечает \"{answer}\". Добавьте типу {annotations} либо уберите "
              "обращение из клиентского кода.",
        "en": "Type '{name}' is declared @{n[НаСервере]}, while method '{method}' is compiled "
              "for the client: the apply answers \"{answer}\". Add {annotations} to the type, "
              "or take the reference out of the client code.",
    },
    f"{TYPE_RULE}.answer-type": {
        "ru": "Тип {name} недоступен в текущем окружении",
        "en": "Type {name} is unavailable in the current environment",
    },
    f"{TYPE_RULE}.answer-value": {
        "ru": "Переменная {name} не определена",
        "en": "Variable {name} is not defined",
    },
}
i18n.register(MESSAGES_TYPE)

#: The declaring keyword of a type in either spelling: the cheap gate before the pair and the
#: parse.
_TYPE_WORD_RE = re.compile(r"(?<![\w])(?:структура|исключение|перечисление|structure|exception"
                           r"|enum)(?![\w])")
#: The environment of a standard type that exists on both sides, as the type pages print it.
_BOTH_AVAILABILITY = "КлиентИСервер"
#: The literal kinds a field may start with and still exist on either side.
_PLAIN_LITERALS = ("NUMBER", "TRUE", "FALSE", "UNDEFINED")


def _declared_types(module: P.Module) -> dict[str, P.Structure | P.Enum]:
    """The structures, exceptions and enumerations the module declares, by name."""
    return {member.name: member for member in module.members
            if isinstance(member, (P.Structure, P.Enum))}


def _type_names(tref: P.TypeRef, toks: list[Token], starts: list[int]) -> list[Token]:
    """The root names of a type reference: every identifier not reached through `.` or `::`.

    The alternatives of a union and the arguments of a generic are read as well:
    `Массив<Строка>` gives both names.
    """
    low, high = bisect_left(starts, tref.start), bisect_left(starts, tref.end)
    names = []
    for i in range(low, high):
        token = toks[i]
        if token.kind != "IDENT":
            continue
        before = toks[i - 1] if i > low else None
        if before is not None and before.kind == "OP" and before.value in (".", "::"):
            continue
        names.append(token)
    return names


def _type_uses(nodes: list, toks: list[Token], starts: list[int], types: dict,
               hidden: frozenset[str]) -> list[tuple[int, str, str]]:
    """(offset, name, how) of every use of a type of the module among the nodes of a method.

    `how` is "type" for a type position - an annotation, a parameter or a result, a
    constructor, a catch clause, a type check, a generic argument - and "value" for the name
    of an enumeration read as a value (`Priority.High`, in the code or as the root word of a
    full interpolation `%{Priority.High}`): the compiler answers the first with `Type "X" is
    unavailable in the current environment` and the second with `Variable "X" is not
    defined`, each at the name. A name the method declares for itself hides an enumeration in
    a value position; a type position always means the type.
    """
    found: set[tuple[int, str, str]] = set()
    for node in nodes:
        if isinstance(node, P.TypeRef):
            for token in _type_names(node, toks, starts):
                if token.value in types:
                    found.add((token.start, token.value, "type"))
        elif isinstance(node, P.Name):
            if node.name not in hidden and isinstance(types.get(node.name), P.Enum):
                found.add((node.start, node.name, "value"))
        elif isinstance(node, P.Literal) and node.kind == "STRING":
            for offset, body in _interpolation_bodies(node.text):
                for match in _ROOT_WORD_RE.finditer(body):
                    name = match.group(1)
                    if name not in hidden and isinstance(types.get(name), P.Enum):
                        found.add((node.start + offset + match.start(1), name, "value"))
    return sorted(found)


def _plain_start(value: P.Expr | None) -> bool:
    """Whether a field starts with nothing, a literal or an empty collection."""
    if value is None:
        return True
    if isinstance(value, P.Unary) and value.op == "-":
        value = value.operand
    if isinstance(value, P.Literal):
        return value.kind in _PLAIN_LITERALS or (
            value.kind == "STRING" and "%" not in value.text and "$" not in value.text)
    if isinstance(value, P.ArrayLit):
        return not value.items
    if isinstance(value, P.MapLit):
        return not value.entries
    return False


def _widenable(declared: P.Structure | P.Enum, sides: dict[str, frozenset[str]],
               toks: list[Token], starts: list[int]) -> bool:
    """Whether the type takes both sides without breaking its own declaration.

    The quick fix only adds an annotation, so it is offered where the rest of the declaration
    exists on both sides as well: an enumeration without methods, and a structure or an
    exception whose every field has a type of both sides - a standard one whose page says
    `ClientAndServer`, or a type of the module that already has both - and starts with a
    literal or nothing. Anything else (a client-only field type, a project type, a call in
    an initializer) leaves the choice to a human.
    """
    if isinstance(declared, P.Enum):
        return not declared.methods
    availability = _type_availability()
    for member in declared.members:
        if not isinstance(member, P.ObjectField) or not _plain_start(member.init):
            return False
        if member.type is None:
            continue
        for token in _type_names(member.type, toks, starts):
            name = token.value
            if name == declared.name:
                continue
            if name in sides:
                if sides[name] != _BOTH:
                    return False
            elif availability.get(terms.russian(name, "types") or name) != _BOTH_AVAILABILITY:
                return False
    return True


def _declaring(declared: P.Structure | P.Enum) -> str:
    """The canonical keyword that declares the type."""
    return declared.kind if isinstance(declared, P.Structure) else "ENUMERATION"


@rule(TYPE_RULE, f"{TYPE_RULE}.title", "D", severity=Severity.ERROR)
def module_type_unavailable(source: SourceFile) -> Iterable[Diagnostic]:
    """A type the module declares, used by a method compiled for a side the type lacks."""
    if source.kind != "xbsl" or not _HAVE_YAML or is_query_file(Path(source.path)):
        return
    if not _TYPE_WORD_RE.search(source.text):
        return
    module_sides = _module_sides(Path(source.path).with_suffix(".yaml"))
    if module_sides is None:
        return
    module, errors = parse(source)
    if errors:
        return
    types = _declared_types(module)
    sides = {name: _sides(declared.annotations, module_sides) for name, declared in types.items()}
    one_side = {name: types[name] for name, where in sides.items() if where != _BOTH}
    if not one_side:
        return
    toks = code_tokens(source)
    starts = [token.start for token in toks]
    lines = linemap(source)
    environment_forms = _annotation_forms()[0] | _annotation_forms()[1]
    fixes: dict[str, TextEdit | None] = {}
    for method in module.members:
        if not isinstance(method, P.Method):
            continue
        method_sides = _sides(method.annotations, module_sides)
        hidden = _method_names(method, walk_nodes(method.body))
        nodes = walk_nodes([method.params, method.return_type, method.body])
        for offset, name, how in _type_uses(nodes, toks, starts, one_side, hidden):
            lacking = method_sides - sides[name]
            if not lacking:
                continue
            # A type lacks one side at most: it exists on the other one.
            missing = _SERVER if _SERVER in lacking else _CLIENT
            declared = one_side[name]
            annotated = any(annotation.name in environment_forms
                            for annotation in declared.annotations)
            if not annotated:
                key = f"{TYPE_RULE}.module-client"
            elif missing == _SERVER:
                key = f"{TYPE_RULE}.client-only"
            else:
                key = f"{TYPE_RULE}.server-only"
            if name not in fixes:
                fixes[name] = (_fix(source, declared, missing, _declaring(declared))
                               if _widenable(declared, sides, toks, starts) else None)
            answer = i18n.t(f"{TYPE_RULE}.answer-{how}", name=name)
            line, col = lines.linecol(offset)
            yield Diagnostic(
                source.rel, line, col, TYPE_RULE, Severity.ERROR,
                i18n.t(key, name=name, method=method.name, answer=answer,
                       annotations=_shown(missing, annotated)),
                fix=fixes[name],
            )


# --- A constant or a type of a common module reached by its qualified name -----------------

QUALIFIED_RULE = "code/qualified-member-unavailable"

MESSAGES_QUALIFIED = {
    f"{QUALIFIED_RULE}.title": {
        "ru": "Константа или тип общего модуля вне своего окружения",
        "en": "A constant or a type of a common module outside its environment",
    },
    f"{QUALIFIED_RULE}.on-server": {
        "ru": "'{name}' ({what}) есть только на клиенте: модуль '{module}' объявляет его "
              "@НаКлиенте, а метод '{method}' компилируется для сервера. Применение отвечает "
              "\"{answer}\". Добавьте объявлению @НаСервере либо уберите обращение из "
              "серверного кода.",
        "en": "'{name}' ({what}) exists on the client only: module '{module}' declares it "
              "@{n[НаКлиенте]}, while method '{method}' is compiled for the server. The apply "
              "answers \"{answer}\". Add @{n[НаСервере]} to the declaration, or take the "
              "reference out of the server code.",
    },
    f"{QUALIFIED_RULE}.on-client": {
        "ru": "'{name}' ({what}) есть только на сервере: модуль '{module}' объявляет его "
              "@НаСервере, а метод '{method}' компилируется для клиента. Применение отвечает "
              "\"{answer}\". Добавьте объявлению @НаКлиенте либо уберите обращение из "
              "клиентского кода.",
        "en": "'{name}' ({what}) exists on the server only: module '{module}' declares it "
              "@{n[НаСервере]}, while method '{method}' is compiled for the client. The apply "
              "answers \"{answer}\". Add @{n[НаКлиенте]} to the declaration, or take the "
              "reference out of the client code.",
    },
    f"{QUALIFIED_RULE}.what-CONST": {"ru": "константа", "en": "a constant"},
    f"{QUALIFIED_RULE}.what-STRUCTURE": {"ru": "структура", "en": "a structure"},
    f"{QUALIFIED_RULE}.what-EXCEPTION": {"ru": "исключение", "en": "an exception"},
    f"{QUALIFIED_RULE}.what-ENUMERATION": {"ru": "перечисление", "en": "an enumeration"},
    f"{QUALIFIED_RULE}.answer-member": {
        "ru": "Неизвестное свойство {name}",
        "en": "Unknown property {name}",
    },
    f"{QUALIFIED_RULE}.answer-type": {
        "ru": "Тип {name} недоступен в текущем окружении",
        "en": "Type {name} is unavailable in the current environment",
    },
}
i18n.register(MESSAGES_QUALIFIED)

#: The kinds a qualified name reaches as a value (`Module.NAME`, `Module.Enumeration.Item`)
#: and as a type (`Module.Structure` in a type position).
_VALUE_KINDS = frozenset({"CONST", "ENUMERATION"})
_TYPE_KINDS = frozenset({"STRUCTURE", "EXCEPTION", "ENUMERATION"})
#: `Root.Member` inside the code of a full interpolation.
_QUALIFIED_WORD_RE = re.compile(r"(?<![\w.:$%&])([^\W\d]\w*)\s*\.\s*([^\W\d]\w*)")


@lru_cache(maxsize=1)
def _visibility_forms() -> frozenset[str]:
    """Both spellings of the visibility annotations that open a declaration to other modules."""
    return frozenset(form for name in ("ВПодсистеме", "ВПроекте", "Глобально")
                     for form in terms.key_forms(name))


dataset.register_reset(_visibility_forms.cache_clear)


def _reading_sides(data: dict) -> frozenset[str] | None:
    """The environments the module of an element is compiled for, or None when the reading
    here does not settle it (the kinds the documentation table leaves out)."""
    kind = object_kind(data)
    if kind in _OWN_ENVIRONMENT_KINDS:
        value = value_of(data, "Окружение", kind)
        server_env, client_env = _environment_forms()
        if value in server_env:
            return frozenset({_SERVER})
        if value in client_env:
            return frozenset({_CLIENT})
        return _BOTH if value in _both_env_forms() else None
    if kind in _SERVER_ENV_KINDS:
        return frozenset({_SERVER})
    if kind in _CLIENT_ENV_KINDS:
        return frozenset({_CLIENT})
    return _BOTH if kind == _ENUM_KIND else None


def _one_side_members(module: P.Module) -> dict[str, list]:
    """{name: [kind, side, open]} of the declarations annotated for one side only.

    `open` tells whether a visibility annotation lets another module see the declaration: a
    local one reached from outside fails on its visibility first, and that is not this rule's
    finding.
    """
    visibility = _visibility_forms()
    members: dict[str, list] = {}
    for member in module.members:
        if isinstance(member, P.ObjectField) and member.kind == "CONST":
            kind = "CONST"
        elif isinstance(member, P.Structure):
            kind = member.kind
        elif isinstance(member, P.Enum):
            kind = "ENUMERATION"
        else:
            continue
        sides = _sides(member.annotations, frozenset())
        if len(sides) != 1:
            continue
        opened = any(annotation.name in visibility for annotation in member.annotations)
        members[member.name] = [kind, next(iter(sides)), opened]
    return members


def _qualified_uses(source: SourceFile, method: P.Method, toks: list[Token], starts: list[int],
                    hidden: frozenset[str]) -> list[tuple[str, str, str, int]]:
    """(root, member, how, offset) of every `Root.Member` of a method whose root is a bare
    name the method does not hide.

    `how` is "member" for a value - a member access in the code or the root word of a full
    interpolation `%{Module.NAME}` in a string - and "type" for a type position. The offset is
    where the compiler points: at the member name for a value, at the root for a type.
    """
    uses: list[tuple[str, str, str, int]] = []
    nodes = walk_nodes([method.params, method.return_type, method.body])
    for node in nodes:
        if isinstance(node, P.Member) and isinstance(node.obj, P.Name):
            root = node.obj.name
            if root in hidden or "::" in root:
                continue
            index = bisect_left(starts, node.obj.end)
            name_token = next((toks[i] for i in range(index, min(index + 3, len(toks)))
                               if toks[i].value == node.name), None)
            if name_token is not None:
                uses.append((root, node.name, "member", name_token.start))
        elif isinstance(node, P.TypeRef):
            low, high = bisect_left(starts, node.start), bisect_left(starts, node.end)
            for i in range(low, high - 2):
                root, dot, name = toks[i], toks[i + 1], toks[i + 2]
                if (root.kind != "IDENT" or dot.kind != "OP" or dot.value != "."
                        or name.kind != "IDENT" or root.value in hidden):
                    continue
                before = toks[i - 1] if i > low else None
                if before is not None and before.kind == "OP" and before.value in (".", "::"):
                    continue
                uses.append((root.value, name.value, "type", root.start))
        elif isinstance(node, P.Literal) and node.kind == "STRING":
            for offset, body in _interpolation_bodies(node.text):
                for match in _QUALIFIED_WORD_RE.finditer(body):
                    if match.group(1) not in hidden:
                        uses.append((match.group(1), match.group(2), "member",
                                     node.start + offset + match.start(2)))
    return uses


def _qualified_mapper(source: SourceFile) -> dict | None:
    """The map phase. A yaml names the environments its module is compiled for (when the
    documentation table settles them), the names the element gives its own members and, for a
    common module of both environments, the name other modules reach it by; a module
    contributes its one-side declarations and every qualified name its methods use, with the
    environment annotations of the method. The reduce joins the pairs."""
    if not _HAVE_YAML:
        return None
    if source.kind == "yaml":
        data = _parsed_object(source)
        if data is None:
            return None
        kind = object_kind(data)
        name = value_of(data, "Имя", kind)
        declaring = (kind == "ОбщийМодуль" and isinstance(name, str)
                     and value_of(data, "Окружение", kind) in _both_env_forms())
        sides = _reading_sides(data)
        return {"k": "y", "stem": _pair_stem(source.rel),
                "sides": sorted(sides) if sides is not None else None,
                "name": name if declaring else None,
                "own": sorted(element_own_names(data))}
    if source.kind != "xbsl" or is_query_file(Path(source.path)):
        return None
    module, errors = parse(source)
    if errors:
        return None
    members = _one_side_members(module)
    toks = code_tokens(source)
    starts = [token.start for token in toks]
    lines = linemap(source)
    declared = frozenset(getattr(member, "name", "") for member in module.members)
    uses: list[list] = []
    for method in module.members:
        if not isinstance(method, P.Method):
            continue
        hidden = _method_names(method, walk_nodes(method.body)) | declared
        annotated = sorted(_sides(method.annotations, frozenset()))
        for root, name, how, offset in _qualified_uses(source, method, toks, starts, hidden):
            line, col = lines.linecol(offset)
            uses.append([root, name, how, method.name, annotated, line, col])
    if not members and not uses:
        return None
    return {"k": "x", "stem": _pair_stem(source.rel), "members": members, "uses": uses}


@rule(QUALIFIED_RULE, f"{QUALIFIED_RULE}.title", "D", scope="project",
      severity=Severity.ERROR, mapper=_qualified_mapper)
def qualified_member_unavailable(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    """`Module.NAME` of a common module of both environments, where the declaration exists on
    one side only and the method reading it is compiled for the other one."""
    modules: dict[str, str] = {}  # stem -> the name of a common module of both environments
    sides_of: dict[str, frozenset[str]] = {}
    own_of: dict[str, set[str]] = {}
    for fact in facts.values():
        if fact["k"] != "y":
            continue
        if fact["name"]:
            modules[fact["stem"]] = fact["name"]
        if fact["sides"] is not None:
            sides_of[fact["stem"]] = frozenset(fact["sides"])
        own_of[fact["stem"]] = set(fact["own"])
    if not modules:
        return
    declarations: dict[str, tuple[str, dict]] = {}  # module name -> (stem, members)
    for fact in facts.values():
        if fact["k"] == "x" and fact["members"] and fact["stem"] in modules:
            declarations[modules[fact["stem"]]] = (fact["stem"], fact["members"])
    if not declarations:
        return
    for rel, fact in facts.items():
        if fact["k"] != "x" or not fact["uses"]:
            continue
        stem = fact["stem"]
        element = stem if stem in sides_of or stem in own_of else stem.rsplit(".", 1)[0]
        module_sides = sides_of.get(element)
        own = own_of.get(element, set())
        for root, name, how, method, annotated, line, col in fact["uses"]:
            declared = declarations.get(root)
            if declared is None or root in own:
                continue
            home, members = declared
            record = members.get(name)
            if record is None:
                continue
            kind, side, opened = record
            if how == "member" and kind not in _VALUE_KINDS:
                continue
            if how == "type" and kind not in _TYPE_KINDS:
                continue
            if not opened and home != stem:
                continue
            method_sides = frozenset(annotated) if annotated else module_sides
            if method_sides is None or not (method_sides - {side}):
                continue
            qualified = f"{root}.{name}"
            yield Diagnostic(
                rel, line, col, QUALIFIED_RULE, Severity.ERROR,
                i18n.t(f"{QUALIFIED_RULE}.on-{'server' if side == _CLIENT else 'client'}",
                       name=qualified, module=root, method=method,
                       what=i18n.t(f"{QUALIFIED_RULE}.what-{kind}"),
                       answer=i18n.t(f"{QUALIFIED_RULE}.answer-{how}", name=qualified)),
            )
