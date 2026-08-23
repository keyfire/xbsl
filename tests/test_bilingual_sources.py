"""Sources spelled in ENGLISH are judged like Russian ones.

The platform reads a project either way - a catalog compiles when spelled
`ElementKind: Catalog` / `Name` / `Attributes` / `MaxLength`, and the yaml key of a property is
its `en` argument or the model member's name capitalized. Before this, a rule looked for
`ВидЭлемента`, did not find it and skipped the whole file: not even a typo was reported.

(The fixtures said `Длина` / `Length` here until the compiler answered
`Неизвестное свойство "Длина"` on a regular attribute - only the built-in `Код` declares that
property - so the "clean" fixture was code the platform would have rejected. The same check
answered `ID required` for an attribute without an `Ид`, hence the identifiers here.)
"""

from __future__ import annotations

import pytest

from xbsl import dataset, engine, metamodel
from xbsl.cli import discover
from xbsl.rules.yaml_schema import object_kind, value_of

if not dataset.available_versions():
    pytest.skip("нет данных Элемента", allow_module_level=True)

RUSSIAN = """\
ВидЭлемента: Справочник
Ид: 42073842-db14-41d6-a17a-7b03a5d57933
Имя: Tasks
Представление: Описание
ОбластьВидимости: ВПроекте
Реквизиты:
    -
        Ид: 8f3a2c14-7b6d-4e05-9a1c-2d5f8b47e903
        Имя: Описание
        МаксимальнаяДлина: 250
"""

ENGLISH = """\
ElementKind: Catalog
Id: 42073842-db14-41d6-a17a-7b03a5d57933
Name: Tasks
Presentation: Description
VisibilityScope: InProject
Attributes:
    -
        Id: 8f3a2c14-7b6d-4e05-9a1c-2d5f8b47e903
        Name: Description
        MaxLength: 250
"""


def _lint(tmp_path, text: str, name: str = "Tasks.yaml"):
    (tmp_path / "Проект.yaml").write_text(
        "Ид: ffeacdec-02d6-4f08-bcfa-be89e9a1861a\nПоставщик: Acme\nИмя: Probe\n"
        "Версия: 1.0.0\nПредставление: Probe\nПредставлениеПоставщика: Acme\n",
        encoding="utf-8",
    )
    (tmp_path / name).write_text(text, encoding="utf-8")
    return [d for d in engine.run(discover([str(tmp_path)])) if d.path.endswith(name)]


def test_english_object_is_clean(tmp_path):
    assert _lint(tmp_path, ENGLISH) == []


def test_russian_object_is_clean(tmp_path):
    assert _lint(tmp_path, RUSSIAN) == []


def test_typo_in_an_english_key_is_caught(tmp_path):
    diags = _lint(tmp_path, ENGLISH.replace("VisibilityScope:", "VisibilityScopeX:"))
    assert [d.rule_id for d in diags] == ["yaml/unknown-property"]
    assert "VisibilityScopeX" in diags[0].message


def test_english_presentation_names_an_english_attribute(tmp_path):
    # the presentation field is resolved through the English section and item keys
    diags = _lint(tmp_path, ENGLISH.replace("Presentation: Description", "Presentation: Missing"))
    assert [d.rule_id for d in diags] == ["yaml/presentation-field"]


def test_object_kind_reads_either_spelling():
    assert object_kind({"ВидЭлемента": "Справочник"}) == "Справочник"
    assert object_kind({"ElementKind": "Catalog"}) == "Справочник"
    assert object_kind({"ElementKind": "Справочник"}) == "Справочник"
    assert object_kind({"Имя": "Х"}) is None


def test_value_of_takes_the_english_twin():
    english = {"ElementKind": "Catalog", "Id": "x", "Presentation": "Description"}
    assert value_of(english, "Ид") == "x"
    assert value_of(english, "Представление") == "Description"
    # a collection item has no kind of its own - the pair is resolved globally
    assert value_of({"Name": "Description"}, "Имя") == "Description"


def test_metamodel_names_the_english_key():
    props = metamodel.properties("Справочник")
    assert props["Реквизиты"]["en"] == "Attributes"
    assert props["ВидЭлемента"]["en"] == "ElementKind"  # an envelope key, synthesized
    assert "Attributes" in metamodel.allowed_keys("Справочник")
    assert metamodel.canonical_key("Справочник", "Attributes") == "Реквизиты"
    assert metamodel.canonical_kind("Catalog") == "Справочник"
    assert metamodel.canonical_kind("Справочник") == "Справочник"


def test_serializer_kind_spellings_canonicalize():
    """What the vendor IDE writes into ElementKind, not what the dictionaries suggest.

    Live issue #1: the type dictionary spells `Перечисление` as `Enum`, while an English
    project's yaml says `ElementKind: Enumeration` - such objects fell out of every
    by-kind view into "Other". Both spellings must canonicalize, and the serializer's
    table must not take the dictionary's spelling away.
    """
    for english, russian in (
        ("Enumeration", "Перечисление"),
        ("Enum", "Перечисление"),
        ("HttpService", "HttpСервис"),
        ("IntegrationProcess", "ПроцессИнтеграции"),
        ("ReportPanel", "ПанельОтчетов"),
        ("DataJournal", "ЖурналДанных"),
        ("IntegrableApplication", "ИнтегрируемоеПриложение"),
    ):
        assert metamodel.canonical_kind(english) == russian, english


def test_serializer_kind_spellings_survive_without_the_dataset_table(monkeypatch):
    """A dataset generated before the `kinds` section joined still resolves the vendor
    spellings - through the constant read out of a current distribution."""
    from xbsl import terms

    monkeypatch.setattr(terms, "kinds_table", lambda: {})
    metamodel._english_kinds.cache_clear()
    try:
        assert metamodel.canonical_kind("Enumeration") == "Перечисление"
        assert metamodel.canonical_kind("Enum") == "Перечисление"
    finally:
        metamodel._english_kinds.cache_clear()


# --- forms ------------------------------------------------------------------------------

EN_FORM = """\
ElementKind: InterfaceComponent
Id: 6f0b6a44-0000-4000-8000-000000000201
Name: OrderPanel
Inherits:
    Type: Group
    Layout: Vertical
    Content:
        -
            Type: Label
            Name: Hint
            Value: "Fill in the order."
        -
            Type: InputField<String>
            Name: Recipient
"""


def test_english_form_builds_the_same_tree():
    from xbsl import formmodel

    form = formmodel.parse_form(EN_FORM)
    assert form.root.type_full == "Group"
    slot = form.root.children[0]
    assert slot.name == "Content" and slot.list_style is True
    assert [(c.type_full, c.name) for c in slot.children] == [
        ("Label", "Hint"), ("InputField<String>", "Recipient"),
    ]
    # Тип and Имя are node fields, not properties, in either spelling
    assert [p.key for p in slot.children[0].properties] == ["Value"]


def test_english_form_is_clean(tmp_path):
    assert _lint(tmp_path, EN_FORM, name="OrderPanel.yaml") == []


def test_wrong_enum_value_in_an_english_form_is_caught(tmp_path):
    diags = _lint(tmp_path, EN_FORM.replace("Layout: Vertical", "Layout: Diagonal"),
                  name="OrderPanel.yaml")
    assert [d.rule_id for d in diags] == ["yaml/unknown-enum-value"]
    # the hint keeps the language of the file
    assert "Horizontal" in diags[0].message and "Горизонтальная" not in diags[0].message


def test_english_value_of_an_enumeration_is_accepted(tmp_path):
    """`DisplayKind: Banner` is legal code - the compiler accepts it.

    The spellings come from uiterms.json (extracted from the distribution): the ui schema
    itself is built from the Russian-only documentation and used to report such values as
    unknown.
    """
    form = EN_FORM.replace(
        "Type: InputField<String>", "Type: StandardCard\n            DisplayKind: Banner"
    )
    assert _lint(tmp_path, form, name="OrderPanel.yaml") == []


def test_form_keys_are_canonicalized_forward():
    from xbsl import formmodel

    assert formmodel.canonical_key("Content") == "Содержимое"
    assert formmodel.canonical_key("RowCommands") == "КомандыСтроки"
    # `Type` is the English of both Тип and ТипЭлементаПроекта - the forward map picks the key
    # this module actually compares by
    assert formmodel.canonical_key("Type") == "Тип"
    assert formmodel.canonical_key("Тип") == "Тип"


# --- the English demo project is the guard -----------------------------------------

def _demo_findings(root) -> list[tuple[str, int]]:
    """{rule: line} of a demo project - the shape both twins must report the same way."""
    diags = engine.run(discover([str(root)]))
    return sorted((d.rule_id, d.line) for d in diags)


def test_both_demo_projects_report_the_same_findings(request):
    """The English twin is judged exactly like the Russian one.

    The deliberate findings sit on the same lines of the same module in both, so a rule that
    goes blind on English sources shows up here as a missing finding rather than as silence.
    """
    root = request.config.rootpath
    russian = _demo_findings(root / "demo")
    english = _demo_findings(root / "demo-en")
    assert russian, "в русском демо-проекте нет находок - фикстура сломана"
    assert english == russian


def test_a_violation_in_an_english_component_is_caught(tmp_path):
    # yaml/size-needs-no-stretch is off by default: the check runs it point-blank
    (tmp_path / "Проект.yaml").write_text(
        "Ид: ffeacdec-02d6-4f08-bcfa-be89e9a1861a\nПоставщик: Acme\nИмя: Probe\n"
        "Версия: 1.0.0\nПредставление: Probe\nПредставлениеПоставщика: Acme\n", encoding="utf-8")
    (tmp_path / "Panel.yaml").write_text(
        "ElementKind: InterfaceComponent\n"
        "Id: 6f0b6a44-0000-4000-8000-0000000003a2\n"
        "Name: Panel\n"
        "Inherits:\n"
        "    Type: Group\n"
        "    Content:\n"
        "        -\n"
        "            Type: HtmlContainer\n"
        "            Name: Inset\n"
        "            Height: 200\n", encoding="utf-8")
    diags = engine.run(discover([str(tmp_path)]), select={"yaml/size-needs-no-stretch"})
    assert [d.rule_id for d in diags] == ["yaml/size-needs-no-stretch"]
    # the advice speaks the language of the file
    assert "VerticalStretch" in diags[0].message


# --- the scaffolding writes in the language of the project ---------------------------------

def test_new_object_follows_the_project_spelling(tmp_path):
    """A new object must look like the files around it, not like a Russian island.

    The language is decided by the sources themselves (by MAJORITY, so one stray file cannot flip
    a project), never by a setting: the tool has to match what is already there.
    """
    from xbsl import scaffold

    project = tmp_path / "acme" / "probe"
    (project / "Main").mkdir(parents=True)
    (project / "Проект.yaml").write_text(
        "Ид: ffeacdec-02d6-4f08-bcfa-be89e9a1861a\nПоставщик: Acme\nИмя: Probe\nВерсия: 1.0.0\n",
        encoding="utf-8",
    )
    (project / "Main" / "Tasks.yaml").write_text(
        "ElementKind: Catalog\nId: 42073842-db14-41d6-a17a-7b03a5d57933\nName: Tasks\n",
        encoding="utf-8",
    )
    assert scaffold.project_language(project / "Main") == "en"
    result = scaffold.op_new_object(project / "Main", "Справочник", "Projects")
    scaffold.apply_result(result)
    written = (project / "Main" / "Projects.yaml").read_text(encoding="utf-8")
    assert written.startswith("ElementKind: Catalog\n")
    assert "Name: Projects" in written and "VisibilityScope: InSubsystem" in written
    assert result.changes

    # A Russian neighbour keeps the Russian spelling - the majority decides.
    (project / "Main" / "Задачи.yaml").write_text(
        "ВидЭлемента: Справочник\nИд: 54c9050e-3377-4a67-8c34-c80d1074edfc\nИмя: Задачи\n",
        encoding="utf-8",
    )
    (project / "Main" / "Ещё.yaml").write_text(
        "ВидЭлемента: Документ\nИд: 771ad094-7290-4156-a847-726ac8f60789\nИмя: Ещё\n",
        encoding="utf-8",
    )
    assert scaffold.project_language(project / "Main") == "ru"


def test_project_descriptor_is_judged_in_english(tmp_path):
    """A project descriptor may be spelled in English - exactly such a project compiles.
    Before this the whole `project/` group went silent on it: a name
    that is not an identifier, a two-part version and an empty presentation all passed."""
    # The layout matches the descriptor on purpose: project/path-matches-descriptor judges the
    # directories around the file, and a descriptor dropped into a bare temporary directory
    # would add a finding that has nothing to do with what this test is about.
    project = tmp_path / "acme corp" / "tasks-en"
    project.mkdir(parents=True)
    (project / "Проект.yaml").write_text(
        "Id: 5b1e77c4-8a20-4f3d-9d21-6a0f4e2c1d90\n"
        "CompatibilityMode: 9.0\n"
        "Vendor: acme corp\n"
        "Name: tasks-en\n"
        "Version: 1.0\n"
        'Presentation: ""\n',
        encoding="utf-8",
    )
    diags = engine.run(discover([str(tmp_path)]))
    found = sorted({d.rule_id for d in diags})
    assert found == ["project/identifier", "project/presentation", "project/version"]


# -- rules that used to read the Russian key alone ------------------------------


_STANDARD_RU = """\
ВидЭлемента: Справочник
Ид: 42073842-db14-41d6-a17a-7b03a5d57934
Имя: Stores
Реквизиты:
    -
        Имя: Наименование
        Длина: 500
"""

_STANDARD_EN = """\
ElementKind: Catalog
Id: 42073842-db14-41d6-a17a-7b03a5d57934
Name: Stores
Attributes:
    -
        Name: Name
        Length: 500
"""


def test_the_standard_field_limit_is_measured_in_an_english_source(tmp_path):
    """The rule read `Attributes`/`Name`/`Length` by their Russian keys alone, so an
    English project passed it by."""
    english = [d for d in _lint(tmp_path, _STANDARD_EN, name="Stores.yaml")
               if d.rule_id == "yaml/standard-field-length"]
    russian = [d for d in _lint(tmp_path, _STANDARD_RU, name="Stores.yaml")
               if d.rule_id == "yaml/standard-field-length"]

    assert len(english) == 1 and len(russian) == 1
    # The position is found by the same scan, so the finding stands on the length line.
    assert english[0].line == russian[0].line == 7


def test_a_developer_attribute_named_name_is_not_a_standard_field(tmp_path):
    """The spelling is taken from the FILE: in a Russian source `Name` is an ordinary name,
    and its length is nobody's business."""
    russian = _STANDARD_RU.replace("Имя: Наименование\n        Длина: 500",
                                   "Имя: Name\n        МаксимальнаяДлина: 500")
    diags = [d for d in _lint(tmp_path, russian, name="Stores.yaml")
             if d.rule_id == "yaml/standard-field-length"]

    assert diags == []


def test_the_presentation_type_is_judged_in_an_english_source(tmp_path):
    """A number as the presentation field is refused by the compiler in either spelling."""
    english = ENGLISH.replace("MaxLength: 250", "Type: Number")
    diags = [d for d in _lint(tmp_path, english) if d.rule_id == "yaml/presentation-field"]

    assert len(diags) == 1 and "Number" in diags[0].message


def test_an_english_string_attribute_is_a_valid_presentation(tmp_path):
    """Negative control: `String` is a string, and the rule must not read it as anything else."""
    english = ENGLISH.replace("MaxLength: 250", "Type: String")
    diags = [d for d in _lint(tmp_path, english) if d.rule_id == "yaml/presentation-field"]

    assert diags == []
