"""Tier D: the halves of computed access control that the compiler does not check.

An object may declare that a permission is decided per record - `Permissions: {Read:
PermissionsCalculatedForEachObject}` - and then name, in `PermissionsCalculatedBy`, the
attributes the decision is allowed to read. The consequences of that contract are silent
until the application runs or refuses to build, and they are settled by this module:

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

- code/permission-handlers-need-recalc: the platform never calls a permission handler by
  itself. The documentation ("Пересчет разрешений и экземпляров ключей") requires an explicit
  `<Entity>.RecomputeAccessPermissions()` in a project-update handler both when the
  algorithm changes and when an access-controlled element is added - without it the edit has
  no effect on existing data, while the deploy looks successful. The rule reports a module
  that declares any of the four computation handlers while the project calls the recompute
  method for that entity nowhere.

  The narrowings, each a measured decision:

  * the judged kinds come from the DATA, not from a list: only a kind whose stdlib record
    carries the recompute method is judged. A rights element (PrivilegeOnAction and kin)
    declares the same-named handler but has no recompute method at all - its currency is
    kept by key recomputation, a different mechanism (verified live on a project);
  * a recompute call whose receiver is not a project entity name silences the rule for the
    WHOLE project: the documentation itself shows the loop form over all catalogs, where
    the receiver is a loop variable, and guessing what such a loop covers would fabricate
    false positives;
  * a call anywhere in the project counts - the documentation asks for the project-update
    handler, but a recompute reachable from seeding or an administrative action keeps the
    permissions current too, and judging the call site would argue with working projects.
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
    "code/access-context-read-noop.title": {
        "ru": "Холостое расширение контекста доступа чтением",
        "en": "A context extension that grants a read everyone already has",
    },
    "code/access-context-read-noop.alone": {
        "ru": "Расширение контекста доступа правом Чтения для '{name}': чтение у этого типа "
              "разрешено всем (Чтение: РазрешеноВсем), выдавать нечего. Вызов холост – он "
              "только создаёт впечатление защищённости; строку можно снять.",
        "en": "Extending the access context with the {n[Чтение]} privilege for '{name}': the "
              "type permits reading to everyone ({n[Чтение]}: {n[РазрешеноВсем]}), so there is "
              "nothing to grant. The call does nothing but suggest the data is guarded – drop "
              "the line.",
    },
    "code/access-context-read-noop.among": {
        "ru": "Право Чтения в расширении контекста доступа для '{name}' холостое: чтение у "
              "этого типа разрешено всем (Чтение: РазрешеноВсем). Остальные права списка "
              "нужны – снять надо только Чтение.",
        "en": "The {n[Чтение]} privilege of the context extension for '{name}' grants nothing: "
              "the type permits reading to everyone ({n[Чтение]}: {n[РазрешеноВсем]}). The "
              "other privileges of the list are needed – drop this one alone.",
    },
    "code/permission-handlers-need-recalc.title": {
        "ru": "Обработчик разрешений без пересчёта",
        "en": "A permission handler with no recomputation",
    },
    "code/permission-handlers-need-recalc.missing": {
        "ru": "Модуль объявляет '{handler}', но нигде в проекте не вызван "
              "'{name}.ПересчитатьРазрешенияДоступа()' – платформа обработчик сама не "
              "вызывает: без пересчёта правка алгоритма прав не действует на существующих "
              "данных, а деплой выглядит успешным. Добавьте пересчёт в обработчик "
              "@ОбновлениеПроекта.",
        "en": "The module declares '{handler}', but "
              "'{name}.{n[ПересчитатьРазрешенияДоступа]}()' is called nowhere in the "
              "project – the platform never calls the handler by itself: without a "
              "recomputation an edit of the permission algorithm has no effect on existing "
              "data, while the deploy looks successful. Add the recomputation to an "
              "@{n[ОбновлениеПроекта]} update handler.",
    },
}
i18n.register(MESSAGES)

_PER_OBJECT = "РазрешенияВычисляютсяДляКаждогоОбъекта"
_COMMON_HANDLER = "ВычислитьРазрешенияДоступа"
_PER_OBJECT_HANDLER = "ВычислитьРазрешенияДоступаДляОбъектов"
_KEYS_READ_HANDLER = "ВычислитьКлючиДоступаДляЧтения"
_KEYS_WRITE_HANDLER = "ВычислитьКлючиДоступаДляИзменения"
_RECALC = "ПересчитатьРазрешенияДоступа"
_RECALC_OBJECTS = "ПересчитатьРазрешенияДоступаДляОбъектов"
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


@lru_cache(maxsize=1)
def _recalc_names() -> tuple[frozenset[str], frozenset[str], frozenset[str]]:
    """(triggering handlers, recompute methods, judged kinds) - all from the data.

    A kind is judged only when its stdlib record carries the recompute method: a rights
    element declares the same-named handler yet has no such method at all, and its currency
    is kept by key recomputation - flagging it would demand a call that cannot compile.
    An empty kind set (no Element data) switches the rule off.
    """
    handlers = frozenset().union(
        _forms(_COMMON_HANDLER), _forms(_PER_OBJECT_HANDLER),
        _forms(_KEYS_READ_HANDLER), _forms(_KEYS_WRITE_HANDLER),
    )
    recalc = frozenset().union(_forms(_RECALC), _forms(_RECALC_OBJECTS))
    try:
        members = dataset.load_json("stdlib.json").get("type_members") or {}
    except Exception:  # noqa: BLE001 - no data, no rule
        members = {}
    kinds = frozenset(
        kind for kind, record in members.items()
        if _RECALC in (record.get("methods") or ())
    )
    return handlers, recalc, kinds


dataset.register_reset(_recalc_names.cache_clear)


def _recalc_mapper(source: SourceFile) -> dict | None:
    """The map phase. Every object yaml contributes its name and kind - the reduce needs
    the full name set to tell a specific recompute receiver from a generic one (a loop
    variable). A module contributes the permission handlers it declares, with their
    positions, and the receivers of the recompute calls it makes."""
    handlers, recalc, kinds = _recalc_names()
    if not kinds:
        return None
    if source.kind == "yaml":
        if not _HAVE_YAML:
            return None
        data, error = _parsed(source)
        if error is not None or not isinstance(data, dict):
            return None
        kind = object_kind(data)
        name = data.get("Имя") or data.get("Name")
        if not kind or not isinstance(name, str) or not name:
            return None
        return {"k": "p", "stem": _pair_stem(source.rel), "name": name, "kind": kind}
    if source.kind != "xbsl":
        return None
    if not any(name in source.text for name in handlers | recalc):
        return None
    toks = code_tokens(source)
    _decls, methods = _module_decls(toks)
    declared: list[tuple[str, int, int]] = []
    n = len(toks)
    for name, _annotations, anchor in methods:
        if name not in handlers:
            continue
        t = toks[anchor + 1] if anchor + 1 < n else toks[anchor]
        declared.append((name, t.line, t.col))
    receivers: list[str] = []
    for i, t in enumerate(toks):
        if (t.kind == "IDENT" and t.value in recalc
                and i >= 2 and toks[i - 1].kind == "OP" and toks[i - 1].value == "."
                and toks[i - 2].kind == "IDENT"
                and i + 1 < n and toks[i + 1].kind == "OP" and toks[i + 1].value == "("):
            receivers.append(toks[i - 2].value)
    if not declared and not receivers:
        return None
    return {"k": "m", "stem": _pair_stem(source.rel),
            "declared": declared, "receivers": receivers}


@rule(
    "code/permission-handlers-need-recalc",
    "code/permission-handlers-need-recalc.title", "D",
    scope="project", severity=Severity.WARNING, mapper=_recalc_mapper,
)
def permission_handlers_need_recalc(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    objects = {f["stem"]: f for f in facts.values() if f["k"] == "p"}
    names = {f["name"] for f in objects.values()}
    _handlers, _recalc_forms, kinds = _recalc_names()
    recalled: set[str] = set()
    for fact in facts.values():
        if fact["k"] != "m":
            continue
        for receiver in fact["receivers"]:
            if receiver in names:
                recalled.add(receiver)
            else:
                # A loop variable or another indirection: what it covers cannot be told,
                # and guessing would fabricate findings - the rule stands down entirely.
                return
    for rel, fact in facts.items():
        if fact["k"] != "m" or not fact["declared"]:
            continue
        entity = objects.get(fact["stem"])
        if entity is None or entity["kind"] not in kinds:
            continue  # no paired yaml, or a kind with no recompute method
        if entity["name"] in recalled:
            continue
        handler, line, col = fact["declared"][0]
        yield Diagnostic(
            rel, line, col, "code/permission-handlers-need-recalc", Severity.WARNING,
            i18n.t("code/permission-handlers-need-recalc.missing",
                   name=entity["name"], handler=handler),
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


# --- code/access-context-read-noop -----------------------------------------------------------

_CONTEXT = "КонтекстДоступа"
_APPEND = "Дополнить"
_TYPE = "Тип"
_PRIVILEGE = "Право"
_READ = "Чтение"
_EVERYONE = "РазрешеноВсем"


@lru_cache(maxsize=1)
def _noop_names() -> tuple[frozenset[str], ...]:
    """Both spellings of every name the no-op check matches by text."""
    return (
        _forms(_CONTEXT), _forms(_APPEND), _forms(_TYPE), _forms(_PRIVILEGE),
        _forms(_READ), _forms(_EVERYONE), _forms("КонтрольДоступа"), _forms("Разрешения"),
    )


dataset.register_reset(_noop_names.cache_clear)


def _read_rights_of(source: SourceFile) -> list[tuple[str, int, int, int]]:
    """(type name, line, col of the Read right, count of rights) of every context extension.

    Only a call that HANDS OUT the read right is returned; the position is that of the right
    itself, because that is what has to go - the call may carry others that are needed.
    """
    context, append, type_kw, privilege, read, *_rest = _noop_names()
    toks = code_tokens(source)
    n = len(toks)
    out: list[tuple[str, int, int, int]] = []
    for i, t in enumerate(toks):
        if not (t.kind == "IDENT" and t.value in context):
            continue
        if not (i + 3 < n and toks[i + 1].value == "." and toks[i + 2].value in append
                and toks[i + 3].value == "("):
            continue
        # The first argument names the entity: `Type<X.Object>`. `Type` is a keyword of the
        # language, not an identifier, so the kind is not checked here.
        name = None
        j = i + 4
        while j < n and toks[j].value != ")":
            if toks[j].value in type_kw and j + 2 < n and toks[j + 1].value == "<":
                name = toks[j + 2].value
                break
            j += 1
        if name is None:
            continue
        rights: list = []
        depth = 0
        k = j
        while k < n:
            value = toks[k].value
            if value == "(":
                depth += 1
            elif value == ")":
                if depth == 0:
                    break
                depth -= 1
            elif (toks[k].kind == "IDENT" and k >= 2 and toks[k - 1].value == "."
                  and toks[k - 2].value in privilege):
                rights.append(toks[k])
            k += 1
        granted = next((r for r in rights if r.value in read), None)
        if granted is not None:
            out.append((name, granted.line, granted.col, len(rights)))
    return out


def _read_noop_mapper(source: SourceFile) -> dict | None:
    """The map phase: what each object declares about READING, and who extends the context."""
    if not _HAVE_YAML:
        return None
    *_head, everyone, control_keys, perm_keys = _noop_names()
    read = _noop_names()[4]
    if source.kind == "yaml":
        data, error = _parsed(source)
        if error is not None or not isinstance(data, dict) or not object_kind(data):
            return None
        control = _first_of(data, control_keys)
        perms = _first_of(control, perm_keys) if isinstance(control, dict) else None
        value = _first_of(perms, read) if isinstance(perms, dict) else None
        name = data.get("Имя") or data.get("Name")
        if not isinstance(name, str) or not isinstance(value, str) or value not in everyone:
            return None
        return {"k": "e", "name": name}  # reading is open to everyone
    if source.kind != "xbsl":
        return None
    calls = _read_rights_of(source)
    return {"k": "c", "calls": calls} if calls else None


@rule(
    "code/access-context-read-noop", "code/access-context-read-noop.title", "D",
    scope="project", severity=Severity.WARNING, mapper=_read_noop_mapper,
)
def access_context_read_noop(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    everyone = {f["name"] for f in facts.values() if f["k"] == "e"}
    if not everyone:
        return
    for rel, fact in facts.items():
        if fact["k"] != "c":
            continue
        for name, line, col, rights in fact["calls"]:
            if name not in everyone:
                continue
            key = ("code/access-context-read-noop.alone" if rights == 1
                   else "code/access-context-read-noop.among")
            yield Diagnostic(
                rel, line, col, "code/access-context-read-noop", Severity.WARNING,
                i18n.t(key, name=name),
            )
