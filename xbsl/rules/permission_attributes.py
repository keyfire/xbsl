"""Tier A: the attributes the permissions of objects are computed by (`ComputePermissionsBy`).

An entity whose access settings compute a permission for each object - a privilege set to
`PermissionsComputedForEachObject`, or the default set so and some privilege left out - reads
the permissions of an object from the attributes `ComputePermissionsBy` lists. The build checks
the list both ways (the processor of those attributes in the compiler, 2026-09; a probe on a
server gave both answers):

- `.missing`: the settings compute a permission for each object, and the list is absent or
  empty. The build refuses it with "Attributes for calculating object access permissions are
  missing" at the start of the `AccessControl` block. The standard permissions of a settings
  storage are the exception: the build takes the attributes of its own then.
- `.without-per-object`: the list is there, and no permission is computed for each object. The
  build refuses it with "It is not allowed to specify attributes for calculating access
  permissions without configuring access permissions calculation for each object", at the
  first attribute of the list.

A privilege takes the value the settings give it or else their default (the administrators
when the default is not written) - the reading code/handler-overrides-nothing shares. The kinds
judged are those whose access settings have the property at all: a catalog, a document, an
exchange plan, a settings storage, an integrable application and the registers. A description
that cannot be read that far is not judged.
"""

from __future__ import annotations

from collections.abc import Iterable

from xbsl import i18n, metamodel
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, rule
from xbsl.rules.handler_annotation import _access_settings, _key_in
from xbsl.rules.yaml_schema import (
    _HAVE_YAML,
    _composed,
    _parsed,
    object_kind,
    object_kind_fast,
    value_of,
)

if _HAVE_YAML:
    import yaml

RULE = "yaml/compute-permissions-by"

MESSAGES = {
    f"{RULE}.title": {
        "ru": "РасчетРазрешенийПо не согласован с расчетом разрешений для каждого объекта",
        "en": "ComputePermissionsBy does not match the permissions computed for each object",
    },
    f"{RULE}.missing": {
        "ru": "Настройки доступа вычисляют разрешения для каждого объекта "
              "(РазрешенияВычисляютсяДляКаждогоОбъекта), а реквизитов в РасчетРазрешенийПо "
              "нет. Сборка откажет: \"Attributes for calculating object access permissions "
              "are missing\". Перечислите в РасчетРазрешенийПо реквизиты, по которым "
              "вычисляются разрешения объекта.",
        "en": "The access settings compute permissions for each object "
              "({n[РазрешенияВычисляютсяДляКаждогоОбъекта]}), yet {n[РасчетРазрешенийПо]} "
              "lists no attribute. The build refuses it: \"Attributes for calculating object "
              "access permissions are missing\". List the attributes the permissions of an "
              "object are computed by under {n[РасчетРазрешенийПо]}.",
    },
    f"{RULE}.without-per-object": {
        "ru": "РасчетРазрешенийПо перечисляет реквизиты, а настройки доступа ни одно "
              "разрешение для каждого объекта не вычисляют. Сборка откажет: \"It is not "
              "allowed to specify attributes for calculating access permissions without "
              "configuring access permissions calculation for each object\". Уберите список "
              "или поставьте разрешению значение РазрешенияВычисляютсяДляКаждогоОбъекта.",
        "en": "{n[РасчетРазрешенийПо]} lists attributes, yet the access settings compute no "
              "permission for each object. The build refuses it: \"It is not allowed to "
              "specify attributes for calculating access permissions without configuring "
              "access permissions calculation for each object\". Remove the list, or set a "
              "permission to {n[РазрешенияВычисляютсяДляКаждогоОбъекта]}.",
    },
}
i18n.register(MESSAGES)

_CONTROL = "КонтрольДоступа"
_BY = "РасчетРазрешенийПо"


def _control_props(kind: str) -> dict[str, dict]:
    """The properties of the access settings of the kind, {} for a kind without them."""
    record = metamodel.properties(kind).get(_CONTROL) or {}
    return metamodel.properties_of_class(record.get("type") or "") if record else {}


def _node_of(root, keys: tuple[str, ...]):
    """The value node under a path of keys (each in either spelling given), or None."""
    node = root
    for spellings in keys:
        if not isinstance(node, yaml.MappingNode):
            return None
        node = next((value for key, value in node.value
                     if isinstance(key, yaml.ScalarNode) and key.value in spellings), None)
        if node is None:
            return None
    return node


@rule(RULE, f"{RULE}.title", "A", severity=Severity.ERROR)
def compute_permissions_by(source: SourceFile) -> Iterable[Diagnostic]:
    """`ComputePermissionsBy` against the permissions computed for each object - see the
    module docstring."""
    if source.kind != "yaml" or not _HAVE_YAML:
        return
    kind = object_kind_fast(source)
    if not kind:
        return
    props = _control_props(kind)
    if _BY not in props:
        return
    data, error = _parsed(source)
    if error is not None or object_kind(data) != kind:
        return
    control = value_of(data, _CONTROL, kind)
    if not isinstance(control, dict):
        return
    settings = _access_settings(data, kind)
    if settings is None:
        return
    listed = _key_in(control, props, _BY)
    if isinstance(listed, str):
        given = bool(listed.strip())
    elif isinstance(listed, (list, dict)):
        given = bool(listed)
    else:
        given = listed is not None
    root = _composed(source)
    if root is None:
        return
    control_keys = {_CONTROL, (metamodel.properties(kind).get(_CONTROL) or {}).get("en")}
    by_keys = {_BY, (props.get(_BY) or {}).get("en")}
    if settings.per_object and not settings.standard and not given:
        node = _node_of(root, (control_keys,))
        if node is None:
            return
        yield Diagnostic(source.rel, node.start_mark.line + 1, node.start_mark.column + 1, RULE,
                         Severity.ERROR, i18n.t(f"{RULE}.missing"))
    elif not settings.per_object and given:
        node = _node_of(root, (control_keys, by_keys))
        if isinstance(node, yaml.SequenceNode) and node.value:
            node = node.value[0]
        if node is None:
            return
        yield Diagnostic(source.rel, node.start_mark.line + 1, node.start_mark.column + 1, RULE,
                         Severity.ERROR, i18n.t(f"{RULE}.without-per-object"))
