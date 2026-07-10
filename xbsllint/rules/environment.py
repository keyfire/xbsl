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

Verified on the real corpus: 0 false positives; the call detection of the first check is
exercised by the corpus (client handlers calling @НаСервере @ДоступноСКлиента methods are
found by the same matching and correctly not flagged).
"""

from __future__ import annotations

from collections.abc import Iterable

from xbsllint import i18n
from xbsllint.diagnostics import Diagnostic, Severity
from xbsllint.engine import SourceFile, rule
from xbsllint.rules._syntax import code_tokens
from xbsllint.rules.enum_values import _shadowed_names
from xbsllint.rules.handlers import _HANDLER_RE, _IDENT_RE
from xbsllint.rules.yaml_schema import _HAVE_YAML, _parsed

MESSAGES = {
    "code/server-call-from-handler.title": {
        "ru": "Серверный метод недоступен клиентскому обработчику",
        "en": "Server method is unavailable to a client handler",
    },
    "code/server-call-from-handler.call": {
        "ru": "Клиентский обработчик '{handler}' вызывает метод '{name}', объявленный "
              "@НаСервере без @ДоступноСКлиента – вызов с клиента недоступен.",
        "en": "Client handler '{handler}' calls method '{name}' declared @НаСервере "
              "without @ДоступноСКлиента – the call is unavailable on the client.",
    },
    "code/client-annotation-in-server-module.title": {
        "ru": "Клиентская аннотация в серверном общем модуле",
        "en": "Client annotation in a server common module",
    },
    "code/client-annotation-in-server-module.annotation": {
        "ru": "Аннотация @{ann} в общем модуле '{module}' с Окружение: Сервер – "
              "допустима только @НаСервере, модулю нужно Окружение: КлиентИСервер.",
        "en": "Annotation @{ann} in common module '{module}' with Окружение: Сервер – "
              "only @НаСервере is allowed, the module needs Окружение: КлиентИСервер.",
    },
    "code/client-module-in-http-service.title": {
        "ru": "Клиентский общий модуль в HTTP-сервисе",
        "en": "Client common module in an HTTP service",
    },
    "code/client-module-in-http-service.call": {
        "ru": "Обращение '{name}' из модуля HTTP-сервиса: у общего модуля '{root}' "
              "Окружение: Клиент – на сервере тип недоступен, нужно КлиентИСервер.",
        "en": "Access '{name}' from an HTTP service module: common module '{root}' has "
              "Окружение: Клиент – the type is unavailable on the server, it needs КлиентИСервер.",
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


def _paired_modules(sources: list[SourceFile]) -> dict[str, SourceFile]:
    return {str(s.path): s for s in sources if s.kind == "xbsl"}


def _yaml_objects(sources: list[SourceFile]) -> Iterable[tuple[SourceFile, dict]]:
    """The parsed yaml descriptions of the project objects (with a ВидЭлемента)."""
    for s in sources:
        if s.kind != "yaml":
            continue
        data, err = _parsed(s)
        if err is None and isinstance(data, dict) and data.get("ВидЭлемента"):
            yield s, data


@rule(
    "code/server-call-from-handler", "code/server-call-from-handler.title", "D",
    scope="project", severity=Severity.WARNING,
)
def server_call_from_handler(sources: list[SourceFile]) -> Iterable[Diagnostic]:
    if not _HAVE_YAML:
        return []
    modules = _paired_modules(sources)

    diags: list[Diagnostic] = []
    for s, data in _yaml_objects(sources):
        if data.get("ВидЭлемента") != "КомпонентИнтерфейса":
            continue
        module = modules.get(str(s.path.with_suffix(".xbsl")))
        if module is None:
            continue
        toks = code_tokens(module)
        decls, methods = _module_decls(toks)
        method_anns = {name: anns for name, anns, _ in methods}
        server_only = {
            name for name, anns in method_anns.items()
            if "НаСервере" in anns and not any(a in anns for a in _CLIENT_SIDE_ANNS)
        }
        if not server_only:
            continue

        handlers = {name for name, anns in method_anns.items() if "Обработчик" in anns}
        for m in _HANDLER_RE.finditer(s.text):
            value = m.group(1).strip()
            if _IDENT_RE.match(value):
                handlers.add(value)

        bodies = _method_bodies(toks, methods, _decl_anchors(toks))
        shadowed = _shadowed_names(toks)
        n = len(toks)
        for handler in sorted(handlers):
            anns = method_anns.get(handler)
            if anns is None or "НаСервере" in anns:
                continue  # not found in the module, or runs on the server itself
            start, end = bodies[handler]
            for i in range(start, end):
                t = toks[i]
                if t.kind != "IDENT" or t.value not in server_only or t.value in shadowed:
                    continue
                if i > 0 and toks[i - 1].kind == "OP" and toks[i - 1].value == ".":
                    continue  # a member of another object, not a bare module method
                if not (i + 1 < n and toks[i + 1].kind == "OP" and toks[i + 1].value == "("):
                    continue  # not a call
                diags.append(Diagnostic(
                    module.rel, t.line, t.col, "code/server-call-from-handler",
                    Severity.WARNING,
                    i18n.t("code/server-call-from-handler.call",
                           handler=handler, name=t.value),
                ))
    return diags


@rule(
    "code/client-annotation-in-server-module",
    "code/client-annotation-in-server-module.title", "D",
    scope="project", severity=Severity.WARNING,
)
def client_annotation_in_server_module(sources: list[SourceFile]) -> Iterable[Diagnostic]:
    if not _HAVE_YAML:
        return []
    modules = _paired_modules(sources)

    diags: list[Diagnostic] = []
    for s, data in _yaml_objects(sources):
        if data.get("ВидЭлемента") != "ОбщийМодуль" or data.get("Окружение") != "Сервер":
            continue
        name = data.get("Имя")
        module = modules.get(str(s.path.with_suffix(".xbsl")))
        if not isinstance(name, str) or module is None:
            continue
        toks = code_tokens(module)
        n = len(toks)
        for i, t in enumerate(toks):
            if (t.kind == "OP" and t.value == "@" and i + 1 < n
                    and toks[i + 1].kind == "IDENT"
                    and toks[i + 1].value in _CLIENT_SIDE_ANNS):
                a = toks[i + 1]
                diags.append(Diagnostic(
                    module.rel, a.line, a.col, "code/client-annotation-in-server-module",
                    Severity.WARNING,
                    i18n.t("code/client-annotation-in-server-module.annotation",
                           ann=a.value, module=name),
                ))
    return diags


@rule(
    "code/client-module-in-http-service",
    "code/client-module-in-http-service.title", "D",
    scope="project", severity=Severity.WARNING,
)
def client_module_in_http_service(sources: list[SourceFile]) -> Iterable[Diagnostic]:
    if not _HAVE_YAML:
        return []
    modules = _paired_modules(sources)

    client_decls: dict[str, dict[str, frozenset[str]]] = {}
    http_modules: list[SourceFile] = []
    for s, data in _yaml_objects(sources):
        kind = data.get("ВидЭлемента")
        module = modules.get(str(s.path.with_suffix(".xbsl")))
        if module is None:
            continue
        if (kind == "ОбщийМодуль" and data.get("Окружение") == "Клиент"
                and isinstance(data.get("Имя"), str)):
            decls, _ = _module_decls(code_tokens(module))
            client_decls[data["Имя"]] = decls
        elif kind == "HttpСервис":
            http_modules.append(module)
    if not client_decls or not http_modules:
        return []

    diags: list[Diagnostic] = []
    for module in http_modules:
        toks = code_tokens(module)
        shadowed = _shadowed_names(toks)
        n = len(toks)
        for i, t in enumerate(toks):
            if t.kind != "IDENT" or t.value not in client_decls or t.value in shadowed:
                continue
            if i > 0 and toks[i - 1].kind == "OP" and toks[i - 1].value == ".":
                continue  # a member of another object, not the module
            if not (i + 3 < n and toks[i + 1].kind == "OP" and toks[i + 1].value == "."
                    and toks[i + 2].kind == "IDENT"
                    and toks[i + 3].kind == "OP" and toks[i + 3].value == "("):
                continue  # only `Модуль.Член(...)` accesses are checked
            member = toks[i + 2]
            anns = client_decls[t.value].get(member.value)
            if anns is None or "НаСервере" in anns:
                continue  # unresolved member, or one that does exist on the server
            diags.append(Diagnostic(
                module.rel, t.line, t.col, "code/client-module-in-http-service",
                Severity.WARNING,
                i18n.t("code/client-module-in-http-service.call",
                       name=f"{t.value}.{member.value}", root=t.value),
            ))
    return diags
