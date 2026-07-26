"""Rules of the project/ group: project properties per the "Заполнение свойств проекта" standard.

These rules need no Element data - they only read the project descriptor, so the tests
pass in a clean checkout as well.
"""

from xbsl import engine

_HEAD = "Ид: ffeacdec-02d6-4f08-bcfa-be89e9a1861a\nРежимСовместимости: 9.0\n"


def _lint(rule_id: str, body: str) -> list:
    source = engine.load_text("Проект.yaml", _HEAD + body)
    return engine.run_sources([source], select={rule_id}, scopes=("file",))


def _project(vendor="Acme", name="Tasks", version="1.0.0",
             presentation='"Задачи (демо)"', vendor_presentation='"Акме"') -> str:
    return (
        f"Поставщик: {vendor}\n"
        f"Имя: {name}\n"
        f"Версия: {version}\n"
        f"Представление: {presentation}\n"
        f"ПредставлениеПоставщика: {vendor_presentation}\n"
    )


def test_valid_project_is_silent():
    for rule_id in ("project/identifier", "project/presentation", "project/version"):
        assert _lint(rule_id, _project()) == []


def test_vendor_lowercase():
    diags = _lint("project/identifier", _project(vendor="acme"))
    assert len(diags) == 1
    assert "Поставщик" in diags[0].message and "acme" in diags[0].message


def test_name_lowercase():
    diags = _lint("project/identifier", _project(name="tasks"))
    assert len(diags) == 1
    assert "Имя" in diags[0].message


def test_identifier_with_separator():
    # separators are not allowed in the identifier: the name derives from the presentation, joined
    assert len(_lint("project/identifier", _project(name="Кабинет_Сотрудника"))) == 1
    assert _lint("project/identifier", _project(name="КабинетСотрудника")) == []


def test_version_two_parts():
    diags = _lint("project/version", _project(version="1.0"))
    assert len(diags) == 1
    assert "1.0.0" in diags[0].message  # the hint completes the missing number


def test_version_four_parts():
    assert len(_lint("project/version", _project(version="1.0.1.5"))) == 1


def test_version_semantic_is_silent():
    assert _lint("project/version", _project(version="2.0.1")) == []


def test_presentation_missing():
    body = "Поставщик: Acme\nИмя: Tasks\nВерсия: 1.0.0\n"
    diags = _lint("project/presentation", body)
    assert len(diags) == 2  # both Представление and ПредставлениеПоставщика
    assert {"Представление", "ПредставлениеПоставщика"} == {
        d.message.split("'")[1] for d in diags
    }


def test_presentation_empty_string():
    assert len(_lint("project/presentation", _project(presentation='""'))) == 1


def test_element_description_is_not_a_project():
    # an element descriptor has ВидЭлемента - the project rules leave it alone
    source = engine.load_text(
        "Задачи.yaml",
        "ВидЭлемента: Справочник\nИд: 42073842-db14-41d6-a17a-7b03a5d57933\nИмя: Задачи\n",
    )
    for rule_id in ("project/identifier", "project/presentation", "project/version"):
        assert engine.run_sources([source], select={rule_id}, scopes=("file",)) == []
