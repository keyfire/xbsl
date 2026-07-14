"""query/in-subquery-composite: `В` с подзапросом по полю составного типа."""

from xbsllint import engine
from xbsllint.cli import discover

_RULE = "query/in-subquery-composite"


def _project(tmp_path, body):
    (tmp_path / "Товары.yaml").write_text(
        "ВидЭлемента: Справочник\n"
        "Имя: Товары\n"
        "Реквизиты:\n"
        "  - Имя: Наименование\n"
        "    Тип: Строка\n"
        "  - Имя: Бейдж\n"
        "    Тип: Строка|Число|?\n"
        "  - Имя: Пометка\n"
        "    Тип: Строка|?\n"
        "  - Имя: Варианты\n"
        "    Тип: Массив<Строка|Число>\n",
        encoding="utf-8",
    )
    (tmp_path / "Параметры.yaml").write_text(
        "ВидЭлемента: РегистрСведений\n"
        "Имя: Параметры\n"
        "Измерения:\n"
        "  - Имя: Ключ\n"
        "    Тип: Строка\n"
        "Ресурсы:\n"
        "  - Имя: Значение\n"
        "    Тип: Булево|Число|Строка|ДатаВремя|?\n",
        encoding="utf-8",
    )
    (tmp_path / "Фильтры.yaml").write_text(
        "ВидЭлемента: Справочник\n"
        "Имя: Фильтры\n"
        "Реквизиты:\n"
        "  - Имя: Бейдж\n"
        "    Тип: Строка|Число|?\n",
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


def test_composite_field_in_subquery(tmp_path):
    diags = _project(tmp_path, _query(
        "        ВЫБРАТЬ Т.Наименование КАК Наименование\n"
        "        ИЗ Товары КАК Т\n"
        "        ГДЕ Т.Бейдж В (ВЫБРАТЬ Ф.Бейдж ИЗ Фильтры КАК Ф)"
    ))
    assert len(diags) == 1
    assert diags[0].rule_id == _RULE
    assert "Т.Бейдж" in diags[0].message
    assert "Строка|Число" in diags[0].message
    assert "СУЩЕСТВУЕТ" in diags[0].message


def test_not_in_suggests_not_exists(tmp_path):
    diags = _project(tmp_path, _query(
        "        ВЫБРАТЬ 1\n"
        "        ИЗ Товары КАК Т\n"
        "        ГДЕ Т.Бейдж НЕ В (ВЫБРАТЬ Ф.Бейдж ИЗ Фильтры КАК Ф)"
    ))
    assert len(diags) == 1
    assert "НЕ СУЩЕСТВУЕТ" in diags[0].message


def test_simple_type_is_silent(tmp_path):
    diags = _project(tmp_path, _query(
        "        ВЫБРАТЬ 1\n"
        "        ИЗ Товары КАК Т\n"
        "        ГДЕ Т.Наименование В (ВЫБРАТЬ Ф.Бейдж ИЗ Фильтры КАК Ф)"
    ))
    assert diags == []


def test_nullable_is_not_composite(tmp_path):
    # `Строка|?` – та же Строка, только с Неопределено: одна альтернатива, стандарт не о ней
    diags = _project(tmp_path, _query(
        "        ВЫБРАТЬ 1\n"
        "        ИЗ Товары КАК Т\n"
        "        ГДЕ Т.Пометка В (ВЫБРАТЬ Ф.Бейдж ИЗ Фильтры КАК Ф)"
    ))
    assert diags == []


def test_union_inside_generic_is_not_composite(tmp_path):
    # `Массив<Строка|Число>` – один тип, а не составной: `|` внутри обобщения не делит
    diags = _project(tmp_path, _query(
        "        ВЫБРАТЬ 1\n"
        "        ИЗ Товары КАК Т\n"
        "        ГДЕ Т.Варианты В (ВЫБРАТЬ Ф.Бейдж ИЗ Фильтры КАК Ф)"
    ))
    assert diags == []


def test_value_list_is_silent(tmp_path):
    # стандарт – про подзапрос; список значений в скобках эффективен и на составном типе
    diags = _project(tmp_path, _query(
        "        ВЫБРАТЬ 1\n"
        "        ИЗ Товары КАК Т\n"
        "        ГДЕ Т.Бейдж В (\"новинка\", 30, &Бейджи)"
    ))
    assert diags == []


def test_english_keywords(tmp_path):
    diags = _project(tmp_path, _query(
        "        SELECT 1\n"
        "        FROM Параметры AS P\n"
        "        WHERE P.Значение IN (SELECT F.Бейдж FROM Фильтры AS F)"
    ))
    assert len(diags) == 1
    assert "P.Значение" in diags[0].message
    assert "EXISTS" in diags[0].message or "СУЩЕСТВУЕТ" in diags[0].message


def test_table_without_alias(tmp_path):
    diags = _project(tmp_path, _query(
        "        ВЫБРАТЬ 1\n"
        "        ИЗ Товары\n"
        "        ГДЕ Товары.Бейдж В (ВЫБРАТЬ Ф.Бейдж ИЗ Фильтры КАК Ф)"
    ))
    assert len(diags) == 1
    assert "Товары.Бейдж" in diags[0].message


def test_alias_redefined_in_subquery_is_skipped(tmp_path):
    # алиас Т в подзапросе – уже другая таблица: таблицу поля мы не знаем и молчим
    diags = _project(tmp_path, _query(
        "        ВЫБРАТЬ 1\n"
        "        ИЗ Товары КАК Т\n"
        "        ГДЕ Т.Бейдж В (ВЫБРАТЬ Т.Бейдж ИЗ Фильтры КАК Т)"
    ))
    assert diags == []


def test_unknown_prefix_is_skipped(tmp_path):
    diags = _project(tmp_path, _query(
        "        ВЫБРАТЬ 1\n"
        "        ИЗ Библиотека.Таблица КАК Т\n"
        "        ГДЕ Т.Бейдж В (ВЫБРАТЬ Ф.Бейдж ИЗ Фильтры КАК Ф)"
    ))
    assert diags == []


def test_deep_chain_is_skipped(tmp_path):
    # `Т.Товар.Бейдж` – тип последнего сегмента цепочки нам неизвестен
    diags = _project(tmp_path, _query(
        "        ВЫБРАТЬ 1\n"
        "        ИЗ Товары КАК Т\n"
        "        ГДЕ Т.Товар.Бейдж В (ВЫБРАТЬ Ф.Бейдж ИЗ Фильтры КАК Ф)"
    ))
    assert diags == []


def test_unknown_field_is_skipped(tmp_path):
    diags = _project(tmp_path, _query(
        "        ВЫБРАТЬ 1\n"
        "        ИЗ Товары КАК Т\n"
        "        ГДЕ Т.Нету В (ВЫБРАТЬ Ф.Бейдж ИЗ Фильтры КАК Ф)"
    ))
    assert diags == []


def test_register_resource_is_composite(tmp_path):
    diags = _project(tmp_path, _query(
        "        ВЫБРАТЬ 1\n"
        "        ИЗ Параметры КАК П\n"
        "        ГДЕ П.Значение В (ВЫБРАТЬ Ф.Бейдж ИЗ Фильтры КАК Ф)"
    ))
    assert len(diags) == 1
    assert "П.Значение" in diags[0].message


def test_two_conditions_in_one_block(tmp_path):
    diags = _project(tmp_path, _query(
        "        ВЫБРАТЬ 1\n"
        "        ИЗ Товары КАК Т\n"
        "        ГДЕ Т.Бейдж В (ВЫБРАТЬ Ф.Бейдж ИЗ Фильтры КАК Ф)\n"
        "        И Т.Пометка В (ВЫБРАТЬ Ф.Бейдж ИЗ Фильтры КАК Ф)\n"
        "        И Т.Бейдж НЕ В (ВЫБРАТЬ Ф.Бейдж ИЗ Фильтры КАК Ф)"
    ))
    # составной Бейдж – дважды, Пометка (nullable Строка) – не в счёт
    assert len(diags) == 2
