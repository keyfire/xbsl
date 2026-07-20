"""Tests of the two member-existence rules: code/unknown-member (a variable of a declared
stdlib type) and code/unknown-static-member (a member reached through a type name).

First-hop and provable negatives only: entity aggregates (the record protocol is incomplete
in the docs), project and parameterized types, Latin member spellings - all skipped.
"""

from __future__ import annotations

from xbsl.diagnostics import Diagnostic
from xbsl.engine import load_text, run_sources


def _lint(code: str) -> list[Diagnostic]:
    src = load_text("Модуль.xbsl", code)
    return list(run_sources([src], select={"code/unknown-member"}, scopes=("file",)))


def test_typo_in_member_with_hint():
    diags = _lint(
        "метод Тест(Имя: Строка): Число\n"
        "    возврат Имя.ДлинаСтроки()\n"
        ";\n"
    )
    assert len(diags) == 1
    assert "Строка" in diags[0].message and "ДлинаСтроки" in diags[0].message


def test_known_member_passes():
    diags = _lint(
        "метод Тест(Имя: Строка): Число\n"
        "    возврат Имя.Длина()\n"
        ";\n"
    )
    assert diags == [], [d.message for d in diags]


def test_declared_variable_is_checked():
    diags = _lint(
        "метод Тест()\n"
        "    пер Момент: ДатаВремя = ДатаВремя.Сейчас()\n"
        "    Сообщить(Момент.НетТакогоЧлена)\n"
        ";\n"
    )
    assert len(diags) == 1


def test_project_type_is_silent():
    diags = _lint(
        "метод Тест(Запись: МояЗапись)\n"
        "    Сообщить(Запись.ЧтоУгодно)\n"
        ";\n"
    )
    assert diags == []


def test_generic_type_is_silent():
    # parameterized types are not checked (first-hop, no inference)
    diags = _lint(
        "метод Тест(Список: Массив<Строка>)\n"
        "    Список.НетТакого()\n"
        ";\n"
    )
    assert diags == []


def test_redeclared_name_is_silent():
    # a name with two differently typed declarations is poisoned - do not raise false accusations
    diags = _lint(
        "метод А(Значение: Строка)\n"
        "    Значение.НетТакого()\n"
        "    знч Ф = метод (Значение: Число) -> Значение\n"
        "    Ф(1)\n"
        ";\n"
    )
    assert diags == []


def test_entity_members_come_from_facets():
    # entity record and reference members live on the facet pages (Пользователи.Объект);
    # the aggregate name covers the union of the facets
    diags = _lint(
        "метод Тест(Пользователь: Пользователи)\n"
        "    Сообщить(Пользователь.Ид)\n"
        "    Сообщить(Пользователь.РазрешенДоступПоТокену)\n"
        ";\n"
    )
    assert diags == [], [d.message for d in diags]
    diags = _lint(
        "метод Тест(Пользователь: Пользователи)\n"
        "    Сообщить(Пользователь.НетТакогоЧлена)\n"
        ";\n"
    )
    assert len(diags) == 1


def test_facet_name_works_as_nominal_type():
    diags = _lint(
        "метод Тест(Данные: ДвоичныйОбъект.Ссылка)\n"
        "    Данные.Загрузить()\n"
        ";\n"
    )
    assert diags == [], [d.message for d in diags]
    diags = _lint(
        "метод Тест(Данные: ДвоичныйОбъект.Ссылка)\n"
        "    Данные.НетТакого()\n"
        ";\n"
    )
    assert len(diags) == 1


# --- code/unknown-static-member: the member is reached through a TYPE NAME ---------------


def _lint_static(module: str, *extra: tuple[str, str]) -> list[Diagnostic]:
    sources = [load_text("Модуль.xbsl", module)]
    for name, text in extra:
        sources.append(load_text(name, text))
    return [
        d for d in run_sources(sources, select={"code/unknown-static-member"})
        if d.rule_id == "code/unknown-static-member"
    ]


def test_static_call_on_type_name():
    diags = _lint_static(
        "метод Тест()\n"
        "    ДатаВремя.Минимальная()\n"
        ";\n"
    )
    assert len(diags) == 1
    assert "ДатаВремя" in diags[0].message and "Минимальная" in diags[0].message


def test_existing_static_call_passes():
    diags = _lint_static(
        "метод Тест()\n"
        "    ДатаВремя.Сейчас()\n"
        ";\n"
    )
    assert diags == [], [d.message for d in diags]


def test_inferred_type_carries_to_the_next_hop():
    # `знч Б = ДатаВремя.Сейчас()` makes Б a ДатаВремя - the chain the rule is here for
    diags = _lint_static(
        "метод Тест()\n"
        "    знч Б = ДатаВремя.Сейчас()\n"
        "    Б.НетТакогоЧлена()\n"
        ";\n"
    )
    assert len(diags) == 1
    assert "ДатаВремя" in diags[0].message


def test_paired_yaml_name_shadows_the_type():
    # a form attribute named Email is not the mail type - and only the project can tell
    module = (
        "метод Тест()\n"
        "    Email.Длина()\n"
        ";\n"
    )
    assert _lint_static(module) != []  # without the pair the bare name reads as a type
    diags = _lint_static(
        module,
        ("Модуль.yaml",
         "ВидЭлемента: КомпонентИнтерфейса\nИмя: Модуль\nРеквизиты:\n  - Имя: Email\n"),
    )
    assert diags == [], [d.message for d in diags]


def test_project_object_name_shadows_the_type_everywhere():
    diags = _lint_static(
        "метод Тест()\n"
        "    Символы.ЧтоУгодно()\n"
        ";\n",
        ("Символы.yaml", "ВидЭлемента: Справочник\nИмя: Символы\n"),
    )
    assert diags == [], [d.message for d in diags]


def test_module_level_name_shadows_the_type():
    diags = _lint_static(
        "структура Символы\n"
        "    пер Поле: Строка\n"
        ";\n"
        "метод Тест()\n"
        "    Символы.ЧтоУгодно()\n"
        ";\n"
    )
    assert diags == [], [d.message for d in diags]


def test_declared_type_is_left_to_the_sibling_rule():
    # a declared type is code/unknown-member's business - no duplicate finding here
    diags = _lint_static(
        "метод Тест(Момент: ДатаВремя)\n"
        "    Момент.НетТакогоЧлена()\n"
        ";\n"
    )
    assert diags == [], [d.message for d in diags]


def test_hierarchy_root_is_silent():
    # Объект is the root of the hierarchy: its own member set is the bare object protocol
    diags = _lint_static(
        "метод Тест()\n"
        "    Объект.Наименование\n"
        ";\n"
    )
    assert diags == [], [d.message for d in diags]


def test_underscore_constant_is_a_known_member():
    # guards the extractor fix: НОВАЯ_СТРОКА used to be dropped from the catalog
    diags = _lint_static(
        "метод Тест()\n"
        "    Символы.НОВАЯ_СТРОКА.Длина()\n"
        ";\n"
    )
    assert diags == [], [d.message for d in diags]
