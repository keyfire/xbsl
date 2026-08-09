"""Variable and constant names (the 1C development standard, mandatory for new code).

The standard "Имена переменных и констант" (the 2026-07 edition of the platform
development standards) goes beyond the code-style conventions of style_naming:
names must be concrete, unabbreviated and free of type words, boolean names come
from the affirmative, constant names must not spell their value, and a variable
must not shadow another project element's name. The rules here are the enforceable
subset; every rule narrows itself to what tokens can prove.

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

import re
from collections.abc import Iterable

from xbsl import i18n
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, rule
from xbsl.lexer import Token
from xbsl.rules._syntax import code_tokens, declarations, signatures, type_expr
from xbsl.rules.style_naming import _structure_ranges
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
