"""Tier A: report query parameters stand under their own key (yaml/report-parameters-alias).

The metamodel read out of the distribution gives the `QueryParameters` property of a report a
second spelling, `Parameters`, the way it keeps the old names of other properties that the
compiler still accepts. The server does not accept this one: a live probe applied a report whose
parameters stood under `Parameters` and was refused with the unknown property message - the
stand answered in Russian, `Неизвестное свойство "Параметры"`. A check that trusts the metamodel
takes the key for valid, so the build fails on a key nothing reported.

The rule reads the top-level keys of a report, either spelling of the file: the English
`Parameters` is not declared for a report at all and fails the same way. The fix renames the key
to `QueryParameters` in the spelling of the file. When the report already has the right key, the
renamed one would repeat it - then the finding comes without a fix, and the two lists are merged
by hand.
"""

from __future__ import annotations

from collections.abc import Iterable
from functools import lru_cache

from xbsl import dataset, i18n, metamodel, terms
from xbsl.diagnostics import Diagnostic, Severity, TextEdit
from xbsl.engine import SourceFile, rule
from xbsl.rules.yaml_schema import _HAVE_YAML, _composed, _parsed, object_kind, object_kind_fast

if _HAVE_YAML:
    import yaml

MESSAGES = {
    "yaml/report-parameters-alias.title": {
        "ru": "Параметры отчета под ключом Параметры",
        "en": "Report parameters under the Parameters key",
    },
    "yaml/report-parameters-alias.found": {
        "ru": "Параметры запроса отчета задаются ключом '{right}': ключ '{key}' сервер не "
              "принимает, сборка упадет с 'Неизвестное свойство \"{key}\"'. Переименуйте ключ в "
              "'{right}'.",
        "en": "The query parameters of a report are set with the '{right}' key: the server does "
              "not accept '{key}', and the build fails with 'Неизвестное свойство \"{key}\"'. "
              "Rename the key to '{right}'.",
    },
}
i18n.register(MESSAGES)

_REPORT = "Отчет"
#: The key the server rejects and the property it stands for, in the metamodel's spelling.
_ALIAS = "Параметры"
_RIGHT = "ПараметрыЗапроса"


@lru_cache(maxsize=1)
def _alias_forms() -> frozenset[str]:
    """Both spellings of the rejected key - `Parameters` is the English of the same word."""
    return frozenset(terms.key_forms(_ALIAS))


@lru_cache(maxsize=1)
def _right_forms() -> tuple[str, str | None]:
    """(the Russian key, its English spelling or None without the data)."""
    record = metamodel.properties(_REPORT).get(_RIGHT) or {}
    return _RIGHT, record.get("en")


for _cache in (_alias_forms, _right_forms):
    dataset.register_reset(_cache.cache_clear)


@rule("yaml/report-parameters-alias", "yaml/report-parameters-alias.title", "A",
      severity=Severity.ERROR)
def report_parameters_alias(source: SourceFile) -> Iterable[Diagnostic]:
    if source.kind != "yaml" or not _HAVE_YAML or object_kind_fast(source) != _REPORT:
        return
    aliases = _alias_forms()
    if not any(alias in source.text for alias in aliases):
        return
    data, err = _parsed(source)
    if err is not None or object_kind(data) != _REPORT:
        return
    root = _composed(source)
    if root is None or not isinstance(root, yaml.MappingNode):
        return
    russian, english = _right_forms()
    keys = {key.value for key, _value in root.value if isinstance(key, yaml.ScalarNode)}
    taken = russian in keys or (english is not None and english in keys)
    for key_node, _value in root.value:
        if not isinstance(key_node, yaml.ScalarNode) or key_node.value not in aliases:
            continue
        key = key_node.value
        # The file speaks the language of the key - so does the replacement.
        right = russian if not key.isascii() or english is None else english
        start, end = key_node.start_mark.index, key_node.end_mark.index
        mechanical = not key_node.style and source.text[start:end] == key and not taken
        yield Diagnostic(
            source.rel, key_node.start_mark.line + 1, key_node.start_mark.column + 1,
            "yaml/report-parameters-alias", Severity.ERROR,
            i18n.t("yaml/report-parameters-alias.found", key=key, right=right),
            fix=TextEdit(start, end, right) if mechanical else None,
        )
