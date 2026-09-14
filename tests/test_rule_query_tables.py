"""query/unknown-table: tables of Запрос{...} blocks against the project objects."""

import pytest

from xbsl import engine
from xbsl.cli import discover

_RULE = "query/unknown-table"


def _project(tmp_path, body):
    (tmp_path / "Товар.yaml").write_text(
        "ВидЭлемента: Справочник\n"
        "Имя: Товар\n"
        "ТабличныеЧасти:\n"
        "  - Имя: Цены\n",
        encoding="utf-8",
    )
    (tmp_path / "Остаток.yaml").write_text(
        "ВидЭлемента: РегистрСведений\nИмя: Остаток\n",
        encoding="utf-8",
    )
    (tmp_path / "Модуль.xbsl").write_text(body, encoding="utf-8")
    return engine.run(discover([str(tmp_path)]), select={_RULE})


def _query(inner):
    return (
        "метод Ф(): Число\n"
        "    знч Р = Запрос{\n"
        f"{inner}\n"
        "    }.Выполнить()\n"
        "    возврат 1\n"
        ";\n"
    )


def test_known_tables_are_silent(tmp_path):
    diags = _project(tmp_path, _query(
        "        ВЫБРАТЬ ПЕРВЫЕ 1 Т.Ссылка КАК Ссылка\n"
        "        ИЗ Товар КАК Т\n"
        "        ВНУТРЕННЕЕ СОЕДИНЕНИЕ Товар.Цены КАК Ц ПО Ц.Ссылка = Т.Ссылка\n"
        "        ГДЕ Т.Наименование = \"х\""
    ))
    assert diags == []


def test_unknown_bare_table(tmp_path):
    diags = _project(tmp_path, _query("        ВЫБРАТЬ 1 ИЗ Тавар"))
    assert len(diags) == 1
    assert "Тавар" in diags[0].message
    assert diags[0].rule_id == _RULE


def test_unknown_tabular_section(tmp_path):
    diags = _project(tmp_path, _query("        ВЫБРАТЬ 1 ИЗ Товар.Цены2 КАК Ц"))
    assert len(diags) == 1
    assert "Цены2" in diags[0].message and "Товар" in diags[0].message


def test_join_with_unknown_section(tmp_path):
    diags = _project(tmp_path, _query(
        "        ВЫБРАТЬ 1 ИЗ Товар КАК Т\n"
        "        СОЕДИНЕНИЕ Товар.Нет КАК Н ПО Н.Ссылка = Т.Ссылка"
    ))
    assert len(diags) == 1


def test_unknown_root_of_dotted_table_is_skipped(tmp_path):
    # the root is not from the project: possibly an external library object - silence
    diags = _project(tmp_path, _query("        ВЫБРАТЬ 1 ИЗ Библиотека.Таблица КАК Т"))
    assert diags == []


def test_virtual_table_is_skipped(tmp_path):
    diags = _project(tmp_path, _query("        ВЫБРАТЬ 1 ИЗ Остаток.СрезПоследних КАК С"))
    assert diags == []


def test_deep_chain_is_skipped(tmp_path):
    diags = _project(tmp_path, _query("        ВЫБРАТЬ 1 ИЗ Товар.Цены.Что КАК Т"))
    assert diags == []


def test_unsupported_block_is_skipped_whole(tmp_path):
    diags = _project(tmp_path, _query(
        "        ВЫБРАТЬ 1 ПОМЕСТИТЬ ВТ\n"
        "        ИЗ Тавар КАК Т"
    ))
    assert diags == []


def test_subquery_in_from_skips_block(tmp_path):
    diags = _project(tmp_path, _query(
        "        ВЫБРАТЬ 1 ИЗ (ВЫБРАТЬ 2 ИЗ Тавар) КАК Т"
    ))
    assert diags == []


def test_two_blocks_are_independent(tmp_path):
    body = (
        "метод А(): Число\n"
        "    знч Р = Запрос{ ВЫБРАТЬ 1 ПОМЕСТИТЬ ВТ ИЗ Тавар }.Выполнить()\n"
        "    возврат 1\n"
        ";\n"
        "метод Б(): Число\n"
        "    знч Р = Запрос{ ВЫБРАТЬ 1 ИЗ Нечто }.Выполнить()\n"
        "    возврат 1\n"
        ";\n"
    )
    diags = _project(tmp_path, body)
    assert len(diags) == 1 and "Нечто" in diags[0].message


def _project_with_descriptor(tmp_path, body):
    (tmp_path / "Проект.yaml").write_text(
        "Ид: f25543fb-c726-496e-9af5-71f61527e97c\nИмя: Сайт\nПоставщик: acme\n",
        encoding="utf-8",
    )
    return _project(tmp_path, body)


def test_qualified_own_table_resolved(tmp_path):
    # a qualified name of our own project: judge by the last segment
    diags = _project_with_descriptor(tmp_path, _query(
        "        ВЫБРАТЬ 1 ИЗ acme::Сайт::Основное::Товар КАК Т"
    ))
    assert diags == []


def test_qualified_own_typo_flagged(tmp_path):
    diags = _project_with_descriptor(tmp_path, _query(
        "        ВЫБРАТЬ 1 ИЗ acme::Сайт::Основное::Тавар КАК Т"
    ))
    assert len(diags) == 1 and "Тавар" in diags[0].message


def test_qualified_foreign_namespace_silent(tmp_path):
    # a foreign namespace - a library object, absent from the project catalog
    diags = _project_with_descriptor(tmp_path, _query(
        "        ВЫБРАТЬ 1 ИЗ globex::ОчередьЛиб::Ядро::Сообщения КАК С"
    ))
    assert diags == []


def test_platform_entity_table_silent(tmp_path):
    # Пользователи is a platform entity, not a project object
    diags = _project(tmp_path, _query(
        "        ВЫБРАТЬ 1 ИЗ Пользователи КАК П"
    ))
    assert diags == []


@pytest.mark.parametrize("inner, missing", [
    ("ВЫБРАТЬ 1 ИЗ Товар КАК Т, НетТаблицы КАК Н", "НетТаблицы"),
    ("SELECT 1 FROM Товар AS T, НетТаблицы AS N", "НетТаблицы"),
    ("ВЫБРАТЬ 1 ИЗ Товар, Остаток, Товар.НетЧасти", "НетЧасти"),
    ("ВЫБРАТЬ 1 ИЗ Товар КАК Т СОЕДИНЕНИЕ Остаток КАК О ПО Т.Ссылка = О.Ссылка, НетТаблицы КАК Н", "НетТаблицы"),
])
def test_every_comma_separated_table_is_checked(tmp_path, inner, missing):
    source = _query(inner)
    diags = _project(tmp_path, source)
    assert len(diags) == 1 and missing in diags[0].message
    at = source.splitlines()[diags[0].line - 1][diags[0].col - 1:]
    assert at.startswith(missing)


@pytest.mark.parametrize("inner", [
    "ВЫБРАТЬ 1 ИЗ Товар, Остаток, Товар.Цены",
    "SELECT 1 FROM Товар T, Остаток O, Товар.Цены P",
    "ВЫБРАТЬ Т.Ссылка, НетТаблицы ИЗ Товар КАК Т",
    "ВЫБРАТЬ 1 ИЗ Товар КАК Т ГДЕ Т.Код В (1, 2, 3)",
    "ВЫБРАТЬ 1 ИЗ Товар, Чужой.Объект, Остаток.СрезПоследних",
    "ВЫБРАТЬ 1 ПОМЕСТИТЬ ВТ ИЗ Товар, НетТаблицы",
    "ВЫБРАТЬ 1 ИЗ (ВЫБРАТЬ 1 ИЗ Товар), НетТаблицы",
])
def test_comma_controls_keep_existing_conservative_boundaries(tmp_path, inner):
    assert _project(tmp_path, _query(inner)) == []


def test_standalone_query_checks_the_second_table(tmp_path):
    _project(tmp_path, _query("ВЫБРАТЬ 1 ИЗ Товар"))
    query = tmp_path / "Проверка.xbql"
    query.write_text("ВЫБРАТЬ 1 ИЗ Товар, НетТаблицы", encoding="utf-8")
    diags = engine.run(discover([str(tmp_path)]), select={_RULE})
    assert len(diags) == 1 and diags[0].path.endswith("Проверка.xbql")
    assert "НетТаблицы" in diags[0].message
