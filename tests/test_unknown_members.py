"""Tests of the two member-existence rules: code/unknown-member (a variable of a declared
stdlib type) and code/unknown-static-member (a member reached through a type name).

First-hop and provable negatives only: entity aggregates (the record protocol is incomplete
in the docs), project and parameterized types, Latin member spellings - all skipped.
"""

from __future__ import annotations

from xbsl.diagnostics import Diagnostic
from xbsl.engine import load, load_text, run_sources


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


def test_generic_head_is_checked():
    # the arguments type the members, they do not name them - the head knows the member set
    diags = _lint(
        "метод Тест(Список: Массив<Строка>)\n"
        "    Список.НетТакого()\n"
        ";\n"
    )
    assert len(diags) == 1 and "Массив" in diags[0].message


def test_member_of_a_generic_passes():
    diags = _lint(
        "метод Тест(Список: Массив<Строка>)\n"
        "    Список.Размер()\n"
        ";\n"
    )
    assert diags == [], [d.message for d in diags]


def test_collection_count_from_another_platform_is_caught():
    """The case from the field: Element collections have Размер, and Количество reached a build."""
    diags = _lint(
        "метод Тест(Список: ЧитаемыйМассив<Строка>): Булево\n"
        "    возврат Список.Количество() > 0\n"
        ";\n"
    )
    assert len(diags) == 1 and "Количество" in diags[0].message


def test_nullable_generic_is_checked():
    diags = _lint(
        "метод Тест(Список: Массив<Строка>?)\n"
        "    Список.НетТакого()\n"
        ";\n"
    )
    assert len(diags) == 1


def test_project_generic_is_silent():
    diags = _lint(
        "метод Тест(Список: МойСписок<Строка>)\n"
        "    Список.ЧтоУгодно()\n"
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


def _lint_static_files(module_path) -> list[Diagnostic]:
    return [
        d for d in run_sources([load(module_path)], select={"code/unknown-static-member"})
        if d.rule_id == "code/unknown-static-member"
    ]


def test_pair_on_disk_shadows_in_a_single_file_run(tmp_path):
    # the editor lints ONE saved module: the paired yaml is on disk but not among the
    # sources, and the form-attribute shadow must still hold (the reduce sees no yaml facts)
    (tmp_path / "Форма.yaml").write_text(
        "ВидЭлемента: КомпонентИнтерфейса\nИмя: Форма\nДанные:\n  - Имя: Email\n",
        encoding="utf-8",
    )
    module = tmp_path / "Форма.xbsl"
    module.write_text(
        "метод Тест(): Булево\n    возврат Email.Длина() == 0\n;\n", encoding="utf-8",
    )
    assert _lint_static_files(module) == []


def test_pair_on_disk_shadows_the_inferred_root(tmp_path):
    # the shadow read from the disk pair also drops candidates carried by a chain root
    (tmp_path / "Форма.yaml").write_text(
        "ВидЭлемента: КомпонентИнтерфейса\nИмя: Форма\nДанные:\n  - Имя: ДатаВремя\n",
        encoding="utf-8",
    )
    module = tmp_path / "Форма.xbsl"
    module.write_text(
        "метод Тест()\n    знч Б = ДатаВремя.Сейчас()\n    Сообщить(Б.НетТакогоЧлена)\n;\n",
        encoding="utf-8",
    )
    assert _lint_static_files(module) == []


def test_single_file_run_without_a_pair_keeps_the_finding(tmp_path):
    # the control: no neighbor on disk - the bare name still reads as a type and is judged
    module = tmp_path / "Форма.xbsl"
    module.write_text(
        "метод Тест(): Булево\n    возврат Email.Длина() == 0\n;\n", encoding="utf-8",
    )
    diags = _lint_static_files(module)
    assert len(diags) == 1 and "Email" in diags[0].message


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


# --- the value came from another module (the project phase resolves it) -----------------

_CALLEE = (
    "Каталог.xbsl",
    "@ВПроекте\n"
    "метод Позиции(Код: Строка): Массив<Строка>\n"
    "    возврат []\n"
    ";\n",
)


def _lint_modules(*files: tuple[str, str]) -> list[Diagnostic]:
    sources = [load_text(name, text) for name, text in files]
    return [
        d for d in run_sources(sources, select={"code/unknown-static-member"})
        if d.rule_id == "code/unknown-static-member"
    ]


def test_return_type_of_another_module_types_the_variable():
    # the line the rule was extended for: no declared type, the type is in the callee module
    diags = _lint_modules(
        _CALLEE,
        ("Витрина.xbsl",
         "метод Тест(Код: Строка): Число\n"
         "    знч Строки = Каталог.Позиции(Код)\n"
         "    возврат Строки.Количество()\n"
         ";\n"),
    )
    assert len(diags) == 1, [d.message for d in diags]
    assert "Массив" in diags[0].message and "Количество" in diags[0].message


def test_existing_member_of_the_returned_type_passes():
    diags = _lint_modules(
        _CALLEE,
        ("Витрина.xbsl",
         "метод Тест(Код: Строка): Число\n"
         "    знч Строки = Каталог.Позиции(Код)\n"
         "    возврат Строки.Размер()\n"
         ";\n"),
    )
    assert diags == [], [d.message for d in diags]


def test_callee_without_a_declared_return_type_is_silent():
    diags = _lint_modules(
        ("Каталог.xbsl", "@ВПроекте\nметод Позиции()\n    // ...\n;\n"),
        ("Витрина.xbsl",
         "метод Тест()\n"
         "    знч Строки = Каталог.Позиции()\n"
         "    Строки.Количество()\n"
         ";\n"),
    )
    assert diags == [], [d.message for d in diags]


def test_variable_named_after_the_module_is_not_read_as_a_module():
    # `пер Разделы = Разделы.ПолучитьВсе()` - the name means both in one method
    diags = _lint_modules(
        ("Разделы.xbsl", "@ВПроекте\nметод ПолучитьВсе(): Массив<Строка>\n    возврат []\n;\n"),
        ("Страница.xbsl",
         "метод Тест()\n"
         "    пер Разделы = Разделы.ПолучитьВсе()\n"
         ";\n"),
    )
    assert diags == [], [d.message for d in diags]


def test_twin_modules_make_the_name_unusable():
    diags = _lint_modules(
        _CALLEE,
        ("вложенный/Каталог.xbsl", "метод Позиции(): Число\n    возврат 0\n;\n"),
        ("Витрина.xbsl",
         "метод Тест(Код: Строка)\n"
         "    знч Строки = Каталог.Позиции(Код)\n"
         "    Строки.Количество()\n"
         ";\n"),
    )
    assert diags == [], [d.message for d in diags]


def test_method_declared_twice_in_the_callee_is_dropped():
    diags = _lint_modules(
        ("Каталог.xbsl",
         "метод Позиции(): Массив<Строка>\n    возврат []\n;\n"
         "метод Позиции(Код: Строка): Строка\n    возврат \"\"\n;\n"),
        ("Витрина.xbsl",
         "метод Тест()\n"
         "    знч Список = Каталог.Позиции()\n"
         "    Список.Количество()\n"
         ";\n"),
    )
    assert diags == [], [d.message for d in diags]


def test_form_attribute_named_like_a_module_is_not_a_module():
    diags = _lint_modules(
        _CALLEE,
        ("Форма.yaml",
         "ВидЭлемента: КомпонентИнтерфейса\nИмя: Форма\n"
         "Данные:\n  -\n    Имя: Каталог\n    Тип: Строка\n"),
        ("Форма.xbsl",
         "метод Тест(Код: Строка)\n"
         "    знч Строки = Каталог.Позиции(Код)\n"
         "    Строки.Количество()\n"
         ";\n"),
    )
    assert diags == [], [d.message for d in diags]


def test_constructor_names_the_type_of_a_variable():
    """`знч Х = новый Массив<Строка>()` names the type as plainly as an annotation.

    The build that lost a deploy cycle to `Количество()` (an array has `Размер`) had exactly
    this shape - a variable without an annotation, typed by its constructor.
    """
    diags = _lint(
        "метод Б(): Число\n"
        "    знч Список = новый Массив<Строка>()\n"
        "    возврат Список.Количество()\n"
        ";\n"
    )
    assert len(diags) == 1 and "Массив" in diags[0].message


def test_constructor_of_a_project_type_is_silent():
    # a project type is not in the stdlib catalog - its members are not ours to judge
    diags = _lint(
        "метод Б(): Число\n"
        "    знч Карточка = новый КарточкаЗаказа()\n"
        "    возврат Карточка.ЧтоУгодно()\n"
        ";\n"
    )
    assert diags == []


def test_correct_member_after_a_constructor_is_silent():
    diags = _lint(
        "метод В(): Число\n"
        "    знч Список = новый Массив<Строка>()\n"
        "    возврат Список.Размер()\n"
        ";\n"
    )
    assert diags == []
