"""code/undefined-name in an object module: what the KIND gives against what the ELEMENT has.

The members of `<вид>.Объект` come from a template page of the help, and that page describes
ONE example element - everything switched on in the example reads as the contract of the whole
kind. Five names of four kinds are not: `Parent` reaches a hierarchical catalog only,
`DeletionMarkInstant` and `DeletionMark` an element whose deletion mode is `DeletionMark`,
`Grant`/`Revoke` an access key granted by hand and `Recompute` a computed one. Taking them for
the whole kind keeps the rule quiet where the compiler refuses: the default of `IsHierarchical`
is `False`, so most catalogs would be covered, and of the two access-key flavours one is always
wrong.

Each name is checked twice - the setting on and the setting off - and the module also uses a
name the platform gives under no setting at all, so a scope that simply went blind would fail.

The scope of an object module that does not depend on a setting is in
test_rule_undefined_name_bilingual.py. That a method of the object type answers only to a call
is checked here too, in a section of its own.
"""

import pytest

from xbsl import dataset, engine
from xbsl.rules import undefined_names

pytestmark = pytest.mark.needs_data

_RULE = "code/undefined-name"

#: What the extractor reads off the template pages, trimmed to the names under test.
_GENERATED = {
    "Справочник.Объект": {
        "properties": ["МоментПометкиУдаления", "ПометкаУдаления", "Представление", "Родитель",
                       "Ссылка"],
        "methods": ["Записать", "Представление", "СоздатьКопию", "ЭтоНовый"],
    },
    "Документ.Объект": {
        "properties": ["МоментПометкиУдаления", "ПометкаУдаления", "Ссылка"],
        "methods": ["Записать", "ЭтоНовый"],
    },
    "ПланОбмена.Объект": {
        "properties": ["МоментПометкиУдаления", "ПометкаУдаления", "Ссылка"],
        "methods": ["Записать", "ЭтоНовый"],
    },
    "КлючДоступа.Объект": {
        "properties": ["Хеш"],
        "methods": ["Выдать", "Отозвать", "Пересчитать"],
    },
}


@pytest.fixture(autouse=True)
def _catalog(monkeypatch):
    """The shipped catalog with `generated_members` set to the fixture above.

    The section reaches the shipped data only when the extractor is run again, and these tests
    are about what the RULE does with it either way.
    """
    real = dataset.load_json

    def load(name, version=None):
        catalog = real(name, version) if version is not None else real(name)
        if name != "stdlib.json":
            return catalog
        return {**catalog, "generated_members": _GENERATED}

    monkeypatch.setattr(undefined_names.dataset, "load_json", load)


def _yaml(kind: str, name: str, uid: str, *settings: str) -> str:
    lines = [f"ВидЭлемента: {kind}", f"Ид: {uid}", f"Имя: {name}",
             "ОбластьВидимости: ВПроекте", *settings]
    return "\n".join(lines) + "\n"


def _found(files: dict[str, str]) -> list:
    sources = [engine.load_text(n, text) for n, text in files.items()]
    return [d for d in engine.run_sources(sources) if d.rule_id == _RULE]


def _names(files: dict[str, str]) -> list[str]:
    return sorted(d.message.split("'")[1] for d in _found(files))


def _module(*reads: str) -> str:
    """An object module reading the given names, one per line, plus a name nothing gives."""
    body = "".join(f"    знч Прочитано{n} = {name}\n" for n, name in enumerate(reads))
    return "метод Проверить()\n" + body + "    знч Контроль = НетТакогоИмени\n;\n"


def _calling(*calls: str) -> str:
    """An object module calling the given methods, plus a name nothing gives.

    A method of the object type answers only to a call: read as a value it is not a name of
    the module at all (the probe got "Variable ... is not defined" for `Write` and `IsNew`).
    """
    body = "".join(f"    {name}()\n" for name in calls)
    return "метод Проверить()\n" + body + "    знч Контроль = НетТакогоИмени\n;\n"


# --- `Parent`: a hierarchical catalog only -------------------------------------------------

def test_a_hierarchical_catalog_knows_its_parent():
    files = {"Разделы.yaml": _yaml("Справочник", "Разделы", "a1000000-0000-4000-8000-000000000001",
                                   "Иерархический: Истина"),
             "Разделы.Объект.xbsl": _module("Родитель")}
    assert _names(files) == ["НетТакогоИмени"]


def test_a_plain_catalog_does_not():
    """`IsHierarchical` defaults to `False`, so this is the shape of most catalogs."""
    files = {"Разделы.yaml": _yaml("Справочник", "Разделы", "a1000000-0000-4000-8000-000000000002"),
             "Разделы.Объект.xbsl": _module("Родитель")}
    assert _names(files) == ["НетТакогоИмени", "Родитель"]


# --- `DeletionMark` / `DeletionMarkInstant`: the deletion mode of the element ---------------

@pytest.mark.parametrize("kind, name", [("Справочник", "Метки"), ("Документ", "Отгрузки"),
                                        ("ПланОбмена", "Узлы")])
def test_an_element_that_is_only_marked_knows_the_mark(kind, name):
    """`DeletionMark` is the default of the mode, so the yaml need not mention it."""
    files = {f"{name}.yaml": _yaml(kind, name, "a1000000-0000-4000-8000-000000000003"),
             f"{name}.Объект.xbsl": _module("ПометкаУдаления", "МоментПометкиУдаления")}
    assert _names(files) == ["НетТакогоИмени"]


@pytest.mark.parametrize("kind, name", [("Справочник", "Метки"), ("Документ", "Отгрузки"),
                                        ("ПланОбмена", "Узлы")])
def test_an_element_deleted_outright_has_no_mark(kind, name):
    """Deleted outright, the record is gone and there is nothing left to carry a mark.

    Of both fields the xbql pages of the three kinds say the same:
    "присутствует только у ... с режимом удаления ПометкаУдаления".
    """
    files = {f"{name}.yaml": _yaml(kind, name, "a1000000-0000-4000-8000-000000000004",
                                   "РежимУдаления: Немедленно"),
             f"{name}.Объект.xbsl": _module("ПометкаУдаления", "МоментПометкиУдаления")}
    assert _names(files) == ["МоментПометкиУдаления", "НетТакогоИмени", "ПометкаУдаления"]


def test_the_attributes_of_the_element_win_over_the_gate():
    """A field the yaml declares itself exists whatever the settings say - the gate withholds
    what the KIND gives, not what the author wrote."""
    yaml = _yaml("Справочник", "Метки", "a1000000-0000-4000-8000-000000000005",
                 "РежимУдаления: Немедленно",
                 "Реквизиты:", "    -", "        Ид: a1000000-0000-4000-8000-000000000006",
                 "        Имя: ПометкаУдаления", "        Тип: Булево")
    files = {"Метки.yaml": yaml, "Метки.Объект.xbsl": _module("ПометкаУдаления")}
    assert _names(files) == ["НетТакогоИмени"]


# --- the two flavours of an access key ------------------------------------------------------

def test_a_key_granted_by_hand_grants_and_revokes():
    files = {"Ключи.yaml": _yaml("КлючДоступа", "Ключи", "a1000000-0000-4000-8000-000000000007",
                                 "РучнаяВыдача: Истина"),
             "Ключи.Объект.xbsl": _calling("Выдать", "Отозвать")}
    assert _names(files) == ["НетТакогоИмени"]


def test_a_key_granted_by_hand_does_not_recompute():
    files = {"Ключи.yaml": _yaml("КлючДоступа", "Ключи", "a1000000-0000-4000-8000-000000000008",
                                 "РучнаяВыдача: Истина"),
             "Ключи.Объект.xbsl": _calling("Пересчитать")}
    assert _names(files) == ["НетТакогоИмени", "Пересчитать"]


def test_a_computed_key_recomputes():
    """`ManualGrant` defaults to `False` - a key that says nothing is the computed flavour."""
    files = {"Ключи.yaml": _yaml("КлючДоступа", "Ключи", "a1000000-0000-4000-8000-000000000009"),
             "Ключи.Объект.xbsl": _calling("Пересчитать")}
    assert _names(files) == ["НетТакогоИмени"]


def test_a_computed_key_neither_grants_nor_revokes():
    files = {"Ключи.yaml": _yaml("КлючДоступа", "Ключи", "a1000000-0000-4000-8000-00000000000a"),
             "Ключи.Объект.xbsl": _calling("Выдать", "Отозвать")}
    assert _names(files) == ["Выдать", "НетТакогоИмени", "Отозвать"]


# --- the gate reaches an English project too ------------------------------------------------

def test_the_gate_reads_the_english_spelling_of_the_setting():
    """An English project writes `DeletionMode: Immediately`; read as "nothing declared", the
    element would keep the default and the mark would stay in scope."""
    yaml = ("ElementKind: Catalog\nId: a1000000-0000-4000-8000-00000000000b\nName: Tags\n"
            "VisibilityScope: InProject\nDeletionMode: Immediately\n")
    module = "method Check()\n    var Read = DeletionMark\n    var Control = NoSuchName\n;\n"
    files = {"Tags.yaml": yaml, "Tags.Object.xbsl": module}
    assert _names(files) == ["DeletionMark", "NoSuchName"]


# --- a kind with no such setting is not judged ----------------------------------------------

def test_a_kind_without_the_setting_keeps_the_name():
    """A settings storage has no deletion mode at all. Nothing to judge by, so the fallback
    table answers as it did - the gate withholds only on a settled `no`."""
    files = {"Настройки.yaml": _yaml("ХранилищеНастроек", "Настройки",
                                     "a1000000-0000-4000-8000-00000000000c"),
             "Настройки.Объект.xbsl": _module("ПометкаУдаления")}
    assert _names(files) == ["НетТакогоИмени"]


# --- a method of the object type answers only to a call -------------------------------------
#
# A probe on a stand read `Write`, `Delete`, `IsNew` and `CreateCopy` as values in the object
# module of a catalog and got "Variable ... is not defined" for each, while `Write()` compiled
# and `Reference`, `DeletionMark` and `Presentation` were read bare - the compiler looks a bare
# name up among the values, and a method is not one.

_CATALOG = _yaml("Справочник", "Метки", "a1000000-0000-4000-8000-00000000000d")


def test_a_bare_method_of_the_object_type_is_reported_with_the_call_to_write():
    found = _found({"Метки.yaml": _CATALOG,
                    "Метки.Объект.xbsl": _module("Записать", "ЭтоНовый", "СоздатьКопию")})
    by_name = {d.message.split("'")[1]: d.message for d in found}
    assert sorted(by_name) == ["Записать", "НетТакогоИмени", "СоздатьКопию", "ЭтоНовый"]
    assert "'Записать()'" in by_name["Записать"] and "'ЭтоНовый()'" in by_name["ЭтоНовый"]


def test_the_same_methods_called_and_the_properties_read_bare_are_clean():
    # The control of the test above: the same names with the parentheses.
    assert _names({"Метки.yaml": _CATALOG,
                   "Метки.Объект.xbsl": _calling("Записать", "ЭтоНовый", "СоздатьКопию")}) == [
        "НетТакогоИмени"]
    assert _names({"Метки.yaml": _CATALOG,
                   "Метки.Объект.xbsl": _module("Ссылка", "ПометкаУдаления")}) == [
        "НетТакогоИмени"]


def test_a_name_the_type_has_both_ways_stays_a_value():
    # `Presentation` is a property of the object type and a method at once: read bare, it
    # compiled.
    assert _names({"Метки.yaml": _CATALOG,
                   "Метки.Объект.xbsl": _module("Представление")}) == ["НетТакогоИмени"]


def test_the_fallback_table_calls_write_and_delete():
    """A kind the generated members say nothing about gets the fallback table, split the same
    way: `Reference` and `DeletionMark` are read, `Write` and `Delete` are called."""
    files = {"Настройки.yaml": _yaml("ХранилищеНастроек", "Настройки",
                                     "a1000000-0000-4000-8000-00000000000e")}
    files["Настройки.Объект.xbsl"] = _module("Ссылка", "Записать", "Удалить")
    assert _names(files) == ["Записать", "НетТакогоИмени", "Удалить"]
    files["Настройки.Объект.xbsl"] = _calling("Записать", "Удалить")
    assert _names(files) == ["НетТакогоИмени"]


def test_an_english_object_module_gets_the_same_split():
    yaml = ("ElementKind: Catalog\nId: a1000000-0000-4000-8000-00000000000f\nName: Tags\n"
            "VisibilityScope: InProject\n")
    module = ("method Check()\n    var Read = Write\n    Write()\n    var Link = Reference\n"
              "    var Control = NoSuchName\n;\n")
    assert _names({"Tags.yaml": yaml, "Tags.Object.xbsl": module}) == ["NoSuchName", "Write"]


# --- the same two flavours in the MANAGER module --------------------------------------------
#
# `<Имя>.xbsl` of an access key is its manager module, and its bare names come from
# manager_members of the kind - merged from the two flavour templates just as the object
# members were. A probe on a stand measured all four corners: the compiler answers
# `Unknown method` to the manager method of the other flavour.

def _manager(*calls: str) -> str:
    body = "".join(f"    {call}()\n" for call in calls)
    return "метод Проверить()\n" + body + "    знч Контроль = НетТакогоИмени\n;\n"


def test_a_key_granted_by_hand_revokes_its_keys():
    files = {"Ключи.yaml": _yaml("КлючДоступа", "Ключи", "a1000000-0000-4000-8000-00000000000d",
                                 "РучнаяВыдача: Истина"),
             "Ключи.xbsl": _manager("ОтозватьКлючи")}
    assert _names(files) == ["НетТакогоИмени"]


def test_a_key_granted_by_hand_does_not_recompute_its_keys():
    files = {"Ключи.yaml": _yaml("КлючДоступа", "Ключи", "a1000000-0000-4000-8000-00000000000e",
                                 "РучнаяВыдача: Истина"),
             "Ключи.xbsl": _manager("ПересчитатьКлючи")}
    assert _names(files) == ["НетТакогоИмени", "ПересчитатьКлючи"]


def test_a_computed_key_recomputes_its_keys():
    files = {"Ключи.yaml": _yaml("КлючДоступа", "Ключи", "a1000000-0000-4000-8000-00000000000f",
                                 "РучнаяВыдача: Ложь"),
             "Ключи.xbsl": _manager("ПересчитатьКлючи")}
    assert _names(files) == ["НетТакогоИмени"]


def test_a_computed_key_does_not_revoke_its_keys():
    files = {"Ключи.yaml": _yaml("КлючДоступа", "Ключи", "a1000000-0000-4000-8000-000000000010",
                                 "РучнаяВыдача: Ложь"),
             "Ключи.xbsl": _manager("ОтозватьКлючи")}
    assert _names(files) == ["НетТакогоИмени", "ОтозватьКлючи"]


def test_the_manager_of_another_kind_keeps_its_own_recompute():
    """A privilege recomputes too, by a name of its own, and has no such setting - the gate
    must not reach it because a row of the table happens to speak about recomputing."""
    files = {"Права.yaml": _yaml("ПравоНаДействие", "Права",
                                 "a1000000-0000-4000-8000-000000000011"),
             "Права.xbsl": _manager("ПересчитатьПрава")}
    assert _names(files) == ["НетТакогоИмени"]
