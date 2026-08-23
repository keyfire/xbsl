"""Tier D: form handlers reference methods that exist in the module.

In a form's yaml description an event is given by a handler key whose value is a method name
in the paired module (`Name.yaml` ↔ `Name.xbsl`). The rule catches the "renamed a method –
forgot to fix the form" drift (and vice versa) before the server-side compilation on deploy.

For every handler key of the set the identifier value must match a method of the paired
module. The set is extended when needed. A value with a dot (an FQN reference to an external module) and a non-identifier are
not checked. The rule is cross-file: without the paired module handlers are not checked
(nothing to resolve against).
"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Iterable
from functools import lru_cache

from xbsl import dataset, i18n, terms, uischema
from xbsl import parser as P
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, rule
from xbsl.lexer import linemap, tokens
from xbsl.parser import parse
from xbsl.rules._syntax import code_tokens
from xbsl.rules.yaml_schema import _composed, _HAVE_YAML, _mapping_nodes

if _HAVE_YAML:
    import yaml

MESSAGES = {
    "form/unknown-handler.title": {
        "ru": "Обработчик формы не найден в модуле",
        "en": "Form handler not found in the module",
    },
    "form/handler-signature.title": {
        "ru": "Сигнатура обработчика не совпадает с событием",
        "en": "Handler signature does not match the event",
    },
    "form/handler-signature.mismatch": {
        "ru": "Параметр {position} обработчика '{handler}' объявлен как '{actual}', а событие "
              "'{event}' компонента '{component}' передаёт '{expected}'. Платформа требует "
              "точного совпадения: при применении сборки компиляция ответит "
              "\"Метод не удовлетворяет сигнатуре\", и проект откатится на прежнюю сборку.",
        "en": "Parameter {position} of the handler '{handler}' is declared as '{actual}', while "
              "the '{event}' event of '{component}' passes '{expected}'. The platform demands an "
              "exact match: applying the build answers that the method does not satisfy the "
              "signature, and the project rolls back to the previous build.",
    },
    "form/unknown-handler.not-found": {
        "ru": "Обработчик '{name}' не найден как метод в модуле формы '{module}'.",
        "en": "Handler '{name}' is not found as a method in the form module '{module}'.",
    },
    "code/close-in-before-close.title": {
        "ru": "Закрыть() внутри ПередЗакрытием",
        "en": "{n[Закрыть]}() inside {n[ПередЗакрытием]}",
    },
    "code/close-in-before-close.nested": {
        "ru": "Вызов {name}() внутри обработчика {n[ПередЗакрытием]} платформа игнорирует, а "
              "процесс закрытия остаётся незавершённым – после этого форму не закрывает уже "
              "ничто. Вынесите закрытие за пределы обработчика разовым таймером: "
              "{n[ПодключитьОбработчикТаймера]}(() -> {name}(...), 0с, {n[Истина]}).",
        "en": "A {name}() call inside the {n[ПередЗакрытием]} handler is ignored by the platform "
              "while the closing stays unfinished – after that nothing closes the form at all. "
              "Move the closing out of the handler with a one-shot timer: "
              "{n[ПодключитьОбработчикТаймера]}(() -> {name}(...), 0с, {n[Истина]}).",
    },
}
i18n.register(MESSAGES)

_HANDLER_KEYS = (
    "Обработчик", "ПриНажатии", "ПриИзменении", "ПриВыделенииСтроки",
    "ПослеЗагрузкиСодержимого", "ПриСменеСтраницы", "ПриВыбореЭлемента",
)


@lru_cache(maxsize=1)
def _handler_re() -> re.Pattern[str]:
    """The event keys above in both spellings - a form may be written in English.

    The English name of every key comes from the component schema, never from a guess; a
    key the schema pairs with nothing keeps its Russian spelling alone.
    """
    keys: list[str] = []
    for key in _HANDLER_KEYS:
        for form in (key, uischema.english_property(key)):
            if form and form not in keys:
                keys.append(form)
    return re.compile(  # a trailing comment and CRLF are allowed after the value
        r"(?m)^[ \t]*(?:" + "|".join(keys) + r"):[ \t]*([^\s#][^\n#]*?)[ \t]*(?:#.*)?\r?$"
    )


dataset.register_reset(_handler_re.cache_clear)

_IDENT_RE = re.compile(r"^[^\W\d]\w*$", re.UNICODE)


def _module_methods(source: SourceFile) -> set[str]:
    """Names of the methods and constructors declared in the module."""
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


def _handler_pair_stem(rel: str) -> str:
    slash = rel.replace("\\", "/")
    return slash[: slash.rfind(".")] if "." in slash.rsplit("/", 1)[-1] else slash


def _handler_mapper(source: SourceFile) -> dict | None:
    """The map phase: a yaml contributes its handler references with positions, a module
    the set of its method names - the reduce joins the pair."""
    if source.kind == "xbsl":
        # Even an empty method set matters: a paired module WITHOUT the referenced
        # method is exactly what the rule flags.
        methods = _module_methods(source)
        return {"k": "x", "stem": _handler_pair_stem(source.rel), "methods": sorted(methods)}
    if source.kind != "yaml":
        return None
    refs: list[tuple[str, int, int]] = []
    lm = None
    for m in _handler_re().finditer(source.text):
        name = m.group(1).strip()
        if not _IDENT_RE.match(name):
            continue  # FQN reference to an external module or a non-identifier – skip
        if lm is None:
            lm = linemap(source)
        line, col = lm.linecol(m.start(1))
        refs.append((name, line, col))
    if not refs:
        return None
    return {
        "k": "y",
        "stem": _handler_pair_stem(source.rel),
        "module_file": source.path.with_suffix(".xbsl").name,
        "refs": refs,
    }


@rule(
    "form/unknown-handler", "form/unknown-handler.title", "D",
    scope="project", severity=Severity.WARNING, mapper=_handler_mapper,
)
def unknown_handler(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    methods_by_stem: dict[str, set[str]] = {}
    for fact in facts.values():
        if fact["k"] == "x":
            methods_by_stem[fact["stem"]] = set(fact["methods"])
    for rel, fact in facts.items():
        if fact["k"] != "y":
            continue
        methods = methods_by_stem.get(fact["stem"])
        if methods is None:
            continue  # no paired module – nothing to resolve handlers against
        for name, line, col in fact["refs"]:
            if name not in methods:
                yield Diagnostic(
                    rel, line, col, "form/unknown-handler", Severity.WARNING,
                    i18n.t(
                        "form/unknown-handler.not-found",
                        name=name, module=fact["module_file"],
                    ),
                )


# The handler the platform runs while the form is closing, in both spellings.
_BEFORE_CLOSE = frozenset({"ПередЗакрытием", "BeforeClose"})

# The call that the platform ignores inside that handler.
_CLOSE_NAMES = frozenset({"Закрыть", "Close"})


def _lambda_spans(method: P.Method) -> list[tuple[int, int]]:
    """[start, end) of every lambda inside the method - a deferred call is not the handler's.

    The AST has no generic walker, and the nodes are dataclasses, so the children are the
    field values: a node, or a sequence holding nodes. The sequence may hold TUPLES rather
    than nodes - the branches of `если` are (condition, body) pairs - so a walker that only
    descends into lists of nodes silently misses everything inside a condition.
    """
    spans: list[tuple[int, int]] = []

    def walk(node) -> None:
        if isinstance(node, (list, tuple)):
            for item in node:
                walk(item)
            return
        if not isinstance(node, P.Node):
            return
        if isinstance(node, P.Lambda):
            spans.append((node.start, node.end))
            return  # a lambda inside a lambda is inside this span anyway
        for f in dataclasses.fields(node):
            walk(getattr(node, f.name, None))

    walk(method.body)
    return spans


@rule(
    "code/close-in-before-close", "code/close-in-before-close.title", "C",
    severity=Severity.WARNING,
)
def close_in_before_close(source: SourceFile) -> Iterable[Diagnostic]:
    """`Закрыть(...)` in the body of `ПередЗакрытием` - the platform ignores it and the form sticks.

    The pattern "ask on closing, Yes = save and close" cannot be written as a nested call: the
    platform ignores it, the closing process stays unfinished, and afterwards even the cross
    does nothing (the symptom is "the form can no longer be closed"). The cure is to save
    synchronously in the handler and close outside it with a one-shot timer - so a call inside
    a LAMBDA is exactly the cure and stays silent; only a call made in the handler's own flow
    is reported. A call through an intermediate method breaks the form just as badly, but a
    file rule cannot see through the call - that half stays with the deploy.
    """
    if source.kind != "xbsl":
        return
    if not any(name in source.text for name in _CLOSE_NAMES):
        return
    module, errors = parse(source)
    if errors:
        return  # a broken file is code/parse-error territory
    toks = code_tokens(source)
    lm = linemap(source)
    for member in module.members:
        if not isinstance(member, P.Method) or member.name not in _BEFORE_CLOSE:
            continue
        spans = _lambda_spans(member)
        for i, t in enumerate(toks):
            if t.start < member.start:
                continue
            if t.start >= member.end:
                break
            if t.kind != "IDENT" or t.value not in _CLOSE_NAMES:
                continue
            following = toks[i + 1] if i + 1 < len(toks) else None
            if following is None or following.kind != "OP" or following.value != "(":
                continue
            previous = toks[i - 1] if i else None
            if previous is not None and previous.kind == "OP" and previous.value == ".":
                continue  # a member call on a value, not the form's own Закрыть
            if any(start <= t.start < end for start, end in spans):
                continue  # inside a lambda - that is the recommended deferred closing
            line, col = lm.linecol(t.start)
            yield Diagnostic(
                source.rel, line, col, "code/close-in-before-close", Severity.WARNING,
                i18n.t("code/close-in-before-close.nested", name=t.value),
            )


# --- form/handler-signature ---------------------------------------------------------------
#
# The yaml points an event at a method, and the platform demands the method match the event's
# delegate EXACTLY: a `СобытиеПриИзменении<Булево>` where the component declares
# `СобытиеПриИзменении<Булево?>` costs a full deploy cycle - the server compilation answers
# "Метод не удовлетворяет сигнатуре" and the whole project rolls back to the previous build.
#
# The signature comes from the ui schema, which carries the delegate of every event property
# (`ПриИзменении: (Флажок, СобытиеПриИзменении<Булево?>)->ничто`), and the component's own
# type arguments are substituted into it: a `ПолеВвода<Строка>` expects
# `СобытиеПриИзменении<Строка>`.
#
# Reconnaissance over four corpora (483 handlers) settled the slice, and it is narrower than
# "the types differ":
#
# - the ARITY is not judged. A standard table column legitimately takes a third parameter
#   (the row data the docs describe as an extra), and nine live handlers do exactly that;
# - a parameter whose HEAD type differs is not judged either: a handler shared by several
#   components declares the base types (`Component`, `ComponentEvent`) and the platform
#   accepts it - twenty-two live handlers are written that way;
# - a type parameter left unsubstituted (a list whose row type resolves through the source
#   type) is not judged: what the compiler sees there is not visible in the file.
#
# What is left is the case the defect was met in: the SAME type, spelled with a different
# argument or nullability. Zero findings on all four corpora.

#: Type expressions are compared by text, so both spellings are folded into the Russian one.
_TYPE_WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)
#: An entity facet is a QUALIFIED name, and the platform pairs it whole
#: (`BinaryObject.Reference` answers `ДвоичныйОбъект.Ссылка`): word by word its tail resolves
#: to nothing, and a translated project then looked as if it wrote another type.
_QUALIFIED_RE = re.compile(r"[^\W\d_]+(?:\.[^\W\d_]+)+", re.UNICODE)


def _folded(type_text: str) -> str:
    """A type expression in one spelling and without spaces - the comparable form."""
    text = (type_text or "").replace(" ", "")

    def swap_qualified(match: re.Match) -> str:
        name = match.group(0)
        return terms.russian(name, "facets") or name

    def swap(match: re.Match) -> str:
        word = match.group(0)
        return terms.common_russian(word) or terms.russian(word, "types") or word

    text = _QUALIFIED_RE.sub(swap_qualified, text)
    return _TYPE_WORD_RE.sub(swap, text)


def _type_head(type_text: str) -> str:
    """`OnChangeEvent<Boolean?>` -> `OnChangeEvent` (already folded)."""
    return type_text.split("<", 1)[0].rstrip("?")


def _signature_params(signature: str) -> list[str]:
    """Parameter types of `(A, B<C>)->ничто`; empty when the shape is not that."""
    if not signature.startswith("("):
        return []
    depth = 0
    inside = ""
    for index, char in enumerate(signature):
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                inside = signature[1:index]
                break
    params: list[str] = []
    depth = 0
    current = ""
    for char in inside:
        if char in "<(":
            depth += 1
        elif char in ">)":
            depth -= 1
        if char == "," and depth == 0:
            params.append(current.strip())
            current = ""
            continue
        current += char
    if current.strip():
        params.append(current.strip())
    return params


@lru_cache(maxsize=None)
def _events_of(component: str) -> tuple[tuple[str, str], ...]:
    """((event property, its delegate signature), ...) of a component the schema knows."""
    record = uischema.component(component) or {}
    props = ((record.get("component") or {}).get("props") or {})
    return tuple(
        (name, spec["event"]) for name, spec in props.items() if isinstance(spec, dict) and spec.get("event")
    )


@lru_cache(maxsize=1)
def _event_names() -> frozenset[str]:
    """Every event property name of the schema - the cheap gate before composing a yaml."""
    names: set[str] = set()
    for component in uischema.catalog().get("components") or {}:
        for name, _signature in _events_of(component):
            names.add(name)
            english = uischema.english_property(name)
            if english:
                names.add(english)
    return frozenset(names)


def _reset_signature_caches() -> None:
    _events_of.cache_clear()
    _event_names.cache_clear()


dataset.register_reset(_reset_signature_caches)


#: The associated types a list-like component names through its source type
#: (`ТипИсточника.ItemDataType`). What the compiler resolves them to is not in the file.
_ASSOCIATED = ("ItemDataType", "NodesDataType", "IdType")


@lru_cache(maxsize=None)
def _type_params(component: str) -> tuple[str, ...]:
    """The type parameters the component declares (`Edit` -> `DataType`)."""
    return tuple(dataset.load_json("stdlib.json").get("type_params", {}).get(component) or ())


def _expected_params(component: str, written: str, signature: str) -> list[str] | None:
    """The delegate parameters with the component's own type arguments substituted.

    The substitution goes INSIDE the type expression, not only over its head: an event is
    named `СобытиеПриИзменении<ТипДанных>`, and the argument the yaml wrote belongs there.

    None - a type parameter is still standing afterwards (the yaml named no argument) or the
    expression resolves through an associated type. Judging either would be guessing.
    """
    own = _type_params(component)
    arguments = dict(zip(own, dataset.generic_args(written)))
    out: list[str] = []
    for param in _signature_params(signature):
        resolved = param
        for name, value in arguments.items():
            resolved = re.sub(rf"\b{re.escape(name)}\b", value, resolved)
        if any(name in resolved for name in own):
            return None
        if any(f".{name}" in resolved for name in _ASSOCIATED):
            return None
        out.append(resolved)
    return out or None


def _module_signatures(source: SourceFile) -> dict[str, list[str]]:
    """{method name: [declared parameter types]} of a module."""
    module, errors = parse(source)
    if errors:
        return {}  # a broken file is code/parse-error territory
    out: dict[str, list[str]] = {}
    for member in module.members:
        if isinstance(member, P.Method):
            out[member.name] = [(p.type.text if p.type else "") for p in member.params]
    return out


def _signature_mapper(source: SourceFile) -> dict | None:
    """The map phase: a module contributes its method signatures, a yaml its handler refs."""
    if source.kind == "xbsl":
        return {
            "k": "x",
            "stem": _handler_pair_stem(source.rel),
            "methods": _module_signatures(source),
        }
    if source.kind != "yaml" or not _HAVE_YAML or not uischema.available():
        return None
    names = _event_names()
    if not any(name in source.text for name in names):
        return None
    root = _composed(source)
    if root is None:
        return None
    refs: list[dict] = []
    for mapping in _mapping_nodes(root):
        entries = {
            key.value: value for key, value in mapping.value
            if isinstance(key, yaml.ScalarNode)
        }
        written = entries.get("Тип") or entries.get("Type")
        if not isinstance(written, yaml.ScalarNode):
            continue
        component = uischema.canonical_component(written.value.split("<", 1)[0].strip())
        if not component:
            continue
        for name, signature in _events_of(component):
            node = entries.get(name) or entries.get(uischema.english_property(name) or name)
            if not isinstance(node, yaml.ScalarNode):
                continue
            handler = node.value.strip()
            if not _IDENT_RE.match(handler):
                continue  # a binding, a reference or an external method - not resolvable here
            expected = _expected_params(component, written.value.strip(), signature)
            if expected is None:
                continue
            refs.append({
                "component": component,
                "event": name,
                "handler": handler,
                "expected": expected,
                "line": node.start_mark.line + 1,
                "col": node.start_mark.column + 1,
            })
    if not refs:
        return None
    return {"k": "y", "stem": _handler_pair_stem(source.rel), "refs": refs}


@rule(
    "form/handler-signature", "form/handler-signature.title", "D",
    scope="project", severity=Severity.WARNING, mapper=_signature_mapper,
)
def handler_signature(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    """A handler whose parameter contradicts the event of the component - see the block above."""
    methods_by_stem: dict[str, dict[str, list[str]]] = {
        fact["stem"]: fact["methods"] for fact in facts.values() if fact["k"] == "x"
    }
    for rel, fact in facts.items():
        if fact["k"] != "y":
            continue
        methods = methods_by_stem.get(fact["stem"])
        if not methods:
            continue  # no paired module - form/unknown-handler speaks about that
        for ref in fact["refs"]:
            actual = methods.get(ref["handler"])
            if actual is None:
                continue  # an unknown handler is form/unknown-handler's finding
            for position, (want, got) in enumerate(zip(ref["expected"], actual), start=1):
                want_folded, got_folded = _folded(want), _folded(got)
                if want_folded == got_folded or not got_folded:
                    continue
                if _type_head(want_folded) != _type_head(got_folded):
                    continue  # a base type is legal: one handler serves several components
                yield Diagnostic(
                    rel, ref["line"], ref["col"], "form/handler-signature", Severity.WARNING,
                    i18n.t(
                        "form/handler-signature.mismatch",
                        handler=ref["handler"], event=ref["event"], component=ref["component"],
                        position=position, expected=want, actual=got,
                    ),
                )
