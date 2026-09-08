"""A yaml that does not parse must not turn its object into an unknown name.

The file has a finding of its own (`yaml/valid`); what must NOT follow is a flood of phantom
findings from every rule that judges names against the project model. Measured on a real
project before the fix: one broken component yaml gave 239 findings instead of 49 (175 of
them `code/undefined-name`), and one broken catalog yaml 180 instead of 50 (63
`yaml/unknown-type`, 31 `query/unknown-table`).
"""

from xbsl import engine
from xbsl.cli import discover

_GOOD = (
    "ВидЭлемента: Справочник\n"
    "Имя: Товар\n"
    "Реквизиты:\n"
    "  - Имя: Цена\n"
    "    Тип: Число\n"
    "ТабличныеЧасти:\n"
    "  - Имя: Цены\n"
)
# A ternary with spaces around the colon: YAML reads it as a nested mapping and gives up.
_BROKEN = _GOOD + "Представление: Условие ? Да : Нет\n"


def _project(tmp_path, yaml_text, rule, extra=None):
    (tmp_path / "Товар.yaml").write_text(yaml_text, encoding="utf-8")
    (tmp_path / "Товар.Объект.xbsl").write_text(
        "метод Проверить(): Число\n"
        "    возврат Цена\n"
        ";\n",
        encoding="utf-8",
    )
    for name, text in (extra or {}).items():
        (tmp_path / name).write_text(text, encoding="utf-8")
    return engine.run(discover([str(tmp_path)]), select={rule})


def test_the_parse_failure_is_reported(tmp_path):
    diags = _project(tmp_path, _BROKEN, "yaml/valid")
    assert [d.rule_id for d in diags] == ["yaml/valid"]


def test_attributes_of_an_unreadable_object_are_not_undefined(tmp_path):
    """The paired module is judged against an UNKNOWN scope, not an empty one."""
    assert _project(tmp_path, _GOOD, "code/undefined-name") == []
    assert _project(tmp_path, _BROKEN, "code/undefined-name") == []


def test_a_type_built_on_an_unreadable_object_is_not_unknown(tmp_path):
    extra = {"Заказ.yaml": (
        "ВидЭлемента: Справочник\n"
        "Имя: Заказ\n"
        "Реквизиты:\n"
        "  - Имя: Строка\n"
        "    Тип: Товар.Ссылка\n"
    )}
    assert _project(tmp_path, _GOOD, "yaml/unknown-type", extra) == []
    assert _project(tmp_path, _BROKEN, "yaml/unknown-type", extra) == []


def test_a_query_table_of_an_unreadable_object_is_not_unknown(tmp_path):
    # A second, healthy object keeps the catalog non-empty: an empty catalog means "no
    # project model at all", and the rule then stays silent for a reason of its own.
    extra = {
        "Заказ.yaml": "ВидЭлемента: Справочник\nИмя: Заказ\n",
        "Отчет.xbsl": (
            "метод Ф(): Число\n"
            "    знч Р = Запрос{\n"
            "        ВЫБРАТЬ ПЕРВЫЕ 1 Т.Ссылка КАК Ссылка\n"
            "        ИЗ Товар КАК Т\n"
            "    }.Выполнить()\n"
            "    возврат 1\n"
            ";\n"
        ),
    }
    assert _project(tmp_path, _GOOD, "query/unknown-table", extra) == []
    assert _project(tmp_path, _BROKEN, "query/unknown-table", extra) == []


def test_a_client_declaration_of_an_unreadable_pair_is_not_unused(tmp_path):
    """The unknown environment counts as client: a file we could not read is no evidence
    that nobody names the method."""
    module = (
        "@ДоступноСКлиента\n"
        "метод Обновить(): Пусто\n"
        ";\n"
        "\n"
        "метод Показать(): Пусто\n"
        "    Обновить()\n"
        ";\n"
    )

    def run(text):
        (tmp_path / "Карточка.yaml").write_text(text, encoding="utf-8")
        (tmp_path / "Карточка.xbsl").write_text(module, encoding="utf-8")
        return engine.run(discover([str(tmp_path)]), select={"code/client-available-unused"})

    good = "ВидЭлемента: КомпонентИнтерфейса\nИмя: Карточка\n"
    assert run(good) == []
    assert run(good + "Заголовок: Условие ? Да : Нет\n") == []


def test_an_import_of_the_subsystem_that_holds_it_is_not_unused(tmp_path):
    """The object stays in its subsystem: dropped from the model, it makes the import of
    that subsystem read as unused - a finding in someone else's file for a broken yaml."""
    root = tmp_path / "Основное"
    root.mkdir()
    (root / "Подсистема.yaml").write_text(
        "ВидЭлемента: Подсистема\nИмя: Основное\n", encoding="utf-8")
    # A second element keeps the subsystem KNOWN: a subsystem with no readable element at
    # all is skipped as a library or a typo, and the case would never arise.
    (root / "Склад.yaml").write_text(
        "ВидЭлемента: Справочник\nИмя: Склад\n", encoding="utf-8")
    other = tmp_path / "Прочее"
    other.mkdir()
    (other / "Подсистема.yaml").write_text(
        "ВидЭлемента: Подсистема\nИмя: Прочее\n", encoding="utf-8")
    (other / "Потребитель.xbsl").write_text(
        "импорт Основное\n"
        "\n"
        "метод Ф(): Число\n"
        "    возврат Товар.Все().Размер\n"
        ";\n",
        encoding="utf-8",
    )

    def run(text):
        (root / "Товар.yaml").write_text(text, encoding="utf-8")
        return engine.run(discover([str(tmp_path)]), select={"code/unused-import"})

    assert run(_GOOD) == []
    assert run(_BROKEN) == []
