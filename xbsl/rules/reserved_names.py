"""Tier D: names the server-side apply rejects, which the compiler does not check.

The code/reserved-name rule: the names `Тип` and `type` are rejected by the server apply
("Invalid field name") when used as a structure field name (`пер/знч/обз` inside a
`структура ... ;` block) or as a method/constructor parameter name. The check is
token-based: structure blocks are delimited from the lowercase `структура` keyword to the
terminating `;` at bracket depth 0 (or, as a safety stop, to the next lowercase
метод/конструктор/структура/перечисление/исключение keyword – a structure holds only field
declarations); parameters come from the shared signature parser. The lexer classifies `Тип`
as a keyword (the type literal), so for the name scan the TYPE keyword is downgraded to an
identifier locally. Three spellings are checked: the two above and the capitalized `Type`
an English structure field carries - a live apply (02.09.2026) refused a field of that name
as reserved, the same refusal as for the other two; other casings are not confirmed to be
rejected. Local variables and other name positions are left alone on
purpose: a local variable named `Тип` inside a method is legal, so widening the rule would
produce false positives.

The yaml/builtin-property-name rule: in a `ВидЭлемента: КомпонентИнтерфейса` yaml, declaring
an own property (`Свойства: - Имя: X`) whose name matches a built-in property of the BASE
component type (`Наследует.Тип`, the root before the generic arguments) is rejected by the
server apply ("Invalid property name") – the classic case is `Заголовок` on an inheritor of
СтандартнаяКарточка. The built-in property set of the base type is taken from the metamodel
class (transitively over inheritance, as in yaml/unknown-property) when the type is present
there; the current metamodel (configuration .xcore) does not describe UI component types, so
the sets come from the versioned catalog (stdlib.json component_props, extracted from the
distribution docs by tools/extract_stdlib.py: the type's own properties plus the inherited
ones the page lists itself), with the module's vetted СтандартнаяКарточка table kept as the
safety net for data generated before that key existed – per base type the two sources are
unioned. A base type found in no source is skipped rather than guessed – in particular a
base that is itself a project component (unresolvable in file scope). The check is strictly
per base type: a property `Заголовок` on an inheritor of КонтейнерHtml (whose documented set
has no Заголовок) is legal, so no cross-type generalization is allowed. Positions are searched only inside the top-level `Свойства:` block – the same name
as an event or a nested component name cannot false-match.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import replace
from functools import lru_cache

from xbsl import dataset, i18n, metamodel, uischema
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, rule
from xbsl.lexer import linemap
from xbsl.rules._syntax import code_tokens, declarations, signatures
from xbsl.rules.yaml_schema import _HAVE_YAML, _parsed, object_kind, value_of
from xbsl.rules.yaml_types import _key_spellings

MESSAGES = {
    "code/reserved-name.title": {
        "ru": "Зарезервированное имя",
        "en": "Reserved name",
    },
    "code/reserved-name.field": {
        "ru": "Имя '{name}' зарезервировано – поле структуры с таким именем "
              "отвергается сервером при применении (Invalid field name).",
        "en": "The name '{name}' is reserved – the server apply rejects "
              "a structure field with this name (Invalid field name).",
    },
    "code/reserved-name.param": {
        "ru": "Имя '{name}' зарезервировано – параметр метода с таким именем "
              "отвергается сервером при применении (Invalid field name).",
        "en": "The name '{name}' is reserved – the server apply rejects "
              "a method parameter with this name (Invalid field name).",
    },
    "yaml/builtin-property-name.title": {
        "ru": "Совпадение со встроенным свойством",
        "en": "Built-in property name clash",
    },
    "yaml/builtin-property-name.clash": {
        "ru": "Свойство '{prop}' повторяет встроенное свойство базового типа '{base}' – "
              "сервер отвергает такое объявление при применении (Invalid property name).",
        "en": "Property '{prop}' duplicates a built-in property of the base type '{base}' – "
              "the server apply rejects such a declaration (Invalid property name).",
    },
}
i18n.register(MESSAGES)

# The exact spellings the server apply is confirmed to reject in field/parameter positions.
_RESERVED_NAMES = frozenset({"Тип", "type", "Type"})

# Keywords that cannot occur inside a structure body – a safety stop for an unterminated block.
_BLOCK_BREAK_KW = ("METHOD", "CONSTRUCTOR", "STRUCTURE", "ENUMERATION", "EXCEPTION")


def _name_tokens(toks: list) -> list:
    """Tokens with the TYPE keyword (`Тип`/`Type`) downgraded to an identifier.

    The lexer classifies `Тип` as a keyword, so the shared declaration/signature parsers
    would not see it in a name position – which is exactly where this rule looks for it.
    The downgrade is local to this rule and does not affect other checks.
    """
    return [
        replace(t, kind="IDENT") if t.kind == "KEYWORD" and t.canonical == "TYPE" else t
        for t in toks
    ]


def _structure_blocks(toks: list) -> list[tuple[int, int]]:
    """Index ranges [start, end) of the token spans inside `структура ... ;` blocks."""
    blocks: list[tuple[int, int]] = []
    n = len(toks)
    i = 0
    while i < n:
        t = toks[i]
        if t.kind == "KEYWORD" and t.value[:1].islower() and t.canonical == "STRUCTURE":
            j = i + 1
            if j < n and toks[j].kind == "IDENT":  # the structure name
                j += 1
            start = j
            depth = 0
            while j < n:
                tj = toks[j]
                if tj.kind == "OP" and tj.value in "([{":
                    depth += 1
                elif tj.kind == "OP" and tj.value in ")]}":
                    depth -= 1
                elif depth == 0 and tj.kind == "OP" and tj.value == ";":
                    break
                elif (tj.kind == "KEYWORD" and tj.value[:1].islower()
                        and tj.canonical in _BLOCK_BREAK_KW):
                    break
                j += 1
            blocks.append((start, j))
            i = j
            continue
        i += 1
    return blocks


@rule("code/reserved-name", "code/reserved-name.title", "D", severity=Severity.WARNING)
def reserved_name(source: SourceFile) -> Iterable[Diagnostic]:
    if source.kind != "xbsl":
        return []
    toks = _name_tokens(code_tokens(source))
    diags: list[Diagnostic] = []
    for start, end in _structure_blocks(toks):
        for decl in declarations(toks[start:end]):
            for name in decl.names:
                if name.value in _RESERVED_NAMES:
                    diags.append(Diagnostic(
                        source.rel, name.line, name.col, "code/reserved-name",
                        Severity.WARNING,
                        i18n.t("code/reserved-name.field", name=name.value),
                    ))
    for sig in signatures(toks):
        for p in sig.params:
            if p.name.value in _RESERVED_NAMES:
                diags.append(Diagnostic(
                    source.rel, p.name.line, p.name.col, "code/reserved-name",
                    Severity.WARNING,
                    i18n.t("code/reserved-name.param", name=p.name.value),
                ))
    return diags


# Built-in properties of platform base component types, verified against the platform docs
# (the stdlib reference of Element 9.2): the type's own properties plus the ones inherited
# from its documented base types (Карточка, Компонент). The primary source is the versioned
# catalog (stdlib.json component_props); this hand-vetted table is the safety net for data
# generated before that key existed, unioned with the catalog per base type. The confirmed
# apply failure is `Заголовок` on an inheritor of СтандартнаяКарточка; the other names of
# the same documented set are rejected by the same name-conflict mechanism.
_BUILTIN_COMPONENT_PROPS: dict[str, frozenset[str]] = {
    "СтандартнаяКарточка": frozenset({
        # own (Стд::Интерфейс::ОбщиеКомпоненты::СтандартнаяКарточка)
        "ВидОтображения", "ВыравниваниеСодержимогоПоВертикали",
        "ВыравниваниеСодержимогоПоГоризонтали", "Заголовок", "Изображение", "Картинка",
        "Команды", "РасположениеИзображенияВБаннере", "РастягиватьИзображениеВБаннере",
        "Содержимое", "Фон", "ЦветЗаголовка", "ЦветСодержимого", "ШрифтЗаголовка",
        "ШрифтСодержимого",
        # inherited from Карточка
        "Групповая", "ОбрабатыватьНажатие", "ОценкаИнформации", "ПриНажатии",
        # inherited from Компонент
        "ВесПриРастягивании", "Видимость", "ВыравниваниеВГруппеПоВертикали",
        "ВыравниваниеВГруппеПоГоризонтали", "Высота", "Доступность", "ЕстьНаведение",
        "МаксимальнаяВысота", "МаксимальнаяШирина", "МинимальнаяВысота", "МинимальнаяШирина",
        "ПриНаведении", "ПриПеретаскивании", "ПриПотереНаведения", "РастягиватьПоВертикали",
        "РастягиватьПоГоризонтали", "ТолькоЧтение", "Ширина", "ШиринаВКолонках",
    }),
}

_BASE_ROOT_RE = re.compile(r"\s*([A-Za-zА-Яа-яЁё_][A-Za-zА-Яа-яЁё_0-9]*)")


@lru_cache(maxsize=None)
def _key_alternation(key: str) -> str:
    """Both spellings of a yaml key as a regex alternation, the metamodel's name first."""
    return "|".join(re.escape(form) for form in _key_spellings(key))


@lru_cache(maxsize=1)
def _props_block_re() -> re.Pattern:
    """The top-level `Свойства:` block: from the key line (a trailing comment is allowed) to
    the next top-level key (or EOF). `[^\\n]` instead of `.` in the comment: DOTALL is on."""
    return re.compile(
        r"(?ms)^(?:" + _key_alternation("Свойства")
        + r"):[ \t]*(?:#[^\n]*)?\r?$(.*?)(?=^\S|\Z)"
    )


dataset.register_reset(_key_alternation.cache_clear)
dataset.register_reset(_props_block_re.cache_clear)


def _base_root(type_expr: str) -> str | None:
    """The root name of `Наследует.Тип` before the generic arguments; None for an FQN."""
    m = _BASE_ROOT_RE.match(type_expr)
    if not m:
        return None
    rest = type_expr[m.end():].lstrip()
    if rest.startswith("."):  # an FQN base is not a vetted bare type
        return None
    return m.group(1)


@lru_cache(maxsize=1)
def _catalog_component_props() -> dict[str, frozenset[str]]:
    """Built-in component properties from the versioned catalog ({} when absent)."""
    try:
        raw = dataset.load_json("stdlib.json").get("component_props") or {}
    except (dataset.DatasetError, KeyError, ValueError):
        return {}
    return {k: frozenset(v) for k, v in raw.items() if isinstance(v, list)}


def _builtin_props(base: str) -> frozenset[str]:
    """Built-in properties of the base type: the metamodel first, then the catalog
    unioned with the vetted safety-net table."""
    if metamodel.has_class(base):
        return metamodel.class_property_names(base)
    return (_catalog_component_props().get(base, frozenset())
            | _BUILTIN_COMPONENT_PROPS.get(base, frozenset()))


def _prop_positions(source: SourceFile, prop: str) -> list[tuple[int, int]]:
    """(line, col) of `Имя: <prop>` lines inside the top-level `Свойства:` block."""
    pat = re.compile(  # \r?: the file may be CRLF
        r"(?m)^[ \t]*(?:- +)?(?:" + _key_alternation("Имя")
        + r"):[ \t]*(['\"]?)(" + re.escape(prop) + r")\1[ \t]*(?:#.*)?\r?$"
    )
    lm = linemap(source)
    out: list[tuple[int, int]] = []
    for bm in _props_block_re().finditer(source.text):
        for m in pat.finditer(bm.group(1)):
            out.append(lm.linecol(bm.start(1) + m.start(2)))
    return out


@rule(
    "yaml/builtin-property-name", "yaml/builtin-property-name.title", "D",
    severity=Severity.WARNING,
)
def builtin_property_name(source: SourceFile) -> Iterable[Diagnostic]:
    if source.kind != "yaml" or not _HAVE_YAML:
        return []
    data, err = _parsed(source)
    if err is not None or not isinstance(data, dict):
        return []
    kind = object_kind(data)
    if kind != "КомпонентИнтерфейса":
        return []
    inherits = value_of(data, "Наследует", kind)
    base_expr = value_of(inherits, "Тип") if isinstance(inherits, dict) else None
    if not isinstance(base_expr, str):
        return []
    base = _base_root(base_expr)
    if base is None:
        return []
    # The built-in table is keyed the platform's own way; a component type and a property
    # written in English answer to the same entry through the ui schema.
    builtin = _builtin_props(uischema.canonical_component(base))
    if not builtin:
        return []  # the base type is not vetted – skip, do not guess
    props = value_of(data, "Свойства", kind)
    if not isinstance(props, list):
        return []

    declared = [
        value_of(item, "Имя") for item in props
        if isinstance(item, dict) and isinstance(value_of(item, "Имя"), str)
    ]
    diags: list[Diagnostic] = []
    for prop in dict.fromkeys(declared):  # unique, in document order
        if uischema.canonical_property(prop) not in builtin:
            continue
        positions = _prop_positions(source, prop) or [(1, 1)]
        diags.extend(
            Diagnostic(
                source.rel, line, col, "yaml/builtin-property-name", Severity.WARNING,
                i18n.t("yaml/builtin-property-name.clash", prop=prop, base=base),
            )
            for line, col in positions
        )
    return diags
