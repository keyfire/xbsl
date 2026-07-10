"""Tier D: completeness of a dynamic list's field set against its object's attributes.

The yaml/dynlist-missing-field rule encodes a pitfall that neither the compiler nor apply
catches: a dynamic list typed with the row data of the object's automatic list form
(`Таблица<ДинамическийСписок<Акция.АвтоматическаяФормаСписка.ДанныеСтрокиСписка>>`) must
select EVERY attribute of that object in `Источник.Поля` – at runtime the list crashes
with "Отсутствует обязательное поле <Имя>" for the first attribute it cannot find. The
typical way to hit it: an attribute is added to the object, the list forms stay behind.

The criterion was established empirically on a real project corpus (9 dynamic lists).
Every list typed with the three-segment chain `<Объект>.АвтоматическаяФормаСписка.
ДанныеСтрокиСписка` carries the object's ENTIRE declared attribute set in `Поля` (plus
`Ссылка`); the corpus contains no `Обязательное: Истина` attributes at all, so the weaker
criterion "only the required attributes" has no empirical support and is not used. Lists
that derive the row type from the declaration itself require nothing and are skipped:
the untyped `Таблица<ДинамическийСписок>` (the corpus keeps a list untyped exactly when
the full set cannot be selected) and a form's own row type (`ФормаX.ДанныеСтрокиСписка`,
two segments – the platform docs declare such lists with a subset of fields).

Zero-false-positive guards (verified on the corpus – 0 diagnostics):
- only nodes whose `Тип` contains exactly one generic argument of the form
  `X.АвтоматическаяФормаСписка.ДанныеСтрокиСписка`, where X is a project object of kind
  Справочник/Документ with a parsed `Реквизиты` list;
- `Источник.ОсновнаяТаблица.Таблица` must equal X – an aliased or foreign table is skipped;
- `Источник.Поля` must be a non-empty list of mappings with string `Выражение` values;
  anything else means the field set cannot be trusted, and the node is skipped;
- collection-typed attributes (Массив/Соответствие/Множество/СписокЗначений) and binary
  ones (ДвоичныйОбъект) are not required: a typed selection cannot carry them at all
  (the compiler rejects "references a collection attribute"; the corpus keeps such lists
  untyped) – a typed list over such an object is a documented false negative;
- `Ссылка` and standard fields not declared in `Реквизиты` are not required – the rule
  checks only what the object's yaml declares;
- an attribute counts as present when its name matches a field's `Выражение` (bare or
  the last segment of a qualified `Псевдоним.Имя`) or the field's `Псевдоним`.

The rule is project-wide: it needs the objects' yaml next to the forms' yaml, so it does
not run in single-file mode.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator

from xbsllint import i18n
from xbsllint.diagnostics import Diagnostic, Severity
from xbsllint.engine import SourceFile, rule
from xbsllint.rules.yaml_schema import _HAVE_YAML, _parsed
from xbsllint.rules.yaml_types import _NAME_RE, _parse_type_string, _value_positions

MESSAGES = {
    "yaml/dynlist-missing-field.title": {
        "ru": "Нет поля динамического списка",
        "en": "Missing dynamic-list field",
    },
    "yaml/dynlist-missing-field.missing": {
        "ru": "В Источник.Поля нет реквизита '{attr}' объекта '{obj}' – список типизирован "
              "'{obj}.АвтоматическаяФормаСписка.ДанныеСтрокиСписка' и требует все реквизиты; "
              "в рантайме список упадёт с ошибкой 'Отсутствует обязательное поле'.",
        "en": "Источник.Поля misses attribute '{attr}' of object '{obj}' – the list is typed "
              "with '{obj}.АвтоматическаяФормаСписка.ДанныеСтрокиСписка' and requires every "
              "attribute; at runtime the list crashes with a required-field error.",
    },
}
i18n.register(MESSAGES)

# The automatic list form's row-data chain: <Объект>.АвтоматическаяФормаСписка.ДанныеСтрокиСписка.
_AUTO_TAIL = ("АвтоматическаяФормаСписка", "ДанныеСтрокиСписка")

# Object kinds whose declared attributes are known to make up the automatic row type.
_OBJECT_KINDS = frozenset({"Справочник", "Документ"})

# Attribute type roots a typed selection cannot carry – excluded from the required set.
_EXCLUDED_ROOTS = frozenset({
    "Массив", "Соответствие", "Множество", "СписокЗначений", "ДвоичныйОбъект",
})


def _object_attributes(sources: list[SourceFile]) -> dict[str, list[str]]:
    """Per Справочник/Документ object: the declared attribute names the row type requires.

    Attributes whose type does not parse, or is rooted in a collection/binary type, are
    left out (the safe direction – the rule requires less). Objects without a parsed
    `Реквизиты` list are absent from the result, and lists over them are skipped.
    """
    out: dict[str, list[str]] = {}
    for s in sources:
        if s.kind != "yaml":
            continue
        data, err = _parsed(s)
        if err is not None or not isinstance(data, dict):
            continue
        if data.get("ВидЭлемента") not in _OBJECT_KINDS:
            continue
        name = data.get("Имя")
        parts = data.get("Реквизиты")
        if not isinstance(name, str) or not isinstance(parts, list):
            continue
        attrs: list[str] = []
        for p in parts:
            if not isinstance(p, dict):
                continue
            attr = p.get("Имя")
            if not isinstance(attr, str) or not _NAME_RE.fullmatch(attr):
                continue
            typ = p.get("Тип")
            if isinstance(typ, str):
                chains = _parse_type_string(typ)
                if chains is None or any(c[0] in _EXCLUDED_ROOTS for c in chains):
                    continue
            attrs.append(attr)
        out[name] = attrs
    return out


def _source_nodes(node) -> Iterator[dict]:
    """Mapping nodes of the parsed yaml tree that carry both `Тип` and a mapping `Источник`."""
    if isinstance(node, dict):
        if "Тип" in node and isinstance(node.get("Источник"), dict):
            yield node
        for v in node.values():
            yield from _source_nodes(v)
    elif isinstance(node, list):
        for item in node:
            yield from _source_nodes(item)


def _declared_names(fields: list) -> set[str] | None:
    """Field names a `Поля` list declares, or None when the list cannot be trusted.

    A name is the `Выражение` itself, the last segment of a qualified expression
    (`Псевдоним.Имя`) and the `Псевдоним` when present. A field without a string
    `Выражение` makes the whole set unreliable – the caller skips the node.
    """
    names: set[str] = set()
    for f in fields:
        if not isinstance(f, dict):
            return None
        expr = f.get("Выражение")
        if not isinstance(expr, str):
            return None
        names.add(expr)
        if "." in expr:
            names.add(expr.rsplit(".", 1)[1])
        alias = f.get("Псевдоним")
        if isinstance(alias, str):
            names.add(alias)
    return names


@rule(
    "yaml/dynlist-missing-field", "yaml/dynlist-missing-field.title", "D",
    scope="project", severity=Severity.WARNING,
)
def dynlist_missing_field(sources: list[SourceFile]) -> Iterable[Diagnostic]:
    if not _HAVE_YAML:
        return []
    objects = _object_attributes(sources)
    if not objects:
        return []

    diags: list[Diagnostic] = []
    for s in sources:
        if s.kind != "yaml":
            continue
        data, err = _parsed(s)
        if err is not None or not isinstance(data, dict) or not data.get("ВидЭлемента"):
            continue
        seen: dict[str, int] = {}  # pairing of repeated `Тип` values with their text positions
        for node in _source_nodes(data):
            typ = node.get("Тип")
            if not isinstance(typ, str):
                continue
            occurrence = seen.get(typ, 0)
            seen[typ] = occurrence + 1
            chains = _parse_type_string(typ)
            if not chains:
                continue
            autos = [c for c in chains if len(c) == 3 and tuple(c[1:]) == _AUTO_TAIL]
            if len(autos) != 1:
                continue
            obj = autos[0][0]
            required = objects.get(obj)
            if not required:
                continue
            src = node["Источник"]
            main = src.get("ОсновнаяТаблица")
            if not isinstance(main, dict) or main.get("Таблица") != obj:
                continue
            fields = src.get("Поля")
            if not isinstance(fields, list) or not fields:
                continue
            present = _declared_names(fields)
            if present is None:
                continue
            missing = [a for a in required if a not in present]
            if not missing:
                continue
            positions = _value_positions(s, typ)
            if occurrence < len(positions):
                line, col = positions[occurrence]
            elif positions:
                line, col = positions[0]
            else:
                line, col = 1, 1
            diags.extend(
                Diagnostic(
                    s.rel, line, col, "yaml/dynlist-missing-field", Severity.WARNING,
                    i18n.t("yaml/dynlist-missing-field.missing", attr=attr, obj=obj),
                )
                for attr in missing
            )
    return diags
