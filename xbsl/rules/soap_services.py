"""Tier A: the description of a SOAP service.

- yaml/soap-handler-name: the name of a handler (an item of `Handlers`) is the name of an
  operation in the WSDL description the platform builds from the element, and the build takes
  it only in Latin letters, digits and the underscore. The documentation says so twice (the
  element page: Cyrillic is forbidden in the names of the handlers; the page on creating a
  service: no Cyrillic and no whitespace), and the compiler answers any other name with
  "Handler name ... contains invalid characters. The name must consist of Latin letters,
  digits and the underscore". The method of the module that serves the handler (`Method`)
  is a name of the module and may stay Cyrillic.

  A probe on a server gave the verdict the rule follows: `ДобавитьТовар`, `Add Item`,
  `1AddItem` and a Latin name with one Cyrillic letter were refused, while `AddToCart` and
  `Add_Item` compiled - and so did `Add-Item` and `Add.Item`, whatever the wording of the
  message. So the rule reports what was refused and nothing else: a letter outside ASCII, a
  whitespace, a digit in the first place. A name that is not a plain string is left alone.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from functools import lru_cache

from xbsl import dataset, i18n, metamodel, terms
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, rule
from xbsl.rules.yaml_schema import _HAVE_YAML, _composed, object_kind_fast

if _HAVE_YAML:
    import yaml

RULE = "yaml/soap-handler-name"

MESSAGES = {
    f"{RULE}.title": {
        "ru": "Имя обработчика SOAP-сервиса не латиницей",
        "en": "A SOAP service handler name outside Latin letters",
    },
    f"{RULE}.invalid": {
        "ru": "Имя обработчика '{name}' {reason}. Это имя операции в WSDL-описании сервиса, "
              "и сборка откажет: \"Имя обработчика содержит недопустимые символы. Имя должно "
              "состоять из латинских букв, цифр и символа нижнего подчеркивания\". Задайте имя "
              "латиницей; метод модуля в Метод может остаться прежним.",
        "en": "Handler name '{name}' {reason}. It is the name of an operation in the WSDL "
              "description of the service, and the build refuses it: \"Handler name contains "
              "invalid characters. The name must consist of Latin letters, digits and the "
              "underscore\". Give it a Latin name; the module method in {n[Метод]} may stay as "
              "it is.",
    },
    f"{RULE}.non-ascii": {
        "ru": "содержит букву не латиницей ('{char}')",
        "en": "contains a letter outside Latin ('{char}')",
    },
    f"{RULE}.space": {
        "ru": "содержит пробельный символ",
        "en": "contains a whitespace",
    },
    f"{RULE}.digit": {
        "ru": "начинается с цифры",
        "en": "starts with a digit",
    },
}
i18n.register(MESSAGES)

_KIND = "SoapСервис"
_HANDLERS = "Обработчики"
_WHITESPACE_RE = re.compile(r"\s")


@lru_cache(maxsize=1)
def _keys() -> tuple[frozenset[str], frozenset[str]]:
    """Both spellings of the handlers section and of the name of a handler."""
    record = metamodel.properties(_KIND).get(_HANDLERS) or {}
    return (frozenset({_HANDLERS, record.get("en")} - {None}),
            frozenset(terms.key_forms("Имя")))


dataset.register_reset(_keys.cache_clear)


def _reason(name: str) -> str | None:
    """Why the build refuses the name, None for a name it accepts (see the module docstring)."""
    foreign = next((char for char in name if not char.isascii()), None)
    if foreign is not None:
        return i18n.t(f"{RULE}.non-ascii", char=foreign)
    if _WHITESPACE_RE.search(name):
        return i18n.t(f"{RULE}.space")
    if name[:1].isdigit():
        return i18n.t(f"{RULE}.digit")
    return None


def _value(mapping, keys: frozenset[str]):
    """The value node under one of the keys of a composed mapping, or None."""
    if not isinstance(mapping, yaml.MappingNode):
        return None
    return next((value for key, value in mapping.value
                 if isinstance(key, yaml.ScalarNode) and key.value in keys), None)


@rule(RULE, f"{RULE}.title", "A", severity=Severity.ERROR)
def soap_handler_name(source: SourceFile) -> Iterable[Diagnostic]:
    """A handler of a SOAP service whose name the build refuses."""
    if not _HAVE_YAML or source.kind != "yaml" or object_kind_fast(source) != _KIND:
        return
    root = _composed(source)
    handlers_keys, name_keys = _keys()
    handlers = _value(root, handlers_keys)
    if not isinstance(handlers, yaml.SequenceNode):
        return
    for item in handlers.value:
        node = _value(item, name_keys)
        if not isinstance(node, yaml.ScalarNode) or node.tag != "tag:yaml.org,2002:str":
            continue
        name = node.value
        reason = _reason(name) if name else None
        if reason is None:
            continue
        yield Diagnostic(
            source.rel, node.start_mark.line + 1, node.start_mark.column + 1, RULE,
            Severity.ERROR, i18n.t(f"{RULE}.invalid", name=name, reason=reason),
        )
