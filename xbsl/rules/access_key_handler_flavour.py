"""Tier D: an access-key handler belongs to the computed flavour only.

``ManualGrant`` selects the access-key flavour. A computed key needs the
``CheckHasAccessKeys`` handler in its manager module. A key granted manually cannot
declare that handler. The compiler rejects both cases, but only after the whole
project is assembled, so the yaml and its paired manager module are joined here.

An object module has a different pairing stem and cannot satisfy the contract. A method
with the same name without the handler annotation is also left alone: it is not the
platform handler. Invalid yaml is owned by the parse rule.
"""

from __future__ import annotations

from collections.abc import Iterable
from functools import lru_cache

from xbsl import dataset, i18n, terms
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, rule
from xbsl.rules._syntax import code_tokens
from xbsl.rules.environment import _module_decls, _pair_stem
from xbsl.rules.yaml_schema import _HAVE_YAML, _parsed, object_kind, value_of

MESSAGES = {
    "code/access-key-handler-flavour.title": {
        "ru": "Обработчик ключа доступа не соответствует разновидности",
        "en": "Access-key handler does not match its flavour",
    },
    "code/access-key-handler-flavour.missing": {
        "ru": "У вычисляемого ключа доступа нет обработчика "
              "{n[ПроверитьНаличиеКлючейДоступа]} в модуле. Платформа требует его, "
              "чтобы сопоставить экземпляры ключа с пользователями.",
        "en": "The computed access key has no {n[ПроверитьНаличиеКлючейДоступа]} "
              "handler in its manager module. The platform requires it to match key "
              "instances to users.",
    },
    "code/access-key-handler-flavour.forbidden": {
        "ru": "Ключ доступа с {n[РучнаяВыдача]}: {n[Истина]} не принимает обработчик "
              "{n[ПроверитьНаличиеКлючейДоступа]}. Уберите обработчик из модуля.",
        "en": "An access key with {n[РучнаяВыдача]}: {n[Истина]} cannot declare the "
              "{n[ПроверитьНаличиеКлючейДоступа]} handler. Remove it from the module.",
    },
}
i18n.register(MESSAGES)

_ACCESS_KEY = "КлючДоступа"
_MANUAL_GRANT = "РучнаяВыдача"
_HANDLER = "ПроверитьНаличиеКлючейДоступа"
_HANDLER_ANNOTATION = "Обработчик"
_TRUE_FORMS = frozenset({"Истина", "True", "true"})
_FALSE_FORMS = frozenset({"Ложь", "False", "false"})


@lru_cache(maxsize=1)
def _names() -> tuple[frozenset[str], frozenset[str]]:
    """Both data-backed spellings of the handler and its annotation."""
    return (
        frozenset({_HANDLER, terms.common_english(_HANDLER)} - {None}),
        frozenset({_HANDLER_ANNOTATION, terms.common_english(_HANDLER_ANNOTATION)} - {None}),
    )


dataset.register_reset(_names.cache_clear)


def _manual_grant(data: dict) -> bool | None:
    """Whether the yaml selects manual granting, or None for an invalid value."""
    written = value_of(data, _MANUAL_GRANT, _ACCESS_KEY)
    if written is None:
        return False
    if written is True or isinstance(written, str) and written in _TRUE_FORMS:
        return True
    if written is False or isinstance(written, str) and written in _FALSE_FORMS:
        return False
    return None


def _has_qualified_handler_annotation(toks: list, anchor: int,
                                      handler_annotations: frozenset[str]) -> bool:
    """Whether the declaration follows an ``@Namespace::Handler`` annotation."""
    index = anchor - 1
    while (index >= 0 and toks[index].kind == "KEYWORD"
           and toks[index].canonical in ("STATIC", "ABSTRACT")):
        index -= 1
    if (index < 0 or toks[index].kind not in ("IDENT", "KEYWORD")
            or toks[index].value not in handler_annotations):
        return False
    index -= 1
    qualified = False
    while (index >= 1 and toks[index].kind == "OP" and toks[index].value == "::"
           and toks[index - 1].kind in ("IDENT", "KEYWORD")):
        qualified = True
        index -= 2
    return qualified and index >= 0 and toks[index].kind == "OP" and toks[index].value == "@"


def _access_key_handler_mapper(source: SourceFile) -> dict | None:
    """Map key flavour from yaml and annotated handler declarations from modules."""
    handler_names, annotation_names = _names()
    if source.kind == "yaml":
        if not _HAVE_YAML:
            return None
        data, error = _parsed(source)
        if error is not None or not isinstance(data, dict) or object_kind(data) != _ACCESS_KEY:
            return None
        manual = _manual_grant(data)
        if manual is None:
            return None
        return {
            "k": "y",
            "stem": _pair_stem(source.rel),
            "manual": manual,
            "unloaded_manager": source.path.with_suffix(".xbsl").is_file(),
        }
    if source.kind != "xbsl":
        return None
    toks = code_tokens(source)
    _decls, methods = _module_decls(toks)
    declared: list[tuple[int, int]] = []
    for name, annotations, anchor in methods:
        if (name not in handler_names or not annotations & annotation_names
                and not _has_qualified_handler_annotation(toks, anchor, annotation_names)):
            continue
        token = toks[anchor + 1] if anchor + 1 < len(toks) else toks[anchor]
        declared.append((token.line, token.col))
    return {"k": "m", "stem": _pair_stem(source.rel), "declared": declared}


@rule(
    "code/access-key-handler-flavour", "code/access-key-handler-flavour.title", "D",
    scope="project", severity=Severity.ERROR, mapper=_access_key_handler_mapper,
)
def access_key_handler_flavour(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    """Report a missing computed handler and a manual key that declares one."""
    modules = {
        fact["stem"]: (rel, fact["declared"])
        for rel, fact in facts.items()
        if fact["k"] == "m"
    }
    for rel, fact in facts.items():
        if fact["k"] != "y":
            continue
        module = modules.get(fact["stem"])
        declared = module[1] if module is not None else []
        if (not fact["manual"] and not declared
                and (module is not None or not fact["unloaded_manager"])):
            yield Diagnostic(
                rel, 1, 1, "code/access-key-handler-flavour", Severity.ERROR,
                i18n.t("code/access-key-handler-flavour.missing"),
            )
        elif fact["manual"] and module is not None:
            for line, col in declared:
                yield Diagnostic(
                    module[0], line, col, "code/access-key-handler-flavour", Severity.ERROR,
                    i18n.t("code/access-key-handler-flavour.forbidden"),
                )
