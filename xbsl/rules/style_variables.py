"""Variable and constant names (the 1C development standard, mandatory for new code).

The standard "Имена переменных и констант" (the 2026-07 edition of the platform
development standards) goes beyond the code-style conventions of style_naming:
names must be concrete, unabbreviated and free of type words, boolean names come
from the affirmative, constant names must not spell their value, and a variable
must not shadow another project element's name. The rules here are the enforceable
subset; every rule narrows itself to what tokens can prove. The one exception is
style/shadow-own-property: it repeats a check of the platform compiler, so it reads the
parsed module and the type catalog the way the compiler reads its meta objects.

Deliberately NOT checked (tokens cannot tell a violation from a forced form):

- "redundant words understood from the context" (1.1) and the general ban on
  abbreviations (1.4) - both need a dictionary of the domain, not of the language;
- digits that replace a meaningful qualifier (1.5): Этап1/Шаг2 (an ordered sequence)
  is legal while Данные1/Данные2 is not, and the difference is semantic - only the
  abstract-stem case (Данные1) is caught, via style/abstract-name;
- shadowing of STDLIB type names (1.2): parameter names of platform handler
  signatures (Событие, Команда) and idiomatic locals (Список, Запрос) coincide with
  type names en masse - a corpus run gave over 900 hits, most of them forced, so
  the shadow rule covers project element names only, where a hit is a real conflict;
- the "abstract constant name" half of 2.2 beyond spelled-out numerals: the correct
  СТАТУС_АДРЕС_ПРОВЕРЕН and the wrong ЭТАП_ПРИЕМА_АНКЕТА differ only in the ROLE the
  constant plays, which no token-level check can see.

Structure bodies are skipped throughout: field names are a serialization contract
(JSON keys), not a naming choice - the same narrowing style/camel-case makes.
"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Iterable, Iterator
from functools import lru_cache

from xbsl import dataset, i18n, metamodel, terms, uischema
from xbsl import parser as P
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, rule
from xbsl.lexer import Token, linemap
from xbsl.rules._syntax import code_tokens, declarations, signatures, type_expr
from xbsl.rules.style_naming import _structure_ranges
from xbsl.rules.environment import _pair_stem
from xbsl.rules.yaml_schema import _HAVE_YAML, _parsed, object_kind, value_of

MESSAGES = {
    "style/abstract-name.title": {
        "ru": "Абстрактное имя переменной",
        "en": "Abstract variable name",
    },
    "style/abstract-name.bare": {
        "ru": "Абстрактное имя '{name}' не отражает суть переменной – дайте осмысленное "
              "имя (ДанныеКлиента, Заказ, Сотрудник). Универсальные имена уместны только "
              "в механизмах, работающих с произвольными типами данных.",
        "en": "The abstract name '{name}' says nothing about the variable – give it a "
              "meaningful name. Universal names belong only to mechanisms that work "
              "with arbitrary data.",
    },
    "style/abstract-name.numbered": {
        "ru": "Имя '{name}' – число вместо осмысленного уточнения: вместо Данные1 и "
              "Данные2 нужны ДанныеПользователя и ДанныеНоменклатуры.",
        "en": "The name '{name}' uses a number where a meaningful qualifier belongs: "
              "UserData and GoodsData, not Data1 and Data2.",
    },
    "style/single-letter-name.title": {
        "ru": "Однобуквенное имя",
        "en": "Single-letter name",
    },
    "style/single-letter-name.found": {
        "ru": "Однобуквенное имя '{name}' – сокращения ухудшают чтение: 'для Индекс = "
              "0', а не 'для И = 0'. Односимвольные имена допустимы только у параметров "
              "коротких лямбда-выражений.",
        "en": "The single-letter name '{name}' hurts readability: a loop wants Index, "
              "not a letter. One-letter names belong only to short lambda parameters.",
    },
    "style/negated-boolean-name.title": {
        "ru": "Булева переменная названа от отрицания",
        "en": "Boolean variable named from the negation",
    },
    "style/negated-boolean-name.not": {
        "ru": "Имя булевой переменной '{name}' образовано от отрицания – называйте от "
              "истинного значения признака: '{suggestion}'.",
        "en": "The boolean name '{name}' is built from the negation – name it from the "
              "affirmative: '{suggestion}'.",
    },
    "style/negated-boolean-name.none": {
        "ru": "Имя булевой переменной '{name}' образовано от отрицания – называйте от "
              "истинного значения признака (ЕстьОшибки, а не НетОшибок).",
        "en": "The boolean name '{name}' is built from the negation – name it from the "
              "affirmative (HasErrors, not NoErrors).",
    },
    "style/type-in-name.title": {
        "ru": "Тип в имени переменной",
        "en": "Type name inside a variable name",
    },
    "style/type-in-name.found": {
        "ru": "Имя '{name}' начинается с типа '{prefix}' – тип виден по объявлению и "
              "подсказке редактора, в имя переменной его не включают.",
        "en": "The name '{name}' starts with the type '{prefix}' – the type is visible "
              "from the declaration and the editor, keep it out of the name.",
    },
    "style/numeral-in-const-name.title": {
        "ru": "Числительное в имени константы",
        "en": "Numeral in a constant name",
    },
    "style/numeral-in-const-name.found": {
        "ru": "Числительное '{word}' в имени константы '{name}' описывает её значение – "
              "называйте константу абстрактно: ТАЙМАУТ, а не ТАЙМАУТ_ОДНА_МИНУТА.",
        "en": "The numeral '{word}' in the constant name '{name}' spells the value – "
              "name the constant abstractly: TIMEOUT, not TIMEOUT_ONE_MINUTE.",
    },
    "style/shadow-own-property.title": {
        "ru": "Локальная переменная скрывает свойство объекта",
        "en": "A local variable hides a property of the object",
    },
    "style/shadow-own-property.found": {
        "ru": "Локальная переменная '{name}' скрывает одноименное свойство {owner} – в теле "
              "метода имя разрешается в переменную, и ни чтение, ни присваивание до свойства "
              "не доходят. Назовите переменную иначе.",
        "en": "The local variable '{name}' hides the same-named property {owner} – inside "
              "the method the name resolves to the variable, so neither a read nor an "
              "assignment reaches the property. Pick another name.",
    },
    "style/shadow-own-property.owner-component": {
        "ru": "компонента {name}",
        "en": "of the component {name}",
    },
    "style/shadow-own-property.owner-inherited": {
        "ru": "типа {base}, от которого наследует компонент {name}",
        "en": "of the type {base} that the component {name} inherits",
    },
    "style/shadow-own-property.owner-object": {
        "ru": "объекта {name}",
        "en": "of the object {name}",
    },
    "style/shadow-own-property.owner-structure": {
        "ru": "структуры {name}",
        "en": "of the structure {name}",
    },
    "style/shadow-project-name.title": {
        "ru": "Имя закрывает элемент проекта",
        "en": "Name shadows a project element",
    },
    "style/shadow-project-name.found": {
        "ru": "Имя '{name}' совпадает с именем элемента проекта ({kind}) – объявление "
              "закрывает обращение к нему из этого кода; назовите переменную иначе "
              "(Участники и Авторы вместо Пользователи).",
        "en": "The name '{name}' coincides with a project element ({kind}) – the "
              "declaration shadows it for this code; pick another name (Members and "
              "Authors instead of Users).",
    },
}
i18n.register(MESSAGES)

# 1.1: names that add no understanding of the context. The stems double as the digit-tail
# case of 1.5 (Данные1, Значение2 - a number instead of a meaningful qualifier).
_ABSTRACT_STEMS = (
    "Данные", "Элемент", "Объект", "Строка", "Значение", "Документ",
    "Data", "Item", "Object", "String", "Value", "Document",
)
_ABSTRACT_RE = re.compile(r"^(?:%s)(\d*)$" % "|".join(_ABSTRACT_STEMS))

# 1.3: container types have no business inside a variable name (МассивСтруктурИмен).
# Only the unambiguous containers are matched; domain words like Строка or Список are
# too often legitimate name heads (СтрокаПоиска is a search box, not a String).
_TYPE_PREFIX_RE = re.compile(r"^(Массив|Структура|Соответствие)(?=[А-ЯЁ])")

# 1.6: the negation prefixes. A following capital keeps Неделя/Нетто out.
_NEGATED_RE = re.compile(r"^(?:Не|Нет)[А-ЯЁ]|^(?:No|Not)[A-Z]")

# 2.2: numerals spelled inside a constant name describe its value.
_NUMERAL_WORDS = frozenset((
    "ОДИН", "ОДНА", "ОДНО", "ДВА", "ДВЕ", "ТРИ", "ЧЕТЫРЕ", "ПЯТЬ", "ШЕСТЬ", "СЕМЬ",
    "ВОСЕМЬ", "ДЕВЯТЬ", "ДЕСЯТЬ", "ДВАДЦАТЬ", "ТРИДЦАТЬ", "СОРОК", "ПЯТЬДЕСЯТ",
    "ШЕСТЬДЕСЯТ", "СЕМЬДЕСЯТ", "ВОСЕМЬДЕСЯТ", "ДЕВЯНОСТО", "СТО", "ДВЕСТИ", "ТРИСТА",
    "ПЯТЬСОТ", "ТЫСЯЧА", "ТЫСЯЧИ", "МИЛЛИОН",
    "ONE", "TWO", "THREE", "FOUR", "FIVE", "SIX", "SEVEN", "EIGHT", "NINE", "TEN",
    "TWENTY", "THIRTY", "FORTY", "FIFTY", "HUNDRED", "THOUSAND", "MILLION",
))

_BOOLEAN_TYPE_NAMES = ("Булево", "Boolean")


def _variable_names(source: SourceFile) -> list[tuple[str, Token]]:
    """(category, token) of the names the module declares as variables.

    Categories: "var" (знч/пер/поймать/обз outside structure bodies), "param" (method
    parameters) and "for" (loop variables). Constants are excluded - they have rules of
    their own; structure fields are a serialization contract; lambda parameters never
    appear here at all (a lambda is a `метод` with no name, so `signatures` skips it,
    and a bare `Имя ->` parameter is an expression, not a declaration) - which is
    exactly the standard's exception for short lambdas.
    """
    toks = code_tokens(source)
    structures = _structure_ranges(toks)
    out: list[tuple[str, Token]] = []
    for sig in signatures(toks):
        out.extend(("param", p.name) for p in sig.params if p.name.kind == "IDENT")
    for decl in declarations(toks):
        if decl.keyword.canonical == "CONST":
            continue
        if any(start <= decl.keyword.start < end for start, end in structures):
            continue
        out.extend(("var", name) for name in decl.names)
    for i, t in enumerate(toks[:-2]):
        if t.kind != "KEYWORD" or t.canonical != "FOR":
            continue
        name, after = toks[i + 1], toks[i + 2]
        if name.kind != "IDENT":
            continue
        if (after.kind == "KEYWORD" and after.canonical == "IN") or (
            after.kind == "OP" and after.value == "="
        ):
            out.append(("for", name))
    return out


@rule(
    "style/abstract-name", "style/abstract-name.title", "C",
    severity=Severity.WARNING,
)
def abstract_name(source: SourceFile) -> Iterable[Diagnostic]:
    """1.1/1.5: `ДанныеКлиента`, not `Данные`; and never `Данные1`, `Данные2`.

    Exact stems only: the standard itself allows universal names in mechanisms that
    work with arbitrary data, and tokens cannot see the mechanism - so a name that
    merely CONTAINS an abstract stem (ДанныеКлиента) is fine and skipped.
    """
    if source.kind != "xbsl":
        return
    for _cat, tok in _variable_names(source):
        m = _ABSTRACT_RE.match(tok.value)
        if m is None:
            continue
        key = "style/abstract-name.numbered" if m.group(1) else "style/abstract-name.bare"
        yield Diagnostic(
            source.rel, tok.line, tok.col, "style/abstract-name", Severity.WARNING,
            i18n.t(key, name=tok.value),
        )


@rule(
    "style/single-letter-name", "style/single-letter-name.title", "C",
    severity=Severity.WARNING,
)
def single_letter_name(source: SourceFile) -> Iterable[Diagnostic]:
    """1.4: `для Индекс = 0`, not `для И = 0` - a letter is not a name.

    Lambda parameters are the standard's own exception (short lambdas use one-letter
    UPPERCASE parameters) and never reach this rule: `_variable_names` collects only
    real declarations, and a lambda declares nothing.
    """
    if source.kind != "xbsl":
        return
    for _cat, tok in _variable_names(source):
        if len(tok.value) == 1 and tok.value.isalpha():
            yield Diagnostic(
                source.rel, tok.line, tok.col, "style/single-letter-name",
                Severity.WARNING,
                i18n.t("style/single-letter-name.found", name=tok.value),
            )


def _boolean_annotation(toks: list[Token], type_start: int | None) -> bool:
    """Whether the annotation at type_start is Булево (nullable and `|?` included)."""
    if type_start is None:
        return False
    te = type_expr(toks, type_start)
    if te is None or not te.alternatives:
        return False
    seen = False
    for alt in te.alternatives:
        if any(t.kind == "OP" and t.value == "." for t in alt):
            return False  # a dotted type is never the boolean
        words = [t.value for t in alt if t.kind == "IDENT"]
        if not words:
            continue  # the bare `|?` alternative
        if len(words) != 1 or words[0] not in _BOOLEAN_TYPE_NAMES:
            return False
        seen = True
    return seen


@rule(
    "style/negated-boolean-name", "style/negated-boolean-name.title", "C",
    severity=Severity.WARNING,
)
def negated_boolean_name(source: SourceFile) -> Iterable[Diagnostic]:
    """1.6: `ЕстьОшибки`/`Подключен`, not `НетОшибок`/`НеПодключен`.

    Judged only where the boolean type is certain: an explicit Булево annotation
    (of a declaration or a parameter) or an initializer that starts with a boolean
    literal. A name alone is not enough - НеПрочитанные may be a perfectly good
    array of messages.
    """
    if source.kind != "xbsl":
        return
    toks = code_tokens(source)
    structures = _structure_ranges(toks)

    def report(tok: Token) -> Iterable[Diagnostic]:
        name = tok.value
        if not _NEGATED_RE.match(name):
            return
        if name.startswith(("Не", "No")) and not name.startswith(("Нет", "Not")):
            suggestion = name[2:]
            key, kwargs = "style/negated-boolean-name.not", {
                "name": name, "suggestion": suggestion,
            }
        else:
            key, kwargs = "style/negated-boolean-name.none", {"name": name}
        yield Diagnostic(
            source.rel, tok.line, tok.col, "style/negated-boolean-name",
            Severity.WARNING, i18n.t(key, **kwargs),
        )

    for decl in declarations(toks):
        if decl.keyword.canonical == "CONST":
            continue
        if any(start <= decl.keyword.start < end for start, end in structures):
            continue
        boolean = _boolean_annotation(toks, decl.type_start)
        if not boolean and decl.type_start is None and decl.value_start is not None \
                and decl.value_start < len(toks):
            value = toks[decl.value_start]
            after = toks[decl.value_start + 1] if decl.value_start + 1 < len(toks) else None
            boolean = (
                value.kind == "KEYWORD" and value.canonical in ("TRUE", "FALSE")
                and not (after is not None and after.kind == "OP" and after.value == ".")
            )
        if not boolean:
            continue
        for tok in decl.names:
            yield from report(tok)

    for sig in signatures(toks):
        for p in sig.params:
            if p.name.kind == "IDENT" and _boolean_annotation(toks, p.type_start):
                yield from report(p.name)


@rule(
    "style/type-in-name", "style/type-in-name.title", "C",
    severity=Severity.WARNING,
)
def type_in_name(source: SourceFile) -> Iterable[Diagnostic]:
    """1.3: `Имена`, not `МассивСтруктурИмен` - the type is not part of the name.

    Only the unambiguous container types are matched (Массив, Структура,
    Соответствие): domain heads like Строка or Список name real things too often
    to judge by tokens.
    """
    if source.kind != "xbsl":
        return
    for _cat, tok in _variable_names(source):
        m = _TYPE_PREFIX_RE.match(tok.value)
        if m is None:
            continue
        yield Diagnostic(
            source.rel, tok.line, tok.col, "style/type-in-name", Severity.WARNING,
            i18n.t("style/type-in-name.found", name=tok.value, prefix=m.group(1)),
        )


@rule(
    "style/numeral-in-const-name", "style/numeral-in-const-name.title", "C",
    severity=Severity.WARNING,
)
def numeral_in_const_name(source: SourceFile) -> Iterable[Diagnostic]:
    """2.2: `конст ТАЙМАУТ = 1м`, not `конст ТАЙМАУТ_ОДНА_МИНУТА = 1м`.

    Only spelled-out numerals are judged: they always describe the value, never the
    role. The wider half of 2.2 (a value's NAME inside the constant name) cannot be
    told from a legitimate enumeration-member constant and is left to review.
    """
    if source.kind != "xbsl":
        return
    for decl in declarations(code_tokens(source)):
        if decl.keyword.canonical != "CONST":
            continue
        for tok in decl.names:
            words = tok.value.upper().split("_")
            hit = next((w for w in words if w in _NUMERAL_WORDS), None)
            if hit is None:
                continue
            yield Diagnostic(
                source.rel, tok.line, tok.col, "style/numeral-in-const-name",
                Severity.WARNING,
                i18n.t("style/numeral-in-const-name.found", name=tok.value, word=hit),
            )


# --- 1.2: a name must not shadow a project element (needs the whole project) ------------

def _shadow_mapper(source: SourceFile) -> dict | None:
    """The map phase: project object names from yamls, declared names from modules."""
    if source.kind == "yaml":
        if not _HAVE_YAML:
            return None
        data, err = _parsed(source)
        if err is not None or not isinstance(data, dict):
            return None
        kind = object_kind(data)
        if not kind:
            return None
        name = value_of(data, "Имя", kind)
        if not isinstance(name, str) or not name:
            return None
        return {"k": "obj", "name": name, "kind": kind}
    if source.kind != "xbsl":
        return None
    toks = code_tokens(source)
    names = [
        (tok.value, tok.line, tok.col) for _cat, tok in _variable_names(source)
    ]
    names.extend(
        (sig.name.value, sig.name.line, sig.name.col) for sig in signatures(toks)
    )
    if not names:
        return None
    return {"k": "code", "names": names}


@rule(
    "style/shadow-project-name", "style/shadow-project-name.title", "D",
    scope="project", severity=Severity.WARNING, mapper=_shadow_mapper,
)
def shadow_project_name(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    """1.2: a variable (or a method) named like a project element hides that element.

    The conflict is real, not stylistic: after `знч Склады = ...` the module
    `Склады` cannot be called from the same scope - the bare name resolves to the
    variable. Platform handler parameter names (Событие, Команда) never collide with
    project element names, so every hit here is actionable.
    """
    objects: dict[str, str] = {}
    for fact in facts.values():
        if fact["k"] == "obj":
            objects.setdefault(fact["name"], fact["kind"])
    if not objects:
        return
    for rel, fact in facts.items():
        if fact["k"] != "code":
            continue
        for name, line, col in fact["names"]:
            kind = objects.get(name)
            if kind is None:
                continue
            yield Diagnostic(
                rel, line, col, "style/shadow-project-name", Severity.WARNING,
                i18n.t("style/shadow-project-name.found", name=name, kind=kind),
            )


# --- style/shadow-own-property ------------------------------------------------------------
#
# The compiler of the platform warns in the IDE about a local variable that hides a property
# of the object the method works on. The check is a question asked of every `знч`/`пер`/`исп`
# statement: does the meta object of the type that owns the method carry a property of that
# name? The name is compared letter for letter with either spelling of the property; a static
# method has no instance to hide a property of and is never asked.

#: The modules of an element that work on one of its facets: `Х.Объект.xbsl` holds the record
#: of `Х.yaml` and `Х.НаборЗаписей.xbsl` its record set (`X.Object.xbsl` and `X.RecordSet.xbsl`
#: in an English tree). The element's own module pairs with the yaml by the stem alone.
_FACET_MODULES = {
    ".Объект": "Объект", ".Object": "Объект",
    ".НаборЗаписей": "НаборЗаписей", ".RecordSet": "НаборЗаписей",
}
_INTERFACE_KIND = "КомпонентИнтерфейса"
_STRUCTURE_KIND = "Структура"
#: The element kinds whose object module holds the record: the attributes, the tabular sections
#: and the properties of the object facet (the reference, the version stamp) are the owner's.
_RECORD_KINDS = frozenset(("Справочник", "Документ", "Обработка"))
_RECORD_SECTIONS = ("Реквизиты", "ТабличныеЧасти")
#: The registers whose record set module works on the record set facet (its filter).
_REGISTER_KINDS = frozenset(("РегистрСведений", "РегистрНакопления"))
#: A scheduled job: its module works on the job, which carries the properties of the platform
#: job type and the parameters, under the name of the yaml section even when it is empty.
_JOB_KIND = "ЗапланированноеЗадание"
_JOB_PARAMETERS_SECTION = "Параметры"
#: The deletion mode of an element. By default the platform deletes by a mark, and the mark is
#: an attribute of the object named like that mode; an element deleted at once has none.
_DELETION_MODE = "РежимУдаления"
#: What the compiler adds to the meta object of every project interface component on top of
#: the declared and the inherited properties (the component constants of the distribution).
_COMPONENT_EXTRAS = (
    "Компоненты", "СобственнаяМодифицированность", "РассчитаннаяМодифицированность",
)
#: The first word of a declaration statement and the blanks after it: the name follows.
_DECLARATION_HEAD_RE = re.compile(r"\S+\s+")


@lru_cache(maxsize=1)
def _server_annotations() -> frozenset[str]:
    """Both spellings of the annotation that compiles a method on the server."""
    return frozenset(terms.key_forms("НаСервере"))


@lru_cache(maxsize=1)
def _client_annotations() -> frozenset[str]:
    """Both spellings of the annotation that compiles a method on the client."""
    return frozenset(terms.key_forms("НаКлиенте"))


@lru_cache(maxsize=1)
def _component_extras() -> frozenset[str]:
    """The properties every project component carries, in both spellings."""
    names = set(_COMPONENT_EXTRAS)
    names.update(english for name in _COMPONENT_EXTRAS if (english := terms.common_english(name)))
    return frozenset(names)


@lru_cache(maxsize=None)
def _inherited_properties(base: str) -> frozenset[str]:
    """The properties of a platform component type, each in both spellings; empty when unknown.

    The type catalog keeps the full set of a type with its bases expanded, so `Group` answers
    for the properties of `Component` too. An event counts as well: a handler is bound by
    assigning it (`Button.OnClick = &Handler`), and the compiler keeps events among the
    properties - a local `OnHover` in a group hides the event. The English spelling is taken
    from the owner's own classes first and from the component schema after that: the compiler
    matches either spelling, and a translated tree names the same properties in English.
    """
    try:
        catalog = dataset.load_json("stdlib.json")
    except dataset.DatasetError:
        return frozenset()
    record = (catalog.get("type_members") or {}).get(base) or {}
    names: set[str] = set()
    for member in (*(record.get("properties") or ()), *(record.get("events") or ())):
        names.add(member)
        english = terms.member_english_of(base, member) or uischema.english_property(member)
        if english:
            names.add(english)
    return frozenset(names)


@lru_cache(maxsize=None)
def _facet_properties(facet: str) -> frozenset[str]:
    """The properties of an element facet (`Справочник.Объект`) in both spellings.

    The type catalog lists them per facet; the English spelling is the one the facet's own class
    of the distribution declares - `Catalog.Object` is the `CatalogObject` class there, where the
    reference is `Reference`, while the flat dictionary calls the same word `Link`.
    """
    try:
        catalog = dataset.load_json("stdlib.json")
    except dataset.DatasetError:
        return frozenset()
    record = (catalog.get("facet_members") or {}).get(facet) or {}
    owner = (terms.english(facet, "facets") or "").replace(".", "")
    names: set[str] = set()
    for prop in record.get("properties") or ():
        names.add(prop)
        english = terms.member_english_of(owner, prop) if owner else None
        if english:
            names.add(english)
    return frozenset(names)


@lru_cache(maxsize=1)
def _job_properties() -> frozenset[str]:
    """What a scheduled job module can hide: the job type's properties and the parameters."""
    names = set(_inherited_properties(_JOB_KIND))
    section = metamodel.properties(_JOB_KIND).get(_JOB_PARAMETERS_SECTION)
    if section is not None:
        names.add(_JOB_PARAMETERS_SECTION)
        if section.get("en"):
            names.add(section["en"])
    return frozenset(names)


def _deletion_mark(kind: str, data: dict) -> list[str]:
    """Both spellings of the deletion mark when the element keeps one, else nothing.

    The metamodel gives the mode its default; the mark is present when the element leaves the
    default or writes it out, in either spelling of the value.
    """
    record = metamodel.properties(kind).get(_DELETION_MODE)
    mark = record.get("default") if record else None
    if not isinstance(mark, str) or not mark:
        return []
    spellings = [mark]
    english = terms.common_english(mark)
    if english:
        spellings.append(english)
    written = value_of(data, _DELETION_MODE, kind)
    return spellings if written is None or written in spellings else []


for _cache in (
    _server_annotations, _client_annotations, _component_extras, _inherited_properties,
    _facet_properties, _job_properties,
):
    dataset.register_reset(_cache.cache_clear)


def _named_items(value) -> Iterator[tuple[str, dict]]:
    """(name, item) of the items of a yaml list section, skipping what carries no name."""
    if not isinstance(value, list):
        return
    for item in value:
        if isinstance(item, dict):
            name = value_of(item, "Имя")
            if isinstance(name, str) and name:
                yield name, item


def _is_true(value) -> bool:
    """A yaml flag written either way: a Russian `True` stays a string for the loader."""
    return value is True or value in ("Истина", "True", "true")


def _owner_fact(source: SourceFile) -> dict | None:
    """The map phase of a yaml: the properties its modules can hide, by the kind of the owner."""
    data, err = _parsed(source)
    if err is not None or not isinstance(data, dict):
        return None
    kind = object_kind(data)
    if not kind:
        return None
    name = value_of(data, "Имя", kind)
    if not isinstance(name, str) or not name:
        return None
    stem = _pair_stem(source.rel)
    if kind == _INTERFACE_KIND:
        own: list[str] = []
        contextual: list[str] = []
        for prop, item in _named_items(value_of(data, "Свойства", kind)):
            own.append(prop)
            if _is_true(value_of(item, "Контекстное")):
                contextual.append(prop)
        # A declared event is a property of the component as well; it never reaches the
        # component context, where only the contextual properties live.
        own.extend(event for event, _item in _named_items(value_of(data, "События", kind)))
        base = ""
        inherits = value_of(data, "Наследует", kind)
        written = value_of(inherits, "Тип") if isinstance(inherits, dict) else None
        if isinstance(written, str) and written.strip():
            base = uischema.canonical_component(written.split("<", 1)[0].strip())
        return {"k": "component", "stem": stem, "name": name, "base": base,
                "own": own, "contextual": contextual}
    if kind == _STRUCTURE_KIND:
        fields = [field for field, _item in _named_items(value_of(data, "Поля", kind))]
        return {"k": "fields", "stem": stem, "name": name, "names": fields} if fields else None
    if kind in _RECORD_KINDS:
        names = [
            entry for section in _RECORD_SECTIONS
            for entry, _item in _named_items(value_of(data, section, kind))
        ]
        names.extend(_deletion_mark(kind, data))
        return {"k": "record", "stem": stem, "name": name, "kind": kind, "names": names}
    if kind in _REGISTER_KINDS:
        return {"k": "register", "stem": stem, "name": name, "kind": kind}
    if kind == _JOB_KIND:
        return {"k": "job", "stem": stem, "name": name}
    return None


def _local_declarations(body: list) -> Iterator[P.VarDecl]:
    """Every `знч`/`пер`/`исп` statement of a method body: nested blocks and lambda bodies too.

    A lambda is bound inside the method that holds it, so a declaration in its body is the
    method's own for the compiler. Loop variables, `поймать` and parameters are other nodes
    and never reach here - the compiler does not ask about them either.
    """
    stack: list[object] = [body]
    while stack:
        node = stack.pop()
        if isinstance(node, (list, tuple)):
            stack.extend(node)
        elif isinstance(node, P.Node):
            if isinstance(node, P.VarDecl):
                yield node
            # Fields, not vars(): the native build compiles the AST classes without __dict__.
            stack.extend(getattr(node, f.name) for f in dataclasses.fields(node))


def _name_position(source: SourceFile, decl: P.VarDecl) -> tuple[int, int]:
    """(line, col) of the declared name; the statement start when the name is not found."""
    head = _DECLARATION_HEAD_RE.match(source.text, decl.start)
    offset = decl.start
    if head is not None and source.text.startswith(decl.name, head.end()):
        offset = head.end()
    return linemap(source).linecol(offset)


def _method_side(method: P.Method) -> str:
    """"server" for a method compiled on the server alone, "client" otherwise.

    A method of an interface component is compiled on the client unless it is marked for
    the server; one marked for both is compiled twice and hides the property on the client.
    """
    names = {annotation.name for annotation in method.annotations}
    if names & _server_annotations() and not names & _client_annotations():
        return "server"
    return "client"


def _module_fact(source: SourceFile) -> dict | None:
    """The map phase of a module: its local declarations with the side of the method.

    The declarations of a local structure are settled right here: the owner of such a
    method is the structure, and its fields are in the same file.
    """
    module, errors = P.parse(source)
    if errors:
        return None  # a module that does not parse is not compiled either
    decls: list[list] = []
    local: list[list] = []
    for member in module.members:
        if isinstance(member, P.Method):
            if member.is_static:
                continue
            side = _method_side(member)
            for decl in _local_declarations(member.body):
                line, col = _name_position(source, decl)
                decls.append([decl.name, line, col, side])
        elif isinstance(member, P.Structure):
            fields = {field.name for field in member.members if isinstance(field, P.ObjectField)}
            for method in member.members:
                if not isinstance(method, P.Method) or method.is_static:
                    continue
                for decl in _local_declarations(method.body):
                    if decl.name in fields:
                        line, col = _name_position(source, decl)
                        local.append([decl.name, line, col, member.name])
    if not decls and not local:
        return None
    stem = _pair_stem(source.rel)
    facet = ""
    for suffix, facet_name in _FACET_MODULES.items():
        if stem.endswith(suffix):
            stem, facet = stem[: -len(suffix)], facet_name
            break
    return {"k": "code", "stem": stem, "facet": facet, "decls": decls, "local": local}


def _own_property_mapper(source: SourceFile) -> dict | None:
    """The map phase: a yaml names the properties of its owner, a module its declarations."""
    if source.kind == "yaml":
        return _owner_fact(source) if _HAVE_YAML else None
    if source.kind == "xbsl":
        return _module_fact(source)
    return None


def _shadow(rel: str, line: int, col: int, variable: str, owner_key: str, **owner) -> Diagnostic:
    """One finding; `owner_key` picks how the owner of the hidden property is described."""
    return Diagnostic(
        rel, line, col, "style/shadow-own-property", Severity.WARNING,
        i18n.t("style/shadow-own-property.found", name=variable,
               owner=i18n.t(f"style/shadow-own-property.{owner_key}", **owner)),
    )


@rule(
    "style/shadow-own-property", "style/shadow-own-property.title", "D",
    scope="project", severity=Severity.WARNING, mapper=_own_property_mapper,
)
def shadow_own_property(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    """A local variable named like a property of the object its method works on.

    The same question the compiler asks before the IDE warns, for the owners whose property
    sets the sources and the platform data describe:

    - a module of an interface component: the declared properties and events, the properties
      and events of the platform type it inherits (`Inherits: Type: Group` brings `Title`,
      `Width`, `Content`, `OnHover`...) and the three the compiler adds to every component
      (`Components` and the two modification flags). A method marked for the server alone
      works on the component context, where only the properties declared `Contextual` exist;
    - the object module of a catalog, a document or a processing: the attributes, the tabular
      sections, the properties of the object facet (the reference and the version stamp) and
      the deletion mark while the element deletes by mark;
    - the record set module of a register: the properties of the record set facet (the filter);
    - the module of a scheduled job: the properties of the job type and the parameters;
    - the module of a structure element: its fields; a local structure: the fields it declares.

    Not judged, each for a reason the compiler shares: static methods (no instance), loop
    variables, `поймать` and parameters (declarations of another kind - a parameter named after
    a property is the ordinary way to pass its value in), and the other modules of an element -
    the manager module of a catalog carries no record in scope. Silent where the data cannot
    tell the set: a base type the catalog does not know, and the contextual properties of a
    platform base type in a server method (the object of an object form is one - the extracted
    data carries no contextual flag for platform properties).
    """
    owners = {
        fact["stem"]: fact for fact in facts.values()
        if fact["k"] in ("component", "fields", "record", "register", "job")
    }
    for rel, fact in facts.items():
        if fact["k"] != "code":
            continue
        for name, line, col, structure in fact["local"]:
            yield _shadow(rel, line, col, name, "owner-structure", name=structure)
        owner = owners.get(fact["stem"])
        if owner is None:
            continue
        if owner["k"] in ("record", "register") or fact["facet"]:
            # A facet is in scope in its own module alone: the manager module of the element
            # works with no record, and a facet module of a kind outside the lists is not judged.
            if owner["k"] == "record" and fact["facet"] == "Объект":
                names = set(owner["names"]) | _facet_properties(f"{owner['kind']}.Объект")
            elif owner["k"] == "register" and fact["facet"] == "НаборЗаписей":
                names = set(_facet_properties(f"{owner['kind']}.НаборЗаписей"))
            else:
                continue
            for name, line, col, _side in fact["decls"]:
                if name in names:
                    yield _shadow(rel, line, col, name, "owner-object", name=owner["name"])
            continue
        if owner["k"] in ("fields", "job"):
            names, owner_key = (
                (set(owner["names"]), "owner-structure") if owner["k"] == "fields"
                else (_job_properties(), "owner-object")
            )
            for name, line, col, _side in fact["decls"]:
                if name in names:
                    yield _shadow(rel, line, col, name, owner_key, name=owner["name"])
            continue
        own = set(owner["own"]) | _component_extras()
        contextual = set(owner["contextual"])
        inherited = _inherited_properties(owner["base"]) if owner["base"] else frozenset()
        for name, line, col, side in fact["decls"]:
            if side == "server":
                if name in contextual:
                    yield _shadow(rel, line, col, name, "owner-component", name=owner["name"])
            elif name in own:
                yield _shadow(rel, line, col, name, "owner-component", name=owner["name"])
            elif name in inherited:
                yield _shadow(
                    rel, line, col, name, "owner-inherited", name=owner["name"],
                    base=terms.type_english(owner["base"]) if i18n.current_lang() == "en"
                    else owner["base"],
                )
