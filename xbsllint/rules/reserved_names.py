"""Tier D: names the server-side apply rejects, which the compiler does not check.

The code/reserved-name rule: the names `Тип` and `type` are rejected by the server apply
("Invalid field name") when used as a structure field name (`пер/знч/обз` inside a
`структура ... ;` block) or as a method/constructor parameter name. The check is
token-based: structure blocks are delimited from the lowercase `структура` keyword to the
terminating `;` at bracket depth 0 (or, as a safety stop, to the next lowercase
метод/конструктор/структура/перечисление/исключение keyword – a structure holds only field
declarations); parameters come from the shared signature parser. The lexer classifies `Тип`
as a keyword (the type literal), so for the name scan the TYPE keyword is downgraded to an
identifier locally. Exactly these two spellings are checked – other casings are not
confirmed to be rejected. Local variables and other name positions are left alone on
purpose: the real corpus legally declares a local variable named `Тип` inside a method,
so widening the rule would produce false positives.

The yaml/builtin-property-name rule: in a `ВидЭлемента: КомпонентИнтерфейса` yaml, declaring
an own property (`Свойства: - Имя: X`) whose name matches a built-in property of the BASE
component type (`Наследует.Тип`, the root before the generic arguments) is rejected by the
server apply ("Invalid property name") – the classic case is `Заголовок` on an inheritor of
СтандартнаяКарточка. The built-in property set of the base type is taken from the metamodel
class (transitively over inheritance, as in yaml/unknown-property) when the type is present
there; the current metamodel (configuration .xcore) does not describe UI component types, so
the module carries a built-in table verified against the platform docs (stdlib reference,
9.2): the type's own properties plus the ones inherited from Карточка and Компонент. A base
type found in neither source is skipped rather than guessed – in particular a base that is
itself a project component (unresolvable in file scope). The check is strictly per base
type: the real corpus legally declares a property `Заголовок` on an inheritor of
КонтейнерHtml, so no cross-type generalization is allowed. Positions are searched only
inside the top-level `Свойства:` block – the same name as an event or a nested component
name cannot false-match.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import replace

from xbsllint import i18n
from xbsllint.diagnostics import Diagnostic, Severity
from xbsllint.engine import SourceFile, rule
from xbsllint.lexer import linemap
from xbsllint.rules._syntax import code_tokens, declarations, signatures
from xbsllint.rules.yaml_properties import _allowed_for_class, _metamodel
from xbsllint.rules.yaml_schema import _HAVE_YAML, _parsed

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
_RESERVED_NAMES = frozenset({"Тип", "type"})

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
# from its documented base types (Карточка, Компонент). Only vetted types are listed; the
# metamodel takes precedence when it describes the type. The confirmed apply failure is
# `Заголовок` on an inheritor of СтандартнаяКарточка; the other names of the same documented
# set are rejected by the same name-conflict mechanism.
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

# The top-level `Свойства:` block: from the key line to the next top-level key (or EOF).
_PROPS_BLOCK_RE = re.compile(r"(?ms)^Свойства:[ \t]*\r?$(.*?)(?=^\S|\Z)")


def _base_root(type_expr: str) -> str | None:
    """The root name of `Наследует.Тип` before the generic arguments; None for an FQN."""
    m = _BASE_ROOT_RE.match(type_expr)
    if not m:
        return None
    rest = type_expr[m.end():].lstrip()
    if rest.startswith("."):  # an FQN base is not a vetted bare type
        return None
    return m.group(1)


def _builtin_props(base: str) -> frozenset[str]:
    """Built-in properties of the base type: the metamodel first, then the vetted table."""
    mm = _metamodel()
    if mm and base in mm.get("classes", {}):
        return _allowed_for_class(base)
    return _BUILTIN_COMPONENT_PROPS.get(base, frozenset())


def _prop_positions(source: SourceFile, prop: str) -> list[tuple[int, int]]:
    """(line, col) of `Имя: <prop>` lines inside the top-level `Свойства:` block."""
    pat = re.compile(  # \r?: the file may be CRLF
        r"(?m)^[ \t]*(?:- +)?Имя:[ \t]*(['\"]?)(" + re.escape(prop) + r")\1[ \t]*(?:#.*)?\r?$"
    )
    lm = linemap(source)
    out: list[tuple[int, int]] = []
    for bm in _PROPS_BLOCK_RE.finditer(source.text):
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
    if data.get("ВидЭлемента") != "КомпонентИнтерфейса":
        return []
    inherits = data.get("Наследует")
    base_expr = inherits.get("Тип") if isinstance(inherits, dict) else None
    if not isinstance(base_expr, str):
        return []
    base = _base_root(base_expr)
    if base is None:
        return []
    builtin = _builtin_props(base)
    if not builtin:
        return []  # the base type is not vetted – skip, do not guess
    props = data.get("Свойства")
    if not isinstance(props, list):
        return []

    declared = [
        item["Имя"] for item in props
        if isinstance(item, dict) and isinstance(item.get("Имя"), str)
    ]
    diags: list[Diagnostic] = []
    for prop in dict.fromkeys(declared):  # unique, in document order
        if prop not in builtin:
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
