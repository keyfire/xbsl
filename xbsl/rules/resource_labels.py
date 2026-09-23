"""Labels of a resource template against the Replace chains that fill them (tier D).

The rules code/resource-replace-absent and code/resource-label-unfilled.

A project keeps markup in resource files - a block of HTML, a stylesheet, an SVG picture - and
fills it in code: the text of the file is read and its labels are replaced one by one
(`Ресурс{card.svg}.ОткрытьПотокЧтения().ПрочитатьКакСтроку().Заменить("{{COLOR}}", Цвет)`).
Neither the compiler nor the browser says a word when the two drift apart. On a live project the
labels of three stylesheets were renamed in the files while the code went on replacing the old
names: every check was green, and the browser dropped the rules the labels stood in.

The analysis finds a value that is provably the TEXT of one resource file, follows it through
the chain of Replace calls applied to it and evaluates that chain on the file itself:

- code/resource-replace-absent - a Replace of a literal the file does not contain outside its
  comments at that step of the chain: the replacement changes nothing;
- code/resource-label-unfilled - a label of the file that a complete chain leaves in place. A
  label is a word between the delimiters the chain itself uses for its literals (`{{NAME}}` when
  the chain replaces `{{A}}` and `{{B}}`), so no convention of a project is built in. A chain is
  complete when nothing shows that the replacement goes on elsewhere: in a caller, in a callee,
  or through a variable that is replaced further.

A text source is recognized by its shape, never by a name of the project:

- `Ресурс{key}.ОткрытьПотокЧтения().ПрочитатьКакСтроку()`, both spellings;
- `ПакетРесурсов.Текущий().Получить("path").ОткрытьПотокЧтения().ПрочитатьКакСтроку()`;
- a call of a project method that returns such a read of its parameter (a path, possibly inside
  an interpolated literal, or a parameter of type `Resource`), wrappers of wrappers included, with
  the Replace, Trim and Substring calls inside the wrapper carried along;
- a call of a project method that always returns the text of one known file;
- a string parameter handed to a project method that goes on replacing in it;
- a local value bound to any of the above;
- an index by a literal key into a map that a project method fills from a literal list of
  paths, also when that map is a parameter of a client parameters element.

What is not judged: a computed path or key, a computed search string, a choice between two
files, a text handed to an unknown builder. For a part of a file (`Substring`, a wrapper that
keeps only the inner part) and for a value that another branch fills from elsewhere only the
absent string is checked: the labels left in such a text prove nothing.

The file is read with its comment bodies blanked by the scanners of restext: a label in a comment
of the file is documentation, not a place to fill.

Both rules are off by default. The analysis reads every module of the project and its resource
files, and whether a project fills its markup this way is its own decision; a project that does
turns the rules on.
"""

from __future__ import annotations

import itertools
import re
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from functools import lru_cache
from pathlib import Path

import yaml

from xbsl import dataset, i18n, restext, scaffold, terms
from xbsl import parser as P
from xbsl import resource_usage as RU
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, is_query_file, rule
from xbsl.rules.undefined_names import _interpolations as _short_interpolations
from xbsl.rules.yaml_imports import _interpolation_bodies as _full_interpolations
from xbsl.typeinfer import _field_names

ABSENT = "code/resource-replace-absent"
UNFILLED = "code/resource-label-unfilled"

MESSAGES = {
    f"{ABSENT}.title": {
        "ru": "Замена строки, которой нет в ресурсе",
        "en": "Replacement of a string the resource does not have",
    },
    f"{ABSENT}.found": {
        "ru": "В тексте ресурса {file} нет строки \"{search}\"{where}: замена ничего не меняет.{hint}",
        "en": "The text of the resource {file} has no \"{search}\"{where}: the replacement changes "
              "nothing.{hint}",
    },
    f"{ABSENT}.comment": {
        "ru": " (она есть только в комментарии файла)",
        "en": " (it is only in a comment of the file)",
    },
    f"{ABSENT}.earlier": {
        "ru": " (ее уже заменил предыдущий шаг цепочки)",
        "en": " (an earlier step of the chain has already replaced it)",
    },
    f"{ABSENT}.renamed": {
        "ru": " Без подстановки остается {labels} – возможно, метку переименовали.",
        "en": " The chain leaves {labels} unfilled – the label may have been renamed.",
    },
    f"{UNFILLED}.title": {
        "ru": "Метка ресурса остается без подстановки",
        "en": "A label of a resource is left unfilled",
    },
    f"{UNFILLED}.found": {
        "ru": "Метка {label} ресурса {file} остается без подстановки: цепочка замен ее не "
              "заполняет.{hint}",
        "en": "The label {label} of the resource {file} is left unfilled: the chain of "
              "replacements does not fill it.{hint}",
    },
    f"{UNFILLED}.renamed": {
        "ru": " Цепочка заменяет {absent}, а этой строки в файле нет – возможно, метку "
              "переименовали.",
        "en": " The chain replaces {absent}, which the file does not have – the label may have "
              "been renamed.",
    },
}
i18n.register(MESSAGES)


# --- platform words, both spellings from the engine's data ----------------------------------


def _member(owner: str, name: str) -> frozenset[str]:
    return frozenset({name, terms.member_english_of(owner, name)} - {None})


@dataclass(frozen=True)
class _Words:
    replace: frozenset[str]
    trim: frozenset[str]
    substring: frozenset[str]
    open: frozenset[str]
    read: frozenset[str]
    insert: frozenset[str]
    pattern_types: frozenset[str]
    map_types: frozenset[str]
    resource_words: frozenset[str]
    resource_types: frozenset[str]
    string_types: frozenset[str]
    kind_keys: frozenset[str]
    name_keys: frozenset[str]
    client_kinds: frozenset[str]
    client_handlers: frozenset[str]


@lru_cache(maxsize=1)
def _words() -> _Words:
    resource_words = frozenset(terms.key_forms("Ресурс"))
    client_kind = "ПараметрыРаботыКлиента"
    client_handler = "ВычислитьПараметрыРаботыКлиента"
    return _Words(
        replace=_member("Строка", "Заменить"),
        trim=_member("Строка", "Сократить"),
        substring=_member("Строка", "Подстрока"),
        open=_member("Ресурс", "ОткрытьПотокЧтения"),
        read=_member("ПотокЧтения", "ПрочитатьКакСтроку"),
        insert=_member("Соответствие", "Вставить"),
        pattern_types=frozenset(terms.forms("Образец", "types")),
        map_types=frozenset(terms.forms("Соответствие", "types")),
        resource_words=resource_words,
        resource_types=resource_words | frozenset(terms.forms("Ресурс", "types")),
        string_types=frozenset(terms.forms("Строка", "types")),
        kind_keys=frozenset(terms.key_forms("ВидЭлемента")),
        name_keys=frozenset(terms.key_forms("Имя")),
        client_kinds=frozenset({client_kind, terms.kinds_table().get(client_kind)} - {None}),
        client_handlers=frozenset({client_handler, terms.common_english(client_handler)} - {None}),
    )


dataset.register_reset(_words.cache_clear)

#: A module that has none of these words holds no chain and is skipped before any evaluation.
_CONST_KINDS = frozenset({"CONST", "конст", "const"})
_WRAP_PREFIX = "method Probe()\n    return "
_WRAP_SUFFIX = "\n;\n"
_IDENT = re.compile(r"[^\W\d]\w*")
#: A literal that looks like a label: a word between one to three delimiter characters.
_LABEL_SHAPE = re.compile(r"^(?P<o>[^\w\s<>\"'=#&;:,.()/]{1,3})(?P<n>[^\W\d]\w*)"
                          r"(?P<c>[^\w\s<>\"'=#&;:,.()/]{1,3})$")
_ESCAPES = {"n": "\n", "t": "\t", "r": "\r"}
#: How deep the evaluation follows a value through locals, calls and wrappers.
_DEPTH = 60


# --- small helpers --------------------------------------------------------------------------


def _unescape(body: str) -> str:
    out: list[str] = []
    i = 0
    while i < len(body):
        ch = body[i]
        if ch == "\\" and i + 1 < len(body):
            out.append(_ESCAPES.get(body[i + 1], body[i + 1]))
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _interpolation_spans(raw: str) -> list[tuple[int, int, str | None]]:
    """(start, end, identifier or None) of each interpolation of a literal, offsets in `raw`."""
    spans = []
    for sign_at, _sign, name in _short_interpolations(raw):
        spans.append((sign_at, sign_at + 1 + len(name), name))
    for body_at, body in _full_interpolations(raw, blank_strings=False):
        ident = body.strip()
        spans.append((body_at - 2, body_at + len(body) + 1,
                      ident if _IDENT.fullmatch(ident) else None))
    return sorted(spans)


def _literal_value(node: object, lookup=None) -> str | None:
    """The value of a string literal; interpolations are filled by `lookup(name)` or refused."""
    if not (isinstance(node, P.Literal) and node.kind == "STRING"):
        return None
    raw = node.text
    if len(raw) < 2 or raw[0] != '"' or raw[-1] != '"':
        return None
    spans = _interpolation_spans(raw)
    if not spans:
        return _unescape(raw[1:-1])
    if lookup is None:
        return None
    parts, pos = [], 1
    for start, end, name in spans:
        parts.append(_unescape(raw[pos:start]))
        value = lookup(name) if name else None
        if value is None:
            return None
        parts.append(value)
        pos = end
    parts.append(_unescape(raw[pos:-1]))
    return "".join(parts)


def _walk_with_parents(root: object) -> list[tuple[object, object]]:
    out = []
    stack: list[tuple[object, object]] = [(root, None)]
    while stack:
        current, parent = stack.pop()
        if isinstance(current, (list, tuple)):
            for item in reversed(current):
                stack.append((item, parent))
            continue
        if not isinstance(current, P.Node):
            continue
        out.append((current, parent))
        for name in reversed(_field_names(type(current))):
            child = getattr(current, name, None)
            if isinstance(child, (P.Node, list, tuple)):
                stack.append((child, current))
    return out


def _line_col(text: str, offset: int) -> tuple[int, int]:
    line = text.count("\n", 0, offset) + 1
    return line, offset - (text.rfind("\n", 0, offset) + 1) + 1


def _label_shape(literals: Iterable[str | None]) -> re.Pattern | None:
    shapes = set()
    for literal in literals:
        if literal is None:
            continue
        match = _LABEL_SHAPE.match(literal)
        if match:
            shapes.add((match["o"], match["c"]))
    if len(shapes) != 1:
        return None
    opener, closer = shapes.pop()
    return re.compile(re.escape(opener) + r"[^\W\d]\w*" + re.escape(closer))


def _masked(path: Path, text: str) -> str:
    """The text with the comment bodies blanked; comments are found by the engine's scanners."""
    kind = restext.SUFFIX_KINDS.get(path.suffix.lower())
    if kind is None:
        return text
    chars = list(text)
    for segment in restext._scan(kind, text):
        if segment.kind == restext.COMMENT:
            for i in range(segment.start, segment.end):
                if chars[i] != "\n":
                    chars[i] = " "
    return "".join(chars)


def _call_argument(call: object, index: int, name: str) -> object:
    if not isinstance(call, P.Call):
        return None
    named = next((arg.value for arg in call.args if arg.name == name), None)
    if named is not None:
        return named
    positional = [arg.value for arg in call.args if arg.name is None]
    return positional[index] if index < len(positional) else None


def _param_name(method: P.Method, call: P.Call, argument: P.CallArg) -> str | None:
    if argument.name:
        return argument.name
    positional = [arg for arg in call.args if arg.name is None]
    index = next((i for i, arg in enumerate(positional) if arg is argument), None)
    if index is None or index >= len(method.params):
        return None
    return method.params[index].name


# --- values ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Step:
    op: str                     # replace | regex | trim | part | unknown
    search: str | None = None
    value: str | None = None    # the literal replacement; None when it is computed
    rel: str = ""
    line: int = 0
    col: int = 0
    generic: bool = False       # written in a text helper that serves other texts too


@dataclass(frozen=True)
class _Val:
    kind: str                   # file | param | unresolved | empty
    files: tuple = ()
    param: tuple | None = None  # (index, name, path | resource | text)
    tmpl: tuple = ("", "")
    scope_path: str | None = None
    steps: tuple = ()
    exact: bool = True
    mixed: bool = False         # another branch returns a text of unknown origin


_EMPTY = _Val("empty")


@dataclass
class _Mod:
    key: tuple
    path: Path
    rel: str
    tree: P.Module
    text: str
    methods: dict
    consts: dict


@dataclass
class _Ctx:
    mod: _Mod
    method: P.Method
    symbolic: bool
    env: dict
    params: dict
    locals: dict
    parents: dict
    nodes: list
    memo: dict = field(default_factory=dict)
    outer: tuple | None = None  # (literal, its parent, outer ctx) for an interpolation tree


@dataclass(frozen=True)
class _Target:
    mod: _Mod
    method: P.Method

    @property
    def key(self) -> tuple:
        return (self.mod.key, self.method.name)


@dataclass(frozen=True)
class _Site:
    node: object
    parent: object
    ctx: _Ctx


@dataclass(frozen=True)
class _Finding:
    rule_id: str
    rel: str
    line: int
    col: int
    message: str


class _Resolver(RU._Analyzer):
    """The engine's own resolution of resource keys and paths, answering instead of collecting."""

    def __init__(self, root: Path, texts: dict[str, str]) -> None:
        super().__init__(root, lambda path: texts.get(str(path)) or path.read_text(encoding="utf-8-sig"))
        self.captured: list | None = None

    def _evidence(self, items, source, text, start, end, kind, strength, detail=""):
        if self.captured is not None:
            self.captured.append((tuple(items), strength, detail))

    def literal(self, path: Path, text: str, written: str) -> tuple:
        self.captured = []
        try:
            self._resolve_static(path, text, written, 0, 0, "literal")
        finally:
            got, self.captured = self.captured, None
        return tuple(dict.fromkeys(item.path for items, strength, _detail in got
                                   if strength == "referenced" for item in items))

    def runtime(self, source: Path, value: str) -> tuple:
        scope = self._scope_of_module(None, source)
        if scope is None:
            return ()
        return tuple(item.path for item in self._exact(scope.directory, value))


# --- the analysis ---------------------------------------------------------------------------


class _Project:
    """One project: its modules, the summaries of their methods and the chains they build."""

    def __init__(self, root: Path, modules: list[tuple[SourceFile, P.Module]],
                 yamls: list[SourceFile], texts: dict[str, str]) -> None:
        self.words = _words()
        self.texts = texts
        self.res = _Resolver(root, texts)
        for source, tree in modules:
            path = Path(source.path)
            project = self.res.layout.project_dir_of(path)
            self.res.modules[(project, path.stem)].append((path, tree, source.text))
        self.mods: dict[tuple, _Mod] = {}
        rels = {str(Path(source.path)): source.rel for source, _tree in modules}
        for key, copies in self.res.modules.items():
            if len(copies) != 1:
                continue
            path, tree, text = copies[0]
            methods, consts = {}, {}
            for member in tree.members:
                if isinstance(member, P.Method):
                    methods.setdefault(member.name, member)
                elif isinstance(member, P.ObjectField) and member.kind in _CONST_KINDS:
                    consts[member.name] = member
            self.mods[key] = _Mod(key, path, rels[str(path)], tree, text, methods, consts)
        self.by_path = {str(mod.path): mod for mod in self.mods.values()}
        self.ctxs: dict[tuple, _Ctx] = {}
        self.summaries: dict[tuple, _Val | None] = {}
        self.map_summaries: dict[tuple, dict | None] = {}
        self.busy: set = set()
        self.generic_memo: dict[tuple, bool] = {}
        self.fate_literals: dict[str, tuple] = {}
        self.interpolation_ctxs: dict[tuple, list[_Ctx]] = defaultdict(list)
        self.callsites = self._index_calls()
        self.client_params = self._client_params(yamls)

    # contexts

    def ctx(self, mod: _Mod, method: P.Method, symbolic: bool) -> _Ctx:
        key = (mod.key, method.name, symbolic)
        found = self.ctxs.get(key)
        if found is not None:
            return found
        pairs = _walk_with_parents(method)
        parents = {id(node): parent for node, parent in pairs}
        counts: dict[str, int] = defaultdict(int)
        for node, _parent in pairs:
            if isinstance(node, P.VarDecl):
                counts[node.name] += 1
        reassigned = {node.target.name for node, _parent in pairs
                      if isinstance(node, P.Assign) and isinstance(node.target, P.Name)}
        local: dict[str, object] = {}
        for node, _parent in pairs:
            if isinstance(node, P.VarDecl):
                single = counts[node.name] == 1 and node.name not in reassigned
                local[node.name] = node if single else None
        params = {param.name: (index, param) for index, param in enumerate(method.params)}
        made = _Ctx(mod, method, symbolic, {}, params, local, parents, pairs)
        self.ctxs[key] = made
        return made

    def target(self, call: object, ctx: _Ctx) -> _Target | None:
        if not isinstance(call, P.Call):
            return None
        callee = call.callee
        if isinstance(callee, P.Name):
            method = ctx.mod.methods.get(callee.name)
            return _Target(ctx.mod, method) if method is not None else None
        if isinstance(callee, P.Member) and isinstance(callee.obj, P.Name):
            owner = callee.obj.name
            if owner in ctx.locals or owner in ctx.params:
                return None
            project = self.res.layout.project_dir_of(ctx.mod.path)
            mod = self.mods.get((project, owner))
            if mod is None:
                return None
            method = mod.methods.get(callee.name)
            return _Target(mod, method) if method is not None else None
        return None

    # strings: paths, keys and search strings

    def str_eval(self, node: object, ctx: _Ctx, depth: int = 0) -> str | None:
        if node is None or depth > 12:
            return None
        if isinstance(node, P.Literal):
            return _literal_value(node, lambda name: self._lookup(name, ctx, depth + 1))
        if isinstance(node, P.Name):
            return self._lookup(node.name, ctx, depth + 1)
        if isinstance(node, P.NonNull):
            return self.str_eval(node.operand, ctx, depth + 1)
        if isinstance(node, P.Binary) and node.op == "+":
            left = self.str_eval(node.left, ctx, depth + 1)
            right = self.str_eval(node.right, ctx, depth + 1)
            return None if left is None or right is None else left + right
        return None

    def _lookup(self, name: str, ctx: _Ctx, depth: int) -> str | None:
        if name in ctx.env:
            return ctx.env[name]
        if name in ctx.locals:
            decl = ctx.locals[name]
            return self.str_eval(decl.init, ctx, depth) if decl is not None else None
        if name in ctx.params:
            return None
        const = ctx.mod.consts.get(name)
        if const is not None and const.init is not None:
            return self.str_eval(const.init, ctx, depth)
        return None

    def param_template(self, node: object, ctx: _Ctx) -> tuple | None:
        """(index, name, prefix, suffix) when `node` is a parameter or a literal around one."""
        if isinstance(node, P.Name) and node.name in ctx.params:
            return ctx.params[node.name][0], node.name, "", ""
        if isinstance(node, P.Literal) and node.kind == "STRING":
            raw = node.text
            spans = _interpolation_spans(raw)
            if len(spans) == 1 and spans[0][2] in ctx.params:
                start, end, name = spans[0]
                return ctx.params[name][0], name, _unescape(raw[1:start]), _unescape(raw[end:-1])
        return None

    # texts

    def ev(self, node: object, ctx: _Ctx, depth: int = 0) -> _Val | None:
        if node is None or depth > _DEPTH:
            return None
        key = id(node)
        if key in ctx.memo:
            return ctx.memo[key]
        ctx.memo[key] = None  # a cycle reads as "unknown"
        result = self._ev(node, ctx, depth)
        ctx.memo[key] = result
        return result

    def _ev(self, node: object, ctx: _Ctx, depth: int) -> _Val | None:
        words = self.words
        if isinstance(node, P.NonNull):
            return self.ev(node.operand, ctx, depth + 1)
        if isinstance(node, P.Literal):
            return _EMPTY if _literal_value(node) == "" else None
        if isinstance(node, P.Name):
            if node.name in ctx.locals:
                decl = ctx.locals[node.name]
                return self.ev(decl.init, ctx, depth + 1) if decl is not None else None
            if ctx.symbolic and node.name in ctx.params:
                index, param = ctx.params[node.name]
                if param.type is None or set(param.type.names) & words.string_types:
                    return _Val("param", param=(index, node.name, "text"))
            return None
        if isinstance(node, P.Index):
            found = self.map_of(node.obj, ctx, depth + 1)
            if found is None:
                return None
            key = self.str_eval(node.index, ctx)
            value = found.get(key) if key is not None else None
            return value if value is not None else _Val("unresolved")
        if isinstance(node, (P.Ternary, P.Coalesce)):
            branches = ([node.then, node.otherwise] if isinstance(node, P.Ternary)
                        else [node.left, node.right])
            return self.join([self.ev(branch, ctx, depth + 1) for branch in branches])
        if not isinstance(node, P.Call):
            return None
        callee = node.callee
        if isinstance(callee, P.Member):
            if callee.name in words.read and not node.args:
                inner = callee.obj
                if (isinstance(inner, P.Call) and isinstance(inner.callee, P.Member)
                        and inner.callee.name in words.open and not inner.args):
                    return self.resource_of(inner.callee.obj, ctx, depth + 1)
                return None
            if callee.name in words.replace and len(node.args) >= 2:
                base = self.ev(callee.obj, ctx, depth + 1)
                if base is None or base.kind == "empty":
                    return None
                return replace(base, steps=base.steps + (self.replace_step(node, ctx),))
            if callee.name in words.trim and not node.args:
                base = self.ev(callee.obj, ctx, depth + 1)
                if base is None or base.kind == "empty":
                    return None
                return replace(base, steps=base.steps + (_Step("trim"),))
            if callee.name in words.substring:
                base = self.ev(callee.obj, ctx, depth + 1)
                if base is None or base.kind == "empty":
                    return None
                return replace(base, steps=base.steps + (_Step("part"),), exact=False)
        target = self.target(node, ctx)
        if target is not None:
            return self.apply(target, node, ctx, depth + 1)
        return None

    @staticmethod
    def join(values: list[_Val | None]) -> _Val | None:
        real = [value for value in values if value is not None and value.kind != "empty"]
        has_empty = any(value is not None and value.kind == "empty" for value in values)
        has_none = any(value is None for value in values)
        if not real:
            return _EMPTY if has_empty and not has_none else None
        first = real[0]
        if any(value != first for value in real[1:]):
            return None
        out = first
        if has_empty:
            out = replace(out, exact=False)
        if has_none:
            out = replace(out, mixed=True)
        return out

    def resource_of(self, node: object, ctx: _Ctx, depth: int) -> _Val | None:
        """The text read from the resource object `node` - the receiver of the stream."""
        words = self.words
        if isinstance(node, P.NonNull):
            return self.resource_of(node.operand, ctx, depth + 1)
        if (isinstance(node, P.Literal) and node.kind == "RESOLVABLE"
                and node.text in words.resource_words):
            raw = ctx.mod.text[node.start:node.end]
            if "{" not in raw or "}" not in raw:
                return None
            written = raw[raw.find("{") + 1:raw.rfind("}")].strip()
            files = self.res.literal(ctx.mod.path, ctx.mod.text, written)
            return _Val("file", files=files) if len(files) == 1 else _Val("unresolved")
        if isinstance(node, P.Call) and RU._current_get(node):
            argument = node.args[0].value if node.args else None
            path = self.str_eval(argument, ctx)
            if path is not None:
                files = self.res.runtime(ctx.mod.path, path)
                return _Val("file", files=files) if len(files) == 1 else _Val("unresolved")
            if ctx.symbolic:
                bound = self.param_template(argument, ctx)
                if bound is not None:
                    return _Val("param", param=(bound[0], bound[1], "path"), tmpl=bound[2:],
                                scope_path=str(ctx.mod.path))
            return _Val("unresolved")
        if isinstance(node, P.Name):
            if node.name in ctx.locals:
                decl = ctx.locals[node.name]
                return self.resource_of(decl.init, ctx, depth + 1) if decl is not None else None
            if ctx.symbolic and node.name in ctx.params:
                index, param = ctx.params[node.name]
                if param.type is not None and set(param.type.names) & words.resource_types:
                    return _Val("param", param=(index, node.name, "resource"))
        return None

    def apply(self, target: _Target, call: P.Call, ctx: _Ctx, depth: int) -> _Val | None:
        summary = self.summary(target)
        if summary is None or summary.kind == "empty":
            return None
        if summary.kind in ("file", "unresolved"):
            return summary
        index, name, kind = summary.param
        argument = _call_argument(call, index, name)
        if argument is None:
            return None
        if kind == "text":
            value = self.ev(argument, ctx, depth + 1)
            if value is None or value.kind == "empty":
                return None
            generic = self.is_generic(target, index, name)
            steps = tuple(replace(step, generic=True) if generic and step.op == "replace" else step
                          for step in summary.steps)
            return replace(value, steps=value.steps + steps,
                           exact=value.exact and summary.exact,
                           mixed=value.mixed or summary.mixed)
        if kind == "resource":
            value = self.resource_of(argument, ctx, depth + 1)
            if value is None:
                return _Val("unresolved")
            return replace(value, steps=value.steps + summary.steps,
                           exact=value.exact and summary.exact,
                           mixed=value.mixed or summary.mixed)
        # a path parameter
        path = self.str_eval(argument, ctx)
        if path is not None:
            full = summary.tmpl[0] + path + summary.tmpl[1]
            files = self.res.runtime(Path(summary.scope_path), full)
            if len(files) == 1:
                return _Val("file", files=files, steps=summary.steps, exact=summary.exact,
                            mixed=summary.mixed)
            return _Val("unresolved")
        if ctx.symbolic:
            bound = self.param_template(argument, ctx)
            if bound is not None:
                return replace(summary, param=(bound[0], bound[1], "path"),
                               tmpl=(summary.tmpl[0] + bound[2], bound[3] + summary.tmpl[1]))
        return _Val("unresolved")

    def summary(self, target: _Target) -> _Val | None:
        key = target.key
        if key in self.summaries:
            return self.summaries[key]
        if key in self.busy:
            return None
        self.busy.add(key)
        try:
            ctx = self.ctx(target.mod, target.method, symbolic=True)
            returns = [node for node, _parent in ctx.nodes if isinstance(node, P.Return)]
            values = [self.ev(ret.value, ctx) if ret.value is not None else None for ret in returns]
            result = self.join(values) if returns else None
        finally:
            self.busy.discard(key)
        self.summaries[key] = result
        return result

    def is_generic(self, target: _Target, index: int, name: str) -> bool:
        """Does a text helper serve more than one text?

        It does when one of its callers hands it a text of no known file, and when its callers
        hand it texts of different files: a Replace of a label that one of those files lacks is
        then the helper doing its common work, not a mistake about that file.
        """
        key = (target.key, index)
        if key in self.generic_memo:
            return self.generic_memo[key]
        self.generic_memo[key] = False
        generic = False
        files: set[tuple] = set()
        for site in self.callsites.get(target.key, ()):
            if site.ctx.outer is not None:
                generic = True
                break
            argument = _call_argument(site.node, index, name)
            concrete = self.ctx(site.ctx.mod, site.ctx.method, symbolic=False)
            value = self.ev(argument, concrete) if argument is not None else None
            if value is None or value.kind != "file":
                generic = True
                break
            files.add(value.files)
            if len(files) > 1:
                generic = True
                break
        self.generic_memo[key] = generic
        return generic

    def replace_step(self, call: P.Call, ctx: _Ctx) -> _Step:
        first = call.args[0].value
        second = call.args[1].value if len(call.args) > 1 else None
        if ctx.outer is None:
            line, col = _line_col(ctx.mod.text, call.callee.end - len(call.callee.name))
        else:  # a call inside an interpolation reports at the literal it lives in
            line, col = _line_col(ctx.mod.text, ctx.outer[0].start)
        where = dict(rel=ctx.mod.rel, line=line, col=col)
        if isinstance(first, P.New) and set(first.type.names) & self.words.pattern_types:
            pattern = _literal_value(first.args[0].value) if first.args else None
            value = self.str_eval(second, ctx) if second is not None else None
            return _Step("regex" if pattern is not None else "unknown", pattern, value, **where)
        search = self.str_eval(first, ctx)
        if search is None:
            return _Step("unknown", None, None, **where)
        value = self.str_eval(second, ctx) if second is not None else None
        return _Step("replace", search, value, **where)

    # maps of resource texts

    def map_of(self, node: object, ctx: _Ctx, depth: int) -> dict | None:
        if depth > 12:
            return None
        if (isinstance(node, P.Member) and isinstance(node.obj, P.Name)
                and node.obj.name in self.client_params
                and node.obj.name not in ctx.locals and node.obj.name not in ctx.params):
            entry = self.client_params[node.obj.name].get(node.name)
            if entry is not None:
                expression, owner_ctx = entry
                return self.map_of(expression, owner_ctx, depth + 1)
            return None
        if isinstance(node, P.Name) and node.name in ctx.locals and ctx.locals[node.name] is not None:
            return self.map_of(ctx.locals[node.name].init, ctx, depth + 1)
        if isinstance(node, P.Call):
            target = self.target(node, ctx)
            if target is not None:
                return self.map_summary(target)
        return None

    def map_summary(self, target: _Target) -> dict | None:
        key = target.key
        if key in self.map_summaries:
            return self.map_summaries[key]
        self.map_summaries[key] = None
        words = self.words
        ctx = self.ctx(target.mod, target.method, symbolic=False)
        returns = [node for node, _parent in ctx.nodes if isinstance(node, P.Return)]
        if len(returns) != 1 or not isinstance(returns[0].value, P.Name):
            return None
        var = returns[0].value.name
        decl = ctx.locals.get(var)
        if (decl is None or not isinstance(decl.init, P.New)
                or not set(decl.init.type.names) & words.map_types):
            return None
        found: dict[str, _Val] = {}
        for node, _parent in ctx.nodes:
            if not (isinstance(node, P.Call) and isinstance(node.callee, P.Member)
                    and node.callee.name in words.insert and isinstance(node.callee.obj, P.Name)
                    and node.callee.obj.name == var and len(node.args) == 2):
                continue
            loops = []
            up = ctx.parents.get(id(node))
            while up is not None:
                if isinstance(up, P.ForEach):
                    loops.append(up)
                up = ctx.parents.get(id(up))
            choices: list | None = []
            for loop in loops:
                if not isinstance(loop.source, P.ArrayLit):
                    choices = None
                    break
                values = [_literal_value(item) for item in loop.source.items]
                if any(value is None for value in values):
                    choices = None
                    break
                choices.append([(loop.var, value) for value in values])
            if choices is None:
                continue
            for combination in itertools.product(*choices):
                bound = replace(ctx, env=dict(combination), memo={})
                map_key = self.str_eval(node.args[0].value, bound)
                value = self.ev(node.args[1].value, bound)
                if map_key is not None and value is not None:
                    found[map_key] = value
        self.map_summaries[key] = found or None
        return self.map_summaries[key]

    def _client_params(self, yamls: list[SourceFile]) -> dict:
        """{element name: {parameter: (its expression, the context of the handler)}}."""
        words = self.words
        out: dict = {}
        for source in yamls:
            if not any(word in source.text for word in words.client_kinds):
                continue
            try:
                data = yaml.safe_load(source.text)
            except yaml.YAMLError:
                continue
            if not isinstance(data, dict):
                continue
            kind = next((data[key] for key in words.kind_keys if key in data), None)
            name = next((data[key] for key in words.name_keys if key in data), None)
            if kind not in words.client_kinds or not name:
                continue
            mod = self.by_path.get(str(Path(source.path).with_suffix(".xbsl")))
            if mod is None:
                continue
            for handler_name, handler in mod.methods.items():
                if handler_name not in words.client_handlers:
                    continue
                hctx = self.ctx(mod, handler, symbolic=False)
                for node, _parent in hctx.nodes:
                    if isinstance(node, P.New) and node.args:
                        for argument in node.args:
                            if argument.name:
                                out.setdefault(name, {})[argument.name] = (argument.value, hctx)
        return out

    # call sites and the fate of a text

    def _index_calls(self) -> dict:
        sites: dict[tuple, list[_Site]] = defaultdict(list)
        for mod in self.mods.values():
            for method in mod.methods.values():
                ctx = self.ctx(mod, method, symbolic=False)
                for node, parent in ctx.nodes:
                    if isinstance(node, P.Call):
                        target = self.target(node, ctx)
                        if target is not None:
                            sites[target.key].append(_Site(node, parent, ctx))
                    elif isinstance(node, P.Literal) and node.kind == "STRING" and (
                            "%{" in node.text or "${" in node.text):
                        for _offset, body in _full_interpolations(node.text, blank_strings=False):
                            tree, errors = P.parse_text(_WRAP_PREFIX + body + _WRAP_SUFFIX)
                            if errors or not tree.members:
                                continue
                            pairs = _walk_with_parents(tree.members[0])
                            inner = _Ctx(mod, method, False, {}, ctx.params, ctx.locals,
                                         {id(n): p for n, p in pairs}, pairs,
                                         outer=(node, parent, ctx))
                            self.interpolation_ctxs[(mod.key, method.name)].append(inner)
                            for small, small_parent in pairs:
                                if isinstance(small, P.Call):
                                    target = self.target(small, inner)
                                    if target is not None:
                                        sites[target.key].append(_Site(small, small_parent, inner))
        return sites

    def var_uses(self, name: str, ctx: _Ctx) -> list[tuple[object, object]]:
        uses = []
        pattern = re.compile(rf"(?<![\w]){re.escape(name)}(?![\w])")
        for node, parent in ctx.nodes:
            if isinstance(node, P.Name) and node.name == name and not isinstance(parent, P.VarDecl):
                uses.append((node, parent))
            elif isinstance(node, P.Literal) and node.kind == "STRING" and (
                    "%" in node.text or "$" in node.text):
                if any(ident == name for _s, _e, ident in _interpolation_spans(node.text)):
                    uses.append((node, parent))
                elif any(pattern.search(body) for _o, body in _full_interpolations(node.text)):
                    uses.append((node, parent))
        return uses

    def continues(self, node: object, parent: object, ctx: _Ctx) -> bool:
        words = self.words
        if isinstance(parent, P.NonNull):
            return True
        if isinstance(parent, (P.Ternary, P.Coalesce)):
            return self.ev(parent, ctx) is not None
        if isinstance(parent, P.Member) and parent.obj is node:
            grand = ctx.parents.get(id(parent))
            if (isinstance(grand, P.Call) and grand.callee is parent
                    and parent.name in (words.replace | words.trim | words.substring)):
                return True
        if isinstance(parent, P.CallArg):
            call = ctx.parents.get(id(parent))
            target = self.target(call, ctx)
            if target is not None:
                summary = self.summary(target)
                if summary is not None and summary.kind == "param":
                    index, name, _kind = summary.param
                    if _call_argument(call, index, name) is node:
                        return True
            if (isinstance(call, P.Call) and isinstance(call.callee, P.Member)
                    and call.callee.name in words.insert):
                return True  # an entry of a map; its reader is judged at the index
        if isinstance(parent, P.VarDecl) and parent.init is node:
            return ctx.locals.get(parent.name) is parent and bool(self.var_uses(parent.name, ctx))
        if isinstance(parent, P.Return):
            if ctx.outer is not None:
                return False  # the end of an interpolation: the text lands in the literal
            target = _Target(ctx.mod, ctx.method)
            summary = self.summary(target)
            if summary is not None and summary.kind == "param":
                return True  # a wrapper: its text is judged where it is called
            if (summary is not None and summary.kind in ("file", "unresolved")
                    and self.callsites.get(target.key)):
                return True
        return False

    def fate(self, node: object, parent: object, ctx: _Ctx, depth: int = 0) -> set[str]:
        """Where the text goes after this expression: "final", or a continuation of the chain."""
        words = self.words
        if depth > 10:
            return {"open"}
        if parent is None:
            return {"final"}
        if isinstance(parent, P.Member) and parent.obj is node:
            grand = ctx.parents.get(id(parent))
            if isinstance(grand, P.Call) and grand.callee is parent:
                if parent.name in words.replace:
                    search = self.str_eval(grand.args[0].value, ctx) if grand.args else None
                    fate = f"continued at {id(grand)}"
                    self.fate_literals[fate] = (search,)
                    return {fate}
                if parent.name in words.trim | words.substring:
                    return self.fate(grand, ctx.parents.get(id(grand)), ctx, depth + 1)
            return {"final"}
        if isinstance(parent, (P.NonNull, P.Ternary, P.Coalesce, P.ArrayLit, P.Binary, P.MapLit)):
            return self.fate(parent, ctx.parents.get(id(parent)), ctx, depth + 1)
        if isinstance(parent, P.CallArg):
            call = ctx.parents.get(id(parent))
            target = self.target(call, ctx)
            if target is None:
                if isinstance(call, (P.Call, P.New)):
                    return self.fate(call, ctx.parents.get(id(call)), ctx, depth + 1)
                return {"final"}
            name = _param_name(target.method, call, parent)
            if name is None:
                return {"final"}
            searches = self.replaced_in(target.method, name)
            if searches:
                fate = f"parameter {name} of {id(target.method)}"
                self.fate_literals[fate] = tuple(searches)
                return {fate}
            if self.flows_to_return(target.method, name):
                return self.result_fate(target, depth + 1)
            return {"final"}
        if isinstance(parent, P.Return):
            if ctx.outer is not None:
                literal, literal_parent, outer_ctx = ctx.outer
                return self.fate(literal, literal_parent, outer_ctx, depth + 1)
            return self.result_fate(_Target(ctx.mod, ctx.method), depth + 1)
        if isinstance(parent, P.VarDecl):
            uses = self.var_uses(parent.name, ctx) if ctx.locals.get(parent.name) is parent else []
            if not uses:
                return {"final"}
            out: set[str] = set()
            for use, use_parent in uses:
                out |= self.fate(use, use_parent, ctx, depth + 1)
            return out
        return {"final"}

    def result_fate(self, target: _Target, depth: int) -> set[str]:
        sites = self.callsites.get(target.key, ())
        if not sites:
            return {"final"}
        out: set[str] = set()
        for site in sites:
            out |= self.fate(site.node, site.parent, site.ctx, depth)
        return out

    def replaced_in(self, method: P.Method, name: str) -> list[str | None]:
        """Search strings of the Replace calls applied to the parameter (None - computed)."""
        found = []
        for node, _parent in _walk_with_parents(method):
            if (isinstance(node, P.Call) and isinstance(node.callee, P.Member)
                    and node.callee.name in self.words.replace
                    and isinstance(node.callee.obj, P.Name)
                    and node.callee.obj.name == name and node.args):
                found.append(_literal_value(node.args[0].value))
        return found

    @staticmethod
    def flows_to_return(method: P.Method, name: str) -> bool:
        pattern = re.compile(rf"(?<![\w]){re.escape(name)}(?![\w])")
        for node, _parent in _walk_with_parents(method):
            if not isinstance(node, P.Return) or node.value is None:
                continue
            for inner, _inner_parent in _walk_with_parents(node.value):
                if isinstance(inner, P.Name) and inner.name == name:
                    return True
                if isinstance(inner, P.Literal) and inner.kind == "STRING":
                    if any(ident == name for _s, _e, ident in _interpolation_spans(inner.text)):
                        return True
                    if any(pattern.search(body) for _o, body in _full_interpolations(inner.text)):
                        return True
        return False

    # the chains

    def chain_ends(self) -> list[tuple[_Mod, object, _Val, set[str]]]:
        """Every place a text of a resource leaves the analysis: (module, anchor, value, fate)."""
        ends = []
        for mod in self.mods.values():
            for method in mod.methods.values():
                ctx = self.ctx(mod, method, symbolic=False)
                trees = [ctx] + self.interpolation_ctxs.get((mod.key, method.name), [])
                for tree_ctx in trees:
                    for node, parent in tree_ctx.nodes:
                        if not isinstance(node, P.Expr):
                            continue
                        value = self.ev(node, tree_ctx)
                        if value is None or value.kind in ("empty", "param"):
                            continue
                        if self.continues(node, parent, tree_ctx):
                            continue
                        anchor = tree_ctx.outer[0] if tree_ctx.outer is not None else node
                        ends.append((mod, anchor, value, self.fate(node, parent, tree_ctx)))
                for name, decl in ctx.locals.items():
                    if decl is None or decl.init is None:
                        continue
                    value = self.ev(decl.init, ctx)
                    if value is None or value.kind in ("empty", "param"):
                        continue
                    for literal, literal_parent in self.var_uses(name, ctx):
                        if isinstance(literal, P.Literal):
                            ends.append((mod, literal, value,
                                         self.fate(literal, literal_parent, ctx)))
        return ends

    def file_key(self, path: Path) -> str:
        """The resource as the code names it: the key under its resources folder."""
        item = self.res.resources.get(str(RU._lexical(path)))
        return item.key if item is not None else path.name

    def file_text(self, path: Path) -> tuple[str, str]:
        """(text, text with comment bodies blanked) of a resource file."""
        text = self.texts.get(str(path))
        if text is None:
            text = path.read_text(encoding="utf-8-sig")
        return text, _masked(path, text)

    def findings(self) -> list[_Finding]:
        chains: dict[tuple, dict] = {}
        for mod, anchor, value, fate in self.chain_ends():
            if not any(step.op in ("replace", "unknown", "regex") for step in value.steps):
                continue
            key = (value.kind, value.files,
                   tuple((step.op, step.rel, step.line, step.col, step.search)
                         for step in value.steps))
            line, col = _line_col(mod.text, anchor.start)
            entry = chains.setdefault(key, dict(value=value, ends=[], fates=set()))
            entry["ends"].append((mod.rel, line, col))
            entry["fates"] |= fate
        out: list[_Finding] = []
        seen: set[tuple] = set()
        for entry in chains.values():
            value = entry["value"]
            if value.kind != "file":
                continue
            try:
                result = _evaluate(value, *self.file_text(Path(value.files[0])))
            except (OSError, UnicodeError):
                continue
            later: set[str] = set()
            complete = True
            for fate in entry["fates"]:
                if fate == "final":
                    continue
                searches = self.fate_literals.get(fate)
                if searches is None or any(search is None for search in searches):
                    complete = False
                    continue
                later |= set(searches)
            left = [label for label in result["left"] if label not in later]
            judged = complete and value.exact and result["known"] and not value.mixed
            file = self.file_key(Path(value.files[0]))
            absent = [item for item in result["absent"] if not item["step"].generic]
            for item in absent:
                step = item["step"]
                marker = (ABSENT, step.rel, step.line, step.col, file, step.search)
                if marker in seen:
                    continue
                seen.add(marker)
                where = (i18n.t(f"{ABSENT}.{item['where']}") if item["where"] else "")
                hint = (i18n.t(f"{ABSENT}.renamed", labels=", ".join(left))
                        if judged and left else "")
                out.append(_Finding(ABSENT, step.rel, step.line, step.col, i18n.t(
                    f"{ABSENT}.found", file=file, search=step.search, where=where, hint=hint)))
            if not judged:
                continue
            rel, line, col = min(entry["ends"])
            missing = [item["step"].search for item in absent if not item["where"]]
            for label in left:
                marker = (UNFILLED, rel, line, col, file, label)
                if marker in seen:
                    continue
                seen.add(marker)
                hint = (i18n.t(f"{UNFILLED}.renamed", absent=", ".join(missing)) if missing
                        else "")
                out.append(_Finding(UNFILLED, rel, line, col, i18n.t(
                    f"{UNFILLED}.found", label=label, file=file, hint=hint)))
        return out


def _evaluate(value: _Val, raw: str, masked: str) -> dict:
    """The chain applied to the text of its file: absent searches, labels and what is left."""
    current = masked
    absent, literals, known = [], [], True
    for index, step in enumerate(value.steps):
        sentinel = f"\x00{index}\x00"
        if step.op == "replace":
            literals.append(step.search)
            if step.search not in current:
                if step.search in masked:
                    where = "earlier"
                elif step.search in raw:
                    where = "comment"
                else:
                    where = ""
                absent.append(dict(step=step, where=where))
            else:
                current = current.replace(step.search,
                                          step.value if step.value is not None else sentinel)
        elif step.op == "regex":
            try:
                pattern = re.compile(step.search)
            except re.error:
                known = False
                continue
            replacement = step.value if step.value is not None else sentinel
            current = pattern.sub(lambda _match: replacement, current)
        elif step.op == "trim":
            current = current.strip()
        elif step.op == "unknown":
            known = False
    shape = _label_shape(literals)
    left = sorted(set(shape.findall(current))) if shape else []
    return dict(absent=absent, left=left, known=known)


# --- the run --------------------------------------------------------------------------------


def _project_dir(path: Path, found: dict[Path, Path | None]) -> Path | None:
    """The folder of the project descriptor above the file, looked up once per folder."""
    chain = []
    folder = path.parent
    while True:
        if folder in found:
            result = found[folder]
            break
        chain.append(folder)
        if scaffold.project_file_in(folder) is not None:
            result = folder
            break
        if folder.parent == folder:
            result = None
            break
        folder = folder.parent
    for item in chain:
        found[item] = result
    return result


_cached: tuple[tuple, list[_Finding]] | None = None


def _findings(sources: list[SourceFile]) -> list[_Finding]:
    """The findings of both rules for one run; the second rule reuses the first one's work."""
    global _cached
    code = [source for source in sources if source.kind == "xbsl" and not is_query_file(source.path)]
    words = _words()
    if not any(any(word in source.text for word in words.replace) for source in code):
        return []
    key = tuple((id(source), hash(source.text)) for source in sources)
    if _cached is not None and _cached[0] == key:
        return _cached[1]
    projects: dict[Path, list[tuple[SourceFile, P.Module]]] = defaultdict(list)
    yamls: dict[Path, list[SourceFile]] = defaultdict(list)
    texts: dict[str, str] = {}
    found: dict[Path, Path | None] = {}
    for source in sources:
        path = Path(source.path).resolve()
        root = _project_dir(path, found)
        if root is None:
            continue
        if source.kind == "yaml":
            yamls[root].append(source)
        elif source.kind == "xbsl" and not is_query_file(source.path):
            tree, errors = P.parse(source)
            if not errors and isinstance(tree, P.Module):
                projects[root].append((source, tree))
        else:
            texts[str(path)] = source.text
    out: list[_Finding] = []
    for root, modules in projects.items():
        out.extend(_Project(root, modules, yamls.get(root, []), texts).findings())
    _cached = (key, out)
    return out


def _diagnostics(sources: list[SourceFile], rule_id: str) -> Iterable[Diagnostic]:
    for finding in _findings(sources):
        if finding.rule_id == rule_id:
            yield Diagnostic(finding.rel, finding.line, finding.col, rule_id, Severity.WARNING,
                             finding.message)


@rule(ABSENT, f"{ABSENT}.title", "D", scope="project", severity=Severity.WARNING,
      enabled_by_default=False, off_reason=f"{ABSENT}.off")
def resource_replace_absent(sources: list[SourceFile]) -> Iterable[Diagnostic]:
    """A Replace of a literal that the text of its resource does not contain."""
    yield from _diagnostics(sources, ABSENT)


@rule(UNFILLED, f"{UNFILLED}.title", "D", scope="project", severity=Severity.WARNING,
      enabled_by_default=False, off_reason=f"{UNFILLED}.off")
def resource_label_unfilled(sources: list[SourceFile]) -> Iterable[Diagnostic]:
    """A label of a resource that a complete chain of replacements leaves in place."""
    yield from _diagnostics(sources, UNFILLED)
