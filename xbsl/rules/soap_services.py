"""Tier A: the description of a web service - SOAP, and HTTP where the rule says so.

- yaml/soap-handler-name: the name of a handler (an item of `Handlers`) is the name of an
  operation in the WSDL description the platform builds from the element, and the build takes
  it only in Latin letters, digits and the underscore. The documentation says so twice (the
  element page: Cyrillic is forbidden in the names of the handlers; the page on creating a
  service: no Cyrillic and no whitespace), and the compiler answers any other name with
  "Handler name ... contains invalid characters. The name must consist of Latin letters,
  digits and the underscore". The method of the module that serves the handler (`Method`)
  is a name of the module and may stay Cyrillic.

  Probes on a server gave the verdict the rule follows: `ДобавитьТовар`, `Add Item`,
  `1AddItem` and a Latin name with one Cyrillic letter were refused, while `AddToCart` and
  `Add_Item` compiled - and so did `Add-Item` and `Add.Item`, whatever the wording of the
  message. Every other printable ASCII character was then put between two Latin words, one
  service per character: `"`, `%`, `<`, `>`, `\\`, `^`, a backquote, `{`, `|` and `}` were
  refused (`%` even as a valid escape, `Add%41Item`), while `!#$&'()*+,/:;=?@[]~` compiled.
  In the first place a hyphen and a dot were refused as well, and the underscore compiled.
  So the rule reports what was refused and nothing else: a letter outside ASCII, a
  whitespace, one of the refused characters, and a digit, a hyphen or a dot in the first
  place. A name that is not a plain string is left alone.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from functools import lru_cache

from xbsl import dataset, i18n, metamodel, terms
from xbsl.diagnostics import Diagnostic, Severity, TextEdit
from xbsl.engine import SourceFile, rule
from xbsl.rules.yaml_schema import _HAVE_YAML, _composed, object_kind_fast
from xbsl.scaffold import latin_url_path

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
    f"{RULE}.char": {
        "ru": "содержит символ '{char}', которого сборка не принимает",
        "en": "contains '{char}', a character the build refuses",
    },
    f"{RULE}.first": {
        "ru": "начинается с '{char}'",
        "en": "starts with '{char}'",
    },
}
i18n.register(MESSAGES)

_KIND = "SoapСервис"
_HANDLERS = "Обработчики"
_WHITESPACE_RE = re.compile(r"\s")
#: The printable ASCII characters a probe saw the build refuse anywhere in the name.
_REFUSED = frozenset('"%<>\\^`{|}')
#: The characters it refused in the first place only; a digit there is reported apart.
_REFUSED_FIRST = frozenset("-.")


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
    refused = next((char for char in name if char in _REFUSED), None)
    if refused is not None:
        return i18n.t(f"{RULE}.char", char=refused)
    if name[:1].isdigit():
        return i18n.t(f"{RULE}.digit")
    if name[:1] in _REFUSED_FIRST:
        return i18n.t(f"{RULE}.first", char=name[0])
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


# --- The root address of a service ------------------------------------------------------------

ROOT_URL = "yaml/root-url-cyrillic"

MESSAGES_ROOT_URL = {
    f"{ROOT_URL}.title": {
        "ru": "КорневойUrl сервиса с кириллицей",
        "en": "A service RootUrl with Cyrillic letters",
    },
    f"{ROOT_URL}.cyrillic": {
        "ru": "КорневойUrl '{value}' содержит кириллицу. Сборка такой адрес принимает, но запрос "
              "до сервиса не доходит: сервер отвечает, что обработчик HTTP-запроса не найден. "
              "Задайте адрес латиницей, например '{latin}'.",
        "en": "{n[КорневойUrl]} '{value}' holds Cyrillic letters. The build takes such an "
              "address, yet no request reaches the service: the server answers that the handler "
              "of the HTTP request is not found. Write the address in Latin letters, for "
              "example '{latin}'.",
    },
}
i18n.register(MESSAGES_ROOT_URL)

#: The kinds whose root address a probe on a server exercised.
_SERVICE_KINDS = ("HttpСервис", "SoapСервис")
_ROOT_URL_KEY = "КорневойUrl"
_CYRILLIC_RE = re.compile(r"[А-Яа-яЁё]")


@lru_cache(maxsize=None)
def _root_url_keys(kind: str) -> frozenset[str]:
    """Both spellings of the root address of a service kind."""
    record = metamodel.properties(kind).get(_ROOT_URL_KEY) or {}
    return frozenset({_ROOT_URL_KEY, record.get("en")} - {None})


dataset.register_reset(_root_url_keys.cache_clear)


@rule(ROOT_URL, f"{ROOT_URL}.title", "A", severity=Severity.WARNING)
def root_url_cyrillic(source: SourceFile) -> Iterable[Diagnostic]:
    """A service whose `RootUrl` holds Cyrillic letters: nothing reaches it.

    Probes on a server published an HTTP service and a SOAP one with a Cyrillic root address
    next to Latin ones. The build took them all and the application ran; a request to a Latin
    address got its answer, while the percent-encoded Cyrillic one got "Handler of HTTP
    request ... not found" (and the raw one never got past the front server). The service
    name and the namespace of a SOAP service worked in Cyrillic, so only the address is
    judged. The quick fix writes it in Latin letters the way new-object does.
    """
    if not _HAVE_YAML or source.kind != "yaml" or not _CYRILLIC_RE.search(source.text):
        return
    kind = object_kind_fast(source)
    if kind not in _SERVICE_KINDS:
        return
    node = _value(_composed(source), _root_url_keys(kind))
    if not isinstance(node, yaml.ScalarNode) or node.tag != "tag:yaml.org,2002:str":
        return
    value = node.value
    if not _CYRILLIC_RE.search(value):
        return
    latin = latin_url_path(value)
    start, end = node.start_mark.index, node.end_mark.index
    fix = TextEdit(start, end, latin) if source.text[start:end] == value else None
    yield Diagnostic(
        source.rel, node.start_mark.line + 1, node.start_mark.column + 1, ROOT_URL,
        Severity.WARNING, i18n.t(f"{ROOT_URL}.cyrillic", value=value, latin=latin), fix=fix,
    )
