"""Tier D: environment (client/server) consistency checks.

The platform assigns every module an environment – Клиент, Сервер or КлиентИСервер (docs
"Исполнение модуля") – and the annotations @НаСервере/@НаКлиенте/@ДоступноСКлиента refine
it per method or type. An environment mismatch is among the most painful failures: the
server-side apply silently rolls the whole project back without pointing at the line.
The checks are all narrow by design (a skipped case is a false negative, never a false
positive); each is project-wide because it needs the paired yaml of the module.

- code/server-call-from-handler: in an interface component module (a form – environment
  Клиент) a client handler – a method named by a handler key in the form's yaml or
  annotated @Обработчик – calls a method of the same module declared @НаСервере without
  @ДоступноСКлиента/@НаКлиенте. The handler runs on the client, so the call fails
  ("unavailable (Клиент)"). Guards: a handler itself annotated @НаСервере runs on the
  server and is skipped; member calls (`х.Имя(...)`) are not bare-module calls; shadowed
  names (see enum_values._shadowed_names), query blocks and comments are excluded.

- code/client-annotation-in-server-module: a common module with `Окружение: Сервер` may
  use only the @НаСервере annotation (docs "Исполнение модуля"), so @ДоступноСКлиента or
  @НаКлиенте in its module contradicts the declared environment – the module has to be
  КлиентИСервер.

- code/client-available-needs-context: @AvailableFromClient on a method of an interface
  component module that is neither `static` nor @Contextual. The environment of such a
  module is Client and its type is not a singleton, so the apply answers `Modifier
  "AvailableFromClient" can only be used in static methods, singleton-type methods, or
  methods with modifier "Contextual"`. Both documented forms are silent: the static server
  call (docs topics/move-execution-from-client-to-server) and the contextual method, which
  is the one that keeps the instance context (docs topics/module-execution). The check is
  confined to interface components on purpose - @Contextual is available in their modules
  alone, and the kinds whose module belongs to a singleton type (a common module, a catalog,
  an information register) accept the plain form.

- code/server-module-in-client-context: the mirror of the check below, and unlike it a
  compile-time failure rather than a runtime one, which is why it is an error. A common
  module with `Environment: Server` may carry only the @OnServer annotation, so nothing in
  it is ever client-available; a module that lives in the Client environment (an interface
  component, a command, a client common module) reaching it as `Module.Member(...)` from a
  method that runs on the client makes the apply refuse the project with
  `<Клиент> Type "X" is unavailable in the current environment` (the environment tag comes
  from the platform verbatim). Only the bodies of methods without @OnServer are read, and
  only the call form is judged.

- code/client-module-in-http-service: a common module with `Окружение: Клиент` does not
  exist on the server, so the module of an HttpСервис (environment Сервер) calling
  `ИмяМодуля.Метод(...)` fails at runtime ("Type unavailable"). Members declared
  @НаСервере inside the client module do exist on the server and are not flagged; a
  member that cannot be resolved in the module is skipped rather than guessed.

- code/component-in-server-context: a `Компонент.Член(...)` access from code compiled
  for the server – a `@НаСервере` method anywhere, or an unannotated method of a module
  whose environment includes the server. The component's type lives on the client, so
  the server compilation refuses with "Переменная X не определена".

The call detection of the first check is exercised by its own tests: a client handler calling
a @НаСервере @ДоступноСКлиента method is found by the same matching and correctly not flagged.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from functools import lru_cache

from xbsl import dataset, i18n, metamodel, terms
from xbsl import parser as P
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, rule
from xbsl.lexer import linemap, tokens
from xbsl.parser import parse
from xbsl.rules._syntax import code_tokens
from xbsl.rules.enum_values import _shadowed_names
from xbsl.rules.handlers import _handler_re, _IDENT_RE
from xbsl.rules.yaml_schema import _HAVE_YAML, _parsed, object_kind, value_of

MESSAGES = {
    "code/client-available-unused.title": {
        "ru": "Метод открыт клиенту, но клиент его не зовёт",
        "en": "A method open to the client that no client calls",
    },
    "code/client-available-unused.unused": {
        "ru": "Метод '{name}' объявлен доступным с клиента, но ни одно клиентское место "
              "проекта его не называет – ни модуль клиентского окружения, ни клиентский метод "
              "серверного модуля, ни yaml, ни строковый литерал. Снимите аннотацию: она "
              "открывает клиенту поверхность, которой никто не пользуется.",
        "en": "Method '{name}' is declared available from the client, yet no client place of "
              "the project names it - neither a module of the client environment, nor a client "
              "method of a server module, nor a yaml, nor a string literal. Drop the "
              "annotation: it opens a surface to the client that nobody uses.",
    },
    "code/server-call-from-handler.title": {
        "ru": "Серверный метод недоступен клиентскому обработчику",
        "en": "Server method is unavailable to a client handler",
    },
    "code/server-call-from-handler.call": {
        "ru": "Клиентский обработчик '{handler}' вызывает метод '{name}', объявленный "
              "@НаСервере без @ДоступноСКлиента – вызов с клиента недоступен.",
        "en": "Client handler '{handler}' calls method '{name}' declared @{n[НаСервере]} "
              "without @{n[ДоступноСКлиента]} – the call is unavailable on the client.",
    },
    "code/client-annotation-in-server-module.title": {
        "ru": "Клиентская аннотация в серверном общем модуле",
        "en": "Client annotation in a server common module",
    },
    "code/client-annotation-in-server-module.annotation": {
        "ru": "Аннотация @{ann} в общем модуле '{module}' с Окружение: Сервер – "
              "допустима только @НаСервере, модулю нужно Окружение: КлиентИСервер.",
        "en": "Annotation @{ann} in common module '{module}' with {n[Окружение]}: {n[Сервер]} – "
              "only @{n[НаСервере]} is allowed, the module needs {n[Окружение]}: {n[КлиентИСервер]}.",
    },
    "code/client-available-needs-context.title": {
        "ru": "Клиентский метод компонента без контекста",
        "en": "Client-available component method without a context",
    },
    "code/client-available-needs-context.method": {
        "ru": "Метод '{name}' модуля компонента интерфейса объявлен @ДоступноСКлиента, но "
              "не статический и без @Контекстный – применение отвергает такой модификатор. "
              "Добавьте @Контекстный, если методу нужен контекст экземпляра, иначе объявите "
              "его статическим.",
        "en": "Method '{name}' of an interface component module is declared "
              "@{n[ДоступноСКлиента]} but is neither {n[статический]} nor @{n[Контекстный]} – "
              "the apply rejects that modifier. Add @{n[Контекстный]} when the method needs "
              "the instance context, otherwise declare it {n[статический]}.",
    },
    "code/server-module-in-client-context.title": {
        "ru": "Серверный общий модуль в клиентском окружении",
        "en": "Server common module in a client environment",
    },
    "code/server-module-in-client-context.call": {
        "ru": "Обращение '{name}' из метода '{method}', исполняемого на клиенте: у общего "
              "модуля '{root}' Окружение: Сервер – на клиенте типа нет. Пометьте метод "
              "@НаСервере либо поднимите модуль до Окружение: КлиентИСервер.",
        "en": "Access '{name}' from method '{method}', which runs on the client: common "
              "module '{root}' has {n[Окружение]}: {n[Сервер]} – the type does not exist on "
              "the client. Annotate the method @{n[НаСервере]}, or raise the module to "
              "{n[Окружение]}: {n[КлиентИСервер]}.",
    },
    "code/client-module-in-http-service.title": {
        "ru": "Клиентский общий модуль в HTTP-сервисе",
        "en": "Client common module in an HTTP service",
    },
    "code/client-module-in-http-service.call": {
        "ru": "Обращение '{name}' из модуля HTTP-сервиса: у общего модуля '{root}' "
              "Окружение: Клиент – на сервере тип недоступен, нужно КлиентИСервер.",
        "en": "Access '{name}' from an HTTP service module: common module '{root}' has "
              "{n[Окружение]}: {n[Клиент]} – the type is unavailable on the server, it needs {n[КлиентИСервер]}.",
    },
}
i18n.register(MESSAGES)

# The environment annotations of the platform (docs "Аннотации окружения"). Both spellings
# of every name: the sources are bilingual, and a project mixes the forms freely - while only
# the Russian ones were matched, an English annotation read as NO annotation and the checks
# below judged the method by the default environment.


@lru_cache(maxsize=1)
def _client_side_ann_forms() -> frozenset[str]:
    """Both spellings of the annotations that put a method on the client side."""
    return frozenset(terms.key_forms("ДоступноСКлиента")) | frozenset(terms.key_forms("НаКлиенте"))


@lru_cache(maxsize=1)
def _handler_ann_forms() -> frozenset[str]:
    """Both spellings of the handler annotation."""
    return frozenset(terms.key_forms("Обработчик"))

# Declaration keywords an annotation block may precede (docs "Исполнение модуля": метод,
# структура, исключение, перечисление, константа).
_DECL_KW = ("METHOD", "CONSTRUCTOR", "STRUCTURE", "ENUMERATION", "EXCEPTION", "CONST")


def _module_decls(toks: list) -> tuple[dict[str, frozenset[str]], list[tuple[str, frozenset[str], int]]]:
    """Module declarations with their annotation sets.

    Returns (decls, methods): decls maps a declared name (method, constructor, structure,
    enumeration, exception, constant) to the frozenset of its annotation names; methods is
    the ordered list of (name, annotations, anchor) for method/constructor declarations,
    where anchor is the token index of the declaring keyword – consecutive anchors of any
    declaration kind delimit method bodies.
    """
    decls: dict[str, frozenset[str]] = {}
    methods: list[tuple[str, frozenset[str], int]] = []
    pending: set[str] = set()
    i, n = 0, len(toks)
    while i < n:
        t = toks[i]
        if (t.kind == "OP" and t.value == "@" and i + 1 < n
                and toks[i + 1].kind in ("IDENT", "KEYWORD")):
            pending.add(toks[i + 1].value)
            i += 2
            # optional annotation arguments, e.g. @JsonСвойство("имя")
            if i < n and toks[i].kind == "OP" and toks[i].value == "(":
                depth = 1
                i += 1
                while i < n and depth:
                    if toks[i].kind == "OP" and toks[i].value == "(":
                        depth += 1
                    elif toks[i].kind == "OP" and toks[i].value == ")":
                        depth -= 1
                    i += 1
            continue
        if t.kind == "KEYWORD" and t.value[:1].islower():
            c = t.canonical
            if c == "STATIC":  # 'статический' sits between the annotations and 'метод'
                i += 1
                continue
            if c in _DECL_KW:
                j = i + 1
                if j < n and toks[j].kind == "IDENT":
                    anns = frozenset(pending)
                    decls[toks[j].value] = anns
                    if c in ("METHOD", "CONSTRUCTOR"):
                        methods.append((toks[j].value, anns, i))
                pending = set()
                i += 1
                continue
        pending = set()
        i += 1
    return decls, methods


def _method_bodies(toks: list, methods: list[tuple[str, frozenset[str], int]],
                   decls_anchors: list[int]) -> dict[str, tuple[int, int]]:
    """Token ranges of method bodies: from past the declaring keyword to the next
    declaration anchor of any kind (a structure between methods is not part of a body)."""
    anchors = sorted(decls_anchors)
    bodies: dict[str, tuple[int, int]] = {}
    n = len(toks)
    for name, _, anchor in methods:
        start = anchor + 1
        nxt = [a for a in anchors if a > anchor]
        bodies[name] = (start, nxt[0] if nxt else n)
    return bodies


def _decl_anchors(toks: list) -> list[int]:
    return [
        i for i, t in enumerate(toks)
        if t.kind == "KEYWORD" and t.value[:1].islower() and t.canonical in _DECL_KW
    ]


def _pair_stem(rel: str) -> str:
    """The pairing key of X.yaml <-> X.xbsl: the rel path without the last extension."""
    slash = rel.replace("\\", "/")
    return slash[: slash.rfind(".")] if "." in slash.rsplit("/", 1)[-1] else slash


def _parsed_object(source: SourceFile) -> dict | None:
    """The parsed yaml of a project object (with a ВидЭлемента), else None."""
    data, err = _parsed(source)
    if err is None and isinstance(data, dict) and object_kind(data):
        return data
    return None


def _server_call_mapper(source: SourceFile) -> dict | None:
    """The map phase. The yaml of an interface component contributes its handler names;
    the module contributes, per method: the annotations and the bare calls of its own
    @НаСервере-without-client methods (all the local skips are settled here). The reduce
    joins the pair and picks the client handlers."""
    if not _HAVE_YAML:
        return None
    if source.kind == "yaml":
        data = _parsed_object(source)
        if data is None or object_kind(data) != "КомпонентИнтерфейса":
            return None
        handlers = []
        for m in _handler_re().finditer(source.text):
            value = m.group(1).strip()
            if _IDENT_RE.match(value):
                handlers.append(value)
        return {"k": "y", "stem": _pair_stem(source.rel), "handlers": handlers}
    if source.kind != "xbsl":
        return None
    toks = code_tokens(source)
    decls, methods = _module_decls(toks)
    method_anns = {name: anns for name, anns, _ in methods}
    server_only = {
        name for name, anns in method_anns.items()
        if (anns & _on_server_forms()) and not (anns & _client_side_ann_forms())
    }
    if not server_only:
        return None
    bodies = _method_bodies(toks, methods, _decl_anchors(toks))
    shadowed = _shadowed_names(toks)
    n = len(toks)
    calls: dict[str, list[tuple[str, int, int]]] = {}
    for name, (start, end) in bodies.items():
        for i in range(start, end):
            t = toks[i]
            if t.kind != "IDENT" or t.value not in server_only or t.value in shadowed:
                continue
            if i > 0 and toks[i - 1].kind == "OP" and toks[i - 1].value == ".":
                continue  # a member of another object, not a bare module method
            if not (i + 1 < n and toks[i + 1].kind == "OP" and toks[i + 1].value == "("):
                continue  # not a call
            calls.setdefault(name, []).append((t.value, t.line, t.col))
    if not calls:
        return None
    return {
        "k": "x",
        "stem": _pair_stem(source.rel),
        "anns": {name: sorted(anns) for name, anns in method_anns.items()},
        "calls": calls,
    }


@rule(
    "code/server-call-from-handler", "code/server-call-from-handler.title", "D",
    scope="project", severity=Severity.WARNING, mapper=_server_call_mapper,
)
def server_call_from_handler(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    yaml_handlers: dict[str, list[str]] = {}
    for fact in facts.values():
        if fact["k"] == "y":
            yaml_handlers[fact["stem"]] = fact["handlers"]
    for rel, fact in facts.items():
        if fact["k"] != "x" or fact["stem"] not in yaml_handlers:
            continue
        anns = fact["anns"]
        handlers = set(yaml_handlers[fact["stem"]])
        handlers.update(
            name for name, a in anns.items() if not _handler_ann_forms().isdisjoint(a)
        )
        for handler in sorted(handlers):
            a = anns.get(handler)
            if a is None or not _on_server_forms().isdisjoint(a):
                continue  # not found in the module, or runs on the server itself
            for name, line, col in fact["calls"].get(handler, ()):
                yield Diagnostic(
                    rel, line, col, "code/server-call-from-handler",
                    Severity.WARNING,
                    i18n.t("code/server-call-from-handler.call",
                           handler=handler, name=name),
                )


def _client_ann_mapper(source: SourceFile) -> dict | None:
    """The map phase: a yaml contributes its server common modules, a module its client
    annotation positions - the reduce joins the pair."""
    if not _HAVE_YAML:
        return None
    if source.kind == "yaml":
        data = _parsed_object(source)
        kind = object_kind(data) if data is not None else None
        if kind != "ОбщийМодуль":
            return None
        server_env, _client_env = _environment_forms()
        if value_of(data, "Окружение", kind) not in server_env:
            return None
        name = value_of(data, "Имя", kind)
        if not isinstance(name, str):
            return None
        return {"k": "y", "stem": _pair_stem(source.rel), "name": name}
    if source.kind != "xbsl":
        return None
    toks = code_tokens(source)
    n = len(toks)
    anns: list[tuple[str, int, int]] = []
    for i, t in enumerate(toks):
        if (t.kind == "OP" and t.value == "@" and i + 1 < n
                and toks[i + 1].kind == "IDENT"
                and toks[i + 1].value in _client_side_ann_forms()):
            a = toks[i + 1]
            anns.append((a.value, a.line, a.col))
    if not anns:
        return None
    return {"k": "x", "stem": _pair_stem(source.rel), "anns": anns}


@rule(
    "code/client-annotation-in-server-module",
    "code/client-annotation-in-server-module.title", "D",
    scope="project", severity=Severity.WARNING, mapper=_client_ann_mapper,
)
def client_annotation_in_server_module(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    server_modules: dict[str, str] = {}
    for fact in facts.values():
        if fact["k"] == "y":
            server_modules[fact["stem"]] = fact["name"]
    if not server_modules:
        return
    for rel, fact in facts.items():
        if fact["k"] != "x":
            continue
        name = server_modules.get(fact["stem"])
        if name is None:
            continue
        for ann, line, col in fact["anns"]:
            yield Diagnostic(
                rel, line, col, "code/client-annotation-in-server-module",
                Severity.WARNING,
                i18n.t("code/client-annotation-in-server-module.annotation",
                       ann=ann, module=name),
            )


@lru_cache(maxsize=1)
def _context_ann_forms() -> tuple[frozenset[str], frozenset[str]]:
    """Both spellings of the two annotations this check reads (from terms.json)."""
    return (frozenset(terms.key_forms("ДоступноСКлиента")),
            frozenset(terms.key_forms("Контекстный")))


dataset.register_reset(_context_ann_forms.cache_clear)


def _client_context_mapper(source: SourceFile) -> dict | None:
    """The map phase: a yaml marks its pair as an interface component, a module contributes
    the methods it declares @AvailableFromClient without a context - the reduce joins the
    pair.

    Only module-level methods are judged: the members of a structure or an enumeration
    declared in the module belong to their own type, and a structure extends its own type
    from the module of that structure anyway (docs topics/structure-type)."""
    if not _HAVE_YAML:
        return None
    if source.kind == "yaml":
        data = _parsed_object(source)
        if data is None or object_kind(data) != "КомпонентИнтерфейса":
            return None
        return {"k": "y", "stem": _pair_stem(source.rel)}
    if source.kind != "xbsl":
        return None
    available, contextual = _context_ann_forms()
    if not any(name in source.text for name in available):
        return None
    module, errors = parse(source)
    if errors:
        return None  # a broken file is code/parse-error territory
    hits: list[tuple[str, int, int]] = []
    lm = linemap(source)
    for member in module.members:
        if not isinstance(member, P.Method) or member.is_static:
            continue
        anns = {a.name for a in member.annotations}
        if not (anns & available) or (anns & contextual):
            continue
        line, col = lm.linecol(member.start)
        hits.append((member.name, line, col))
    if not hits:
        return None
    return {"k": "x", "stem": _pair_stem(source.rel), "hits": hits}


@rule(
    "code/client-available-needs-context",
    "code/client-available-needs-context.title", "D",
    scope="project", severity=Severity.ERROR, mapper=_client_context_mapper,
)
def client_available_needs_context(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    components = {fact["stem"] for fact in facts.values() if fact["k"] == "y"}
    if not components:
        return
    for rel, fact in facts.items():
        if fact["k"] != "x" or fact["stem"] not in components:
            continue
        for name, line, col in fact["hits"]:
            yield Diagnostic(
                rel, line, col, "code/client-available-needs-context",
                Severity.ERROR,
                i18n.t("code/client-available-needs-context.method", name=name),
            )


# Kinds whose module exists in the Client environment by default (docs topics/module-execution).
# A common module is judged by its own `Environment` instead, and a structure element is left
# out: the docs give it the environment of the project element, which its yaml does not settle.
_CLIENT_ENV_KINDS = ("КомпонентИнтерфейса", "НавигационнаяКоманда", "ОбычнаяКоманда",
                     "ПереключаемаяКоманда", "ХранимаяСтруктура")


@lru_cache(maxsize=1)
def _environment_forms() -> tuple[frozenset[str], frozenset[str]]:
    """Both spellings of the two `Environment` values this check reads (from terms.json)."""
    def forms(value: str) -> frozenset[str]:
        return frozenset({value, terms.english(value, "enums") or value})
    return forms("Сервер"), forms("Клиент")


@lru_cache(maxsize=1)
def _client_side_environments() -> frozenset[str]:
    """Both spellings of every `Environment` value whose module runs on the client.

    Taken from the enumeration of the metamodel rather than matched as a substring: the two
    values that include the client are `Client` and `ClientAndServer`, and each English
    spelling comes from the term dictionary, never from a translation.
    """
    return frozenset(
        form
        for value in metamodel.enum_values("EEnvironmentKind")
        if "Клиент" in value
        for form in (value, terms.english(value, "enums"))
        if form
    )


@lru_cache(maxsize=1)
def _on_server_forms() -> frozenset[str]:
    """Both spellings of the @OnServer annotation (from terms.json)."""
    return frozenset(terms.key_forms("НаСервере"))


dataset.register_reset(_environment_forms.cache_clear)
dataset.register_reset(_client_side_environments.cache_clear)
dataset.register_reset(_on_server_forms.cache_clear)


def _server_module_mapper(source: SourceFile) -> dict | None:
    """The map phase. A yaml names its pair either a server common module or a module that
    lives in the Client environment; a module contributes the bare `Module.Member(...)`
    accesses of the methods that run on the client. The reduce joins the pairs.

    A method annotated @OnServer executes on the server, where the type does exist, so its
    body is not read at all - which is also why a method carrying both @OnServer and
    @OnClient is skipped rather than guessed."""
    if not _HAVE_YAML:
        return None
    if source.kind == "yaml":
        data = _parsed_object(source)
        if data is None:
            return None
        kind = object_kind(data)
        server_env, client_env = _environment_forms()
        if kind == "ОбщийМодуль":
            env = value_of(data, "Окружение", kind)
            if env in server_env:
                name = value_of(data, "Имя", kind)
                if not isinstance(name, str):
                    return None
                return {"k": "y", "stem": _pair_stem(source.rel),
                        "role": "server", "name": name}
            if env in client_env:
                return {"k": "y", "stem": _pair_stem(source.rel), "role": "client"}
            return None
        if kind in _CLIENT_ENV_KINDS:
            return {"k": "y", "stem": _pair_stem(source.rel), "role": "client"}
        return None
    if source.kind != "xbsl":
        return None
    toks = code_tokens(source)
    _decls, methods = _module_decls(toks)
    on_server = _on_server_forms()
    client_side = [m for m in methods if not (m[1] & on_server)]
    if not client_side:
        return None
    bodies = _method_bodies(toks, client_side, _decl_anchors(toks))
    shadowed = _shadowed_names(toks)
    n = len(toks)
    accesses: list[tuple[str, str, str, int, int]] = []
    for method, (start, end) in bodies.items():
        for i in range(start, min(end, n)):
            t = toks[i]
            if t.kind != "IDENT" or t.value in shadowed:
                continue
            if i > 0 and toks[i - 1].kind == "OP" and toks[i - 1].value == ".":
                continue  # a member of another object, not the module
            if not (i + 3 < n and toks[i + 1].kind == "OP" and toks[i + 1].value == "."
                    and toks[i + 2].kind == "IDENT"
                    and toks[i + 3].kind == "OP" and toks[i + 3].value == "("):
                continue  # only `Модуль.Член(...)` accesses are checked
            accesses.append((t.value, toks[i + 2].value, method, t.line, t.col))
    if not accesses:
        return None
    return {"k": "x", "stem": _pair_stem(source.rel), "accesses": accesses}


@rule(
    "code/server-module-in-client-context",
    "code/server-module-in-client-context.title", "D",
    scope="project", severity=Severity.ERROR, mapper=_server_module_mapper,
)
def server_module_in_client_context(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    server_names: set[str] = set()
    client_stems: set[str] = set()
    for fact in facts.values():
        if fact["k"] != "y":
            continue
        if fact["role"] == "server":
            server_names.add(fact["name"])
        else:
            client_stems.add(fact["stem"])
    if not server_names or not client_stems:
        return
    for rel, fact in facts.items():
        if fact["k"] != "x" or fact["stem"] not in client_stems:
            continue
        for root, member, method, line, col in fact["accesses"]:
            if root not in server_names:
                continue
            yield Diagnostic(
                rel, line, col, "code/server-module-in-client-context",
                Severity.ERROR,
                i18n.t("code/server-module-in-client-context.call",
                       name=f"{root}.{member}", method=method, root=root),
            )


def _client_http_mapper(source: SourceFile) -> dict | None:
    """The map phase. A yaml marks its pair as a client common module or an HTTP service;
    a module contributes its declarations (with the НаСервере bit) and its bare
    `Модуль.Член(...)` accesses with the local skips settled. The reduce joins the pairs
    and matches the accesses of the HTTP service modules against the client modules."""
    if not _HAVE_YAML:
        return None
    if source.kind == "yaml":
        data = _parsed_object(source)
        if data is None:
            return None
        kind = object_kind(data)
        _server_env, client_env = _environment_forms()
        name = value_of(data, "Имя", kind)
        if (kind == "ОбщийМодуль" and value_of(data, "Окружение", kind) in client_env
                and isinstance(name, str)):
            return {"k": "y", "stem": _pair_stem(source.rel),
                    "role": "client", "name": name}
        if kind == "HttpСервис":
            return {"k": "y", "stem": _pair_stem(source.rel), "role": "http"}
        return None
    if source.kind != "xbsl":
        return None
    toks = code_tokens(source)
    decls, _methods = _module_decls(toks)
    shadowed = _shadowed_names(toks)
    n = len(toks)
    accesses: list[tuple[str, str, int, int]] = []
    for i, t in enumerate(toks):
        if t.kind != "IDENT" or t.value in shadowed:
            continue
        if i > 0 and toks[i - 1].kind == "OP" and toks[i - 1].value == ".":
            continue  # a member of another object, not the module
        if not (i + 3 < n and toks[i + 1].kind == "OP" and toks[i + 1].value == "."
                and toks[i + 2].kind == "IDENT"
                and toks[i + 3].kind == "OP" and toks[i + 3].value == "("):
            continue  # only `Модуль.Член(...)` accesses are checked
        accesses.append((t.value, toks[i + 2].value, t.line, t.col))
    if not decls and not accesses:
        return None
    return {
        "k": "x",
        "stem": _pair_stem(source.rel),
        "server_bit": {name: bool(anns & _on_server_forms()) for name, anns in decls.items()},
        "accesses": accesses,
    }


@rule(
    "code/client-module-in-http-service",
    "code/client-module-in-http-service.title", "D",
    scope="project", severity=Severity.WARNING, mapper=_client_http_mapper,
)
def client_module_in_http_service(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    client_stems: dict[str, str] = {}   # stem -> module name
    http_stems: set[str] = set()
    for fact in facts.values():
        if fact["k"] != "y":
            continue
        if fact["role"] == "client":
            client_stems[fact["stem"]] = fact["name"]
        else:
            http_stems.add(fact["stem"])
    if not client_stems or not http_stems:
        return
    client_bits: dict[str, dict[str, bool]] = {}  # module name -> {member: НаСервере?}
    for fact in facts.values():
        if fact["k"] == "x" and fact["stem"] in client_stems:
            client_bits[client_stems[fact["stem"]]] = fact["server_bit"]
    if not client_bits:
        return
    for rel, fact in facts.items():
        if fact["k"] != "x" or fact["stem"] not in http_stems:
            continue
        for root, member, line, col in fact["accesses"]:
            bits = client_bits.get(root)
            if bits is None:
                continue
            on_server = bits.get(member)
            if on_server is None or on_server:
                continue  # unresolved member, or one that does exist on the server
            yield Diagnostic(
                rel, line, col, "code/client-module-in-http-service",
                Severity.WARNING,
                i18n.t("code/client-module-in-http-service.call",
                       name=f"{root}.{member}", root=root),
            )


# --- A query block in a method that compiles as client code -----------------------------

MESSAGES_QUERY = {
    "code/query-needs-server.title": {
        "ru": "Запрос в методе без @НаСервере",
        "en": "Query in a method without @{n[НаСервере]}",
    },
    "code/query-needs-server.found": {
        "ru": "Блок Запрос{{}} в методе '{name}' без @НаСервере: модуль исполняется на "
              "клиенте ({env}), тип Запрос там недоступен – компилятор откажет.",
        "en": "A {n[Запрос]}{{}} block in method '{name}' without @{n[НаСервере]}: the module runs "
              "on the client ({env}), where the type {n[Запрос]} does not exist - the compiler "
              "will reject it.",
    },
}
i18n.register(MESSAGES_QUERY)


def _client_environment(data: dict) -> str | None:
    """The environment label when the module provably runs on the client, else None.

    Only the two kinds whose client side is beyond doubt are judged: a form module (an
    interface component is client code by definition) and a common module that says so
    itself. Everything else - HttpСервис, object and manager modules of catalogs and
    registers, the kinds without a documented environment - is left alone: a missed case
    is a false negative, a guessed one would be a false positive on working code.
    """
    kind = object_kind(data)
    if kind == "КомпонентИнтерфейса":
        return "Клиент"
    if kind == "ОбщийМодуль":
        env = value_of(data, "Окружение", kind)
        if isinstance(env, str) and env in _client_side_environments():
            return env
    return None


def _query_openings(source: SourceFile) -> list[tuple[int, int, int]]:
    """(line, col, offset of the `{`) of every `Запрос{...}` block.

    The `{` is what tells a query literal from a variable that happens to be named Запрос -
    the lexer reports the word as a keyword in both cases. The position returned is the
    keyword's, which is where the compiler points as well.
    """
    toks = tokens(source)
    n = len(toks)
    out: list[tuple[int, int, int]] = []
    for i, t in enumerate(toks):
        if not (t.kind == "KEYWORD" and t.canonical == "QUERY"):
            continue
        j = i + 1
        while j < n and toks[j].kind == "COMMENT":
            j += 1
        if j < n and toks[j].kind == "OP" and toks[j].value == "{":
            out.append((t.line, t.col, toks[j].start))
    return out


def _query_server_mapper(source: SourceFile) -> dict | None:
    """The map phase: the yaml says whether the module runs on the client, the module says
    which of its methods hold a query block without @НаСервере (position of the block)."""
    if not _HAVE_YAML:
        return None
    if source.kind == "yaml":
        data = _parsed_object(source)
        if data is None:
            return None
        env = _client_environment(data)
        if env is None:
            return None
        return {"k": "y", "stem": _pair_stem(source.rel), "env": env}
    if source.kind != "xbsl":
        return None
    openings = _query_openings(source)
    if not openings:
        return None
    toks = code_tokens(source)
    if not toks:
        return None
    _decls, methods = _module_decls(toks)
    bodies = _method_bodies(toks, methods, _decl_anchors(toks))
    anns = {name: a for name, a, _ in methods}
    found: list[tuple[str, int, int]] = []
    for name, (start, end) in bodies.items():
        if (anns.get(name, frozenset()) & _on_server_forms()) or start >= len(toks):
            continue
        lo = toks[start].start
        hi = toks[end - 1].end if end - 1 < len(toks) else len(source.text)
        for line, col, brace in openings:
            if lo <= brace < hi:
                found.append((name, line, col))
                break  # one finding per method: the fix is the same annotation
    return {"k": "x", "stem": _pair_stem(source.rel), "queries": found} if found else None


@rule(
    "code/query-needs-server", "code/query-needs-server.title", "D",
    scope="project", severity=Severity.ERROR, mapper=_query_server_mapper,
)
def query_needs_server(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    """A `Запрос{...}` block in a client-side method - the compiler rejects such a project.

    Checked on a two-subsystem probe built and applied on a server: in a common module with
    `Окружение: КлиентИСервер`, the method carrying @НаСервере compiles as `<Сервер>` and the
    one without it as `<Клиент>`, failing with `Type "Запрос" is unavailable in the current
    environment`. Neither a blank line nor a comment between the annotation block and the
    method breaks their bond - that was checked on the same probe, so nothing here judges
    the layout; only the presence of the annotation counts.

    This is the check that pays for the class of errors where inserting a method by a text
    anchor steals the annotations of its neighbour: the robbed method loses @НаСервере, and
    the compiler then reports it far from the cause. A client-side method holding a query is
    expected to carry @НаСервере - the rule is a guard.
    """
    client_stems: dict[str, str] = {}
    for fact in facts.values():
        if fact["k"] == "y":
            client_stems[fact["stem"]] = fact["env"]
    if not client_stems:
        return
    for rel, fact in facts.items():
        if fact["k"] != "x":
            continue
        env = client_stems.get(fact["stem"])
        if env is None:
            continue
        for name, line, col in fact["queries"]:
            yield Diagnostic(
                rel, line, col, "code/query-needs-server", Severity.ERROR,
                i18n.t("code/query-needs-server.found", name=name, env=env),
            )


# --- A global name outside its environment ----------------------------------------------

MESSAGES_GLOBALS = {
    "code/global-unavailable.title": {
        "ru": "Глобальное имя вне своего окружения",
        "en": "A global name outside its environment",
    },
    "code/global-unavailable.on-server": {
        "ru": "Глобальное имя '{name}' существует только на клиенте, а метод '{method}' "
              "исполняется на сервере – применение отвечает \"Метод недоступен в текущем "
              "окружении\". Перенесите вызов в клиентский код (метод @НаКлиенте, модуль "
              "формы или команды).",
        "en": "The global name '{name}' exists on the client only, while method "
              "'{method}' runs on the server - the apply answers \"the method is "
              "unavailable in the current environment\". Move the call to client code "
              "(a @{n[НаКлиенте]} method, a form or command module).",
    },
    "code/global-unavailable.on-client": {
        "ru": "Глобальное имя '{name}' существует только на сервере, а метод '{method}' "
              "исполняется на клиенте – пометьте его @НаСервере.",
        "en": "The global name '{name}' exists on the server only, while method "
              "'{method}' runs on the client - annotate it @{n[НаСервере]}.",
    },
}
i18n.register(MESSAGES_GLOBALS)

# Kinds whose modules exist in the Server environment (docs topics/module-execution);
# a common module is judged by its own `Environment`, as everywhere in this file.
_SERVER_ENV_KINDS = ("HttpСервис", "КлючДоступа", "Пользователи", "ПроцессИнтеграции",
                     "РегистрСведений", "Справочник")


_globals_env_cache: dict[str, str] | None = None


def _global_availability() -> dict[str, str]:
    """Global name -> its environment, for the names whose docs print one (Сообщить -
    Клиент, Вычислить - Сервер); the names available everywhere carry КлиентИСервер."""
    global _globals_env_cache
    if _globals_env_cache is None:
        try:
            data = dataset.load_json("stdlib.json")
        except Exception:  # noqa: BLE001 - no data, no rule
            data = {}
        _globals_env_cache = data.get("global_availability") or {}
    return _globals_env_cache


def _reset_globals_env() -> None:
    global _globals_env_cache
    _globals_env_cache = None


dataset.register_reset(_reset_globals_env)


@lru_cache(maxsize=1)
def _on_client_forms() -> frozenset[str]:
    """Both spellings of the @НаКлиенте annotation (from terms.json)."""
    return frozenset(terms.key_forms("НаКлиенте"))


dataset.register_reset(_on_client_forms.cache_clear)


def _global_env_mapper(source: SourceFile) -> dict | None:
    """The map phase. The yaml names the environment role of its pair (a server-kind
    element or a common module with an explicit `Environment`); the module contributes its
    bare calls of one-environment globals, each with the execution side of its method:
    @НаСервере pins the server, @НаКлиенте pins the client (living reference code carries
    @НаКлиенте methods inside catalog modules), no annotation leaves the module's own
    environment. A method carrying both runs where it is called from and is skipped
    rather than guessed - as in the other checks of this file.
    """
    if not _HAVE_YAML:
        return None
    if source.kind == "yaml":
        data = _parsed_object(source)
        if data is None:
            return None
        kind = object_kind(data)
        server_env, client_env = _environment_forms()
        if kind == "ОбщийМодуль":
            env = value_of(data, "Окружение", kind)
            if env in server_env:
                return {"k": "y", "stem": _pair_stem(source.rel), "role": "server"}
            if env in client_env:
                return {"k": "y", "stem": _pair_stem(source.rel), "role": "client"}
            return None
        if kind in _SERVER_ENV_KINDS:
            return {"k": "y", "stem": _pair_stem(source.rel), "role": "server"}
        if kind in _CLIENT_ENV_KINDS:
            return {"k": "y", "stem": _pair_stem(source.rel), "role": "client"}
        return None
    if source.kind != "xbsl":
        return None
    availability = _global_availability()
    if not availability:
        return None
    toks = code_tokens(source)
    decls, methods = _module_decls(toks)
    on_server = _on_server_forms()
    on_client = _on_client_forms()
    bodies = _method_bodies(toks, methods, _decl_anchors(toks))
    anns = {name: a for name, a, _ in methods}
    shadowed = _shadowed_names(toks)
    n = len(toks)
    calls: list[list] = []
    for method, (start, end) in bodies.items():
        method_anns = anns.get(method, frozenset())
        server_ann = bool(method_anns & on_server)
        client_ann = bool(method_anns & on_client)
        if server_ann and client_ann:
            continue  # runs where called from - not judged
        side = "server" if server_ann else "client" if client_ann else "module"
        for i in range(start, min(end, n)):
            t = toks[i]
            if t.kind != "IDENT":
                continue
            env = availability.get(t.value)
            if env is None or env == "КлиентИСервер":
                continue
            if t.value in shadowed or t.value in decls:
                continue  # the project gives the name its own meaning
            if i > 0 and toks[i - 1].kind == "OP" and toks[i - 1].value == ".":
                continue  # a member of something, not the global
            if not (i + 1 < n and toks[i + 1].kind == "OP" and toks[i + 1].value == "("):
                continue  # only the call form is judged
            calls.append([t.value, env, method, side, t.line, t.col])
    if not calls:
        return None
    return {"k": "x", "stem": _pair_stem(source.rel), "calls": calls}


@rule(
    "code/global-unavailable", "code/global-unavailable.title", "D",
    scope="project", severity=Severity.ERROR, mapper=_global_env_mapper,
)
def global_unavailable(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    """A call of a one-environment global from code that runs in the other environment.

    The environments come from the docs: the standard module environments by element kind
    (topics/module-execution) and the per-member "Доступность" lines of the global context
    packages (`Сообщить` - Клиент, `Вычислить`/`Пауза` - Сервер). A method executes in
    its module's environment unless an annotation pins the side: @НаСервере is server
    anywhere, @НаКлиенте is client anywhere (catalog modules of living reference code carry
    such methods). A client-only global in server-side code is the shape that passed the
    linter and failed a live apply with "Метод \"Сообщить\" недоступен в текущем
    окружении"; the server-only global in client-side code is the same refusal mirrored.
    """
    roles: dict[str, str] = {}
    for fact in facts.values():
        if fact["k"] == "y":
            roles[fact["stem"]] = fact["role"]
    if not roles:
        return
    for rel, fact in facts.items():
        if fact["k"] != "x":
            continue
        stem = fact["stem"]
        # The entity's own modules: X.xbsl pairs the yaml outright, X.Объект.xbsl adds
        # one dotted suffix to the same stem.
        role = roles.get(stem) or roles.get(stem.rsplit(".", 1)[0])
        if role is None:
            continue
        for name, env, method, side, line, col in fact["calls"]:
            runs_on = role if side == "module" else side
            if env == "Клиент" and runs_on == "server":
                message = i18n.t("code/global-unavailable.on-server",
                                 name=name, method=method)
            elif env == "Сервер" and runs_on == "client":
                message = i18n.t("code/global-unavailable.on-client",
                                 name=name, method=method)
            else:
                continue
            yield Diagnostic(
                rel, line, col, "code/global-unavailable", Severity.ERROR, message,
            )


# --- An interface component referenced from server-compiled code ------------------------

MESSAGES_COMPONENT = {
    "code/component-in-server-context.title": {
        "ru": "Компонент интерфейса в серверном окружении",
        "en": "Interface component in a server environment",
    },
    "code/component-in-server-context.call": {
        "ru": "Обращение '{name}' из метода '{method}', который компилируется для "
              "серверного окружения: '{root}' – компонент интерфейса, он существует "
              "только на клиенте, и на сервере компиляция откажет (\"Переменная {root} "
              "не определена\"). Пометьте метод @НаКлиенте либо перенесите обращение "
              "в клиентский код.",
        "en": "Access '{name}' from method '{method}', which is compiled for the server "
              "environment: '{root}' is an interface component and exists on the client "
              "only – the server compilation refuses (\"Variable {root} is not defined\"). "
              "Annotate the method @{n[НаКлиенте]} or move the access to client code.",
    },
}
i18n.register(MESSAGES_COMPONENT)


@lru_cache(maxsize=1)
def _both_env_forms() -> frozenset[str]:
    """Both spellings of the client-and-server environment value (from terms.json)."""
    return frozenset({"КлиентИСервер", terms.english("КлиентИСервер", "enums") or "КлиентИСервер"})


dataset.register_reset(_both_env_forms.cache_clear)


def _component_env_mapper(source: SourceFile) -> dict | None:
    """The map phase. Every project yaml contributes its element's name and kind (the
    component names and their possible namesakes are only known in the reduce) plus the
    environment role of its pair; a module contributes its bare `Имя.Член(...)` accesses,
    each with the execution side of its method, exactly as in _global_env_mapper.

    The roles differ from that mapper in one value: a common module (or a structure) with
    `Environment: ClientAndServer` is `both` – an unannotated method of such a module is
    compiled for BOTH environments, so a component reference in it fails the server half
    even when every runtime path is client-side. That is the exact shape of the live
    failure this rule encodes. An enumeration module is `both` by the standard
    environments table (docs topics/module-execution)."""
    if not _HAVE_YAML:
        return None
    if source.kind == "yaml":
        data = _parsed_object(source)
        if data is None:
            return None
        kind = object_kind(data)
        server_env, client_env = _environment_forms()
        role = None
        if kind in ("ОбщийМодуль", "Структура"):
            env = value_of(data, "Окружение", kind)
            if env in server_env:
                role = "server"
            elif env in client_env:
                role = "client"
            elif env in _both_env_forms():
                role = "both"
        elif kind in _SERVER_ENV_KINDS:
            role = "server"
        elif kind in _CLIENT_ENV_KINDS:
            role = "client"
        elif kind == "Перечисление":
            role = "both"
        name = value_of(data, "Имя", kind)
        if not isinstance(name, str):
            name = None
        if role is None and name is None:
            return None
        return {"k": "y", "stem": _pair_stem(source.rel), "role": role,
                "name": name, "kind": kind}
    if source.kind != "xbsl":
        return None
    toks = code_tokens(source)
    decls, methods = _module_decls(toks)
    on_server = _on_server_forms()
    on_client = _on_client_forms()
    bodies = _method_bodies(toks, methods, _decl_anchors(toks))
    anns = {name: a for name, a, _ in methods}
    shadowed = _shadowed_names(toks)
    n = len(toks)
    accesses: list[list] = []
    for method, (start, end) in bodies.items():
        method_anns = anns.get(method, frozenset())
        server_ann = bool(method_anns & on_server)
        client_ann = bool(method_anns & on_client)
        if server_ann and client_ann:
            continue  # runs where called from - not judged
        side = "server" if server_ann else "client" if client_ann else "module"
        if side == "client":
            continue  # pinned to the client - the component is at home there
        for i in range(start, min(end, n)):
            t = toks[i]
            if t.kind != "IDENT" or t.value in shadowed or t.value in decls:
                continue
            if i > 0 and toks[i - 1].kind == "OP" and toks[i - 1].value == ".":
                continue  # a member of another object, not the bare name
            if not (i + 3 < n and toks[i + 1].kind == "OP" and toks[i + 1].value == "."
                    and toks[i + 2].kind == "IDENT"
                    and toks[i + 3].kind == "OP" and toks[i + 3].value == "("):
                continue  # only `Имя.Член(...)` accesses are judged
            accesses.append([t.value, toks[i + 2].value, method, side, t.line, t.col])
    if not accesses:
        return None
    return {"k": "x", "stem": _pair_stem(source.rel), "accesses": accesses}


@rule(
    "code/component-in-server-context",
    "code/component-in-server-context.title", "D",
    scope="project", severity=Severity.ERROR, mapper=_component_env_mapper,
)
def component_in_server_context(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    """A qualified access to an interface component from code compiled for the server.

    The component's type lives in the Client environment (docs topics/module-execution),
    so its name is simply not declared on the server: the apply refuses with
    "Переменная X не определена" – after the linter said nothing and the stand silently
    rolled back to the previous build. Flagged are the accesses of `@НаСервере` methods
    anywhere and of unannotated methods in server or client-and-server modules; a name
    that also belongs to a non-component element somewhere in the project (a namesake
    across subsystems) is left alone rather than guessed.
    """
    components: set[str] = set()
    other_kinds: set[str] = set()
    roles: dict[str, str] = {}
    for fact in facts.values():
        if fact["k"] != "y":
            continue
        if fact["role"] is not None:
            roles[fact["stem"]] = fact["role"]
        name = fact.get("name")
        if name:
            if fact.get("kind") == "КомпонентИнтерфейса":
                components.add(name)
            else:
                other_kinds.add(name)
    judged = components - other_kinds
    if not judged:
        return
    for rel, fact in facts.items():
        if fact["k"] != "x":
            continue
        stem = fact["stem"]
        role = roles.get(stem) or roles.get(stem.rsplit(".", 1)[0])
        for root, member, method, side, line, col in fact["accesses"]:
            if root not in judged:
                continue
            runs_on = role if side == "module" else side
            if runs_on not in ("server", "both"):
                continue
            yield Diagnostic(
                rel, line, col, "code/component-in-server-context", Severity.ERROR,
                i18n.t("code/component-in-server-context.call",
                       name=f"{root}.{member}", method=method, root=root),
            )


# --- code/client-available-unused ------------------------------------------------------------

#: Every word-like token of a text: a mention of a method by name, wherever it is written.
_WORDS_RE = re.compile(r"[^\W\d]\w*", re.UNICODE)


def _client_use_mapper(source: SourceFile) -> dict | None:
    """The map phase: who is declared available to the client, and what the CLIENT names.

    A module cannot tell whether its own pair runs on the client - that is in the other file
    of the pair - so it hands the reduce two disjoint word sets: the ones that are a client
    mention wherever this module runs (a string literal, the body of an `@OnClient` method)
    and everything else. The reduce adds the second set only for a module whose pair does run
    on the client.
    """
    if not _HAVE_YAML:
        return None
    if source.kind == "yaml":
        data = _parsed_object(source)
        if data is None:
            return None
        # A yaml wires handlers by name, and the interface it describes is client code.
        return {"k": "y", "stem": _pair_stem(source.rel),
                "client": bool(object_kind(data) in _CLIENT_ENV_KINDS or _client_environment(data)),
                "words": sorted(set(_WORDS_RE.findall(source.text)))}
    if source.kind != "xbsl":
        return None
    available = frozenset(terms.key_forms("ДоступноСКлиента"))
    on_client = frozenset(terms.key_forms("НаКлиенте"))
    toks = code_tokens(source)
    decls: list[tuple[str, int, int]] = []
    if any(name in source.text for name in available):
        module, errors = parse(source)
        if errors:
            return None  # a broken file is code/parse-error territory
        lm = linemap(source)
        for member in module.members:
            if not isinstance(member, P.Method) or member.is_static:
                continue
            if not {a.name for a in member.annotations} & available:
                continue
            line, col = lm.linecol(member.start)
            decls.append((member.name, line, col))
    _names, methods = _module_decls(toks)
    bodies = _method_bodies(toks, methods, _decl_anchors(toks))
    client_ranges = [
        span for name, (start, end) in bodies.items()
        for _n, anns, _i in methods
        if _n == name and anns & on_client
        for span in ((start, end),)
    ]
    client_words: set[str] = set()
    other_words: set[str] = set()
    for i, tok in enumerate(toks):
        previous = toks[i - 1] if i else None
        if previous is not None and previous.kind == "KEYWORD" \
                and previous.canonical in ("METHOD", "CONSTRUCTOR"):
            continue  # the declaration itself is not a use
        words = _WORDS_RE.findall(tok.value)
        if not words:
            continue
        # A string literal counts wherever it stands: an HTML container bridge calls a method
        # by name from the browser, and that call is as client as it gets.
        if tok.kind == "STRING" or any(start <= i < end for start, end in client_ranges):
            client_words.update(words)
        else:
            other_words.update(words)
    return {"k": "x", "stem": _pair_stem(source.rel), "decls": decls,
            "client_words": sorted(client_words),
            "other_words": sorted(other_words - client_words)}


@rule(
    "code/client-available-unused", "code/client-available-unused.title", "D",
    scope="project", severity=Severity.WARNING, enabled_by_default=False,
    off_reason="code/client-available-unused.off", mapper=_client_use_mapper,
)
def client_available_unused(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    client_stems = {f["stem"] for f in facts.values() if f["k"] == "y" and f["client"]}
    named_by_client: set[str] = set()
    for fact in facts.values():
        if fact["k"] == "y":
            named_by_client.update(fact["words"])
            continue
        named_by_client.update(fact["client_words"])
        if fact["stem"] in client_stems:
            named_by_client.update(fact["other_words"])
    for rel, fact in facts.items():
        if fact["k"] != "x":
            continue
        for name, line, col in fact["decls"]:
            if name not in named_by_client:
                yield Diagnostic(
                    rel, line, col, "code/client-available-unused", Severity.WARNING,
                    i18n.t("code/client-available-unused.unused", name=name),
                )
