"""`comment/unknown-name`: a name in a comment that exists nowhere in the project.

The rule knows a name only against the platform catalog - without it every platform name would
read as unknown - and it reads the identifiers of a module with the lexer, so the tests that run
the rule over a project are marked `needs_data`. The helpers that judge the shape of a line and
of a word need nothing and run in a public checkout.
"""

import pytest

from xbsl import engine, i18n
from xbsl.rules import comment_names

RULE = "comment/unknown-name"

_STORES = "ВидЭлемента: Справочник\nИмя: Склады\n"
_BATCHES = "ВидЭлемента: ОбщийМодуль\nИмя: Партии\n"
_CARD = (
    "ВидЭлемента: ОбщийКомпонент\nИмя: КарточкаСклада\n"
    "Содержимое:\n    Тип: Надпись\n    Имя: ИмяСклада\n"
)
_BATCHES_MODULE = "метод ПересчитатьПартии()\n;\n"


def _project(**files: str):
    """Run the rule over a project of in-memory files: name -> text."""
    sources = [engine.load_text(name, text) for name, text in files.items()]
    return engine.run_sources(sources, select={RULE})


def _module(comments: str, **more: str):
    """A project whose module `Склады.xbsl` starts with `comments`."""
    files = {
        "Склады.yaml": _STORES,
        "Склады.xbsl": comments + "метод Пересчитать()\n;\n",
        "Партии.yaml": _BATCHES,
        "Партии.xbsl": _BATCHES_MODULE,
        "КарточкаСклада.yaml": _CARD,
    }
    files.update(more)
    return _project(**files)


def _names(diags):
    assert all(d.rule_id == RULE for d in diags), [d.message for d in diags]
    return [d.message.split('"')[1] for d in diags]


# --- the rule as a whole ------------------------------------------------------------------------

def test_unknown_name_is_a_project_warning_off_by_default():
    info = next(r for r in engine.RULES if r.id == RULE)

    assert info.severity.value == "warning"
    assert info.enabled_by_default is False
    assert info.tier == "D" and info.scope == "project"
    assert info.mapper is not None
    assert "--enable" in info.off_reason_text


def test_unknown_name_speaks_english_without_cyrillic_outside_quotes():
    i18n.set_lang("en")
    try:
        texts = [
            i18n.t(key, name="w")
            for key in i18n.registered_keys() if key.startswith(RULE + ".")
        ]
    finally:
        i18n.set_lang("ru")
    assert texts
    for text in texts:
        bare = [part for index, part in enumerate(text.split('"')) if index % 2 == 0]
        assert not any("а" <= ch.lower() <= "я" for part in bare for ch in part), text


def test_unknown_name_needs_the_platform_catalog(monkeypatch):
    monkeypatch.setattr(comment_names, "_stdlib_names", frozenset)

    diags = _project(**{"Склады.yaml": "# Остатки считает ПересчитатьОстатки.\n" + _STORES})

    assert diags == []


# --- the shape of a word and of a line ----------------------------------------------------------

@pytest.mark.parametrize(("word", "expected"), (
    ("ЗаписатьОбъект", True),
    ("SaveRow", True),
    ("ОтветHTTP", True),
    ("HTTPСоединение", False),
    ("Склад", False),
    ("HTTP", False),
    ("имяПоля", False),
    ("Шаг2Задачи", False),
    ("Имя_Поля", False),
))
def test_unknown_name_candidate_shape(word, expected):
    assert comment_names._is_candidate(word) is expected


@pytest.mark.parametrize("line", (
    "пер ОстатокСклада = 0",
    "Итог = СуммаПартий()",
    "возврат НовыйОстаток",
    "возврат новый Число(Остаток)",
    "если ЕстьОстаток",
    "если Остаток.Количество != 0",
    "если Начало >= ДатаОт и Конец <= ДатаДо",
    "новый ОшибкаОстатка(Описание = Текст,",
    "Партии.Добавить(",
    "Партии.Добавить(новый СтрокаОстатка<Строка>(",
    "Партии.Пересчитать(Склад)",
    "для Партия из СписокПартий",
    "// знч Итог = СуммаПартий()",
    "//пер ОстатокСклада = 0",
    "var total = new Totals.Object()",
    '"ПересчитатьОстатки"',
))
def test_unknown_name_commented_out_code_is_recognized(line):
    assert comment_names._is_code(line)


@pytest.mark.parametrize("line", (
    "Остатки пересчитывает ПересчитатьОстатки.",
    "в отличие от прежнего ПересчитатьВсе(), который читал регистр целиком.",
    "Открывается из КарточкиСклада (кнопка ПоказатьПартии).",
    "Все данные приходят одним вызовом (Партии.ДанныеСклада);",
    "если склад не задан, берется основной",
    "Возврат значения из ЗаписатьОстаток()",
))
def test_unknown_name_prose_is_not_code(line):
    assert not comment_names._is_code(line)


@pytest.mark.parametrize(("inflected", "name"), (
    ("КарточкиСклада", "КарточкаСклада"),
    ("КарточкойСклада", "КарточкаСклада"),
    ("ГлавногоОкна", "ГлавноеОкно"),
    ("НастроекОтчета", "НастройкиОтчета"),
    ("СсылокСклада", "СсылкиСклада"),
))
def test_unknown_name_inflected_forms_match(inflected, name):
    index = comment_names._inflection_index({name})

    assert comment_names._inflected(inflected, index)


@pytest.mark.parametrize(("other", "name"), (
    ("ЗаказчикиСклада", "ЗаказыСклада"),
    ("КарточкаПартии", "КарточкаСклада"),
    ("КарточкаСкладаИтог", "КарточкаСклада"),
))
def test_unknown_name_other_words_do_not_match(other, name):
    index = comment_names._inflection_index({name})

    assert not comment_names._inflected(other, index)


# --- the rule over a project --------------------------------------------------------------------

@pytest.mark.needs_data
def test_unknown_name_in_a_module_comment_is_reported():
    comment = "// Остатки пересчитывает ПересчитатьОстатки.\n"

    (diag,) = _module(comment)

    assert diag.rule_id == RULE
    assert diag.path.replace("\\", "/").endswith("Склады.xbsl")
    assert (diag.line, diag.col) == (1, comment.index("ПересчитатьОстатки") + 1)
    assert '"ПересчитатьОстатки"' in diag.message


@pytest.mark.needs_data
def test_unknown_name_known_names_are_left_alone():
    comments = (
        "// Партии пересчитывает ПересчитатьПартии, ответ пишет ЗаписатьОбъект.\n"
        "// Подпись выводит ИмяСклада в КарточкаСклада.\n"
    )

    assert _module(comments) == []


@pytest.mark.needs_data
def test_unknown_name_inflected_name_is_known_and_a_quoted_one_is_exact():
    assert _module("// Открывается из КарточкиСклада.\n") == []
    assert _names(_module("// Открывается из `КарточкиСклада`.\n")) == ["КарточкиСклада"]


@pytest.mark.needs_data
def test_unknown_name_commented_out_code_is_left_alone():
    comments = (
        "// пер ОстатокСклада = 0\n"
        "// возврат НовыйОстаток\n"
        "// если ЕстьОстаток\n"
        "// // знч Итог = СуммаПартий()\n"
        "/*\n"
        "Партии.Добавить(\n"
        "*/\n"
    )

    assert _module(comments) == []


@pytest.mark.needs_data
def test_unknown_name_member_after_a_known_root_is_reported():
    assert _names(_module("// Пересчет: Партии.ПересчитатьВсе.\n")) == ["ПересчитатьВсе"]


@pytest.mark.needs_data
def test_unknown_name_renamed_module_with_a_living_method_is_reported():
    names = _names(_module("// Данные дает СтарыеПартии.ПересчитатьПартии.\n"))

    assert names == ["СтарыеПартии"]


@pytest.mark.needs_data
def test_unknown_name_chain_of_another_system_is_left_alone():
    localized = "ВидЭлемента: Локализация\nИмя: ТекстыСклада\nСтроки:\n    ТекстПустогоСклада: Пусто\n"

    assert _module("// Поля повторяют ДругаяСистема.СписокПартий.\n") == []
    assert _module(
        "// Текст как в ДругаяСистема.ТекстПустогоСклада.\n", **{"ТекстыСклада.yaml": localized},
    ) == []


@pytest.mark.needs_data
def test_unknown_name_of_another_product_without_a_chain_is_reported():
    names = _names(_module("// Поля повторяют документ ОстаткиДругойСистемы.\n"))

    assert names == ["ОстаткиДругойСистемы"]


@pytest.mark.needs_data
def test_unknown_name_in_a_yaml_comment_is_reported():
    card = "# Нажатие ПриНажатии обрабатывает ОткрытьКарточкуСклада.\n" + _CARD

    (diag,) = _module("", **{"КарточкаСклада.yaml": card})

    assert diag.path.replace("\\", "/").endswith("КарточкаСклада.yaml")
    assert (diag.line, diag.col) == (1, card.index("ОткрытьКарточкуСклада") + 1)


@pytest.mark.needs_data
def test_unknown_name_translation_dictionary_gives_no_names():
    dictionary = (
        "# ПересчитатьВсе остался от прежней версии\n"
        "version: 1\nlanguage: en\ntokens:\n    ПересчитатьОстатки: RecalculateBalances\n"
    )

    diags = _module(
        "// Остатки пересчитывает ПересчитатьОстатки.\n", **{"словарь.yaml": dictionary},
    )

    assert _names(diags) == ["ПересчитатьОстатки"]


@pytest.mark.needs_data
def test_unknown_name_is_reported_once_per_file():
    comments = "// ПересчитатьОстатки\n// и снова ПересчитатьОстатки\n"

    assert _names(_module(comments)) == ["ПересчитатьОстатки"]


@pytest.mark.needs_data
def test_unknown_name_word_of_the_other_script_is_left_alone():
    assert _module("// Ответ приходит в формате OpenApi, поле totalCount.\n") == []


@pytest.mark.needs_data
def test_unknown_name_fragments_are_left_alone():
    comments = "// Остатки считает ПересчитатьОс-\n// татки, а до него ...ОстаткиСкладов.\n"

    assert _module(comments) == []
