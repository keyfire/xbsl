"""Tier D: environment (client/server) consistency checks.

The platform assigns every module an environment – Клиент, Сервер or КлиентИСервер (docs
"Исполнение модуля") – and the annotations @НаСервере/@НаКлиенте/@ДоступноСКлиента refine
it per method or type. An environment mismatch is among the most painful failures: the
server-side apply silently rolls the whole project back without pointing at the line.
Three checks, all narrow by design (a skipped case is a false negative, never a false
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

- code/client-module-in-http-service: a common module with `Окружение: Клиент` does not
  exist on the server, so the module of an HttpСервис (environment Сервер) calling
  `ИмяМодуля.Метод(...)` fails at runtime ("Type unavailable"). Members declared
  @НаСервере inside the client module do exist on the server and are not flagged; a
  member that cannot be resolved in the module is skipped rather than guessed.

The call detection of the first check is exercised by its own tests: a client handler calling
a @НаСервере @ДоступноСКлиента method is found by the same matching and correctly not flagged.
"""

from __future__ import annotations

from collections.abc import Iterable

from xbsl import i18n
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, rule
from xbsl.lexer import tokens
from xbsl.rules._syntax import code_tokens
from xbsl.rules.enum_values import _shadowed_names
from xbsl.rules.handlers import _HANDLER_RE, _IDENT_RE
from xbsl.rules.yaml_schema import _HAVE_YAML, _parsed, object_kind, value_of

MESSAGES = {
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

# The environment annotations of the platform (docs "Аннотации окружения").
_CLIENT_SIDE_ANNS = ("ДоступноСКлиента", "НаКлиенте")

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
        for m in _HANDLER_RE.finditer(source.text):
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
        if "НаСервере" in anns and not any(a in anns for a in _CLIENT_SIDE_ANNS)
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
        handlers.update(name for name, a in anns.items() if "Обработчик" in a)
        for handler in sorted(handlers):
            a = anns.get(handler)
            if a is None or "НаСервере" in a:
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
        if (data is None or object_kind(data) != "ОбщийМодуль"
                or data.get("Окружение") != "Сервер"):
            return None
        name = value_of(data, "Имя")
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
                and toks[i + 1].value in _CLIENT_SIDE_ANNS):
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
        if (kind == "ОбщийМодуль" and data.get("Окружение") == "Клиент"
                and isinstance(value_of(data, "Имя"), str)):
            return {"k": "y", "stem": _pair_stem(source.rel),
                    "role": "client", "name": data["Имя"]}
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
        "server_bit": {name: "НаСервере" in anns for name, anns in decls.items()},
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
        "en": "A Запрос{{}} block in method '{name}' without @{n[НаСервере]}: the module runs "
              "on the client ({env}), where the type Запрос does not exist - the compiler "
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
        env = data.get("Окружение")
        if isinstance(env, str) and "Клиент" in env:
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
        if "НаСервере" in anns.get(name, frozenset()) or start >= len(toks):
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
