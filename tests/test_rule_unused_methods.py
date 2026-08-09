"""Checks of the code/unused-method rule (dead methods, tier D, scope=project).

The rule needs the lexer, and the lexer needs the Element language data; without the data
the whole module is skipped (conftest does not know this file, so we guard ourselves).
"""

import pytest

from xbsl import dataset, engine
from xbsl.cli import discover

pytestmark = pytest.mark.skipif(
    not dataset.available_versions(),
    reason="нет данных Элемента – сгенерируйте: python tools/extract.py --dist ...",
)

RULE = "code/unused-method"


def _lint_dir(tmp_path, **files):
    for name, content in files.items():
        (tmp_path / name.replace("__", ".")).write_text(content, encoding="utf-8")
    return engine.run(discover([str(tmp_path)]), select={RULE})


def _hits(diags):
    return [d for d in diags if d.rule_id == RULE]


# --- The signal: declared and never seen anywhere else ---------------------------------

def test_dead_method_flagged(tmp_path):
    d = _lint_dir(
        tmp_path,
        М__xbsl="метод Живой()\n;\n\nметод Мёртвый()\n;\n\nметод Главный()\n    Живой()\n;\n",
        Ф__yaml="Обработчик: Главный\n",
    )
    hits = _hits(d)
    assert len(hits) == 1 and "Мёртвый" in hits[0].message


def test_position_is_declaration_name(tmp_path):
    d = _lint_dir(tmp_path, М__xbsl="// шапка\nметод Мёртвый()\n;\n")
    hits = _hits(d)
    assert (hits[0].line, hits[0].col) == (2, 7)


def test_off_by_default(tmp_path):
    (tmp_path / "М.xbsl").write_text("метод Мёртвый()\n;\n", encoding="utf-8")
    d = engine.run(discover([str(tmp_path)]))
    assert not _hits(d)


# --- Guard: the name is mentioned somewhere else ----------------------------------------

def test_qualified_call_from_other_module_not_flagged(tmp_path):
    # a static manager method called with the Модуль.Метод qualification
    d = _lint_dir(
        tmp_path,
        Менеджер__xbsl="стат метод Посчитать(): Число\n    возврат 1\n;\n",
        Клиент__xbsl="@Обработчик\nметод ПослеСоздания()\n    Менеджер.Посчитать()\n;\n",
    )
    assert not _hits(d)


def test_mention_in_yaml_not_flagged(tmp_path):
    d = _lint_dir(
        tmp_path,
        Ф__xbsl="метод Клик(Источник: Надпись)\n;\n",
        Ф__yaml="Содержимое:\n    -\n        Тип: Надпись\n        ПриНажатии: Клик\n",
    )
    assert not _hits(d)


def test_mention_in_string_literal_not_flagged(tmp_path):
    # the HTML insert bridge calls the method by name inside a string literal
    d = _lint_dir(
        tmp_path,
        Ф__xbsl=(
            "метод ОбновитьСчётчик()\n;\n\n"
            "метод Разметка(): Строка\n"
            "    возврат \"<script>bridge.call('ОбновитьСчётчик')</script>\"\n"
            ";\n"
        ),
        Ф__yaml="Обработчик: Разметка\n",
    )
    assert not _hits(d)


def test_mention_in_comment_not_flagged(tmp_path):
    # a mention in a comment silences too: silence is better than a false positive
    d = _lint_dir(
        tmp_path,
        М__xbsl="// Колбэк: платформа вызывает ПоТаймеру\nметод ПоТаймеру()\n;\n",
    )
    assert not _hits(d)


# --- Guard: annotations -----------------------------------------------------------------

def test_platform_annotation_not_flagged(tmp_path):
    # the platform and the contracts call these themselves - no project mention is required
    d = _lint_dir(
        tmp_path,
        М__xbsl=(
            "@Обработчик\nметод ПриСобытии()\n;\n\n"
            "@Подписка\nстатический метод НаЗапись()\n;\n\n"
            "@Реализация\nметод Выполнить()\n;\n\n"
            "@Переопределение\nметод Заголовок()\n;\n\n"
            "@Устарело\nметод Старый()\n;\n"
        ),
    )
    assert not _hits(d)


def test_unknown_annotation_not_flagged(tmp_path):
    # a project may declare its own annotation; an unknown name silences the finding
    d = _lint_dir(tmp_path, М__xbsl="@МояАннотация\nметод Помеченный()\n;\n")
    assert not _hits(d)


def test_annotation_with_arguments_not_flagged(tmp_path):
    d = _lint_dir(
        tmp_path,
        М__xbsl='@ОбновлениеПроекта(Ид = "Конвертация", Номер = 1)\nметод Конвертация()\n;\n',
    )
    assert not _hits(d)


# --- The signal: visibility and environment annotations do NOT silence -------------------

def test_public_method_without_callers_flagged(tmp_path):
    # the public API of a common module is exactly where dead code piles up
    d = _lint_dir(
        tmp_path,
        М__xbsl="@НаСервере @ВПроекте\nметод Осиротевший()\n;\n",
    )
    hits = _hits(d)
    assert len(hits) == 1 and "Осиротевший" in hits[0].message


def test_public_method_with_caller_not_flagged(tmp_path):
    # the negative control of the test above: one caller elsewhere silences the rule
    d = _lint_dir(
        tmp_path,
        М__xbsl="@НаСервере @ВПроекте\nметод Осиротевший()\n;\n",
        П__xbsl="@НаСервере\nметод Главный()\n    М.Осиротевший()\n;\n",
        П__yaml="Обработчик: Главный\n",
    )
    assert not _hits(d)


def test_environment_annotation_still_judged(tmp_path):
    d = _lint_dir(tmp_path, М__xbsl="@ДоступноСКлиента\nметод Клиентский()\n;\n")
    hits = _hits(d)
    assert len(hits) == 1 and "Клиентский" in hits[0].message


def test_english_visibility_annotation_still_judged(tmp_path):
    # the project is bilingual: the English spelling of the annotation is the same guard
    d = _lint_dir(tmp_path, M__xbsl="@OnServer @InProject\nmethod Orphan()\n;\n")
    hits = _hits(d)
    assert len(hits) == 1 and "Orphan" in hits[0].message


def test_comment_between_annotation_and_method(tmp_path):
    # the annotation block is read through a comment line, so the guard still applies
    d = _lint_dir(
        tmp_path,
        М__xbsl="@Обработчик\n// платформа зовёт его сама\nметод ПриСобытии()\n;\n",
    )
    assert not _hits(d)


def test_annotation_of_next_method_not_inherited(tmp_path):
    # the annotation belongs to the next method, not the previous one
    d = _lint_dir(
        tmp_path,
        М__xbsl="метод Мёртвый()\n;\n\n@НаСервере\nметод Живой()\n;\n\nметод Главный()\n    Живой()\n;\n",
        Ф__yaml="Обработчик: Главный\n",
    )
    hits = _hits(d)
    assert len(hits) == 1 and "Мёртвый" in hits[0].message


def test_static_between_annotation_and_method(tmp_path):
    # the modifier does not hide the annotation: the platform one still silences the method
    d = _lint_dir(tmp_path, М__xbsl="@Обработчик\nстатический метод Утилита()\n;\n")
    assert not _hits(d)


def test_static_public_method_flagged(tmp_path):
    # the same walk, the other verdict: a visibility annotation leaves the method judged
    d = _lint_dir(tmp_path, М__xbsl="@ВПроекте\nстатический метод Утилита()\n;\n")
    hits = _hits(d)
    assert len(hits) == 1 and "Утилита" in hits[0].message


# --- Guard: platform events -------------------------------------------------------------

def test_platform_event_without_annotation_not_flagged(tmp_path):
    d = _lint_dir(
        tmp_path,
        М__xbsl="метод ПослеСоздания()\n;\n\nметод ПередЗаписью()\n;\n",
    )
    assert not _hits(d)


# --- Guard: special modules -------------------------------------------------------------

def test_object_module_skipped(tmp_path):
    d = _lint_dir(
        tmp_path,
        Полезное__Объект__xbsl="метод ПодготовитьКод()\n;\n",
    )
    assert not _hits(d)


def test_http_service_module_skipped(tmp_path):
    d = _lint_dir(
        tmp_path,
        Апи__yaml="ВидЭлемента: HttpСервис\nИмя: Апи\n",
        Апи__xbsl="метод ОбработатьЗапрос()\n;\n",
    )
    assert not _hits(d)


def test_http_service_with_trailing_comment_skipped(tmp_path):
    # a comment after the kind does not hide the HTTP service from the exemption
    d = _lint_dir(
        tmp_path,
        Апи__yaml="ВидЭлемента: HttpСервис # публичное апи\nИмя: Апи\n",
        Апи__xbsl="метод ОбработатьЗапрос()\n;\n",
    )
    assert not _hits(d)


# --- Miscellaneous ----------------------------------------------------------------------

def test_same_name_in_two_modules_not_flagged(tmp_path):
    # two same-named declarations silence each other (a mention exists - no verdict possible)
    d = _lint_dir(
        tmp_path,
        А__xbsl="метод Общий()\n;\n",
        Б__xbsl="метод Общий()\n;\n",
    )
    assert not _hits(d)


def test_structure_method_checked(tmp_path):
    d = _lint_dir(
        tmp_path,
        М__xbsl=(
            "структура Держатель\n"
            "    метод МёртвыйЧлен()\n    ;\n"
            ";\n"
        ),
    )
    hits = _hits(d)
    assert len(hits) == 1 and "МёртвыйЧлен" in hits[0].message
