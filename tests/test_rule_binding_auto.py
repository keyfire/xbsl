"""Checks of the yaml/binding-needs-auto rule (a nullable binding on a plain property).

The rule reads the ui schema (property unions and their nullable flags), so the whole module
is data-dependent - it is listed in conftest._DATA_DEPENDENT and skipped in a public
checkout without the Element data.
"""

from xbsl import engine
from xbsl.cli import discover

_RULE = "yaml/binding-needs-auto"

_CARD_YAML = (
    "ВидЭлемента: КомпонентИнтерфейса\nИмя: Ф\nНаследует:\n"
    "    Тип: СтандартнаяКарточка\n"
    "    Фон: =ФонКарточки()\n"
)


def _run(tmp_path, yaml_text, module_text, name="Ф"):
    (tmp_path / (name + ".yaml")).write_text(yaml_text, encoding="utf-8")
    (tmp_path / (name + ".xbsl")).write_text(module_text, encoding="utf-8")
    return engine.run(discover([str(tmp_path)]), select={_RULE})


def _has(diags):
    return any(d.rule_id == _RULE for d in diags)


def test_nullable_binding_flagged(tmp_path):
    d = _run(
        tmp_path, _CARD_YAML,
        "метод ФонКарточки(): Цвет?\n    возврат Неопределено\n;\n",
    )
    assert len(d) == 1 and d[0].rule_id == _RULE
    assert d[0].severity.name == "WARNING"
    assert "Авто|Цвет" in d[0].message and "ФонКарточки" in d[0].message
    # the position points at the binding value
    assert (d[0].line, d[0].col) == (5, 10)


def test_auto_union_return_not_flagged(tmp_path):
    d = _run(
        tmp_path, _CARD_YAML,
        "метод ФонКарточки(): Авто|Цвет\n    возврат Авто\n;\n",
    )
    assert not _has(d)


def test_plain_return_not_flagged(tmp_path):
    d = _run(
        tmp_path, _CARD_YAML,
        "метод ФонКарточки(): Цвет\n    возврат Цвет.Красный\n;\n",
    )
    assert not _has(d)


def test_nullable_property_not_flagged(tmp_path):
    # `Изображение` carries the nullable flag in the schema - the empty value is legal there
    d = _run(
        tmp_path,
        "ВидЭлемента: КомпонентИнтерфейса\nИмя: Ф\nНаследует:\n"
        "    Тип: СтандартнаяКарточка\n"
        "    Изображение: =Картинка()\n",
        "метод Картинка(): Url?\n    возврат Неопределено\n;\n",
    )
    assert not _has(d)


def test_generic_argument_nullable_not_flagged(tmp_path):
    # `?` inside a generic argument is not a nullable return (a live corpus case)
    d = _run(
        tmp_path,
        "ВидЭлемента: КомпонентИнтерфейса\nИмя: Ф\nНаследует:\n"
        "    Тип: ВыборЗначения<Булево?>\n"
        "    СписокВыбора: =Список()\n",
        "метод Список(): Массив<Булево?|ЭлементСпискаЗначений<Булево?>>\n    возврат []\n;\n",
    )
    assert not _has(d)


def test_call_with_arguments_not_judged(tmp_path):
    d = _run(
        tmp_path,
        "ВидЭлемента: КомпонентИнтерфейса\nИмя: Ф\nНаследует:\n"
        "    Тип: СтандартнаяКарточка\n"
        "    Фон: =ФонКарточки(Истина)\n",
        "метод ФонКарточки(Наведена: Булево): Цвет?\n    возврат Неопределено\n;\n",
    )
    assert not _has(d)


def test_cross_module_call_not_judged(tmp_path):
    d = _run(
        tmp_path,
        "ВидЭлемента: КомпонентИнтерфейса\nИмя: Ф\nНаследует:\n"
        "    Тип: СтандартнаяКарточка\n"
        "    Фон: =Стиль.Фон()\n",
        "метод Другой(): Цвет?\n    возврат Неопределено\n;\n",
    )
    assert not _has(d)


def test_method_of_other_component_not_joined(tmp_path):
    # the binding joins the PAIRED module only - a namesake elsewhere is not it
    (tmp_path / "Ф.yaml").write_text(_CARD_YAML, encoding="utf-8")
    (tmp_path / "Чужой.xbsl").write_text(
        "метод ФонКарточки(): Цвет?\n    возврат Неопределено\n;\n", encoding="utf-8",
    )
    d = engine.run(discover([str(tmp_path)]), select={_RULE})
    assert not _has(d)


def test_project_component_not_judged(tmp_path):
    # a project component's own properties are outside the palette schema
    d = _run(
        tmp_path,
        "ВидЭлемента: КомпонентИнтерфейса\nИмя: Ф\nНаследует:\n"
        "    Тип: МояКарточка\n"
        "    Фон: =ФонКарточки()\n",
        "метод ФонКарточки(): Цвет?\n    возврат Неопределено\n;\n",
    )
    assert not _has(d)
