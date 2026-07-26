"""Tier D: the two halves of per-object access control that the compiler does not check.

An object may declare that a permission is decided per record - `Permissions: {Read:
PermissionsCalculatedForEachObject}` - and then name, in `PermissionsCalculatedBy`, the
attributes the decision is allowed to read. Two consequences of that contract are silent
until the application runs or refuses to build, and both are settled by the pair of files:

- code/per-object-permissions-need-common: an object asking for per-object permissions still
  needs the common handler `ВычислитьРазрешенияДоступа` in its module. It may return an empty
  array - the point is that the common calculation exists; without it the object has no
  general permissions at all and nothing falls through to the per-object one.

- code/permission-field-not-declared: inside `ВычислитьРазрешенияДоступаДляОбъектов` the
  record is reached as `Запись.<Поле>`, and only the attributes listed in
  `PermissionsCalculatedBy` are readable there. The rule reports two shapes of the same
  mistake: a field the list does not carry, and a DECLARED field reached through `Сущность`
  instead of the record ("Variable Сущность is not defined"). The second half needs the
  declared list to tell it from the legal `Сущность.Право`, which is a namespace of the
  platform and appears in the very same handler - hence the check fires only on a name the
  yaml itself declares as a record attribute.

Both are narrow on purpose. The field check runs only inside the body of the per-object
handler (a variable named `Запись` elsewhere in the module is not this record) and only when
the yaml lists the fields at all - an object that declares none is a different defect and is
left alone rather than guessed at.
"""

from __future__ import annotations

from collections.abc import Iterable
from functools import lru_cache

import yaml as _yaml

from xbsl import dataset, i18n, metamodel, terms
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, rule
from xbsl.rules._syntax import code_tokens
from xbsl.rules.environment import _decl_anchors, _method_bodies, _module_decls, _pair_stem
from xbsl.rules.yaml_schema import (
    _composed,
    _HAVE_YAML,
    _mapping_nodes,
    _parsed,
    object_kind,
)

MESSAGES = {
    "code/per-object-permissions-need-common.title": {
        "ru": "Нет общего расчёта разрешений при per-object",
        "en": "No common permission calculation alongside the per-object one",
    },
    "code/per-object-permissions-need-common.missing": {
        "ru": "У объекта '{name}' разрешения ({rights}) вычисляются для каждого объекта, но в "
              "модуле нет обработчика ВычислитьРазрешенияДоступа – он обязателен и при "
              "per-object. Объявите его, возвращая пустой массив разрешений.",
        "en": "Object '{name}' calculates its permissions ({rights}) per object, but its module "
              "declares no {n[ВычислитьРазрешенияДоступа]} handler – it is required even then. "
              "Declare it returning an empty array of permissions.",
    },
    "code/permission-field-not-declared.title": {
        "ru": "Поле записи вне расчёта разрешений",
        "en": "A record field outside the permission calculation",
    },
    "code/permission-field-not-declared.field": {
        "ru": "Обращение 'Запись.{field}' в обработчике '{method}': поля '{field}' нет среди "
              "РасчетРазрешенийПо ({declared}) – в расчёте разрешений оно недоступно. Добавьте "
              "поле в РасчетРазрешенийПо либо читайте одно из объявленных.",
        "en": "Access '{n[Запись]}.{field}' in handler '{method}': the field is not among "
              "{n[РасчетРазрешенийПо]} ({declared}) – it is unavailable to the permission "
              "calculation. Add it there, or read one of the declared fields.",
    },
    "code/permission-field-not-declared.wrong-root": {
        "ru": "Обращение 'Сущность.{field}' в обработчике '{method}': реквизит записи читается "
              "как 'Запись.{field}' – через Сущность он не виден (\"Variable Сущность is not "
              "defined\"). Сама Сущность остаётся пространством имён для Сущность.Право.",
        "en": "Access '{n[Сущность]}.{field}' in handler '{method}': a record attribute is read "
              "as '{n[Запись]}.{field}' – it is not visible through {n[Сущность]} (\"Variable "
              "Entity is not defined\"). {n[Сущность]} itself stays the namespace of "
              "{n[Сущность]}.{n[Право]}.",
    },
}
i18n.register(MESSAGES)

_PER_OBJECT = "РазрешенияВычисляютсяДляКаждогоОбъекта"
_COMMON_HANDLER = "ВычислитьРазрешенияДоступа"
_PER_OBJECT_HANDLER = "ВычислитьРазрешенияДоступаДляОбъектов"
_RECORD = "Запись"
_ENTITY = "Сущность"


def _forms(name: str) -> frozenset[str]:
    """Both spellings of a platform name, taken from its own dictionaries.

    `terms` answers for types and enumeration values, the metamodel for the property keys of
    an element; a name written out here instead was once wrong (`PermissionsCalculatedBy`
    against the platform's `ComputePermissionsBy`), so nothing is guessed.
    """
    english = terms.common_english(name) or metamodel.english_name(name)
    return frozenset({name, english} - {None})


@lru_cache(maxsize=1)
def _names() -> tuple[frozenset[str], ...]:
    """Both spellings of every platform name this module matches by text."""
    return (
        _forms(_PER_OBJECT),
        _forms(_COMMON_HANDLER),
        _forms(_PER_OBJECT_HANDLER),
        _forms(_RECORD),
        _forms(_ENTITY),
        _forms("КонтрольДоступа"),
        _forms("Разрешения"),
        _forms("РасчетРазрешенийПо"),
    )


dataset.register_reset(_names.cache_clear)


def _first_of(data: dict, keys: frozenset[str]):
    for key in keys:
        if key in data:
            return data[key]
    return None


def _permissions_position(source: SourceFile, control_keys: frozenset[str]) -> tuple[int, int]:
    """Line and column of the КонтрольДоступа key, or the start of the file."""
    root = _composed(source)
    if root is not None:
        for mapping in _mapping_nodes(root):
            for key_node, _value in mapping.value:
                if isinstance(key_node, _yaml.ScalarNode) and key_node.value in control_keys:
                    return key_node.start_mark.line + 1, key_node.start_mark.column + 1
    return 1, 1


def _access_mapper(source: SourceFile) -> dict | None:
    """The map phase. A yaml contributes the per-object rights it declares and the fields the
    calculation may read; a module contributes its declared names and the `Запись.<Поле>`
    accesses of the per-object handler alone."""
    if not _HAVE_YAML:
        return None
    (per_object, common, per_object_method, record, entity,
     control_keys, perm_keys, by_keys) = _names()
    if source.kind == "yaml":
        data, error = _parsed(source)
        if error is not None or not isinstance(data, dict) or not object_kind(data):
            return None
        control = _first_of(data, control_keys)
        if not isinstance(control, dict):
            return None
        perms = _first_of(control, perm_keys)
        rights = sorted(
            name for name, value in (perms.items() if isinstance(perms, dict) else ())
            if value in per_object
        )
        if not rights:
            return None
        declared = _first_of(control, by_keys)
        fields = [f for f in (declared or ()) if isinstance(f, str)]
        line, col = _permissions_position(source, control_keys)
        name = data.get("Имя") or data.get("Name") or "?"
        return {"k": "y", "stem": _pair_stem(source.rel), "name": name,
                "rights": rights, "fields": fields, "line": line, "col": col}
    if source.kind != "xbsl":
        return None
    toks = code_tokens(source)
    decls, methods = _module_decls(toks)
    has_common = bool(decls.keys() & common)
    bodies = _method_bodies(toks, methods, _decl_anchors(toks))
    n = len(toks)
    accesses: list[tuple[str, str, int, int]] = []
    for method, (start, end) in bodies.items():
        if method not in per_object_method:
            continue
        for i in range(start, min(end, n)):
            t = toks[i]
            if not (t.kind == "IDENT" and i + 2 < n
                    and toks[i + 1].kind == "OP" and toks[i + 1].value == "."
                    and toks[i + 2].kind == "IDENT"):
                continue
            member = toks[i + 2]
            if t.value in record:
                accesses.append(("record", method, member.value, member.line, member.col))
            elif t.value in entity:
                accesses.append(("entity", method, member.value, member.line, member.col))
    # A fact is produced for EVERY module, not only for one that already declares a
    # handler: "the module has neither" is exactly the case the common-handler rule must
    # report, and a mapper that returned None there would make it indistinguishable from
    # "no paired module at all".
    return {"k": "x", "stem": _pair_stem(source.rel),
            "has_common": has_common, "accesses": accesses}


@rule(
    "code/per-object-permissions-need-common",
    "code/per-object-permissions-need-common.title", "D",
    scope="project", severity=Severity.WARNING, mapper=_access_mapper,
)
def per_object_permissions_need_common(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    modules = {f["stem"]: f for f in facts.values() if f["k"] == "x"}
    for rel, fact in facts.items():
        if fact["k"] != "y":
            continue
        module = modules.get(fact["stem"])
        if module is None:
            continue  # no paired module at all - structure/xbsl-pair territory
        if module["has_common"]:
            continue
        yield Diagnostic(
            rel, fact["line"], fact["col"],
            "code/per-object-permissions-need-common", Severity.WARNING,
            i18n.t("code/per-object-permissions-need-common.missing",
                   name=fact["name"], rights=", ".join(fact["rights"])),
        )


@rule(
    "code/permission-field-not-declared",
    "code/permission-field-not-declared.title", "D",
    scope="project", severity=Severity.WARNING, mapper=_access_mapper,
)
def permission_field_not_declared(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    declared_by = {
        f["stem"]: f["fields"] for f in facts.values()
        if f["k"] == "y" and f["fields"]
    }
    if not declared_by:
        return
    for rel, fact in facts.items():
        if fact["k"] != "x":
            continue
        fields = declared_by.get(fact["stem"])
        if not fields:
            continue
        allowed = set(fields)
        for root, method, field, line, col in fact["accesses"]:
            if root == "entity":
                # `Сущность.Право` is the namespace and is legal; a DECLARED field behind
                # `Сущность` is the record read through the wrong root.
                if field not in allowed:
                    continue
                key = "code/permission-field-not-declared.wrong-root"
            else:
                if field in allowed:
                    continue
                key = "code/permission-field-not-declared.field"
            yield Diagnostic(
                rel, line, col,
                "code/permission-field-not-declared", Severity.WARNING,
                i18n.t(key, field=field, method=method, declared=", ".join(fields)),
            )
