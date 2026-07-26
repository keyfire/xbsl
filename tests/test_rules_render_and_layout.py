"""Rules over what the platform accepts but does not do: the render, the closing, the layout.

The five checks share a shape - the compiler is happy and the defect shows up later (on the
screen, on the deploy, in the database), so working code is silent on them and every test
here carries its own negative control.

Everything that goes through the parser needs the Element data (the grammar lives in it), so
those tests are marked; the project-layout checks read the path and stay data-free.
"""

from __future__ import annotations

import pytest

from xbsl.cli import discover
from xbsl.engine import run


def _diags(tmp_path, name: str, text: str, rule_id: str):
    (tmp_path / name).write_text(text, encoding="utf-8")
    found = run(discover([str(tmp_path)]), select={rule_id})
    return [(d.line, d.col, d.message) for d in found]


# --- code/close-in-before-close -----------------------------------------------------

_HANDLER = """@Обработчик
метод ПередЗакрытием(Событие: ПараметрыЗакрытияФормы)
    если ФормаИзменена
        Событие.РежимЗакрытияФормы = РежимЗакрытияФормы.НеЗакрывать
        если Сохранить()
            {call}
        ;
    ;
;
"""


@pytest.mark.needs_data
def test_close_inside_before_close_is_reported(tmp_path):
    found = _diags(
        tmp_path, "Форма.xbsl", _HANDLER.format(call="Закрыть(Истина)"),
        "code/close-in-before-close",
    )
    assert len(found) == 1
    assert found[0][0] == 6
    assert "ПередЗакрытием" in found[0][2]


@pytest.mark.needs_data
def test_deferred_close_in_a_lambda_is_silent(tmp_path):
    """The cure itself: the closing is handed to a one-shot timer, so it runs outside the
    handler. The lambda may sit inside a condition - the branches of `если` hold (condition,
    body) TUPLES, and a walker that only descends into lists of nodes misses them."""
    call = "ПодключитьОбработчикТаймера(() -> Закрыть(Истина), 0с, Истина)"
    assert _diags(
        tmp_path, "Форма.xbsl", _HANDLER.format(call=call), "code/close-in-before-close",
    ) == []


@pytest.mark.needs_data
def test_close_outside_the_handler_is_silent(tmp_path):
    text = "метод ЗакрытьФорму()\n    Закрыть(Истина)\n;\n"
    assert _diags(tmp_path, "Форма.xbsl", text, "code/close-in-before-close") == []


@pytest.mark.needs_data
def test_member_close_is_not_the_forms_own(tmp_path):
    call = "Окно.Закрыть(Истина)"
    assert _diags(
        tmp_path, "Форма.xbsl", _HANDLER.format(call=call), "code/close-in-before-close",
    ) == []


# --- query/no-isnull ----------------------------------------------------------------

@pytest.mark.needs_data
def test_isnull_in_a_query_is_reported(tmp_path):
    text = (
        "метод Данные(): ПроизвольныйЗапрос\n"
        "    возврат Запрос{ВЫБРАТЬ ЕСТЬNULL(Т.Ссылка.Код, 0) ИЗ Товары КАК Т}\n"
        ";\n"
    )
    found = _diags(tmp_path, "Модуль.xbsl", text, "query/no-isnull")
    assert len(found) == 1 and found[0][0] == 2


@pytest.mark.needs_data
def test_isnull_outside_a_query_is_silent(tmp_path):
    """Only a query literal is judged - a method of the project may legitimately be named so."""
    text = "метод Проверка(): Число\n    возврат ЕСТЬNULL(1)\n;\n"
    assert _diags(tmp_path, "Модуль.xbsl", text, "query/no-isnull") == []


@pytest.mark.needs_data
def test_a_word_without_a_call_is_silent(tmp_path):
    text = (
        "метод Данные(): ПроизвольныйЗапрос\n"
        "    возврат Запрос{ВЫБРАТЬ Т.ЕстьNull ИЗ Товары КАК Т}\n"
        ";\n"
    )
    assert _diags(tmp_path, "Модуль.xbsl", text, "query/no-isnull") == []


# --- project/path-matches-descriptor -------------------------------------------------

_DESCRIPTOR = (
    "Ид: 5b1e77c4-8a20-4f3d-9d21-6a0f4e2c1d90\n"
    "РежимСовместимости: 9.0\n"
    "Поставщик: Acme\n"
    "Имя: Tasks\n"
    "Версия: 1.0.0\n"
    'Представление: "Задачи"\n'
    'ПредставлениеПоставщика: "Acme"\n'
)


def _project_diags(tmp_path, vendor_dir: str, name_dir: str):
    project = tmp_path / vendor_dir / name_dir
    project.mkdir(parents=True)
    (project / "Проект.yaml").write_text(_DESCRIPTOR, encoding="utf-8")
    found = run(discover([str(tmp_path)]), select={"project/path-matches-descriptor"})
    return [d.message for d in found]


def test_path_matching_the_descriptor_is_silent(tmp_path):
    assert _project_diags(tmp_path, "Acme", "Tasks") == []


def test_a_renamed_project_is_reported(tmp_path):
    found = _project_diags(tmp_path, "Acme", "Задачи")
    assert len(found) == 1 and "Tasks" in found[0]


def test_the_case_of_the_path_matters(tmp_path):
    """A build compares the names as they are: `acme/tasks` under `Acme`/`Tasks` is refused
    exactly like a different name would be (verified against the build tool)."""
    found = _project_diags(tmp_path, "acme", "tasks")
    assert len(found) == 1


# --- yaml/empty-group-sized and yaml/hint-too-long ------------------------------------

_FORM_HEAD = (
    "ВидЭлемента: КомпонентИнтерфейса\n"
    "Ид: 6f1d2c0e-1111-2222-3333-444455556666\n"
    "Имя: ПробнаяФорма\n"
    "Содержимое:\n"
)


@pytest.mark.needs_data
def test_empty_group_with_a_size_is_reported(tmp_path):
    text = _FORM_HEAD + "    -\n        Тип: Группа\n        Высота: 20\n"
    found = _diags(tmp_path, "ПробнаяФорма.yaml", text, "yaml/empty-group-sized")
    assert len(found) == 1
    assert "КонтейнерHtml" in found[0][2]


@pytest.mark.needs_data
def test_a_group_with_content_is_silent(tmp_path):
    text = (
        _FORM_HEAD
        + "    -\n        Тип: Группа\n        Высота: 20\n        Содержимое:\n"
          "            -\n                Тип: Надпись\n                Заголовок: Есть\n"
    )
    assert _diags(tmp_path, "ПробнаяФорма.yaml", text, "yaml/empty-group-sized") == []


@pytest.mark.needs_data
def test_a_group_without_a_size_is_silent(tmp_path):
    text = _FORM_HEAD + "    -\n        Тип: Группа\n        Компоновка: Вертикальная\n"
    assert _diags(tmp_path, "ПробнаяФорма.yaml", text, "yaml/empty-group-sized") == []


@pytest.mark.needs_data
def test_a_long_hint_is_reported(tmp_path):
    long_hint = "а" * 400
    text = (
        _FORM_HEAD
        + f"    -\n        Тип: Надпись\n        Заголовок: Поле\n        Подсказка: {long_hint}\n"
    )
    found = _diags(tmp_path, "ПробнаяФорма.yaml", text, "yaml/hint-too-long")
    assert len(found) == 1 and "400" in found[0][2]


@pytest.mark.needs_data
def test_a_hint_within_the_limit_is_silent(tmp_path):
    text = (
        _FORM_HEAD
        + f"    -\n        Тип: Надпись\n        Заголовок: Поле\n        Подсказка: {'а' * 200}\n"
    )
    assert _diags(tmp_path, "ПробнаяФорма.yaml", text, "yaml/hint-too-long") == []


@pytest.mark.needs_data
def test_a_computed_hint_is_silent(tmp_path):
    """A binding carries no text in the file - its length is not knowable here."""
    text = (
        _FORM_HEAD
        + "    -\n        Тип: Надпись\n        Заголовок: Поле\n        Подсказка: =ДлинныйТекст()\n"
    )
    assert _diags(tmp_path, "ПробнаяФорма.yaml", text, "yaml/hint-too-long") == []
