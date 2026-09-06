"""The reference member, the qualified enumeration default and the automatic size.

Three gaps the parity seeds (tools/parity_seed.py) found in the translator, each pinned by
a hand-written English twin the platform dictionaries spell:

- `.Ссылка` after a variable is the REFERENCE of the record when the variable holds a facet
  of a project object, and the property `Link` of a label, a picture or an open-by-link
  event otherwise - the flat compiler dictionary answered `Link` for both;
- a default qualified by its own enumeration (`Дежурства.Черновик`) kept both halves Russian
  next to an enumeration the tree had already renamed;
- `Auto` on a property typed by a union (`Авто|Число`) is a type of the schema, not data.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from xbsl import engine
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
