"""Rules that judge a NAME by a Russian table: the same name in English has to be judged too.

1C:Element is bilingual all the way into the identifiers: a catalog is `Users` in one project
and its Russian spelling in the other, a generated type is `PermissionsComputeData`, a member is
`Visible`. The tables a rule judges by are extracted from the distribution and keyed by the
Russian spelling alone, so a project written in English is measured against a vocabulary that
does not contain it: what the compiler accepts comes back as a finding. Every check below is a
pair - the Russian project, where the rule was already right, next to the English one - plus the
negative controls that keep the wider reading from turning into a blind one.

Everything is linted from memory (engine.load_text) on a demo project of its own: an Applications
catalog, a FeatureImagePosition enumeration, a Users query and a card module.
"""

import pytest

from xbsl import engine
import xbsl.rules  # noqa: F401 - registers every rule

pytestmark = pytest.mark.needs_data


def _lint(files: dict[str, str], rule: str) -> list:
    sources = [engine.load_text(name, text) for name, text in files.items()]
    return [d for d in engine.run_sources(sources, select={rule}) if d.rule_id == rule]


# --- code/unknown-object-type: the derived types an object generates -----------------------

_RULE_OBJECT_TYPE = "code/unknown-object-type"

_CATALOG_RU = """\
ВидЭлемента: Справочник
Ид: 1d1f5c60-0000-4000-8000-0000000000a1
Имя: Заявки
ОбластьВидимости: ВПроекте
"""
_CATALOG_EN = """\
ElementKind: Catalog
Id: 1d1f5c60-0000-4000-8000-0000000000a1
Name: Applications
VisibilityScope: InProject
"""


def test_derived_type_of_a_russian_object():
    files = {
        "Заявки.yaml": _CATALOG_RU,
        "Заявки.xbsl": "метод Проба(Данные: Заявки.ДанныеРасчетаРазрешений)\n;\n",
    }
    assert _lint(files, _RULE_OBJECT_TYPE) == []


def test_derived_type_of_an_english_object():
    """The regression: the catalog of generated types is Russian, the source is English."""
    files = {
        "Applications.yaml": _CATALOG_EN,
        "Applications.xbsl": "method Probe(Data: Applications.PermissionsComputeData)\n;\n",
    }
    found = _lint(files, _RULE_OBJECT_TYPE)
    assert found == [], [d.message for d in found]


def test_unknown_derived_type_of_an_english_object_is_still_flagged():
    files = {
        "Applications.yaml": _CATALOG_EN,
        "Applications.xbsl": "method Probe(Data: Applications.PermissionsComputeFudge)\n;\n",
    }
    found = _lint(files, _RULE_OBJECT_TYPE)
    assert len(found) == 1 and "PermissionsComputeFudge" in found[0].message


_EXCHANGE_RU = """\
ВидЭлемента: ПланОбмена
Ид: 1d1f5c60-0000-4000-8000-0000000000c1
Имя: Обмены
ОбластьВидимости: ВПроекте
"""
_EXCHANGE_EN = """\
ElementKind: ExchangePlan
Id: 1d1f5c60-0000-4000-8000-0000000000c1
Name: Exchanges
VisibilityScope: InProject
"""


def test_a_derived_type_of_another_kind_is_flagged_in_both_spellings():
    """The two spellings are twins: a catalog does not generate what an exchange plan does.

    The regression this locks down: the English half of the family was collected as ONE union
    over every kind of the catalog, while the Russian half stayed per-kind - so the English
    spelling of a foreign kind's type passed where the Russian one was reported, and the English
    tree forgave what the Russian one forbade.
    """
    russian = _lint({
        "Заявки.yaml": _CATALOG_RU,
        "Заявки.xbsl": "метод Проба(Схема: Заявки.СхемаДанных)\n;\n",
    }, _RULE_OBJECT_TYPE)
    english = _lint({
        "Applications.yaml": _CATALOG_EN,
        "Applications.xbsl": "method Probe(Schema: Applications.DataSchema)\n;\n",
    }, _RULE_OBJECT_TYPE)
    assert len(russian) == 1, [d.message for d in russian]
    assert len(english) == 1, [d.message for d in english]
    assert "СхемаДанных" in russian[0].message and "DataSchema" in english[0].message


def test_that_same_type_stays_clean_on_the_kind_that_generates_it():
    """The negative control of the pair above: per-kind must not mean blind."""
    russian = _lint({
        "Обмены.yaml": _EXCHANGE_RU,
        "Обмены.xbsl": "метод Проба(Схема: Обмены.СхемаДанных)\n;\n",
    }, _RULE_OBJECT_TYPE)
    english = _lint({
        "Exchanges.yaml": _EXCHANGE_EN,
        "Exchanges.xbsl": "method Probe(Schema: Exchanges.DataSchema)\n;\n",
    }, _RULE_OBJECT_TYPE)
    assert russian == [], [d.message for d in russian]
    assert english == [], [d.message for d in english]


# --- style/exception-prefix: the English idiom is a suffix ---------------------------------

_RULE_EXCEPTION = "style/exception-prefix"


def test_russian_exception_carries_the_prefix():
    assert _lint({"M.xbsl": "исключение ИсключениеАвторизации\n;\n"}, _RULE_EXCEPTION) == []


def test_english_exception_carries_the_suffix():
    """The regression: the rule asked for the prefix and offered it glued onto a Latin name."""
    found = _lint({"M.xbsl": "exception AuthenticationException\n;\n"}, _RULE_EXCEPTION)
    assert found == [], [d.message for d in found]


def test_english_exception_without_the_marker_is_still_flagged():
    found = _lint({"M.xbsl": "exception Authentication\n;\n"}, _RULE_EXCEPTION)
    assert len(found) == 1 and "Authentication" in found[0].message


def test_english_exception_is_offered_the_suffix_not_the_prefix():
    """The suggestion follows the script of the name: a Cyrillic prefix helps nobody here."""
    found = _lint({"M.xbsl": "exception Authentication\n;\n"}, _RULE_EXCEPTION)
    assert "AuthenticationException" in found[0].message
    assert "Исключение" not in found[0].message


def test_russian_exception_is_still_offered_the_prefix():
    found = _lint({"M.xbsl": "исключение ЧтениеФайла\n;\n"}, _RULE_EXCEPTION)
    assert "ИсключениеЧтениеФайла" in found[0].message


# --- yaml/missing-subsystem-usage: the section key is `Using` ------------------------------

_RULE_USAGE = "yaml/missing-subsystem-usage"

_SUB_PRIVATE_EN = "Interface:\n    IncludeInAutoInterface: False\n"
_GOODS_EN = "ElementKind: Catalog\nName: Goods\nVisibilityScope: InProject\n"
_TASKS_EN = (
    "ElementKind: Catalog\n"
    "Name: Tasks\n"
    "Import:\n"
    "    - Other\n"
)


def _subsystems_en(descriptor: str) -> dict[str, str]:
    return {
        "Main/Subsystem.yaml": descriptor,
        "Other/Subsystem.yaml": _SUB_PRIVATE_EN,
        "Other/Goods.yaml": _GOODS_EN,
        "Main/Tasks.yaml": _TASKS_EN,
    }


def test_english_subsystem_without_a_using_section_is_flagged():
    found = _lint(_subsystems_en(_SUB_PRIVATE_EN), _RULE_USAGE)
    assert len(found) == 1 and "Other" in found[0].message


def test_english_subsystem_with_the_using_section_is_clean():
    """The regression: the rule read the section as `Usage` alone, a word the platform never
    writes - so an English project had its permission unread."""
    found = _lint(_subsystems_en("Using:\n    - Other\n"), _RULE_USAGE)
    assert found == [], [d.message for d in found]


def test_a_section_the_platform_does_not_read_is_reported():
    """`Usage` is what this linter and its documentation named up to 0.70 - and it permits nothing.

    No serializer writes that word and the platform does not know it, so a descriptor spelled
    this way grants no permission at all. Accepting it would hide a section that does not work.
    """
    found = _lint(_subsystems_en("Usage:\n    - Other\n"), _RULE_USAGE)
    assert len(found) == 1, [d.message for d in found]


def test_the_english_section_keys_stand_without_the_distribution(tmp_path):
    """A clean public clone has no term pairs - the English spellings must not vanish with them.

    key_forms degrades to the Russian key alone when there is no data, so without the fallback
    an English project had its permission unread and every import through it reported.
    """
    from xbsl import dataset
    from xbsl.rules import yaml_imports

    (tmp_path / "index.json").write_text(
        '{"available": ["1.0"], "default": "1.0"}', encoding="utf-8")
    (tmp_path / "1.0").mkdir()
    dataset.set_data_root(tmp_path)
    try:
        assert yaml_imports._usage_keys() == ("Использование", "Using")
    finally:
        dataset.set_data_root(None)



# --- style/boolean-compare: the member whose type forces the comparison ---------------------

_RULE_BOOLEAN = "style/boolean-compare"


def test_russian_member_of_a_union_type_needs_the_comparison():
    files = {
        "M.xbsl": "метод Проба()\n"
                  "    если Компоненты.Подсказка.Видимость == Истина тогда\n    ;\n;\n",
    }
    assert _lint(files, _RULE_BOOLEAN) == []


def test_english_member_of_a_union_type_needs_the_comparison():
    """The regression: `Видимость` is `Авто|Булево` in the catalog, `Visible` was unknown."""
    files = {
        "M.xbsl": "method Probe()\n"
                  "    if Components.Hint.Visible == True then\n    ;\n;\n",
    }
    found = _lint(files, _RULE_BOOLEAN)
    assert found == [], [d.message for d in found]


def test_english_comparison_of_a_plain_boolean_is_still_flagged():
    files = {"M.xbsl": "method Probe(Flag: Boolean)\n    if Flag == True then\n    ;\n;\n"}
    found = _lint(files, _RULE_BOOLEAN)
    assert len(found) == 1, [d.message for d in found]


def test_a_member_name_ambiguous_in_english_answers_the_same_in_both_spellings():
    """One English spelling covers two Russian members - both spellings must agree anyway.

    `Enabled` is the English of a plain-boolean member AND of an `Авто|Булево` one. The pooled
    types used to go to the English key alone, so the English source was left alone while its
    Russian twin was reported - the twin trees disagreed on the same line of the same project.
    """
    russian = _lint({
        "M.xbsl": "метод Проба()\n"
                  "    если Компоненты.Кнопка.Включено == Истина тогда\n    ;\n;\n",
    }, _RULE_BOOLEAN)
    english = _lint({
        "M.xbsl": "method Probe()\n"
                  "    if Components.Button.Enabled == True then\n    ;\n;\n",
    }, _RULE_BOOLEAN)
    assert russian == [], [d.message for d in russian]
    assert english == [], [d.message for d in english]


# --- code/unknown-enum-value: an item named `No` -------------------------------------------

_RULE_ENUM = "code/unknown-enum-value"

_ENUM_EN = """\
ElementKind: Enumeration
Id: 0f2a6c31-1d54-4b90-9c07-5ab3e8d4f612
Name: FeatureImagePosition
Items:
    -
        Id: 4c1b7e28-90da-4f36-b8e1-73c05a29d4f7
        Name: No
    -
        Id: b7d95f10-2a63-4c8e-95af-1e6407bd3a52
        Name: Left
"""


def test_english_enumeration_item_spelled_like_a_yaml_boolean():
    """The regression: YAML 1.1 reads the item name `No` as False, so the item vanished."""
    files = {
        "FeatureImagePosition.yaml": _ENUM_EN,
        "Card.xbsl": "method Probe(): FeatureImagePosition\n"
                     "    return FeatureImagePosition.No\n;\n",
    }
    found = _lint(files, _RULE_ENUM)
    assert found == [], [d.message for d in found]


def test_english_enumeration_item_spelled_like_a_yaml_boolean_in_a_binding():
    files = {
        "FeatureImagePosition.yaml": _ENUM_EN,
        "Card.yaml": (
            "ElementKind: InterfaceComponent\n"
            "Id: 8e30d5a7-64b1-4f22-a0c9-95d178e2b463\n"
            "Name: Card\n"
            "Inherits:\n"
            "    Type: Group\n"
            "    Content:\n"
            "        -\n"
            "            Type: Label\n"
            "            Name: Hint\n"
            "            Visible: '=Position == FeatureImagePosition.No'\n"
        ),
    }
    found = _lint(files, _RULE_ENUM)
    assert found == [], [d.message for d in found]


def test_unknown_item_of_that_english_enumeration_is_still_flagged():
    files = {
        "FeatureImagePosition.yaml": _ENUM_EN,
        "Card.xbsl": "method Probe(): FeatureImagePosition\n"
                     "    return FeatureImagePosition.Yes\n;\n",
    }
    found = _lint(files, _RULE_ENUM)
    assert len(found) == 1 and "FeatureImagePosition.Yes" in found[0].message


def test_a_yaml_boolean_property_still_reads_as_a_boolean():
    """The negative control of the loader change: `True`/`False` stay booleans."""
    from xbsl.rules.yaml_schema import _parsed

    source = engine.load_text("Sub.yaml", "Interface:\n    IncludeInAutoInterface: False\n")
    data, err = _parsed(source)
    assert err is None
    assert data["Interface"]["IncludeInAutoInterface"] is False


# --- query/unknown-table: an entity of the platform ----------------------------------------

_RULE_TABLE = "query/unknown-table"

_QUERY_RU = """\
метод Проба()
    знч Результат = Запрос{
        ВЫБРАТЬ Ссылка ИЗ Пользователи
    }
;
"""
_QUERY_EN = """\
method Probe()
    val Result = Query{
        SELECT Reference FROM Users
    }
;
"""


def test_platform_entity_table_in_a_russian_query():
    files = {"Заявки.yaml": _CATALOG_RU, "Заявки.xbsl": _QUERY_RU}
    assert _lint(files, _RULE_TABLE) == []


def test_platform_entity_table_in_an_english_query():
    """The regression: the entity names come from the catalog, which spells them Russian."""
    files = {"Applications.yaml": _CATALOG_EN, "Applications.xbsl": _QUERY_EN}
    found = _lint(files, _RULE_TABLE)
    assert found == [], [d.message for d in found]


def test_unknown_table_of_an_english_query_is_still_flagged():
    files = {
        "Applications.yaml": _CATALOG_EN,
        "Applications.xbsl": _QUERY_EN.replace("FROM Users", "FROM Userz"),
    }
    found = _lint(files, _RULE_TABLE)
    assert len(found) == 1 and "Userz" in found[0].message
