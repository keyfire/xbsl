"""Tier D: a call of a platform method kept for compatibility only - `code/deprecated-api`.

The documentation marks such a form of a method with `@Устарело`, and the editor of the platform
warns about every call that binds to it, naming the form to use instead. The code still compiles,
so nothing stops such a call on the way to production - until the platform drops the form.

Most deprecated methods are deprecated in every form (`ObjectStorage.UploadFromBytes`), and the
name alone decides. Some share their name with current overloads: `ObjectStorage.Upload(Stream,
Size)` is deprecated, `ObjectStorage.Upload("file.txt", Bytes)` is not, and the old one-argument
`JsonSerialization.ReadObject(Text)` exists only up to version 9.0 of the platform, where it is
deprecated, while a project of a newer compatibility mode calls a current form or nothing at all.
So the rule does what the compiler does before it warns: it picks the overloads the call can bind
to, and reports the call only when every one of them is deprecated.

The forms come from the catalog (`deprecated_members`: every form of a member that has a
deprecated one, with the platform versions each exists in, the compatibility modes the deprecation
applies in and the member the documentation names instead). A form is a candidate for a call when:

- the compatibility mode of the project admits it (`CompatibilityMode` of the project description;
  a mode the platform does not support is checked as the newest one, as the editor does). Without
  a known mode a form limited by version decides nothing, and the call is left alone;
- the arguments fit its parameters: no more positional arguments than parameters, every named
  argument names one of them, every required parameter gets an argument, and an argument of a
  known type is not of a type the parameter cannot take (`ReadableStream` for `FileName: String?`).
  The documentation does not print every default value (a settings object has one it does not
  show), so a parameter without a printed default is required only when a default would be printed
  for it: the parameter may hold the empty value, or it takes a string, a number or a boolean;
- a generic form can learn its type parameter from the call: one of the arguments goes to a
  parameter that names it. `ПрочитатьОбъект<ТипОбъекта>(Источник, Тип: Тип<ТипОбъекта>)` with the
  source alone infers nothing, and the compiler binds such a call elsewhere.

The call is reported when every candidate is deprecated in the mode of the project. The
declaration of the member in the distribution names the modes: the object storage deprecates its
old uploads from mode 8.0 on, the shorthand readers of a JSON reader only in the newest mode. When
the data does not state the modes, the mark of the documentation is held for the newest mode only.

What keeps the rule quiet where it cannot know:

- the receiver is typed by the engine's inference over the project catalog (the shared project
  typing, `typeinfer.project_typings`), and a bare name that is a project element or module is never
  read as a platform type;
- an argument the inference cannot type fits any parameter;
- a relation of two types is "cannot take" only between two platform types, neither the same nor
  an ancestor of the other; a project type may implement a contract, and that is not judged here.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache

from xbsl import dataset, i18n, terms, typeinfer
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, rule
from xbsl.lexer import linemap
from xbsl.rules._syntax import code_tokens
from xbsl.rules.component_since import _version
from xbsl.rules.type_casts import _TextSource

RULE_ID = "code/deprecated-api"

MESSAGES = {
    "code/deprecated-api.title": {
        "ru": "Вызов устаревшего метода платформы",
        "en": "A call of a deprecated platform method",
    },
    "code/deprecated-api.found": {
        "ru": "Метод '{member}' типа '{owner}' устарел: документация оставляет его только для "
              "совместимости.",
        "en": "Method '{member}' of type '{owner}' is deprecated: the documentation keeps it for "
              "compatibility only.",
    },
    "code/deprecated-api.replaced": {
        "ru": "Метод '{member}' типа '{owner}' устарел: документация оставляет его только для "
              "совместимости и предлагает вместо него '{replacement}'.",
        "en": "Method '{member}' of type '{owner}' is deprecated: the documentation keeps it for "
              "compatibility only and suggests '{replacement}' instead.",
    },
    "code/deprecated-api.form": {
        "ru": "Такая форма вызова метода '{member}' типа '{owner}' устарела: документация оставляет "
              "её только для совместимости, а текущие формы того же метода принимают другие "
              "аргументы.",
        "en": "This form of a call of method '{member}' of type '{owner}' is deprecated: the "
              "documentation keeps it for compatibility only, and the current forms of the same "
              "method take other arguments.",
    },
}
i18n.register(MESSAGES)

#: The project descriptor: its folder is the boundary of one catalog and one compatibility mode.
_PROJECT_FILES = frozenset({"Проект.yaml", "Project.yaml"})
#: The root of the type hierarchy: a parameter of this type takes anything.
_ROOT_TYPE = "Объект"


# --- the catalog side ------------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _deprecated() -> tuple[dict[str, dict[str, list[dict]]], frozenset[str]]:
    """({type: {member: [form]}}, every spelling of a deprecated member name), empty without data.

    The spellings are the prefilter of the mapper: a module that calls none of them has nothing
    to judge, and its text does not travel to the reduce.
    """
    try:
        catalog = dataset.load_json("stdlib.json")
    except Exception:  # noqa: BLE001 - no data, nothing is deprecated
        return {}, frozenset()
    table = catalog.get("deprecated_members") or {}
    names: set[str] = set()
    for owner, members in table.items():
        for member in members:
            names.add(member)
            english = terms.member_english_of(owner, member)
            if english:
                names.add(english)
    return table, frozenset(names)


dataset.register_reset(_deprecated.cache_clear)

#: A value of the platform's compatibility mode enumeration names the mode by its numbers: the
#: value for mode 9.0 ends with `9_0`.
_MODE_VALUE_RE = re.compile(r"^Версия(\d+)_(\d+)$")


@lru_cache(maxsize=1)
def _supported_modes() -> frozenset[tuple[int, ...]]:
    """The compatibility modes a project may declare, from the enumeration of the modes.

    The platform accepts a mode "not below version 6.0" (topic about updating the application) and
    names each one as a value of its mode enumeration. A project declaring a mode outside the list
    is refused by the build, and the editor then checks the code in the newest mode - the same
    calls warn as in a project of that mode.
    """
    try:
        catalog = dataset.load_json("stdlib.json")
    except Exception:  # noqa: BLE001 - no data, no list
        return frozenset()
    record = (catalog.get("type_members") or {}).get("РежимСовместимости") or {}
    modes = set()
    for value in record.get("properties") or ():
        match = _MODE_VALUE_RE.match(value)
        if match:
            modes.add((int(match.group(1)), int(match.group(2))))
    return frozenset(modes)


dataset.register_reset(_supported_modes.cache_clear)


def _effective_mode(declared: tuple[int, ...] | None) -> tuple[int, ...] | None:
    """The mode the code is checked in: the declared one, or the newest when it is not supported."""
    supported = _supported_modes()
    if declared is None or not supported or declared in supported:
        return declared
    return max(supported)


@dataclass(frozen=True)
class _Param:
    name: str
    written: str
    variadic: bool
    default: bool


@dataclass(frozen=True)
class _Form:
    params: tuple[_Param, ...]
    type_params: frozenset[str]
    deprecated: bool
    #: The versions the form exists in (the version lines of the documentation).
    since: tuple[int, ...] | None
    until: tuple[int, ...] | None
    #: The modes the deprecation applies in, (the first, the last) with None for an open end, from
    #: the declaration of the member in the distribution; None when the data does not state them.
    deprecated_modes: tuple[tuple[int, ...] | None, tuple[int, ...] | None] | None
    replacement: str

    def deprecated_in(self, mode: tuple[int, ...], newest: tuple[int, ...] | None) -> bool:
        """Whether the deprecation applies in a mode.

        Without the modes in the data only the mark of the documentation is known, and the
        documentation describes the newest mode: an older one may still call the form silently.
        """
        if not self.deprecated:
            return False
        if self.deprecated_modes is None:
            return newest is not None and mode >= newest
        first, last = self.deprecated_modes
        return (first is None or first <= mode) and (last is None or mode <= last)

    def exists_in(self, mode: tuple[int, ...]) -> bool:
        return (self.since is None or self.since <= mode) and (self.until is None or mode <= self.until)

    def depends_on_mode(self) -> bool:
        """Whether the form is there, or deprecated, only in some of the modes (or maybe so)."""
        return bool(self.since or self.until
                    or (self.deprecated and self.deprecated_modes != (None, None)))


#: `Имя<ТипОбъекта>(` - the head of a generic method's signature.
_GENERIC_HEAD_RE = re.compile(r"^[^\s(<]+<([^>]*)>\s*\(")


def _split_top(text: str) -> list[str]:
    """Parts of a parameter list split at the commas of its top level."""
    parts: list[str] = []
    depth = 0
    current = ""
    for index, char in enumerate(text):
        if char in "<([":
            depth += 1
        elif char in ")]" or (char == ">" and text[index - 1: index] != "-"):
            depth -= 1
        if char == "," and depth == 0:
            parts.append(current)
            current = ""
            continue
        current += char
    parts.append(current)
    return [part.strip() for part in parts if part.strip()]


@lru_cache(maxsize=None)
def _form(signature: str, deprecated: bool, since: str, until: str, deprecated_modes: tuple[str, str] | None,
          replacement: str) -> _Form | None:
    """The parameters of one printed form, or None when the text is not a signature."""
    open_paren = signature.find("(")
    if open_paren < 0:
        return None
    depth = 0
    close = -1
    for index in range(open_paren, len(signature)):
        if signature[index] == "(":
            depth += 1
        elif signature[index] == ")":
            depth -= 1
            if depth == 0:
                close = index
                break
    if close < 0:
        return None
    params: list[_Param] = []
    for part in _split_top(signature[open_paren + 1:close]):
        declared, equals, _default = part.partition("=")
        name, colon, written = declared.strip().partition(":")
        variadic = name.strip().startswith("...")
        params.append(_Param(name.strip().lstrip("."), written.strip() if colon else "", variadic,
                             bool(equals)))
    generic = _GENERIC_HEAD_RE.match(signature)
    type_params = frozenset(p.strip() for p in generic.group(1).split(",")) if generic else frozenset()
    modes = None
    if deprecated_modes is not None:
        first, last = deprecated_modes
        modes = (_version(first) if first else None, _version(last) if last else None)
    return _Form(tuple(params), type_params, deprecated, _version(since) if since else None,
                 _version(until) if until else None, modes, replacement)


def _modes_of(stored: object) -> tuple[str, str] | None:
    """`[first, last]` of a stored form (either may be null) as a pair of strings, or None."""
    if not isinstance(stored, list) or len(stored) != 2:
        return None
    return str(stored[0] or ""), str(stored[1] or "")


def _bases() -> dict[str, list[str]]:
    try:
        return dataset.load_json("stdlib.json").get("bases") or {}
    except Exception:  # noqa: BLE001 - no data, no hierarchy
        return {}


def _forms_of(owner: str, member: str) -> tuple[str, list[_Form]] | None:
    """(the Russian member name, its forms) for a member of a platform type or of an ancestor.

    The type itself answers first, then its ancestors from the nearest one: an heir that prints
    the forms of the member again speaks for itself.
    """
    table, _names = _deprecated()
    bases = _bases()
    for holder in (owner, *reversed(dataset.nearest_last(bases.get(owner) or (), bases))):
        members = table.get(holder) or {}
        for name, forms in members.items():
            if member != name and terms.member_english_of(holder, name) != member:
                continue
            parsed = [
                _form(str(form.get("signature") or ""), bool(form.get("deprecated")),
                      str(form.get("since") or ""), str(form.get("until") or ""),
                      _modes_of(form.get("deprecated_modes")), str(form.get("replacement") or ""))
                for form in forms
            ]
            if any(form is None for form in parsed):
                return None
            return name, [form for form in parsed if form is not None]
    return None


# --- the facts: the shared ones of the project typing ------------------------------------------------

def _calls_deprecated_name(source: SourceFile) -> bool:
    """Whether a module writes `.Имя` for a name some platform type deprecates.

    Registered with the shared facts of the project typing (`typeinfer.wants_text`): a module
    that calls none of the names has nothing to judge, and its text does not travel to the reduce.
    """
    _table, names = _deprecated()
    if not names or source.kind != "xbsl":
        return False
    toks = code_tokens(source)
    for index, token in enumerate(toks):
        if token.kind == "IDENT" and token.value in names and index > 0:
            before = toks[index - 1]
            if before.kind == "OP" and before.value in (".", "?."):
                return True
    return False


typeinfer.wants_text(_calls_deprecated_name)


# --- the reduce --------------------------------------------------------------------------------------

def _modes(facts: dict[str, dict]) -> dict[str, tuple[int, ...] | None]:
    """{rel: the compatibility mode of the project the source belongs to}, by the project groups of
    the shared typing - the same grouping the catalog of each module is built over."""
    out: dict[str, tuple[int, ...] | None] = {}
    for root, group in typeinfer._projects(facts).items():
        declared = next((fact.get("compat") for fact in group.values()
                         if fact.get("k") == "project" and fact.get("root") in (root, ".") and fact.get("compat")),
                        None)
        mode = _effective_mode(tuple(declared) if declared else None)
        for rel in group:
            out[rel] = mode
    return out


def _findings(facts: dict[str, dict]) -> list[Diagnostic]:
    table, names = _deprecated()
    if not table:
        return []
    modes = _modes(facts)
    found: list[Diagnostic] = []
    for rel, typing in typeinfer.project_typings(facts).items():
        lines = None
        for site in typing.calls(names):
            verdict = _verdict(site, typing.catalog, modes.get(rel))
            if verdict is None:
                continue
            key, fields = verdict
            if lines is None:
                lines = linemap(_TextSource(typing.text))
            callee = site.node.callee
            line, col = lines.linecol(callee.end - len(callee.name))
            found.append(Diagnostic(rel, line, col, RULE_ID, Severity.WARNING, i18n.t(key, **fields)))
    return found


def _receiver(owner: object, catalog: typeinfer.ProjectCatalog) -> str | None:
    """The platform type a call is made on, in the catalog's spelling, or None."""
    if isinstance(owner, typeinfer.StaticName):
        name = owner.name
        if name in catalog.elements or name in catalog.modules or "." in name:
            return None
        return typeinfer.platform_head(name)
    if isinstance(owner, typeinfer.TypeSet) and len(owner.names) == 1 and not owner.null:
        head, _args = typeinfer.split_nominal(next(iter(owner.names)))
        if head in catalog.elements or head.split(".", 1)[0] in catalog.elements:
            return None
        return typeinfer.platform_head(head)
    return None


def _verdict(site: typeinfer.CallSite, catalog: typeinfer.ProjectCatalog,
             mode: tuple[int, ...] | None) -> tuple[str, dict[str, str]] | None:
    owner = _receiver(site.owner, catalog)
    if owner is None:
        return None
    member_written = site.node.callee.name
    got = _forms_of(owner, member_written)
    if got is None:
        return None
    member, forms = got
    candidates = [form for form in forms if _admits(form, site, catalog)]
    if mode is None:
        # Without the mode of the project a form limited by versions may or may not be there, and
        # a deprecation limited by modes may or may not apply: nothing is decided.
        if any(form.depends_on_mode() for form in candidates):
            return None
        deprecated = all(form.deprecated for form in candidates)
    else:
        newest = max(_supported_modes(), default=None)
        candidates = [form for form in candidates if form.exists_in(mode)]
        deprecated = all(form.deprecated_in(mode, newest) for form in candidates)
    if not candidates or not deprecated:
        return None
    replacements = {form.replacement for form in candidates}
    replacement = replacements.pop() if len(replacements) == 1 else ""
    fields = {"member": _member_shown(owner, member), "owner": i18n.name(owner, "types")}
    if replacement and replacement == member:
        return "code/deprecated-api.form", fields
    if replacement:
        return "code/deprecated-api.replaced", {**fields, "replacement": _member_shown(owner, replacement)}
    return "code/deprecated-api.found", fields


def _member_shown(owner: str, member: str) -> str:
    if i18n.current_lang() != "en":
        return member
    return terms.member_english_of(owner, member) or member


def _admits(form: _Form, site: typeinfer.CallSite, catalog: typeinfer.ProjectCatalog) -> bool:
    """Whether a call can bind to a form by the number, the names and the types of its arguments."""
    params = form.params
    by_name = {param.name: param for param in params}
    bound: list[tuple[_Param, object]] = []
    position = 0
    for name, value in site.args:
        if name is None:
            if position >= len(params):
                return False
            param = params[position]
            if not param.variadic:
                position += 1  # a variadic parameter takes every positional argument after it
            bound.append((param, value))
            continue
        param = by_name.get(name) or by_name.get(terms.common_russian(name) or "")
        if param is None:
            return False
        bound.append((param, value))
    supplied = {param.name for param, _value in bound}
    if any(_required(param) and param.name not in supplied for param in params):
        return False
    if form.type_params and not any(
        any(type_param in _names_in(param.written) for type_param in form.type_params)
        for param, _value in bound
    ):
        return False
    return all(_fits(value, param.written, form.type_params, catalog) for param, value in bound)


#: The types whose default the documentation prints as a literal when there is one.
_LITERAL_TYPES = frozenset({"Строка", "Число", "Булево"})
_UNDEFINED_NAMES = frozenset({"Неопределено", "Undefined"})


def _required(param: _Param) -> bool:
    """Whether a call must pass the parameter: no printed default, and none could be unprinted.

    The documentation prints a default it can write as a literal - the empty value of a nullable
    parameter, a string, a number, a boolean. A default it cannot write, a settings object made
    for the call, it leaves out: a JSON read binds a call that passes nothing but the source,
    while the settings parameter shows no default. So a parameter of such a type without a
    printed default is taken as optional, and one of a nullable or literal type as required - an
    upload that names the stream alone does not bind to the form that begins with the file name.
    """
    if param.default or param.variadic or not param.written:
        return False
    alternatives = [part.strip() for part in param.written.split("|")]
    if any(part == "?" or part.endswith("?") or part in _UNDEFINED_NAMES for part in alternatives):
        return True
    return all(part in _LITERAL_TYPES for part in alternatives)


_NAME_RE = re.compile(r"[A-Za-zА-Яа-яЁё_][\wЁё]*(?:\.[A-Za-zА-Яа-яЁё_][\wЁё]*)?")


def _names_in(written: str) -> set[str]:
    return set(_NAME_RE.findall(written))


def _fits(value: object, written: str, type_params: frozenset[str], catalog: typeinfer.ProjectCatalog) -> bool:
    """False only when an argument of a known type surely cannot go to the parameter."""
    if not isinstance(value, typeinfer.TypeSet) or not value.names or not written:
        return True
    if "->" in written or type_params & _names_in(written):
        return True
    target = typeinfer.parse_type(written, catalog.resolver(None, strict=True))
    if target is None or not target.names:
        return True
    return all(any(not _surely_foreign(name, wanted, catalog) for wanted in target.names)
               for name in value.names)


def _surely_foreign(source: str, target: str, catalog: typeinfer.ProjectCatalog) -> bool:
    """Whether a value of the canonical type `source` is certainly not a value of `target`.

    Said only of two platform types: the same head (whatever the arguments) or a target among the
    ancestors of the source is a fit, and so is the root of the hierarchy. A project type may
    implement a contract the target names, which the catalog of this rule does not model.
    """
    if source == target or target == _ROOT_TYPE:
        return False
    source_head, _source_args = typeinfer.split_nominal(source)
    target_head, _target_args = typeinfer.split_nominal(target)
    if source_head == target_head:
        return False
    for head in (source_head, target_head):
        if head in catalog.elements or head.split(".", 1)[0] in catalog.elements \
                or head.split(".", 1)[0] in catalog.modules or typeinfer.platform_head(head) is None:
            return False
    bases = (dataset.load_json("stdlib.json").get("bases") or {}).get(source_head) or ()
    return target_head not in bases


@rule(
    RULE_ID, "code/deprecated-api.title", "D",
    scope="project", severity=Severity.WARNING, mapper=typeinfer.project_fact,
)
def deprecated_api(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    """A call that binds only to forms of a platform method the documentation marks deprecated."""
    return _findings(facts)
