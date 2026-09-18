"""A form built on a component the reference pages have retired.

The platform keeps shipping such a component - a project written for an older compatibility
mode is built on it and the compiler accepts it - while the help leaves a page that states
nothing: a struck-out heading and the name of the replacement. The type catalog then carries
the NAME of the component and not one member of it, and the two rules that ask what a base
gives a form go silent: the receiver analysis of the server-call rules cannot tell an
inherited name from a module, and style/shadow-own-property has no property to shadow.

The extractor now fills those members from the machine description the runtime ships
(extract/stdlib.py, retired_components). What this module pins is the other half - that the
members are what the rules were missing - so it runs the rules over a copy of the data with
the entry and without it.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from xbsl import dataset, engine

pytestmark = pytest.mark.needs_data

#: The component of the batch: retired in compatibility mode 8.0, named by the help, described
#: by the runtime alone. Its properties here are two of the sixteen the description states.
BASE = "ФиксированнаяГруппа"
BASE_PROPERTIES = ["Заголовок", "Ориентация"]


def _data_root(root: Path, *, described: bool) -> Path:
    """A copy of the generated data where the retired component has members, or has none."""
    version = dataset.resolve_version()
    target = root / version
    target.mkdir(parents=True)
    for path in (dataset.data_root() / version).glob("*.json"):
        shutil.copyfile(path, target / path.name)
    stdlib = json.loads((target / "stdlib.json").read_text(encoding="utf-8"))
    stdlib.setdefault("type_members", {}).pop(BASE, None)
    stdlib.setdefault("bases", {}).pop(BASE, None)
    if described:
        stdlib["type_members"][BASE] = {"properties": list(BASE_PROPERTIES)}
        stdlib["bases"][BASE] = ["Группа"]
    (target / "stdlib.json").write_text(json.dumps(stdlib, ensure_ascii=False), encoding="utf-8")
    (root / "index.json").write_text(
        json.dumps({"available": [version], "default": version}), encoding="utf-8")
    return root


@pytest.fixture(scope="module")
def data_roots(tmp_path_factory) -> dict[str, Path]:
    base = tmp_path_factory.mktemp("retired")
    return {"described": _data_root(base / "described", described=True),
            "silent": _data_root(base / "silent", described=False)}


@pytest.fixture()
def described(data_roots):
    dataset.set_data_root(data_roots["described"])
    yield
    dataset.set_data_root(None)


@pytest.fixture()
def undescribed(data_roots):
    dataset.set_data_root(data_roots["silent"])
    yield
    dataset.set_data_root(None)


_PANEL_YAML = (
    "ВидЭлемента: КомпонентИнтерфейса\n"
    "Имя: Панель\n"
    "Наследует:\n"
    f"    Тип: {BASE}\n"
)
_PANEL_MODULE = (
    "@Обработчик\n"
    "метод ПриСоздании()\n"
    "    знч Заголовок = \"x\"\n"
    "    Сообщить(Заголовок)\n"
    ";\n"
)

_CATALOG_YAML = (
    "ВидЭлемента: Справочник\n"
    "Ид: 019ef4c8-232f-7f33-9da6-c36047203001\n"
    "Имя: Значки\n"
)
_CATALOG_MODULE = (
    "@НаСервере @ДоступноСКлиента\n"
    "метод ИконкаПоКоду(Код: Строка): Строка\n"
    "    возврат Код\n"
    ";\n"
)
_FORM_YAML = (
    "ВидЭлемента: КомпонентИнтерфейса\n"
    "Ид: 019ef4c8-232f-7f33-9da6-c36047203002\n"
    "Имя: ФормаСписка\n"
    "Наследует:\n"
    f"    Тип: {BASE}\n"
    "Содержимое:\n"
    "    -\n"
    "        Тип: Картинка\n"
    "        Имя: Логотип\n"
    '        Изображение: =Значки.ИконкаПоКоду("а")\n'
)


def _lint(files: dict[str, str], rule: str):
    sources = [engine.load_text(name, content) for name, content in files.items()]
    return [d for d in engine.run_sources(sources, select={rule}) if d.rule_id == rule]


def test_shadow_own_property_sees_the_members_of_a_retired_base(described):
    found = _lint({"Панель.yaml": _PANEL_YAML, "Панель.xbsl": _PANEL_MODULE},
                  "style/shadow-own-property")

    assert len(found) == 1 and "Заголовок" in found[0].message


def test_shadow_own_property_is_silent_while_the_base_has_no_members(undescribed):
    """The state the data was in: the base is a name with nothing behind it."""
    assert _lint({"Панель.yaml": _PANEL_YAML, "Панель.xbsl": _PANEL_MODULE},
                 "style/shadow-own-property") == []


def test_the_receiver_analysis_sees_a_form_on_a_retired_base(described):
    found = _lint({"Значки.yaml": _CATALOG_YAML, "Значки.xbsl": _CATALOG_MODULE,
                   "ФормаСписка.yaml": _FORM_YAML}, "code/image-binding-server-call")

    assert len(found) == 1 and "Значки.ИконкаПоКоду" in found[0].message


def test_the_receiver_analysis_is_silent_while_the_base_has_no_members(undescribed):
    """An unknown base makes the whole scope of the form unknown, and an unknown scope may
    hide the name the binding calls - so the rule says nothing rather than guess."""
    assert _lint({"Значки.yaml": _CATALOG_YAML, "Значки.xbsl": _CATALOG_MODULE,
                  "ФормаСписка.yaml": _FORM_YAML}, "code/image-binding-server-call") == []
