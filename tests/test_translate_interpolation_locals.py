"""Names inside a string interpolation read the way the code around the string reads them.

An interpolation is re-tokenized apart from its module, and it used to know nothing of the
method it stands in. A local named like a platform type then read as a static call on the type,
the platform pair came before the project dictionary, and the declaration and the read went out
under two different words: `val Inscription = ...` and `"%{Label.Length()}"`. The variable was
left unread and the call named a member the type does not have. The fragment is now handed what
the walk over the module knows at that place: the declared names and their types, the method
whose name qualifies an entry, and the names the element of the module puts in scope.

The same shortcut misread a property of the module's own element in the code itself: the
attribute of a record in its object module, the property of an interface component in its
module. There the owner decides, as the compiler does: a static method has no instance, and a
method a component compiles on the server alone sees its contextual properties only.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from xbsl import engine
from xbsl.translation import dictionary as dict_module
from xbsl.translation import names
from xbsl.translation.code import Resolver, translate_code
from xbsl.translation.project import translate_project
from xbsl.translation.reporting import FileReport


def _dictionary(tokens: dict, literals: dict | None = None) -> dict_module.Dictionary:
    return dict_module.Dictionary(tokens=dict(tokens), phrases={}, literals=dict(literals or {}))


def _code(text: str, tokens: dict, literals: dict | None = None) -> tuple[str, FileReport]:
    source = engine.load_text("Склады.xbsl", text)
    report = FileReport(path="Склады.xbsl")
    return translate_code(source, Resolver(_dictionary(tokens, literals)), report), report


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


_TOKENS = {"Подпись": "Caption", "Надпись": "Inscription", "Размер": "Size", "Список": "Items",
           "Итог": "Total"}


# --- the names a method declares ------------------------------------------------------------


_LENGTH = "Inscription.Length()"


@pytest.mark.parametrize("text, read", [
    pytest.param(
        "метод Подпись(): Строка\n"
        '    знч Надпись = "метка"\n'
        "    знч Размер = Надпись.Длина()\n"
        '    возврат "%{Надпись.Длина()}"\n'
        ";\n", _LENGTH, id="local"),
    pytest.param(
        "метод Подпись(Надпись: Строка): Строка\n"
        "    знч Размер = Надпись.Длина()\n"
        '    возврат "%{Надпись.Длина()}"\n'
        ";\n", _LENGTH, id="parameter"),
    pytest.param(
        "метод Подпись(Список: Массив<Строка>): Строка\n"
        '    пер Итог = ""\n'
        "    для Надпись из Список\n"
        "        знч Размер = Надпись.Длина()\n"
        '        Итог = "%{Надпись.Длина()}"\n'
        "    ;\n"
        "    возврат Итог\n"
        ";\n", _LENGTH, id="loop-variable"),
    pytest.param(
        "метод Подпись(Список: Массив<Строка>): Строка\n"
        "    знч Размер = Список.Фильтровать(Надпись -> Надпись.Длина() > 0).Размер()\n"
        '    возврат Список.Преобразовать(Надпись -> "%{Надпись.Длина()}").Первый()\n'
        ";\n", _LENGTH, id="lambda-parameter"),
    pytest.param(
        "метод Подпись(Список: Массив<Строка>): Строка\n"
        "    знч Размер = Список.Фильтровать((Надпись: Строка) -> Надпись.Длина() > 0).Размер()\n"
        '    возврат Список.Преобразовать((Итог, Надпись) -> "%{Надпись.Длина()}").Первый()\n'
        ";\n", _LENGTH, id="parenthesized-lambda-parameters"),
    pytest.param(
        "метод Подпись(): Строка\n"
        "    попытка\n"
        '        возврат ""\n'
        "    поймать Надпись: Исключение\n"
        "        знч Размер = Надпись.Описание\n"
        '        возврат "%{Надпись.Описание}"\n'
        "    ;\n"
        ";\n", "Inscription.Description", id="catch-variable"),
])
def test_a_name_declared_like_a_platform_type_reads_as_declared_inside_an_interpolation(
        text, read):
    """Read in the code first and in the string after it: both take the declared name."""
    out, _report = _code(text, _TOKENS)
    assert read in out.split('"%{', 1)[0], "the code reads the declared name"
    assert f'"%{{{read}}}"' in out
    assert "Label" not in out


def test_a_string_inside_an_interpolation_reads_the_same_local():
    out, _report = _code(
        "метод Подпись(): Строка\n"
        '    знч Надпись = "метка"\n'
        '    возврат "%{"<%{Надпись.Длина()}>"}"\n'
        ";\n",
        _TOKENS,
    )
    assert '"%{"<%{Inscription.Length()}>"}"' in out


def test_an_entry_written_for_the_method_answers_inside_both_interpolation_forms():
    """`Подпись.Надпись` speaks about the local of that one method, in code and in its strings."""
    out, report = _code(
        "метод Подпись(): Строка\n"
        '    знч Надпись = "метка"\n'
        "    знч Размер = Надпись.Длина()\n"
        '    возврат "%{Надпись} %Надпись"\n'
        ";\n",
        {**_TOKENS, "Подпись.Надпись": "Mark"},
    )
    assert "val Mark = " in out and "val Size = Mark.Length()" in out
    assert '"%{Mark} %Mark"' in out
    assert not report.missing_tokens


def test_the_method_scope_ends_with_the_method():
    """A local of one method does not hide the platform type in the next one."""
    out, _report = _code(
        "метод Подпись(): Строка\n"
        '    знч ДатаВремя = "метка"\n'
        '    возврат "%{ДатаВремя.Длина()}"\n'
        ";\n"
        "\n"
        "метод Размер(): Строка\n"
        '    возврат "%{ДатаВремя.Сейчас()}"\n'
        ";\n",
        {**_TOKENS, "ДатаВремя": "Moment"},
    )
    assert '"%{Moment.Length()}"' in out
    assert '"%{DateTime.Now()}"' in out


def test_a_method_of_the_module_reads_the_same_inside_an_interpolation():
    out, _report = _code(
        "метод Надпись(): Строка\n"
        '    возврат "метка"\n'
        ";\n"
        "\n"
        "метод Подпись(): Строка\n"
        "    знч Размер = Надпись().Длина()\n"
        '    возврат "%{Надпись().Длина()}"\n'
        ";\n",
        _TOKENS,
    )
    assert "val Size = Inscription().Length()" in out
    assert '"%{Inscription().Length()}"' in out


# --- a named literal ------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["Length: %{Надпись.Длина()}", "Length: %{Inscription.Length()}"])
def test_a_named_literal_reads_its_substitutions_in_the_method_it_stands_in(value):
    """Both the entry and its key are read in the method: an entry spelling the substitution in
    English matches the key, and a Russian one is translated into the same words."""
    out, report = _code(
        "метод Подпись(): Строка\n"
        '    знч Надпись = "метка"\n'
        '    возврат "Длина: %{Надпись.Длина()}"\n'
        ";\n",
        _TOKENS,
        literals={"Длина: %{Надпись.Длина()}": value},
    )
    assert '"Length: %{Inscription.Length()}"' in out
    assert report.placeholder_mismatches == []


def test_a_name_declared_twice_is_typed_by_the_block_of_the_string():
    """A map in the first block, a platform object with another spelling of the member in the
    second: each interpolation follows its own block - the named literal too, whose text holds
    no offsets of the module at all."""
    out, _report = _code(
        "метод Очистить(Данные: Объект, Признак: Булево, Ключ: Строка): Строка\n"
        "    если Признак\n"
        "        знч Элемент = Данные как Соответствие<Строка, Число>\n"
        '        возврат "Удалено: %{Элемент.Удалить(Ключ)}"\n'
        "    иначе\n"
        "        знч Элемент = Данные как Файлы\n"
        '        возврат "%{Элемент.Удалить(Ключ)}"\n'
        "    ;\n"
        ";\n",
        {"Очистить": "Clear", "Данные": "Data", "Признак": "Flag", "Ключ": "Key",
         "Элемент": "Item"},
        literals={"Удалено: %{Элемент.Удалить(Ключ)}": "Removed: %{Элемент.Удалить(Ключ)}"},
    )
    assert 'return "Removed: %{Item.Remove(Key)}"' in out
    assert 'return "%{Item.Delete(Key)}"' in out


# --- the names the element of the module puts in scope --------------------------------------


_CATALOG = (
    "ВидЭлемента: Справочник\n"
    "Ид: 1d1f5c60-0000-4000-8000-000000000e01\n"
    "Имя: Склады\n"
    "ОбластьВидимости: ВПроекте\n"
    "Реквизиты:\n"
    "    -\n"
    "        Ид: 1d1f5c60-0000-4000-8000-000000000e02\n"
    "        Имя: Надпись\n"
    "        Тип: Строка\n"
    "    -\n"
    "        Ид: 1d1f5c60-0000-4000-8000-000000000e03\n"
    "        Имя: ДатаВремя\n"
    "        Тип: Строка\n"
)


@pytest.mark.parametrize("tokens, spelled", [
    pytest.param({"Склады": "Warehouses", "Подпись": "Caption", "Размер": "Size",
                  "Надпись": "Inscription"}, "Inscription", id="with-an-entry"),
    pytest.param({"Склады": "Warehouses", "Подпись": "Caption", "Размер": "Size"}, "Надпись",
                 id="without-an-entry"),
])
def test_an_attribute_named_like_a_platform_type_is_the_attribute_in_its_object_module(
        tmp_path: Path, tokens, spelled):
    """With an entry the attribute moves together with its declaration; without one it stays
    Russian in both places and is reported, instead of turning into the type."""
    root = tmp_path / "ru"
    _write(root / "Склады.yaml", _CATALOG)
    _write(root / "Склады.Объект.xbsl", (
        "метод Подпись(): Строка\n"
        "    знч Размер = Надпись.Длина()\n"
        '    возврат "%{Надпись.Длина()}"\n'
        ";\n"
    ))
    out = tmp_path / "en"
    report = translate_project(root, _dictionary(tokens), out)
    module = (out / "Warehouses.Object.xbsl").read_text(encoding="utf-8")
    assert f"val Size = {spelled}.Length()" in module
    assert f'"%{{{spelled}.Length()}}"' in module
    assert f"Name: {spelled}" in (out / "Warehouses.yaml").read_text(encoding="utf-8")
    if spelled == "Надпись":
        assert "Надпись" in report.files["Склады.Объект.xbsl"].missing_tokens


def test_the_manager_module_of_a_catalog_keeps_the_platform_type(tmp_path: Path):
    """The module of the catalog itself works on no record: an attribute spelled like a type is
    not in scope there, and a static call of the type stays the type's."""
    root = tmp_path / "ru"
    _write(root / "Склады.yaml", _CATALOG)
    _write(root / "Склады.xbsl", (
        "метод Подпись(): Строка\n"
        '    возврат "%{ДатаВремя.Сейчас()}" + ДатаВремя.Сейчас()\n'
        ";\n"
    ))
    out = tmp_path / "en"
    translate_project(root, _dictionary({"Склады": "Warehouses", "Подпись": "Caption",
                                         "ДатаВремя": "Moment"}), out)
    module = (out / "Warehouses.xbsl").read_text(encoding="utf-8")
    assert 'return "%{DateTime.Now()}" + DateTime.Now()' in module


_COMPONENT = (
    "ВидЭлемента: КомпонентИнтерфейса\n"
    "Ид: 1d1f5c60-0000-4000-8000-000000000e04\n"
    "Имя: КарточкаСклада\n"
    "ОбластьВидимости: ВПроекте\n"
    "Наследует:\n"
    "    Тип: Группа\n"
    "Свойства:\n"
    "    -\n"
    "        Имя: ДатаВремя\n"
    "        Тип: Строка\n"
    "    -\n"
    "        Имя: Надпись\n"
    "        Тип: Строка\n"
    "        Контекстное: Истина\n"
)


def test_a_component_property_is_the_property_where_the_method_sees_it(tmp_path: Path):
    """A client method sees every property; a static one none, and the platform type keeps its
    static call; a server method sees the contextual property alone."""
    root = tmp_path / "ru"
    _write(root / "КарточкаСклада.yaml", _COMPONENT)
    _write(root / "КарточкаСклада.xbsl", (
        "метод Клиентский(): Строка\n"
        "    знч Размер = ДатаВремя.Длина()\n"
        '    возврат "%{ДатаВремя.Длина()} %{Надпись.Длина()}"\n'
        ";\n"
        "\n"
        "статический метод Общий(): Строка\n"
        '    возврат "%{ДатаВремя.Сейчас()}" + ДатаВремя.Сейчас()\n'
        ";\n"
        "\n"
        "@НаСервере\n"
        "метод Серверный(): Строка\n"
        '    возврат "%{ДатаВремя.Сейчас()} %{Надпись.Длина()}"\n'
        ";\n"
    ))
    out = tmp_path / "en"
    translate_project(root, _dictionary({
        "КарточкаСклада": "WarehouseCard", "Клиентский": "OnClientSide", "Общий": "Shared",
        "Серверный": "OnServerSide", "Размер": "Size", "ДатаВремя": "Moment",
        "Надпись": "Inscription",
    }), out)
    module = (out / "WarehouseCard.xbsl").read_text(encoding="utf-8")
    assert "val Size = Moment.Length()" in module
    assert 'return "%{Moment.Length()} %{Inscription.Length()}"' in module
    assert 'return "%{DateTime.Now()}" + DateTime.Now()' in module
    assert 'return "%{DateTime.Now()} %{Inscription.Length()}"' in module


# --- the owner of a module ------------------------------------------------------------------


def test_the_owner_of_a_module_is_read_off_the_yaml_it_pairs_with(tmp_path: Path):
    _write(tmp_path / "Склады.yaml", _CATALOG)
    _write(tmp_path / "КарточкаСклада.yaml", _COMPONENT)
    _write(tmp_path / "КурсВалюты.yaml", (
        "ВидЭлемента: Структура\n"
        "Ид: 1d1f5c60-0000-4000-8000-000000000e05\n"
        "Имя: КурсВалюты\n"
        "Поля:\n"
        "    -\n"
        "        Имя: Список\n"
        "        Тип: Строка\n"
    ))
    record = {"Надпись", "ДатаВремя"}
    assert names.module_owner(tmp_path / "Склады.Объект.xbsl", engine.load).names == record
    assert names.module_owner(tmp_path / "Склады.Object.xbsl", engine.load).names == record
    assert names.module_owner(tmp_path / "Склады.xbsl", engine.load) == names.ModuleOwner()
    component = names.module_owner(tmp_path / "КарточкаСклада.xbsl", engine.load)
    assert component.names == {"ДатаВремя", "Надпись"}
    assert component.visible(static=False, server_only=True) == {"Надпись"}
    assert component.visible(static=True, server_only=False) == frozenset()
    assert names.module_owner(tmp_path / "КурсВалюты.xbsl", engine.load).names == {"Список"}
    assert names.module_owner(tmp_path / "Партии.xbsl", engine.load) == names.ModuleOwner()
