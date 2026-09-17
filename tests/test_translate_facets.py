"""The reference member, the qualified enumeration default and the automatic size.

Three gaps the parity seeds (tools/parity_seed.py) found in the translator, each pinned by
a hand-written English twin the platform dictionaries spell:

- `.Ссылка` after a variable is the REFERENCE of the record when the variable holds a facet
  of a project object, and the property `Link` of a label, a picture or an open-by-link
  event otherwise - the flat compiler dictionary answered `Link` for both;
- a default qualified by its own enumeration (`Дежурства.Черновик`) kept both halves Russian
  next to an enumeration the tree had already renamed;
- `Auto` on a property typed by a union (`Авто|Число`) is a type of the schema, not data.

Two more come from a live project translated without a dictionary: a member whose owner only a
chain tells (`Объект.Товары.Граница()` - the bound of an array, not the border of a
spreadsheet area), and a method of the manager of a project element
(`ПравоНаОтчеты.Проверить()` - Check on a privilege, Verify on a signature).
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from xbsl import dataset, engine
from xbsl.translation import dictionary as dict_module
from xbsl.translation.code import Resolver, translate_code
from xbsl.translation.project import translate_project
from xbsl.translation.reporting import FileReport
from xbsl.translation.yamlfile import translate_yaml

pytestmark = pytest.mark.needs_data


def _dictionary(tokens: dict | None = None) -> dict_module.Dictionary:
    return dict_module.Dictionary(tokens=dict(tokens or {}), phrases={}, literals={})


def _code(text: str, tokens: dict, names: set[str]) -> tuple[str, FileReport]:
    source = engine.load_text("Наряды.xbsl", text)
    report = FileReport(path="Наряды.xbsl")
    resolver = Resolver(_dictionary(tokens), frozenset(names))
    return translate_code(source, resolver, report), report


def _yaml(text: str, name: str, tokens: dict) -> tuple[str, FileReport]:
    source = engine.load_text(name, text)
    report = FileReport(path=name)
    return translate_yaml(source, Resolver(_dictionary(tokens)), report), report


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


_TOKENS = {
    "Наряды": "WorkOrders", "Проба": "Probe", "Наряд": "WorkOrder", "Созданный": "Created",
    "Сработавшее": "Fired", "Мишень": "Target", "Ярлычок": "Tag", "Плакат": "Poster",
    "Считанный": "Loaded", "Собственный": "Own", "Россыпь": "Scatter", "Выданный": "Issued",
    "Близнец": "Twin", "Табличка": "Plate",
}
_NAMES = {"Наряды", "Проба"}


# --- the reference member --------------------------------------------------------------------


def test_the_reference_member_of_a_receiver_typed_by_a_project_facet_is_the_facet_word():
    """A parameter declared as a reference, a local built as an object, a local loaded from a
    reference: each holds a facet of a project object, and its `.Ссылка` is the reference of
    the record - `Reference`, the facet word - never the property `Link`."""
    out, report = _code(
        "метод Проба(Наряд: Наряды.Ссылка)\n"
        "    знч Объект = Наряд.Ссылка.ЗагрузитьОбъект()!\n"
        "    знч Созданный = новый Наряды.Объект()\n"
        "    знч Считанный = Наряд.ЗагрузитьОбъект()!\n"
        "    знч Собственный = Считанный.Ссылка\n"
        "    возврат Созданный.Ссылка\n;\n",
        _TOKENS, _NAMES,
    )
    assert "val Object = WorkOrder.Reference.LoadObject()!" in out
    assert "val Own = Loaded.Reference" in out
    assert "return Created.Reference" in out
    assert report.missing_tokens == {}


def test_the_link_property_of_a_platform_receiver_keeps_the_property_word():
    """An open-by-link event, a label and a picture reached through the components carry the
    PROPERTY - a hyperlink, spelled `Link` by the owner's own table."""
    out, _report = _code(
        "метод Проба(Сработавшее: СобытиеПриОткрытииПоСсылке)\n"
        "    знч Табличка = новый Надпись()\n"
        "    знч Мишень = Сработавшее.Ссылка\n"
        "    знч Ярлычок = Табличка.Ссылка\n"
        "    знч Плакат = Компоненты.Картинка.Ссылка\n;\n",
        _TOKENS, _NAMES,
    )
    assert "val Target = Fired.Link" in out
    assert "val Tag = Plate.Link" in out
    assert "val Poster = Components.Picture.Link" in out


def test_an_untyped_receiver_is_told_by_the_load_that_follows_and_keeps_link_otherwise():
    """A row of a query result has no type the inference can name. Its `.Ссылка` followed by
    the load of the record is a reference - only a reference facet declares that method; the
    same member standing alone is left to the flat dictionary, which spells the property."""
    out, _report = _code(
        "метод Проба()\n"
        "    пер Россыпь = Запрос{ ВЫБРАТЬ Н.Наименование ИЗ Наряды КАК Н }.Выполнить()\n"
        "    для Выданный из Россыпь\n"
        "        знч Объект = Выданный.Ссылка.ЗагрузитьОбъект()!\n"
        "        знч Близнец = Выданный.Ссылка!.ЗагрузитьОбъект()\n"
        "        знч Собственный = Выданный.Ссылка\n"
        "    ;\n;\n",
        _TOKENS, _NAMES,
    )
    assert "val Object = Issued.Reference.LoadObject()!" in out
    assert "val Twin = Issued.Reference!.LoadObject()" in out
    assert "val Own = Issued.Link" in out


def test_the_dictionary_still_answers_the_reference_member_first():
    """An entry qualified by the variable is about that variable, facet or not."""
    out, _report = _code(
        "метод Проба(Наряд: Наряды.Ссылка)\n    возврат Наряд.Ссылка\n;\n",
        {**_TOKENS, "Наряд.Ссылка": "Href"}, _NAMES,
    )
    assert "return WorkOrder.Href" in out


# --- the qualified enumeration default -------------------------------------------------------


_DUTIES_RU = (
    "ВидЭлемента: Перечисление\n"
    "Имя: Дежурства\n"
    "Элементы:\n"
    "    -\n"
    "        Имя: Черновик\n"
)


def _work_orders_ru(default: str) -> str:
    return (
        "ВидЭлемента: Справочник\n"
        "Имя: Наряды\n"
        "Реквизиты:\n"
        "    -\n"
        "        Имя: Дежурство\n"
        "        Тип: Дежурства?\n"
        f"        ЗначениеПоУмолчанию: {default}\n"
    )


_DUTIES_TOKENS = {"Дежурства": "Duties", "Черновик": "Draft", "Наряды": "WorkOrders",
                  "Дежурство": "Duty"}


def test_a_default_qualified_by_its_own_enumeration_moves_in_both_halves(tmp_path: Path):
    """`Дежурства.Черновик` under `Тип: Дежурства?` is the qualified form the rule
    yaml/enum-default-value reports; translated, it has to name the enumeration and the item
    the way the tree spells them, so the English tree carries the same finding."""
    root = tmp_path / "Acme" / "Demo"
    _write(root / "Дежурства.yaml", _DUTIES_RU)
    _write(root / "Наряды.yaml", _work_orders_ru("Дежурства.Черновик"))
    out = tmp_path / "out"
    translate_project(root, _dictionary(_DUTIES_TOKENS), out, swap_localization=False)
    written = (out / "WorkOrders.yaml").read_text(encoding="utf-8")
    assert "Type: Duties?" in written
    assert "DefaultValue: Duties.Draft" in written


def test_a_default_qualified_by_a_foreign_name_is_left_as_written(tmp_path: Path):
    """Only the field's own type before the item is the proven form; a value qualified by
    another name is not a default the rule reads, and the translator does not guess at it."""
    root = tmp_path / "Acme" / "Demo"
    _write(root / "Дежурства.yaml", _DUTIES_RU)
    _write(root / "Наряды.yaml", _work_orders_ru("Иное.Черновик"))
    out = tmp_path / "out"
    translate_project(root, _dictionary({**_DUTIES_TOKENS, "Иное": "Other"}), out,
                      swap_localization=False)
    assert "DefaultValue: Иное.Черновик" in (out / "WorkOrders.yaml").read_text(encoding="utf-8")


# --- the automatic size --------------------------------------------------------------------


def test_the_automatic_value_of_a_union_typed_property_is_spelled_by_the_schema():
    """`MaxWidth` and `Height` are typed `Авто|Число`, `Tooltip` is `Авто|Строка`: a value
    spelling the union's own member is that member, and its spelling is the platform's pair
    for the type. A number stays a number, and a string-typed title reading the same word
    stays data."""
    out, _report = _yaml(
        "ВидЭлемента: КомпонентИнтерфейса\n"
        "Имя: ФормаНаряда\n"
        "Наследует:\n"
        "    Тип: ФормаОбъекта<Наряды.Объект>\n"
        "    Содержимое:\n"
        "        Тип: Группа\n"
        "        Компоновка: Матричная\n"
        "        Заголовок: Авто\n"
        "        МаксимальнаяШирина: Авто\n"
        "        Высота: Авто\n"
        "        МинимальнаяШирина: 200\n"
        "        Содержимое:\n"
        "            -\n"
        "                Тип: Картинка\n"
        "                Подсказка: Авто\n",
        name="ФормаНаряда.yaml",
        tokens={"ФормаНаряда": "WorkOrderForm", "Наряды": "WorkOrders"},
    )
    assert "Layout: Matrix" in out
    assert "MaxWidth: Auto" in out
    assert "Height: Auto" in out
    assert "MinWidth: 200" in out
    assert "Tooltip: Auto" in out
    assert "Title: Авто" in out


# --- the data the privileges are spelled by ------------------------------------------------------


def privilege_data_root(root: Path, *, stated: bool) -> Path:
    """A copy of the generated data of the current version with the two facts the extractor
    states for the privileges - or without them, the way data extracted before them looks.

    The values of the privilege facet are the pairs of the enumeration class the extractor names
    after the facet (the compiler dictionary keeps the class under its own name); the manager is
    the row the compiler files the privilege manager under.
    """
    version = dataset.resolve_version()
    target = root / version
    target.mkdir(parents=True)
    for path in (dataset.data_root() / version).glob("*.json"):
        shutil.copyfile(path, target / path.name)
    uiterms = json.loads((target / "uiterms.json").read_text(encoding="utf-8"))
    full = json.loads((target / "terms_full.json").read_text(encoding="utf-8"))
    tables = uiterms.setdefault("enum_values", {})
    if stated:
        tables["Сущность.Право"] = dict(full["members"]["EntityPrivilegeG5Enum"])
        full.setdefault("manager_owners", {})["ПравоНаДействие"] = "PrivilegeOnActionManager"
    else:
        tables.pop("Сущность.Право", None)
        full.pop("manager_owners", None)
    for name, content in (("uiterms.json", uiterms), ("terms_full.json", full)):
        (target / name).write_text(json.dumps(content, ensure_ascii=False), encoding="utf-8")
    (root / "index.json").write_text(
        json.dumps({"available": [version], "default": version}), encoding="utf-8")
    return root


@pytest.fixture(scope="module")
def privilege_roots(tmp_path_factory) -> dict[str, Path]:
    base = tmp_path_factory.mktemp("privileges")
    return {
        "stated": privilege_data_root(base / "stated", stated=True),
        "before": privilege_data_root(base / "before", stated=False),
    }


@pytest.fixture()
def stated_privileges(privilege_roots):
    dataset.set_data_root(privilege_roots["stated"])
    yield privilege_roots
    dataset.set_data_root(None)


# --- a member whose owner a chain holds --------------------------------------------------------


_ORDERS = (
    "ВидЭлемента: Справочник\n"
    "Имя: Заказы\n"
    "Реквизиты:\n"
    "    -\n"
    "        Имя: Клиент\n"
    "        Тип: Строка\n"
    "ТабличныеЧасти:\n"
    "    -\n"
    "        Имя: Товары\n"
    "        Реквизиты:\n"
    "            -\n"
    "                Имя: Количество\n"
    "                Тип: Число\n"
)

_ORDER_TOKENS = {
    "Заказы": "Orders", "Клиент": "Customer", "Товары": "Goods", "Количество": "Quantity",
    "ЗаказыФормаОбъекта": "OrdersObjectForm", "КопироватьСтроку": "CopyRow",
    "Исходная": "Source", "Индекс": "Position", "УзелСтрок": "RowNode", "Строки": "Rows",
    "НайтиУзел": "FindNode", "Последняя": "Last", "Узел": "Node", "УзелОбласти": "AreaNode",
    "Область": "Area", "Рамка": "Frame", "Узлы": "Nodes",
}


def _order_project(root: Path) -> None:
    _write(root / "Заказы.yaml", _ORDERS)
    _write(root / "ЗаказыФормаОбъекта.yaml", (
        "ВидЭлемента: КомпонентИнтерфейса\n"
        "Имя: ЗаказыФормаОбъекта\n"
        "Наследует:\n"
        "    Тип: ФормаОбъекта<Заказы.Объект>\n"
    ))
    _write(root / "ЗаказыФормаОбъекта.xbsl", (
        "метод КопироватьСтроку(Исходная: Заказы.Товары)\n"
        "    знч Индекс = Объект.Товары.Найти(Исходная) ?? Объект.Товары.Граница()\n"
        ";\n"
    ))
    _write(root / "Узлы.xbsl", (
        "структура УзелСтрок\n"
        "    пер Строки: Массив<Строка>\n"
        ";\n"
        "\n"
        "структура УзелОбласти\n"
        "    пер Область: ВыводимаяОбластьТабличногоДокумента\n"
        ";\n"
        "\n"
        "метод НайтиУзел(): УзелСтрок?\n"
        "    возврат Неопределено\n"
        ";\n"
        "\n"
        "метод Последняя(): Число\n"
        "    знч Узел = НайтиУзел()\n"
        "    возврат Узел!.Строки.Граница()\n"
        ";\n"
        "\n"
        "метод Рамка(Узел: УзелОбласти)\n"
        "    знч Область = Узел.Область.Граница\n"
        ";\n"
    ))


def test_the_bound_of_a_tabular_section_read_off_the_object_of_a_form(tmp_path: Path):
    """`Объект` of an object form is the object its base type names, `Товары` is a tabular
    section of it - an array of rows, whose `Граница` is Bound. The dictionary spells only the
    project's words."""
    root = tmp_path / "Acme" / "Demo"
    _order_project(root)
    out = tmp_path / "en"
    report = translate_project(root, _dictionary(_ORDER_TOKENS), out, swap_localization=False)

    form = (out / "OrdersObjectForm.xbsl").read_text(encoding="utf-8")
    assert "Object.Goods.Find(Source) ?? Object.Goods.Bound()" in form
    assert all("Граница" not in file.missing_platform for file in report.files.values())


def test_the_owner_of_a_member_after_a_structure_field_is_the_type_of_the_field(tmp_path: Path):
    """An unwrapped local holding a structure, then its field: the member belongs to the type the
    field declares. The same word is Bound on an array and Border on a spreadsheet area, so the
    chain has to be read - no single spelling of the word is right for both."""
    root = tmp_path / "Acme" / "Demo"
    _order_project(root)
    out = tmp_path / "en"
    translate_project(root, _dictionary(_ORDER_TOKENS), out, swap_localization=False)

    nodes = (out / "Nodes.xbsl").read_text(encoding="utf-8")
    assert "return Node!.Rows.Bound()" in nodes
    assert "val Area = Node.Area.Border" in nodes


def test_a_chain_of_no_known_type_keeps_the_word_and_reports_the_gap(tmp_path: Path):
    root = tmp_path / "Acme" / "Demo"
    _write(root / "Проба.xbsl", "метод Проба()\n    возврат Нечто.Поле.Граница()\n;\n")
    out = tmp_path / "en"
    report = translate_project(root, _dictionary({"Проба": "Probe"}), out,
                               swap_localization=False)

    written = (out / "Probe.xbsl").read_text(encoding="utf-8")
    assert "Нечто." in written and ".Граница()" in written
    assert "Bound" not in written and "Border" not in written
    assert "Граница" in report.files["Проба.xbsl"].missing_platform


# --- a method of the manager of a project element ------------------------------------------------


_PRIVILEGE_TOKENS = {
    "ПравоНаОтчеты": "ReportsPrivilege", "ПроверкаОтчетов": "ReportsCheck",
    "Доступ": "Access", "Склады": "Warehouses",
}


def _privilege_project(root: Path, kind_line: str = "ВидЭлемента: ПравоНаДействие") -> None:
    _write(root / "ПравоНаОтчеты.yaml", f"{kind_line}\nИмя: ПравоНаОтчеты\n")
    _write(root / "Доступ.xbsl", (
        "метод ПроверкаОтчетов()\n"
        "    ПравоНаОтчеты.Проверить()\n"
        ";\n"
    ))


def test_the_check_of_a_privilege_is_the_word_of_its_manager(tmp_path: Path, stated_privileges):
    root = tmp_path / "Acme" / "Demo"
    _privilege_project(root)
    out = tmp_path / "en"
    report = translate_project(root, _dictionary(_PRIVILEGE_TOKENS), out,
                               swap_localization=False)

    assert "ReportsPrivilege.Check()" in (out / "Access.xbsl").read_text(encoding="utf-8")
    assert "Проверить" not in report.files["Доступ.xbsl"].missing_platform


def test_an_element_kind_written_in_english_names_the_same_manager(tmp_path: Path,
                                                                   stated_privileges):
    root = tmp_path / "Acme" / "Demo"
    _privilege_project(root, kind_line="ElementKind: PrivilegeOnAction")
    out = tmp_path / "en"
    translate_project(root, _dictionary(_PRIVILEGE_TOKENS), out, swap_localization=False)

    assert "ReportsPrivilege.Check()" in (out / "Access.xbsl").read_text(encoding="utf-8")


def test_a_method_of_the_manager_module_of_another_kind_stays_the_project_s(
        tmp_path: Path, stated_privileges):
    root = tmp_path / "Acme" / "Demo"
    _write(root / "Склады.yaml", "ВидЭлемента: Справочник\nИмя: Склады\n")
    _write(root / "Склады.xbsl", "метод Проверить()\n;\n")
    _write(root / "Доступ.xbsl", "метод ПроверкаОтчетов()\n    Склады.Проверить()\n;\n")
    out = tmp_path / "en"
    translate_project(root, _dictionary({**_PRIVILEGE_TOKENS, "Проверить": "Inspect"}), out,
                      swap_localization=False)

    assert "Warehouses.Inspect()" in (out / "Access.xbsl").read_text(encoding="utf-8")


def test_a_local_spelled_like_the_element_is_not_its_manager(tmp_path: Path, stated_privileges):
    """A local of no known type named like the element is the local: its members are not the
    manager's, whatever the element of that name has."""
    root = tmp_path / "Acme" / "Demo"
    _privilege_project(root)
    _write(root / "Доступ.xbsl", (
        "метод ПроверкаОтчетов()\n"
        "    знч ПравоНаОтчеты = ПолучитьЧтоУгодно()\n"
        "    ПравоНаОтчеты.Проверить()\n"
        ";\n"
    ))
    out = tmp_path / "en"
    translate_project(root, _dictionary(_PRIVILEGE_TOKENS), out, swap_localization=False)

    assert ".Check()" not in (out / "Access.xbsl").read_text(encoding="utf-8")


def test_data_without_the_manager_keeps_the_call_a_gap(tmp_path: Path, privilege_roots):
    root = tmp_path / "Acme" / "Demo"
    _privilege_project(root)
    out = tmp_path / "en"
    dataset.set_data_root(privilege_roots["before"])
    try:
        report = translate_project(root, _dictionary(_PRIVILEGE_TOKENS), out,
                                   swap_localization=False)
    finally:
        dataset.set_data_root(None)

    assert "ReportsPrivilege.Проверить()" in (out / "Access.xbsl").read_text(encoding="utf-8")
    assert "Проверить" in report.files["Доступ.xbsl"].missing_platform


def test_an_entry_that_repeats_the_manager_is_an_echo_unless_the_project_needs_it(
        tmp_path: Path, stated_privileges):
    """The entry `Проверить: Check` used to be what spelled the call. Now the platform does, and
    the entry is named as the workaround it was - unless the project declares a method of that
    name, where the entry is the only answer."""
    tokens = {**_PRIVILEGE_TOKENS, "Проверить": "Check"}
    root = tmp_path / "Acme" / "Demo"
    _privilege_project(root)
    report = translate_project(root, _dictionary(tokens), tmp_path / "en",
                               swap_localization=False)
    assert report.echoed.get("Проверить") == "Check"

    _write(root / "Склады.yaml", "ВидЭлемента: Справочник\nИмя: Склады\n")
    _write(root / "Склады.xbsl", "метод Проверить()\n;\n")
    report = translate_project(root, _dictionary(tokens), tmp_path / "en2",
                               swap_localization=False)
    assert "Проверить" not in report.echoed


def test_a_method_the_element_s_own_module_declares_is_not_the_manager_s(
        tmp_path: Path, stated_privileges):
    root = tmp_path / "Acme" / "Demo"
    _privilege_project(root)
    _write(root / "ПравоНаОтчеты.xbsl", "метод Проверить()\n;\n")
    out = tmp_path / "en"
    translate_project(root, _dictionary({**_PRIVILEGE_TOKENS, "Проверить": "Inspect"}), out,
                      swap_localization=False)

    assert "ReportsPrivilege.Inspect()" in (out / "Access.xbsl").read_text(encoding="utf-8")


def test_a_structure_declared_under_the_name_of_a_module_types_none_of_its_names(
        tmp_path: Path):
    """Only what the metadata of the project describes under the module's name - its element,
    its component - puts names in scope of the module; a structure of another module that
    happens to share the name does not."""
    root = tmp_path / "Acme" / "Demo"
    _write(root / "Типы.xbsl", "структура Настройки\n    пер Строки: Массив<Строка>\n;\n")
    _write(root / "Настройки.xbsl", "метод Проба()\n    возврат Строки.Граница()\n;\n")
    out = tmp_path / "en"
    report = translate_project(root, _dictionary({"Проба": "Probe", "Настройки": "Settings",
                                                  "Типы": "Types", "Строки": "Rows"}), out,
                               swap_localization=False)

    assert "Bound" not in (out / "Settings.xbsl").read_text(encoding="utf-8")
    assert "Граница" in report.files["Настройки.xbsl"].missing_platform
