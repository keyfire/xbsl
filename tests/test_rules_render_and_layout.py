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


# --- yaml/insert-row-needs-align -----------------------------------------------------

ALIGN_RULE = "yaml/insert-row-needs-align"

_ROW_HEAD = (
    "ВидЭлемента: КомпонентИнтерфейса\n"
    "Ид: aaaaaaaa-1111-2222-3333-444444444444\n"
    "Имя: Ф\n"
    "Содержимое:\n"
    "    -\n"
    "        Тип: Группа\n"
    "        Имя: Ряд\n"
    "        Компоновка: Горизонтальная\n"
)


def _row(cards: str, *, align: str = "", head: str = _ROW_HEAD) -> str:
    aligned = f"        ВыравниваниеСодержимогоПоВертикали: {align}\n" if align else ""
    return head + aligned + "        Содержимое:\n" + cards


_CARD_WITH_INSERT = (
    "            -\n"
    "                Тип: Группа\n"
    "                Имя: КарточкаСоВставкой\n"
    "                Компоновка: Вертикальная\n"
    "                Содержимое:\n"
    "                    -\n"
    "                        Тип: КонтейнерHtml\n"
    "                        Имя: Вставка\n"
)
_PLAIN_CARD = (
    "            -\n"
    "                Тип: Группа\n"
    "                Имя: КарточкаТекст\n"
    "                Компоновка: Вертикальная\n"
    "                Содержимое:\n"
    "                    -\n"
    "                        Тип: Надпись\n"
    "                        Значение: Текст\n"
)


def test_row_with_an_insert_card_flagged(tmp_path):
    """The live case: a bento row where the card holding an insert slides down 50 px."""
    d = _diags(tmp_path, "Ф.yaml", _row(_CARD_WITH_INSERT + _PLAIN_CARD), ALIGN_RULE)
    assert len(d) == 1, d
    assert d[0][:2] == (8, 9)  # the layout key of the row, not the top of the file
    assert "БАЗОВОЙ" in d[0][2]


def test_an_explicit_alignment_silences_the_row(tmp_path):
    d = _diags(tmp_path, "Ф.yaml", _row(_CARD_WITH_INSERT + _PLAIN_CARD, align="Верх"), ALIGN_RULE)
    assert d == []


def test_a_row_without_an_insert_is_left_alone(tmp_path):
    d = _diags(tmp_path, "Ф.yaml", _row(_PLAIN_CARD + _PLAIN_CARD), ALIGN_RULE)
    assert d == []


def test_a_single_child_has_nothing_to_slide_against(tmp_path):
    d = _diags(tmp_path, "Ф.yaml", _row(_CARD_WITH_INSERT), ALIGN_RULE)
    assert d == []


def test_a_vertical_group_is_not_a_row(tmp_path):
    head = _ROW_HEAD.replace("Компоновка: Горизонтальная", "Компоновка: Вертикальная")
    d = _diags(tmp_path, "Ф.yaml", _row(_CARD_WITH_INSERT + _PLAIN_CARD, head=head), ALIGN_RULE)
    assert d == []


def test_the_nearest_row_answers_not_its_parent(tmp_path):
    """A live project's media group reads exactly this way: the inner strip is aligned, so
    the outer row must stay silent - the insert's baseline is settled deeper."""
    inner = (
        "            -\n"
        "                Тип: Группа\n"
        "                Имя: Полоса\n"
        "                Компоновка: Горизонтальная\n"
        "                ВыравниваниеСодержимогоПоВертикали: Центр\n"
        "                Содержимое:\n"
        "                    -\n"
        "                        Тип: КонтейнерHtml\n"
        "                        Имя: Вставка\n"
        "                    -\n"
        "                        Тип: Надпись\n"
        "                        Значение: Рядом\n"
    )
    d = _diags(tmp_path, "Ф.yaml", _row(inner + _PLAIN_CARD), ALIGN_RULE)
    assert d == []
