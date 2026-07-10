"""Проверки правила code/unused-method (мёртвые методы, тир D, scope=project).

Правилу нужен лексер, а лексеру – языковые данные Элемента; без данных модуль
пропускается целиком (conftest этот файл не знает, страхуемся сами).
"""

import pytest

from xbsllint import dataset, engine
from xbsllint.cli import discover

pytestmark = pytest.mark.skipif(
    not dataset.available_versions(),
    reason="нет данных Элемента – сгенерируйте tools/extract_grammar.py + extract_stdlib.py",
)

RULE = "code/unused-method"


def _lint_dir(tmp_path, **files):
    for name, content in files.items():
        (tmp_path / name.replace("__", ".")).write_text(content, encoding="utf-8")
    return engine.run(discover([str(tmp_path)]), select={RULE})


def _hits(diags):
    return [d for d in diags if d.rule_id == RULE]


# --- Сигнал: объявлен и больше нигде не встречается ------------------------------------

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


# --- Гард: имя упоминается где-то ещё ---------------------------------------------------

def test_qualified_call_from_other_module_not_flagged(tmp_path):
    # статический метод менеджера, вызываемый с квалификацией Модуль.Метод
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
    # мост HTML-вставки вызывает метод по имени внутри строкового литерала
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
    # упоминание в комментарии тоже глушит: лучше молчание, чем ложное
    d = _lint_dir(
        tmp_path,
        М__xbsl="// Колбэк: платформа вызывает ПоТаймеру\nметод ПоТаймеру()\n;\n",
    )
    assert not _hits(d)


# --- Гард: аннотации --------------------------------------------------------------------

def test_any_annotation_not_flagged(tmp_path):
    d = _lint_dir(
        tmp_path,
        М__xbsl=(
            "@НаСервере @ВПроекте\nметод Серверный()\n;\n\n"
            "@ДоступноСКлиента\nметод Клиентский()\n;\n"
        ),
    )
    assert not _hits(d)


def test_annotation_with_arguments_not_flagged(tmp_path):
    d = _lint_dir(
        tmp_path,
        М__xbsl='@ОбновлениеПроекта(Ид = "Конвертация", Номер = 1)\nметод Конвертация()\n;\n',
    )
    assert not _hits(d)


def test_annotation_of_next_method_not_inherited(tmp_path):
    # аннотация принадлежит следующему методу, а не предыдущему
    d = _lint_dir(
        tmp_path,
        М__xbsl="метод Мёртвый()\n;\n\n@НаСервере\nметод Живой()\n;\n\nметод Главный()\n    Живой()\n;\n",
        Ф__yaml="Обработчик: Главный\n",
    )
    hits = _hits(d)
    assert len(hits) == 1 and "Мёртвый" in hits[0].message


def test_static_between_annotation_and_method(tmp_path):
    d = _lint_dir(tmp_path, М__xbsl="@НаСервере\nстатический метод Утилита()\n;\n")
    assert not _hits(d)


# --- Гард: события платформы ------------------------------------------------------------

def test_platform_event_without_annotation_not_flagged(tmp_path):
    d = _lint_dir(
        tmp_path,
        М__xbsl="метод ПослеСоздания()\n;\n\nметод ПередЗаписью()\n;\n",
    )
    assert not _hits(d)


# --- Гард: особые модули ----------------------------------------------------------------

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


# --- Прочее -----------------------------------------------------------------------------

def test_same_name_in_two_modules_not_flagged(tmp_path):
    # два одноимённых объявления глушат друг друга (упоминание есть – судить нельзя)
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
