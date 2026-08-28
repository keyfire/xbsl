"""The source translator: the dictionary model, code and yaml rewriting, the project walk."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from xbsl import engine
from xbsl.translation import dictionary as dict_module
from xbsl.translation.code import Resolver, translate_code
from xbsl.translation.project import translate_project
from xbsl.translation.reporting import FileReport
from xbsl.translation.yamlfile import translate_yaml


def _dictionary(
    tokens: dict | None = None, phrases: dict | None = None, literals: dict | None = None,
) -> dict_module.Dictionary:
    return dict_module.Dictionary(
        tokens=dict(tokens or {}), phrases=dict(phrases or {}), literals=dict(literals or {}),
    )


def _code(text: str, tokens=None, phrases=None, literals=None) -> tuple[str, FileReport]:
    source = engine.load_text("Модуль.xbsl", text)
    report = FileReport(path="Модуль.xbsl")
    out = translate_code(source, Resolver(_dictionary(tokens, phrases, literals)), report)
    return out, report


def _yaml(text: str, tokens=None, phrases=None, name="Задачи.yaml") -> tuple[str, FileReport]:
    source = engine.load_text(name, text)
    report = FileReport(path=name)
    out = translate_yaml(source, Resolver(_dictionary(tokens, phrases)), report)
    return out, report


# --- the dictionary ------------------------------------------------------------------------


def test_dictionary_merges_directory_and_refuses_conflicts(tmp_path: Path):
    folder = tmp_path / "xbsl-translation"
    folder.mkdir()
    (folder / "a.yaml").write_text(
        "version: 1\nlanguage: en\ntokens:\n    Задачи: Tasks\n", encoding="utf-8")
    (folder / "b.yaml").write_text(
        "tokens:\n    Шаги: Steps\nphrases:\n    \"текст\": \"text\"\n", encoding="utf-8")
    loaded = dict_module.load(folder)
    assert loaded.tokens == {"Задачи": "Tasks", "Шаги": "Steps"}
    assert loaded.phrases == {"текст": "text"}

    (folder / "c.yaml").write_text("tokens:\n    Задачи: Jobs\n", encoding="utf-8")
    with pytest.raises(dict_module.DictionaryError):
        dict_module.load(folder)


def test_dictionary_validates_token_values(tmp_path: Path):
    bad = tmp_path / "xbsl-translation.yaml"
    bad.write_text("tokens:\n    Задачи: \"With space\"\n", encoding="utf-8")
    with pytest.raises(dict_module.DictionaryError):
        dict_module.load(bad)


def test_dictionary_keyword_named_value_is_a_note_not_an_error(tmp_path: Path):
    file = tmp_path / "xbsl-translation.yaml"
    file.write_text("tokens:\n    Шаг: Step\n", encoding="utf-8")
    loaded = dict_module.load(file)
    assert loaded.tokens == {"Шаг": "Step"}
    assert loaded.notes


def test_dictionary_discover_walks_up(tmp_path: Path):
    (tmp_path / "xbsl-translation").mkdir()
    project = tmp_path / "e1c" / "app"
    project.mkdir(parents=True)
    assert dict_module.discover(project) == tmp_path / "xbsl-translation"


def test_stub_roundtrip(tmp_path: Path):
    stub = tmp_path / "missing.yaml"
    dict_module.write_stub(
        stub,
        {"Задачи": {"count": 3, "sample": "Задачи.yaml:1"},
         "Значок.svg": {"count": 1, "sample": "Форма.yaml:5", "resource": True}},
        {"комментарий: с двоеточием": {"count": 2, "sample": "Модуль.xbsl:7"}},
    )
    loaded = dict_module.load(stub)
    assert loaded.empty  # the empty values are stubs, not translations
    filled = stub.read_text(encoding="utf-8").replace('Задачи: ""', "Задачи: Tasks")
    stub.write_text(filled, encoding="utf-8")
    assert dict_module.load(stub).tokens == {"Задачи": "Tasks"}


# --- code ------------------------------------------------------------------------------------


def test_code_keywords_keep_case_and_idents_resolve():
    out, report = _code(
        "метод Посчитать(Задачи: Массив)\n"
        "    пер Итог = 0\n"
        "    для Задача из Задачи\n"
        "        если Истина\n"
        "            Итог = Итог + 1\n"
        "        ;\n"
        "    ;\n"
        "    возврат Итог\n"
        ";\n",
        tokens={"Посчитать": "Count", "Задачи": "Tasks", "Задача": "Task", "Итог": "Total"},
    )
    assert "method Count(Tasks: Array)" in out
    assert "var Total = 0" in out
    assert "for Task in Tasks" in out
    assert "if True" in out
    assert report.user_missing == 0


def test_code_reports_missing_tokens_and_translates_comments():
    out, report = _code(
        "// Задача помечается выполненной.\n"
        "пер Пометка = Истина  // хвостовое пояснение\n",
        phrases={"Задача помечается выполненной.": "The task is marked done."},
    )
    assert "// The task is marked done." in out
    assert "Пометка" in out  # not in the dictionary - left as written
    assert list(report.missing_tokens) == ["Пометка"]
    assert list(report.missing_phrases) == ["хвостовое пояснение"]
    assert report.phrases_done == 1


def test_code_translates_interpolation_and_query():
    out, report = _code(
        'пер Адрес = "%{АдресСтраницы}?p=plans"\n'
        "пер Выборка = Запрос{ ВЫБРАТЬ Наименование ИЗ Задачи КАК Т }\n",
        tokens={"АдресСтраницы": "PageAddress", "Задачи": "Tasks",
                "Наименование": "Name", "Адрес": "Address", "Выборка": "Selection"},
    )
    assert '"%{PageAddress}?p=plans"' in out
    # The alias Т is a platform pair too (the Latin T), which is only welcome.
    assert "Query{ SELECT Name FROM Tasks AS T }" in out
    assert report.user_missing == 0


def test_code_warns_on_string_equal_to_token():
    _out, report = _code(
        'пер Имя = "ОбработатьЗадачу"\n',
        tokens={"ОбработатьЗадачу": "HandleTask", "Имя": "Name"},
    )
    assert any(kind == "string-equals-token" for kind, *_ in report.warnings)


# --- yaml ------------------------------------------------------------------------------------


_CATALOG = """ВидЭлемента: Справочник
Ид: 42073842-db14-41d6-a17a-7b03a5d57933
Имя: Задачи
ОбластьВидимости: ВПроекте
Реквизиты:
    -
        Ид: 54c9050e-3377-4a67-8c34-c80d1074edfc
        Имя: Срок
        Тип: Дата
    -
        Имя: Родитель
        Тип: Задачи.Ссылка?
Иерархический: Истина
"""


def test_yaml_catalog_surfaces(tmp_path: Path):
    out, report = _yaml(_CATALOG, tokens={"Задачи": "Tasks", "Срок": "DueDate", "Родитель": "Parent"})
    assert "ElementKind: Catalog" in out
    assert "Id: 42073842-db14-41d6-a17a-7b03a5d57933" in out
    assert "Name: Tasks" in out
    assert "VisibilityScope: InProject" in out
    assert "Name: DueDate" in out
    assert "Type: Date" in out
    assert "Type: Tasks.Reference?" in out
    assert "Hierarchical: True" in out
    assert report.user_missing == 0


def test_yaml_component_tree():
    text = (
        "ВидЭлемента: КомпонентИнтерфейса\n"
        "Имя: КарточкаЗадачи\n"
        "Наследует:\n"
        "    Тип: ФормаОбъекта<Задачи.Объект>\n"
        "    Заголовок: Задача\n"
        "    Содержимое:\n"
        "        Тип: Группа\n"
        "        Компоновка: Вертикальная\n"
        "        РастягиватьПоГоризонтали: Истина\n"
        "        Содержимое:\n"
        "            -\n"
        "                Тип: Кнопка\n"
        "                Имя: КнопкаЗаписать\n"
        "                Заголовок: $СловарьСтрок.Записать\n"
        "                ПриНажатии: ОбработатьЗапись\n"
    )
    out, report = _yaml(text, tokens={
        "КарточкаЗадачи": "TaskCard", "Задачи": "Tasks", "КнопкаЗаписать": "SaveButton",
        "ОбработатьЗапись": "HandleSave", "СловарьСтрок": "StringsDictionary",
        "Записать": "Save",
    }, name="КарточкаЗадачи.yaml")
    assert "Type: ObjectForm<Tasks.Object>" in out
    assert "Layout: Vertical" in out
    assert "HorizontalStretch: True" in out
    assert "Title: Задача" in out  # a literal label is data and stays
    assert "Title: $StringsDictionary.Save" in out
    assert "OnClick: HandleSave" in out
    assert "Name: SaveButton" in out
    assert report.user_missing == 0


def test_yaml_enum_value_of_a_block_the_schema_does_not_describe():
    """The sorting item of a list and an item of its filter are not in the ui schema.

    Such a block names its property after the enumeration the value belongs to, and that
    table is in the schema even when the property is not: without it the key beside the value
    turned English while the value itself stayed Cyrillic, and the build refuses that.
    """
    text = (
        "ВидЭлемента: КомпонентИнтерфейса\n"
        "Имя: СписокЗадач\n"
        "Наследует:\n"
        "    Тип: Группа\n"
        "    Содержимое:\n"
        "        Тип: ДинамическийСписок<Задачи.Ссылка>\n"
        "        Сортировка:\n"
        "            -\n"
        "                Поле: Наименование\n"
        "                НаправлениеСортировки: ПоВозрастанию\n"
        "        Отбор:\n"
        "            -\n"
        "                Поле: Готова\n"
        "                ВидСравнения: Равно\n"
    )
    out, _report = _yaml(text, tokens={"СписокЗадач": "TaskList", "Задачи": "Tasks"},
                         name="СписокЗадач.yaml")

    assert "SortingDirection: Ascending" in out
    assert "ComparisonKind: Equal" in out


def test_yaml_value_outside_the_named_enumeration_is_left_alone():
    """Only the table of the enumeration the KEY names answers - never a global lookup.

    A word that is not a value of THAT enumeration is data: the project may name a property
    after a platform enumeration and put its own value there, and inventing a spelling for it
    would rename data.
    """
    text = (
        "ВидЭлемента: КомпонентИнтерфейса\n"
        "Имя: СписокЗадач\n"
        "Наследует:\n"
        "    Тип: Группа\n"
        "    Содержимое:\n"
        "        Тип: ДинамическийСписок<Задачи.Ссылка>\n"
        "        Сортировка:\n"
        "            -\n"
        "                НаправлениеСортировки: Наискосок\n"
    )
    out, _report = _yaml(text, tokens={"СписокЗадач": "TaskList", "Задачи": "Tasks"},
                         name="СписокЗадач.yaml")

    assert "SortingDirection: Наискосок" in out


def test_yaml_localized_strings_and_translation_body():
    base = (
        "ВидЭлемента: ЛокализованныеСтроки\n"
        "Ид: 11ac08d0-a2ef-4011-bdbc-0b7a1358e4e7\n"
        "Имя: СловарьСтрок\n"
        "Строки:\n"
        "    # подпись кнопки\n"
        "    Записать: Записать документ\n"
        "Шаблоны:\n"
        "    СчётчикШагов: \"шагов: $0\"\n"
    )
    tokens = {"СловарьСтрок": "StringsDictionary", "Записать": "Save", "СчётчикШагов": "StepCounter"}
    phrases = {"подпись кнопки": "the button label"}
    out, report = _yaml(base, tokens=tokens, phrases=phrases, name="СловарьСтрок.yaml")
    assert "ElementKind: LocalizedStrings" in out
    assert "Strings:" in out and "Templates:" in out
    assert "    Save: Записать документ" in out  # the key translates, the value is data
    assert "    StepCounter:" in out
    assert "# the button label" in out
    assert report.user_missing == 0

    body = "Строки:\n    Записать: Save the document\n"
    out_body, _report = _yaml(body, tokens=tokens, name="СловарьСтрок.yaml")
    assert out_body.startswith("Strings:\n")
    assert "    Save: Save the document" in out_body


def test_yaml_subsystem_descriptor():
    text = (
        "Использование:\n"
        "    - Основное\n"
        "Интерфейс: ВключатьВАвтоИнтерфейс\n"
    )
    out, report = _yaml(text, tokens={"Основное": "Main"}, name="Подсистема.yaml")
    assert "- Main" in out
    assert report.user_missing == 0


# --- the project walk --------------------------------------------------------------------------


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_translate_project_renames_swaps_and_flips(tmp_path: Path):
    root = tmp_path / "Acme" / "Задачник"
    _write(root / "Проект.yaml", (
        "Ид: ffeacdec-02d6-4f08-bcfa-be89e9a1861a\n"
        "РежимСовместимости: 9.0\n"
        "Поставщик: Acme\n"
        "Имя: Задачник\n"
        "Версия: 1.0.0\n"
        "Представление: \"Задачник (демо)\"\n"
        "ЯзыкиЛокализации: [Русский, Английский]\n"
        "ЯзыкПоУмолчанию: Русский\n"
        "ЯзыкРазработки: Русский\n"
    ))
    _write(root / "Проект.xbsl", "// обработчики обновления\n")
    _write(root / "Основное" / "Подсистема.yaml", "Интерфейс: ВключатьВАвтоИнтерфейс\n")
    _write(root / "Основное" / "СловарьСтрок.yaml", (
        "ВидЭлемента: ЛокализованныеСтроки\n"
        "Ид: 11ac08d0-a2ef-4011-bdbc-0b7a1358e4e7\n"
        "Имя: СловарьСтрок\n"
        "ОбластьВидимости: ВПроекте\n"
        "Строки:\n"
        "    Записать: Записать\n"
        "    БезПеревода: Только русское значение\n"
    ))
    _write(root / "Основное" / "Локализация" / "En" / "СловарьСтрок.yaml", (
        "Строки:\n"
        "    Записать: Save\n"
    ))
    dictionary = _dictionary(
        tokens={"Задачник": "TaskBook", "Основное": "Main", "СловарьСтрок": "StringsDictionary",
                "Записать": "Save", "БезПеревода": "Untranslated"},
        phrases={"обработчики обновления": "the update handlers"},
    )
    out = tmp_path / "out"
    report = translate_project(root, dictionary, out)

    assert (out / "Project.yaml").is_file()
    assert (out / "Project.xbsl").read_text(encoding="utf-8") == "// the update handlers\n"
    assert (out / "Main" / "Subsystem.yaml").is_file()

    base = (out / "Main" / "StringsDictionary.yaml").read_text(encoding="utf-8")
    assert "Name: StringsDictionary" in base
    assert "    Save: Save" in base  # the En value became the base value
    assert '    Untranslated: "Только русское значение"' in base  # kept, and reported
    # The problem names the key the SOURCE file spells (the translation next to it): the
    # reader greps the sources, and 'Untranslated' alone would need the reverse dictionary.
    assert any("'БезПеревода' (Untranslated)" in problem for problem in report.problems), \
        report.problems

    ru = (out / "Main" / "Localization" / "Ru" / "StringsDictionary.yaml").read_text(encoding="utf-8")
    assert ru.startswith("Strings:")
    assert "    Save: Записать" in ru

    project_yaml = (out / "Project.yaml").read_text(encoding="utf-8")
    assert "LocalizationLanguages: [Russian, English]" in project_yaml
    assert "DefaultLanguage: English" in project_yaml
    assert "DevelopmentLanguage: English" in project_yaml
    assert "Id: ffeacdec-02d6-4f08-bcfa-be89e9a1861a" in project_yaml


# --- the linter rule -----------------------------------------------------------------------------


def _rule_findings(paths):
    """Run the project rule the way the engine does: mapper per file, then the reduce."""
    from xbsl.rules import translation_gaps

    translation_gaps._dictionary_at.cache_clear()
    facts = {}
    for path in paths:
        source = engine.load(path)
        fact = translation_gaps._gaps_mapper(source)
        if fact is not None:
            facts[source.rel] = fact
    return [d.message for d in translation_gaps.missing_translation(facts)]


def _rule_findings(paths):
    """Run the project rule the way the engine does: mapper per file, then the reduce."""
    from xbsl.rules import translation_gaps

    translation_gaps._dictionary_at.cache_clear()
    facts = {}
    for path in paths:
        source = engine.load(path)
        fact = translation_gaps._gaps_mapper(source)
        if fact is not None:
            facts[source.rel] = fact
    return [d.message for d in translation_gaps.missing_translation(facts)]


def test_missing_translation_rule(tmp_path: Path):
    (tmp_path / "xbsl-translation").mkdir()
    (tmp_path / "xbsl-translation" / "dict.yaml").write_text(
        "tokens:\n    Задачи: Tasks\n", encoding="utf-8")
    module = tmp_path / "Задачи.xbsl"
    module.write_text(
        "// комментарий без перевода\n"
        "метод Посчитать()\n"
        "    возврат Задачи.Размер()\n"
        ";\n",
        encoding="utf-8",
    )
    texts = _rule_findings([module])
    assert any("Посчитать" in t for t in texts)
    assert any("комментарий без перевода" in t for t in texts)
    assert not any(t.startswith("Имя 'Задачи'") for t in texts)


def test_missing_translation_rule_reports_a_declared_platform_word(tmp_path: Path):
    """A word the platform knows is a gap when the PROJECT declares it - the gate refuses it."""
    (tmp_path / "xbsl-translation").mkdir()
    (tmp_path / "xbsl-translation" / "dict.yaml").write_text(
        "tokens:\n    Состояния: States\n", encoding="utf-8")
    catalog = tmp_path / "Состояния.yaml"
    catalog.write_text(
        "ВидЭлемента: Перечисление\nИмя: Состояния\nЭлементы:\n    -\n        Имя: Основная\n",
        encoding="utf-8",
    )
    module = tmp_path / "Модуль.xbsl"
    module.write_text("метод Вид()\n    возврат Состояния.Основная\n;\n", encoding="utf-8")
    texts = _rule_findings([catalog, module])
    assert any("Основная" in t and "объявлено проектом" in t for t in texts), texts


def test_missing_translation_rule_is_silent_without_a_dictionary(tmp_path: Path):
    module = tmp_path / "Задачи.xbsl"
    module.write_text("пер Пометка = Истина\n", encoding="utf-8")
    assert _rule_findings([module]) == []


def test_declared_names_are_never_translated_by_the_platform(tmp_path: Path):
    """A value the project declares moves only with a dictionary entry - never on its own.

    Without the gate the platform dictionary answered the USE (`SubscriptionKind.Main`)
    while the DECLARATION waited for an entry and stayed Russian - the pair no longer met
    and the build refused the tree.
    """
    from xbsl.translation import names

    root = tmp_path / "Acme" / "Demo"
    _write(root / "Задачи.yaml", (
        "ВидЭлемента: Перечисление\n"
        "Имя: Состояния\n"
        "Элементы:\n"
        "    -\n"
        "        Имя: Основная\n"
    ))
    _write(root / "Модуль.xbsl", "метод Вид()\n    возврат Состояния.Основная\n;\n")
    collected = names.collect(root, engine.load)
    assert "Основная" in collected and "Состояния" in collected

    # No entry: both halves stay as written, and the gap is reported once per place.
    report = translate_project(root, _dictionary(), swap_localization=False)
    assert "Основная" in report.merged_missing_tokens()

    # With an entry: both halves move together.
    out = tmp_path / "out"
    translate_project(
        root,
        _dictionary({"Состояния": "States", "Основная": "Main", "Модуль": "Module",
                     "Задачи": "Tasks", "Вид": "Kind"}),
        out,
        swap_localization=False,
    )
    assert "Name: Main" in (out / "Tasks.yaml").read_text(encoding="utf-8")
    assert "return States.Main" in (out / "Module.xbsl").read_text(encoding="utf-8")


def test_dictionary_keys_live_in_their_own_namespace(tmp_path: Path):
    """A dictionary key is the project's word inside its dictionary - and nowhere else.

    Mixing keys into the project-wide set would let the translation of a caption reach a
    standard attribute of the same name (a key "Наименование" is a caption, the attribute is
    the platform's `Name`).
    """
    from xbsl.translation import names

    root = tmp_path / "Acme" / "Demo"
    _write(root / "Словарь.yaml", (
        "ВидЭлемента: ЛокализованныеСтроки\n"
        "Имя: Словарь\n"
        "Строки:\n"
        "    Наименование: Название\n"
    ))
    _write(root / "Задачи.yaml", (
        "ВидЭлемента: Справочник\n"
        "Имя: Задачи\n"
        "Реквизиты:\n"
        "    -\n"
        "        Имя: Наименование\n"
        "        Длина: 150\n"
    ))
    _write(root / "Модуль.xbsl", "метод Подпись()\n    возврат Словарь.Наименование()\n;\n")

    assert "Наименование" not in names.collect(root, engine.load)
    assert names.dictionary_scopes(root, engine.load) == frozenset({"Словарь"})

    out = tmp_path / "out"
    translate_project(
        root,
        _dictionary({"Словарь": "Strings", "Задачи": "Tasks", "Модуль": "Module",
                     "Подпись": "Caption", "Словарь.Наименование": "Title"}),
        out,
        swap_localization=False,
    )
    # The attribute takes the platform spelling, the key takes the qualified entry.
    assert "Name: Name" in (out / "Tasks.yaml").read_text(encoding="utf-8")
    assert "    Title: Название" in (out / "Strings.yaml").read_text(encoding="utf-8")
    assert "return Strings.Title()" in (out / "Module.xbsl").read_text(encoding="utf-8")


def test_facets_stay_platform_even_when_the_project_declares_the_word(tmp_path: Path):
    """`.Ссылка` is a facet of a type expression - a project attribute of that name must not gate it."""
    resolver = Resolver(_dictionary({"Задачи": "Tasks"}), frozenset({"Задачи", "Ссылка"}))
    report = FileReport(path="x.yaml")
    from xbsl.translation.code import translate_type_expression

    assert translate_type_expression("Задачи.Ссылка?", resolver, report) == "Tasks.Reference?"


def test_translating_an_already_english_tree_changes_nothing(tmp_path: Path):
    """Idempotence: a translated project run through the translator again comes out identical.

    A CI job may translate a tree that is already English (a mixed repository, a second pass);
    a rewrite that "translated" English words back would be silent corruption.
    """
    root = tmp_path / "Acme" / "Demo"
    _write(root / "Project.yaml", (
        "Id: ffeacdec-02d6-4f08-bcfa-be89e9a1861a\n"
        "CompatibilityMode: 9.0\n"
        "Vendor: Acme\n"
        "Name: Demo\n"
        "Version: 1.0.0\n"
        "Presentation: \"Demo\"\n"
        "LocalizationLanguages: [Russian]\n"
        "DevelopmentLanguage: Russian\n"
    ))
    _write(root / "Main" / "Subsystem.yaml", "Interface:\n    IncludeInAutoInterface: True\n")
    _write(root / "Main" / "Tasks.yaml", (
        "ElementKind: Catalog\n"
        "Name: Tasks\n"
        "Attributes:\n"
        "    -\n"
        "        Name: DueDate\n"
        "        Type: Date\n"
    ))
    _write(root / "Main" / "Tasks.xbsl", "method Count()\n    return 0\n;\n")
    out = tmp_path / "out"
    translate_project(root, _dictionary(), out)
    for path in sorted(root.rglob("*")):
        if path.is_file():
            twin = out / path.relative_to(root)
            assert twin.is_file(), twin
            assert twin.read_bytes() == path.read_bytes(), twin


# --- the dictionary as a table ----------------------------------------------------------------


def _dict_dir(tmp_path: Path) -> Path:
    folder = tmp_path / "xbsl-translation"
    folder.mkdir()
    (folder / "010-objects.yaml").write_text(
        "version: 1\nlanguage: en\ntokens:\n"
        "    Задачи: Tasks\n"
        "    Словарь.Наименование: Title\n"
        "phrases:\n"
        '    "строка комментария": "a comment line"\n',
        encoding="utf-8",
    )
    return folder


def test_entries_are_read_with_their_place(tmp_path: Path):
    from xbsl.translation import entries

    folder = _dict_dir(tmp_path)
    rows = {(e.kind, e.key): e for e in entries.read_entries(folder)}
    assert rows[("token", "Задачи")].value == "Tasks"
    assert rows[("token", "Задачи")].line == 4
    assert rows[("token", "Словарь.Наименование")].scope == "Словарь"
    assert rows[("phrase", "строка комментария")].value == "a comment line"


def test_plan_entries_adds_corrects_and_removes(tmp_path: Path):
    from xbsl.translation import entries

    folder = _dict_dir(tmp_path)
    plan = entries.plan_entries(folder, [
        {"key": "Шаги", "value": "Steps", "kind": "token"},          # new
        {"key": "Задачи", "value": "Jobs", "kind": "token"},          # corrected in place
        {"key": "строка комментария", "value": "", "kind": "phrase"},  # removed
    ])
    assert plan["added"] == 1 and plan["changed"] == 1 and plan["removed"] == 1
    target = str(folder / entries.DEFAULT_TARGET)
    assert "    Шаги: Steps" in plan["files"][target]
    edited = plan["files"][str(folder / "010-objects.yaml")]
    assert "    Задачи: Jobs" in edited
    assert "строка комментария" not in edited
    # Nothing is written by planning alone.
    assert not (folder / entries.DEFAULT_TARGET).exists()

    entries.write_entries(folder, [{"key": "Шаги", "value": "Steps", "kind": "token"}])
    assert (folder / entries.DEFAULT_TARGET).is_file()


def test_gaps_carry_count_place_and_suggestion(tmp_path: Path):
    from xbsl.translation import entries

    root = tmp_path / "Acme" / "Demo"
    _write(root / "Задачи.yaml", (
        "ВидЭлемента: Справочник\n"
        "Имя: Задачи\n"
        "Реквизиты:\n"
        "    -\n"
        "        Имя: Заголовок\n"
        "        Тип: Строка\n"
    ))
    _write(root / "Модуль.xbsl", "// пояснение\nметод Подпись()\n    возврат Задачи.Заголовок\n;\n")
    gaps = {gap.key: gap for gap in entries.gaps_of_project(root, _dictionary())}
    assert gaps["Заголовок"].kind == "token"
    assert gaps["Заголовок"].suggestion == "Title"  # the platform spelling, offered as a hint
    assert gaps["Заголовок"].places and gaps["Заголовок"].places[0][1] > 0
    assert gaps["пояснение"].kind == "phrase"


def test_internal_platform_names_are_not_suggested():
    """A metadata class name is not a translation - offering it would look authoritative."""
    from xbsl.translation import entries

    assert entries._suggestion("Код") == ""      # the dictionary only knows `CodeAttrMd`
    assert entries._suggestion("Объект") == "Object"


def test_rule_finding_carries_machine_readable_data(tmp_path: Path):
    (tmp_path / "xbsl-translation").mkdir()
    (tmp_path / "xbsl-translation" / "d.yaml").write_text("tokens:\n    Задачи: Tasks\n", encoding="utf-8")
    module = tmp_path / "Задачи.xbsl"
    module.write_text("метод Заголовок()\n    возврат \"\"\n;\n", encoding="utf-8")

    from xbsl.rules import translation_gaps

    translation_gaps._dictionary_at.cache_clear()
    facts = {}
    source = engine.load(module)
    facts[source.rel] = translation_gaps._gaps_mapper(source)
    found = [d for d in translation_gaps.missing_translation(facts) if d.data]
    payload = [d.data["translation"] for d in found]
    assert {"kind": "token", "key": "Заголовок", "suggestion": "Title"} in payload


# --- json resources: a key is the other half of a structure field ---------------------------


def test_json_resource_keys_follow_their_structure_fields(tmp_path: Path):
    """A field renamed in the module and a key left in the data bind nothing - and say nothing."""
    from xbsl.translation.jsonfile import translate_json
    from xbsl.translation.names import structure_field_owners

    source = engine.load_text("Справочники.xbsl", (
        "структура JsonКорень\n"
        "    пер Шаги: Массив<JsonШаг>\n"
        "    пер Задачи: Массив<JsonЗадача>\n"
        ";\n"
        "перечисление ВидЗадачи\n"
        "    Обычная\n"
        ";\n"
        "метод ПрочитатьШаги()\n"
        ";\n"
    ))
    owners = structure_field_owners(source)
    assert set(owners) == {"Шаги", "Задачи"}
    assert owners["Шаги"] == {"JsonКорень"}
    fields = {field: next(iter(group)) for field, group in owners.items()}

    text = (
        '{\n'
        '    "Шаги": [ {"Код": "первый"} ],\n'
        '    "Прочее": {"Шаги": 1},\n'
        '    "Подпись": "тут написано \\"Шаги\\": не ключ"\n'
        '}\n'
    )
    report = FileReport(path="Справочники.json")
    out = translate_json(text, _dictionary({"Шаги": "Steps", "Код": "Code"}), fields, report)

    assert '"Steps": [ {"Код": "первый"} ]' in out   # the key of a field moves, a data key stays
    assert '"Прочее": {"Steps": 1}' in out           # nesting is a field too, wherever it sits
    assert 'тут написано \\"Шаги\\": не ключ' in out  # a value that spells a key is still a value
    assert report.data_keys == 2


def test_json_resource_key_without_an_entry_is_counted_not_guessed(tmp_path: Path):
    from xbsl.translation.jsonfile import translate_json

    report = FileReport(path="Данные.json")
    out = translate_json('{"Шаги": 1}\n', _dictionary(), {"Шаги": "JsonКорень"}, report)
    assert out == '{"Шаги": 1}\n'
    assert (report.data_keys, report.data_keys_missing) == (0, 1)


def test_translate_project_renames_json_keys_of_its_own_resources(tmp_path: Path):
    root = tmp_path / "Acme" / "Задачник"
    _write(root / "Проект.yaml", (
        "Ид: ffeacdec-02d6-4f08-bcfa-be89e9a1861a\n"
        "РежимСовместимости: 9.0\n"
        "Поставщик: Acme\n"
        "Имя: Задачник\n"
        "Версия: 1.0.0\n"
    ))
    _write(root / "Основное" / "Справочники.xbsl", (
        "структура JsonКорень\n"
        "    пер Шаги: Массив<Строка>\n"
        ";\n"
    ))
    _write(root / "Основное" / "Ресурсы" / "Справочники.json", '{\n    "Шаги": ["первый"]\n}\n')
    dictionary = _dictionary(tokens={
        "Задачник": "TaskBook", "Основное": "Main", "Справочники": "Catalogs",
        "Ресурсы": "Resources", "Шаги": "Steps", "JsonКорень": "JsonRoot",
    })
    out = tmp_path / "out"
    report = translate_project(root, dictionary, out)

    written = (out / "Main" / "Resources" / "Catalogs.json").read_text(encoding="utf-8")
    assert written == '{\n    "Steps": ["первый"]\n}\n'
    assert report.totals()["data_keys"] == 1


def test_resource_path_literal_follows_the_renamed_tree():
    """The pass renames the resource files - a path written as data has to follow them."""
    out, report = _code(
        'метод Значок()\n'
        '    возврат ПакетРесурсов.Текущий().Получить("Значки/%Код.svg")\n'
        '    // подпись остаётся: "Значки" тут не путь\n'
        ';\n',
        tokens={"Значок": "Icon", "Значки": "Icons", "Код": "Code"},
        phrases={'подпись остаётся: "Значки" тут не путь': 'the label stays: "Значки" is no path here'},
    )
    assert '"Icons/%Code.svg"' in out
    assert 'the label stays: "Значки" is no path here' in out


def test_a_sentence_with_a_slash_is_not_a_resource_path():
    out, _ = _code(
        'метод Подсказка()\n'
        '    возврат "Задачи / Шаги"\n'
        ';\n',
        tokens={"Подсказка": "Hint", "Задачи": "Tasks", "Шаги": "Steps"},
    )
    assert '"Задачи / Шаги"' in out


def test_a_regular_expression_is_not_a_resource_path():
    """A pattern has slashes; the slashes are syntax, not a path to a resource file."""
    out, _ = _code(
        'метод Разобрать()\n'
        '    возврат Образец{"<a[^>]*>(?<Заголовок>.*?)</a>"}\n'
        ';\n',
        tokens={"Разобрать": "Parse", "Заголовок": "Title"},
    )
    # The group NAME is the project's own and moves by the token map (see the group
    # tests below); the pattern around it is untouched - nothing is read as a file name.
    assert '"<a[^>]*>(?<Title>.*?)</a>"' in out


def test_dictionary_writer_copies_the_indent_of_the_section(tmp_path: Path):
    """A file written with two spaces stays valid: four-space entries would nest inside the last."""
    import yaml as yaml_module

    from xbsl.translation.entries import _merge_section, read_entries

    two_spaces = "version: 1\ntokens:            # пояснение секции\n  Задачи: Tasks\n"
    merged = _merge_section(two_spaces, "tokens", {"Шаги": "Steps"})
    assert merged.endswith("  Задачи: Tasks\n  Шаги: Steps\n")
    assert yaml_module.safe_load(merged)["tokens"] == {"Задачи": "Tasks", "Шаги": "Steps"}

    # A section whose head carries a comment is READ by the table too: a writer that missed the
    # entry would add a key that is already there, and the dictionary would refuse the duplicate.
    path = tmp_path / "xbsl-translation" / "010.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(merged, encoding="utf-8")
    keys = {entry.key for entry in read_entries(path.parent)}
    assert keys == {"Задачи", "Шаги"}


def test_a_key_that_carries_a_quote_is_recognised_not_duplicated(tmp_path: Path):
    """A comment line citing something is an ordinary key - and the writer must find it there."""
    from xbsl.translation.entries import plan_entries, read_entries

    folder = tmp_path / "xbsl-translation"
    folder.mkdir()
    cited_key = 'Коды через "|" с обеих сторон.'
    (folder / "030-phrases.yaml").write_text(
        'version: 1\nlanguage: en\nphrases:\n'
        f'    {json.dumps(cited_key, ensure_ascii=False)}: "The codes are separated by \\"|\\"."\n',
        encoding="utf-8",
    )

    read = {entry.key: entry.value for entry in read_entries(folder)}
    assert cited_key in read, "ключ с кавычкой внутри не прочитался"

    plan = plan_entries(folder, [{"key": cited_key, "value": "Codes on both sides.", "kind": "phrase"}])
    assert (plan["changed"], plan["added"]) == (1, 0), "правка ушла новой записью - в словаре вырос дубль"
    written = "".join(plan["files"].values())
    assert written.count(json.dumps(cited_key, ensure_ascii=False)) == 1
    assert "Codes on both sides." in written


# --- literals: the names and the messages a project writes as strings -------------------------


def test_the_literals_plane_merges_and_refuses_a_conflict(tmp_path: Path):
    """The third plane loads like the other two - and a second reading is a refusal, not a guess."""
    folder = tmp_path / "xbsl-translation"
    folder.mkdir()
    (folder / "a.yaml").write_text(
        "version: 1\nlanguage: en\nliterals:\n"
        '    "Заявка не найдена": "The request was not found"\n',
        encoding="utf-8")
    (folder / "b.yaml").write_text("literals:\n    Обложка: Cover\n", encoding="utf-8")
    loaded = dict_module.load(folder)
    assert loaded.literals == {"Заявка не найдена": "The request was not found", "Обложка": "Cover"}
    assert loaded.literal("Обложка") == "Cover"
    assert not loaded.empty  # a plane of its own still fills the dictionary

    (folder / "c.yaml").write_text("literals:\n    Обложка: Jacket\n", encoding="utf-8")
    with pytest.raises(dict_module.DictionaryError):
        dict_module.load(folder)


def test_literal_is_replaced_whole():
    """A NAME written as a string is data the project must name itself - and it goes whole."""
    out, report = _code(
        'метод Прочитать()\n'
        '    возврат Параметры.Получить("ТокенЗаданияЗадач")\n'
        ';\n',
        tokens={"Прочитать": "Read"},
        literals={"ТокенЗаданияЗадач": "TaskJobToken"},
    )
    assert '"TaskJobToken"' in out
    assert report.literals_done == 1
    assert not report.missing_literals


def test_literal_with_an_interpolation_keeps_the_source_spelling_in_the_key():
    """The author writes the sentence as they see it; the code inside moves by the usual path."""
    out, report = _code(
        'метод Сообщить(Описание: Строка)\n'
        '    возврат "Не разобрано тело: %{Описание}"\n'
        ';\n',
        tokens={"Сообщить": "Report", "Описание": "Details"},
        literals={"Не разобрано тело: %{Описание}": "Could not parse the body: %{Описание}"},
    )
    assert '"Could not parse the body: %{Details}"' in out
    assert report.literals_done == 1


def test_a_literal_inside_a_query_or_a_pattern_is_code_not_data():
    """Inside `Запрос{...}` and `Образец{...}` the text is a program - the plane stays out."""
    out, report = _code(
        'метод Отобрать()\n'
        '    пер Найденные = Запрос{ ВЫБРАТЬ Ссылка ИЗ Задачи КАК Т ГДЕ Т.Состояние = "Новая" }\n'
        '    возврат Образец{"^(?<Состояние>Новая)$"}\n'
        ';\n',
        tokens={"Отобрать": "Select", "Задачи": "Tasks", "Найденные": "Found",
                "Состояние": "State"},
        literals={"Новая": "New"},
    )
    assert '= "Новая" }' in out, "литерал запроса заменён планом literals"
    # The TEXT of the pattern is a program and the plane stays out of it; only the name
    # of the named group moves, and by the token map - the code reads the group by it.
    assert '"^(?<State>Новая)$"' in out, "литерал образца заменён планом literals"
    assert report.literals_done == 0
    assert not report.missing_literals
    # Out of the plane's reach, but not out of sight: a real project has hundreds of such
    # blocks, and a literal nobody ever shows is a literal nobody ever checks.
    kept = {text: (line, col) for text, line, col in report.texts_kept}
    assert kept["Новая"][0] == 2
    assert kept["^(?<Состояние>Новая)$"][0] == 3


def test_a_cyrillic_literal_without_an_entry_is_counted_and_shown_as_a_gap(tmp_path: Path):
    """What the plane does not name stays Russian - and says so in the report and the table."""
    from xbsl.translation import entries

    root = tmp_path / "Acme" / "Demo"
    _write(root / "Модуль.xbsl",
           'метод Проверить()\n    возврат "Заявка не найдена"\n;\n')
    report = translate_project(
        root, _dictionary(tokens={"Проверить": "Check", "Модуль": "Module"}), None)
    totals = report.totals()
    assert totals["missing_literals"] == 1
    assert totals["coverage"] == 1.0, "литералы испортили покрытие словаря"

    gaps = {gap.key: gap for gap in entries.gaps_of_project(root, _dictionary())}
    assert gaps["Заявка не найдена"].kind == "literal"
    assert gaps["Заявка не найдена"].count == 1
    assert gaps["Заявка не найдена"].suggestion == ""


def test_a_query_literal_is_reported_as_kept_data_and_asks_for_no_entry(tmp_path: Path):
    """The project-wide surfaces agree: such a literal is visible, but it is not a gap."""
    from xbsl.translation import entries

    root = tmp_path / "Acme" / "Demo"
    _write(root / "Модуль.xbsl",
           'метод Отобрать()\n'
           '    возврат Запрос{ ВЫБРАТЬ Ссылка ИЗ Задачи КАК Т ГДЕ Т.Состояние = "Новая" }\n'
           ';\n')
    report = translate_project(
        root, _dictionary(tokens={"Отобрать": "Select", "Задачи": "Tasks", "Модуль": "Module"}),
        None)
    totals = report.totals()
    assert totals["texts_kept"] == 1, "литерал запроса не показан нигде"
    assert totals["missing_literals"] == 0, "литерал запроса засчитан пробелом словаря"
    kept = report.files["Модуль.xbsl"].texts_kept
    assert kept == [("Новая", 2, 70)]

    assert not [gap for gap in entries.gaps_of_project(root, _dictionary()) if gap.kind == "literal"]


# --- an entry writes the text the way the source writes it, and the engine checks it ----------

#: The shape half the messages of a real project have: a quote inside a quoted string.
_QUOTED = 'Не заполнено поле \\"Наименование\\"'


def _literals_file(folder: Path, key: str, value: str) -> Path:
    """A one-entry dictionary written the way a person writes one: single-quoted yaml scalars.

    Single quotes are what keeps the convention honest - yaml passes a backslash through them
    untouched, so the line carries exactly the characters the source carries and the author
    escapes once, for XBSL, and never again for yaml.
    """
    folder.mkdir(parents=True, exist_ok=True)
    file = folder / "a.yaml"
    file.write_text(
        f"version: 1\nlanguage: en\nliterals:\n    '{key}': '{value}'\n", encoding="utf-8")
    return file


def test_the_key_and_the_value_are_the_source_text_with_its_own_escaping(tmp_path: Path):
    """One escaping, the one the code already carries - the dictionary asks for no second."""
    folder = tmp_path / "xbsl-translation"
    _literals_file(folder, _QUOTED, 'The \\"Name\\" field is empty')
    loaded = dict_module.load(folder)
    assert loaded.literal(_QUOTED) == 'The \\"Name\\" field is empty'


@pytest.mark.parametrize("value, reason", [
    ('Поле "Наименование" пустое', "кавычка"),          # a bare quote ends the literal early
    ("Путь C:\\temp\\", "слеш"),                        # a trailing backslash eats the quote
    ("Первая\nВторая", "перевод строки"),               # a break splits one line into two
    ("Путь C:\\мой", "последовательность"),             # \м opens nothing the literal knows
    ("Итого: %{Сумма", "лексер"),                       # an interpolation swallows the quote
])
def test_a_value_that_is_not_a_literal_body_is_refused_on_load(tmp_path, value, reason):
    """The plane refuses a broken value the way the tokens plane refuses a broken name."""
    folder = tmp_path / "xbsl-translation"
    _literals_file(folder, "Ошибка", "@@")  # a valid file first, so the refusal is the value's
    (folder / "a.yaml").write_text(
        "version: 1\nlanguage: en\nliterals:\n"
        + f"    Ошибка: {json.dumps(value, ensure_ascii=False)}\n",
        encoding="utf-8")
    with pytest.raises(dict_module.DictionaryError) as caught:
        dict_module.load(folder)
    assert "Ошибка" in str(caught.value)
    assert reason in str(caught.value), str(caught.value)


def test_a_key_that_could_never_be_a_literal_body_is_refused_too(tmp_path: Path):
    """A key no source could carry names nothing - a silent dud, not a translation."""
    folder = tmp_path / "xbsl-translation"
    folder.mkdir()
    (folder / "a.yaml").write_text(
        'version: 1\nlanguage: en\nliterals:\n    \'Поле "Имя"\': "The Name field"\n',
        encoding="utf-8")
    with pytest.raises(dict_module.DictionaryError):
        dict_module.load(folder)


def test_an_escaped_quote_survives_to_the_output_and_the_lexer_sees_one_token(tmp_path: Path):
    """The whole point of the check: what the plane writes back still lexes as ONE literal."""
    from xbsl import lexer

    out, report = _code(
        'метод Проверить()\n'
        f'    возврат "{_QUOTED}"\n'
        ';\n',
        tokens={"Проверить": "Check"},
        literals={_QUOTED: 'The \\"Name\\" field is empty'},
    )
    assert report.literals_done == 1
    assert 'return "The \\"Name\\" field is empty"' in out, out
    strings = [tok for tok in lexer.tokenize(out) if tok.kind == "STRING"]
    assert len(strings) == 1, [tok.value for tok in strings]
    assert not strings[0].flags.get("unterminated")
    assert strings[0].value == '"The \\"Name\\" field is empty"'


def test_the_summary_counts_literals_in_one_unit(tmp_path: Path):
    """Translated and missing are both DISTINCT texts - the occurrences are named apart."""
    root = tmp_path / "Acme" / "Demo"
    _write(root / "Модуль.xbsl",
           'метод Проверить()\n'
           '    Сообщить("Задача записана")\n'
           '    Сообщить("Задача записана")\n'
           '    возврат "Заявка не найдена"\n'
           ';\n')
    report = translate_project(
        root,
        _dictionary(tokens={"Проверить": "Check", "Модуль": "Module"},
                    literals={"Задача записана": "The task is saved"}),
        None)
    totals = report.totals()
    assert totals["literals_translated"] == 1, "переведённые считаются вхождениями"
    assert totals["missing_literals"] == 1
    assert totals["literal_occurrences"] == 2, "вхождения потеряны вовсе"


def test_a_broken_literal_value_is_refused_at_the_write_too(tmp_path: Path):
    """Refused where it is typed, not a day later when the dictionary next loads."""
    from xbsl.translation import entries

    folder = tmp_path / "xbsl-translation"
    folder.mkdir()
    result = entries.write_entries(folder, [
        {"key": "Готово", "value": "Done", "kind": "literal"},
        {"key": _QUOTED, "value": 'The "Name" field is empty', "kind": "literal"},
    ])
    assert (result["added"], len(result["refused"])) == (1, 1)
    assert result["refused"][0]["key"] == _QUOTED
    loaded = dict_module.load(folder)
    assert loaded.literals == {"Готово": "Done"}, "негодная запись всё-таки попала в словарь"


def test_set_with_the_literal_kind_writes_into_the_literals_plane(tmp_path: Path):
    from xbsl.translation import entries

    folder = tmp_path / "xbsl-translation"
    folder.mkdir()
    entries.write_entries(folder, [
        {"key": "Заявка не найдена", "value": "The request was not found", "kind": "literal"},
    ])
    loaded = dict_module.load(folder)
    assert loaded.literals == {"Заявка не найдена": "The request was not found"}
    rows = {(e.kind, e.key): e for e in entries.read_entries(folder)}
    assert rows[("literal", "Заявка не найдена")].value == "The request was not found"


def test_rule_reports_an_untranslated_literal_with_its_own_kind(tmp_path: Path):
    (tmp_path / "xbsl-translation").mkdir()
    (tmp_path / "xbsl-translation" / "d.yaml").write_text(
        "tokens:\n    Проверить: Check\n", encoding="utf-8")
    module = tmp_path / "Модуль.xbsl"
    module.write_text('метод Проверить()\n    возврат "Заявка не найдена"\n;\n', encoding="utf-8")

    from xbsl.rules import translation_gaps

    translation_gaps._dictionary_at.cache_clear()
    source = engine.load(module)
    facts = {source.rel: translation_gaps._gaps_mapper(source)}
    payload = [d.data["translation"] for d in translation_gaps.missing_translation(facts) if d.data]
    assert {"kind": "literal", "key": "Заявка не найдена"} in payload


# --- comments are re-wrapped after the translation lengthened them ---------------------------

#: A paragraph whose English runs longer than its Russian: line for line it no longer fits.
_RU_PARAGRAPH = [
    "Список задач заполняется один раз при открытии карточки, а затем обновляется точечно",
    "по событию записи: полная перечитка на каждое изменение обходится слишком дорого",
    "и заметна пользователю на больших наборах данных подчинённого справочника шагов",
]
_EN_PARAGRAPH = [
    "The task list is filled once when the card opens and after that is refreshed point by"
    " point on the write event",
    "a full re-read on every change costs too much and the user notices it on large data sets"
    " of the subordinate steps catalog",
    "so the pass keeps the rows it already has and touches only the row the write event"
    " actually changed in the list",
]


def _long_lines(text: str) -> list[int]:
    """The lines style/line-length flags - the rule's own verdict, not a length guess."""
    diagnostics = engine.run_sources(
        [engine.load_text("Модуль.xbsl", text)], select={"style/line-length"})
    return [d.line for d in diagnostics]


def _comment_lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.lstrip().startswith("//")]


def _comment_text(text: str) -> str:
    """Everything the `//` lines say, as one string - what the re-wrap must not lose."""
    payloads = [line.lstrip()[2:].strip() for line in _comment_lines(text)]
    return " ".join(payload for payload in payloads if payload)


def test_a_translated_paragraph_is_wrapped_back_under_the_limit():
    module = "метод Ф()\n" + "".join(f"    // {line}\n" for line in _RU_PARAGRAPH) + ";\n"
    assert _long_lines(module) == [], "the source itself is within the limit"

    out, _ = _code(module, phrases=dict(zip(_RU_PARAGRAPH, _EN_PARAGRAPH)))
    assert _long_lines(out) == []
    assert _comment_text(out) == " ".join(_EN_PARAGRAPH), "the text of the paragraph survived"
    assert all(line.startswith("    // ") for line in _comment_lines(out))


def test_a_comment_that_still_fits_is_left_alone():
    module = "метод Ф()\n    // Короткая строка\n    // и вторая\n;\n"
    out, _ = _code(module, phrases={
        "Короткая строка": "A short line", "и вторая": "and a second one"})
    assert out == "method Ф()\n    // A short line\n    // and a second one\n;\n"


def test_a_frame_line_keeps_its_shape():
    frame = "─── Заголовок раздела ───"
    module = ("метод Ф()\n"
              f"    // {frame}\n"
              + "".join(f"    // {line}\n" for line in _RU_PARAGRAPH) + ";\n")
    out, _ = _code(module, phrases={
        frame: "─── Section title ───", **dict(zip(_RU_PARAGRAPH, _EN_PARAGRAPH))})
    assert _comment_lines(out)[0] == "    // ─── Section title ───"
    assert _long_lines(out) == []
    assert _comment_text(out) == "─── Section title ─── " + " ".join(_EN_PARAGRAPH)


def test_a_list_is_not_glued_into_a_paragraph():
    items = [
        "- первый пункт списка",
        "- второй пункт списка, который после перевода станет заметно длиннее",
    ]
    english = [
        "- the first item of the list",
        "- the second item of the list, which after the translation grows well past the width"
        " limit of the project and would be re-split if the list were prose",
    ]
    module = "метод Ф()\n" + "".join(f"    // {line}\n" for line in items) + ";\n"
    out, _ = _code(module, phrases=dict(zip(items, english)))
    assert _comment_lines(out) == [f"    // {line}" for line in english], "line for line"


def test_a_table_row_and_a_code_sample_are_not_reflowed():
    rows = [
        "Поле        | Тип     | Назначение",
        "Наименование| Строка  | заголовок задачи, который после перевода вырастет по ширине",
    ]
    english = [
        "Field       | Type    | Purpose",
        "Description | String  | the caption of the task, which after the translation grows"
        " past the width limit of the project and must still keep its columns",
    ]
    module = "метод Ф()\n" + "".join(f"    // {line}\n" for line in rows) + ";\n"
    out, _ = _code(module, phrases=dict(zip(rows, english)))
    assert _comment_lines(out) == [f"    // {line}" for line in english], "the columns stay"


def test_a_line_long_in_the_source_stays_as_it_was_written():
    long_ru = "Подробности: https://example.invalid/docs/задачи/" + "х" * 90
    long_en = "Details: https://example.invalid/docs/tasks/" + "x" * 90
    module = f"метод Ф()\n    // {long_ru}\n;\n"
    assert _long_lines(module) == [2], "the author already wrote it over the limit"

    out, _ = _code(module, phrases={long_ru: long_en})
    assert _comment_lines(out) == [f"    // {long_en}"], "written that way on purpose"


def test_a_long_source_line_does_not_drag_its_neighbours_into_a_paragraph():
    long_ru = "Ссылка: https://example.invalid/" + "ч" * 100
    long_en = "Link: https://example.invalid/" + "c" * 100
    module = ("метод Ф()\n"
              f"    // {long_ru}\n"
              + "".join(f"    // {line}\n" for line in _RU_PARAGRAPH) + ";\n")
    out, _ = _code(module, phrases={long_ru: long_en, **dict(zip(_RU_PARAGRAPH, _EN_PARAGRAPH))})
    assert _comment_lines(out)[0] == f"    // {long_en}"
    assert _long_lines(out) == [2], "only the paragraph under it needed the re-split"


def test_a_doc_comment_is_not_reflowed():
    ru = "Возвращает список шагов задачи в порядке их выполнения исполнителем"
    en = ("Returns the list of the steps of the task in the order in which the performer of the"
          " task is expected to run them, one after another and skipping none of them")
    module = f"/** {ru} */\nметод Ф()\n;\n"
    assert _long_lines(module) == [], "the source itself is within the limit"

    out, _ = _code(module, phrases={ru: en})
    assert out.splitlines()[0] == f"/** {en} */", "a doc comment stays one line"
    assert _long_lines(out) == [1], "over the limit and still not re-flowed"


def test_a_comment_after_code_keeps_its_line():
    ru = "пересчёт делается один раз"
    en = ("the recalculation is done once, and every later change only touches the row that the"
          " write event reported")
    module = f"метод Ф()\n    знч Х = 1 // {ru}\n;\n"
    out, _ = _code(module, phrases={ru: en})
    assert out.splitlines()[1] == f"    val Х = 1 // {en}", "it explains the statement next to it"
    assert _long_lines(out) == [2], "over the limit and still left where it is"


def test_the_windows_line_ending_of_a_block_survives_the_rewrap():
    module = "метод Ф()\r\n" + "".join(f"    // {line}\r\n" for line in _RU_PARAGRAPH) + ";\r\n"
    out, _ = _code(module, phrases=dict(zip(_RU_PARAGRAPH, _EN_PARAGRAPH)))
    assert "\n" not in out.replace("\r\n", ""), "every break stayed a windows one"
    assert _long_lines(out) == []


def test_the_width_comes_from_the_rule_and_is_not_a_second_setting(monkeypatch):
    """The re-wrap obeys style/line-length: move the rule's limit and the pass follows."""
    from xbsl.rules import style_layout

    ru = ["Задача записана", "и список обновлён"]
    en = ["The task has been written down by the handler", "and the list of the steps is refreshed"]
    module = "метод Ф()\n" + "".join(f"    // {line}\n" for line in ru) + ";\n"

    wide, _ = _code(module, phrases=dict(zip(ru, en)))
    assert _comment_lines(wide) == [f"    // {line}" for line in en], "at 120 nothing to re-split"

    monkeypatch.setattr(style_layout, "MAX_LINE", 50)
    narrow, _ = _code(module, phrases=dict(zip(ru, en)))
    assert _long_lines(narrow) == []
    assert _comment_text(narrow) == " ".join(en)
    assert len(_comment_lines(narrow)) > len(_comment_lines(wide)), "re-split at the new limit"


def test_a_line_under_a_list_item_belongs_to_the_item():
    """A continuation of an item is not prose: an empty comment line closes the item."""
    item = "- второй пункт списка"
    tail = "продолжение этого пункта, которое после перевода станет заметно длиннее"
    english = {
        item: "- the second item of the list",
        tail: "the continuation of that very item, which after the translation grows well past"
              " the width limit and still belongs where its author put it",
    }
    module = ("метод Ф()\n"
              f"    // {item}\n"
              f"    // {tail}\n"
              "    //\n"
              + "".join(f"    // {line}\n" for line in _RU_PARAGRAPH) + ";\n")
    out, _ = _code(module, phrases={**english, **dict(zip(_RU_PARAGRAPH, _EN_PARAGRAPH))})
    lines = _comment_lines(out)
    assert lines[:3] == [f"    // {english[item]}", f"    // {english[tail]}", "    //"]
    assert _long_lines(out) == [3], "the item is left whole, the paragraph below it re-split"
    assert " ".join(line.lstrip()[2:].strip() for line in lines[3:]) == " ".join(_EN_PARAGRAPH)


def test_a_block_of_one_line_at_the_end_of_a_file_is_split_into_lines():
    """A file that ends without a break is an ordinary file - and its last line is a comment."""
    ru = "Список задач заполняется один раз при открытии карточки"
    en = ("The task list is filled once when the card opens and after that is refreshed point by"
          " point on the write event, never by a full re-read")
    module = f"метод Ф()\n;\n    // {ru}"
    assert _long_lines(module) == [], "the source itself is within the limit"

    out, _ = _code(module, phrases={ru: en})
    assert _long_lines(out) == []
    assert len(_comment_lines(out)) > 1, out
    assert all(line.count("//") == 1 for line in _comment_lines(out)), "no line was glued"
    assert _comment_text(out) == en, "the text of the paragraph survived"
    assert not out.endswith("\n"), "the break the file did not have is not invented"


def test_the_last_block_of_a_windows_file_is_split_with_windows_breaks():
    """The ending the pass ADDS is the ending of the file, not the one of the platform."""
    ru = "Список задач заполняется один раз при открытии карточки"
    en = ("The task list is filled once when the card opens and after that is refreshed point by"
          " point on the write event, never by a full re-read")
    module = f"метод Ф()\r\n;\r\n    // {ru}"

    out, _ = _code(module, phrases={ru: en})
    assert "\n" not in out.replace("\r\n", ""), "every break stayed a windows one"
    assert _long_lines(out) == []


def test_a_dash_that_carried_a_sentence_over_is_prose_not_an_item():
    """A wrapped sentence often opens a line with a dash: the line above it simply did not end."""
    ru = ["Суффикс даты в русской записи",
          "– часть шаблона словаря, а не кода"]
    en = ["The suffix of the Russian spelling of the date",
          "- is part of the template of the dictionary and not of the code, where one shared"
          " template would print it in the English spelling as well"]
    module = "метод Ф()\n" + "".join(f"    // {line}\n" for line in ru) + ";\n"
    assert _long_lines(module) == [], "the source itself is within the limit"

    out, _ = _code(module, phrases=dict(zip(ru, en)))
    assert _long_lines(out) == []
    assert _comment_text(out) == " ".join(en), "the text of the paragraph survived"
    assert _comment_lines(out)[0] != f"    // {en[0]}", "the two lines were re-flowed as one"


def test_a_dash_list_announced_by_a_colon_stays_a_list():
    """Real sources open a list right under the line that announces it, with no empty line."""
    ru = ["Правила контракта:",
          "- имена свойств JSON совпадают с именами реквизитов",
          "- ссылки на другие объекты адресуются их кодами"]
    en = ["The rules of the contract:",
          "- the names of the JSON properties are the names of the attributes of the object, and"
          " the service ones are left out of the contract",
          "- a reference to another object is addressed by its code, and a value of an enumeration"
          " by the name the enumeration gives it"]
    module = "метод Ф()\n" + "".join(f"    // {line}\n" for line in ru) + ";\n"

    out, _ = _code(module, phrases=dict(zip(ru, en)))
    assert _comment_lines(out) == [f"    // {line}" for line in en], "line for line"


def test_an_empty_comment_line_closes_the_item_above_it():
    """The lines under an item belong to it - and an empty comment line is what ends the item."""
    item = "- пункт списка"
    module = ("метод Ф()\n"
              f"    // {item}\n"
              "    // \n"
              + "".join(f"    // {line}\n" for line in _RU_PARAGRAPH) + ";\n")

    out, _ = _code(module, phrases={item: "- an item of the list",
                                    **dict(zip(_RU_PARAGRAPH, _EN_PARAGRAPH))})
    lines = _comment_lines(out)
    assert lines[0] == "    // - an item of the list"
    assert lines[1].strip() == "//", "the empty line kept its place"
    assert _long_lines(out) == [], "the paragraph under the empty line was re-split"
    assert " ".join(line.lstrip()[2:].strip() for line in lines[2:]) == " ".join(_EN_PARAGRAPH)


def test_a_line_of_a_literal_is_not_a_comment_even_when_it_opens_with_two_slashes():
    """The lexer says what a line is: inside a multi-line literal the two slashes are data."""
    name = "ДлинноеИмя"
    english = "TheNameOfTheVariableThatTheHandlerOfTheWriteEventFillsInBeforeTheListIsRefreshed"
    data = "// данные %{" + name + "} внутри строкового литерала, и трогать их нельзя"
    module = ("метод Ф()\n"
              f"    знч {name} = 1\n"
              '    знч Текст = "начало\n'
              f"{data}\n"
              'конец"\n'
              ";\n")

    out, _ = _code(module, tokens={name: english})
    assert "// данные %{" + english + "} внутри строкового литерала" in out
    assert out.count("//") == 1, "the line of the literal was not re-split into two"


def test_two_code_lines_are_never_taken_for_a_paragraph():
    """Only a comment is re-flowed - and the lexer is what says which line opens with one."""
    name = "ОченьДлинноеИмяМетода"
    english = ("TheNameOfTheMethodThatFillsTheListOfTheStepsOfTheTaskWhenTheCardOfTheTaskIsOpened"
               "ByThePerformerOfThatVeryTask")
    module = ("метод Ф()\n"
              f"    знч Первое = {name}(1)\n"
              f"    знч Второе = {name}(2)\n"
              ";\n")

    out, _ = _code(module, tokens={name: english, "Первое": "First", "Второе": "Second"})
    assert _long_lines(out) == [2, 3], "both statements came out over the limit"
    assert out.splitlines()[1] == f"    val First = {english}(1)"
    assert out.splitlines()[2] == f"    val Second = {english}(2)"


def test_a_column_too_narrow_to_wrap_in_is_left_alone(monkeypatch):
    """Below a readable body a re-split only shreds the paragraph, so the block is left as it is."""
    from xbsl.rules import style_layout

    monkeypatch.setattr(style_layout, "MAX_LINE", 40)
    ru = "Шаг"
    en = "The step of the task that the handler writes down"
    indent = " " * 24
    module = f"метод Ф()\n{indent}// {ru}\n;\n"

    out, _ = _code(module, phrases={ru: en})
    assert _comment_lines(out) == [f"{indent}// {en}"], "one line, as wide as it came out"


def test_a_long_name_and_a_hyphenated_word_are_never_broken():
    """A word longer than the column is a name or a link: breaking it breaks what it names."""
    url = "https://example.invalid/docs/tasks/" + "a" * 90
    chain = "read-modify-write-" + "b" * 90
    ru = ["Ссылка на документацию", "и правило обмена"]
    en = [f"The details are at {url}", f"and the {chain} rule of the exchange applies to them"]
    module = "метод Ф()\n" + "".join(f"    // {line}\n" for line in ru) + ";\n"

    out, _ = _code(module, phrases=dict(zip(ru, en)))
    assert url in out, "a link is not broken in the middle"
    assert chain in out, "a hyphenated name is not broken at its hyphens"
    assert _comment_text(out) == " ".join(en), "the text of the paragraph survived"


def test_a_text_that_no_longer_lines_up_with_its_source_is_left_alone():
    """Without the source, line for line, there is no telling which line was long on purpose."""
    from xbsl.translation.rewrap import rewrap_comments

    text = "метод Ф()\n;\n    // " + "слово " * 30 + "\n"
    assert rewrap_comments(text, "метод Ф()\n;\n") == text


def test_rewrap_never_changes_the_words_of_a_comment():
    """The pass moves line breaks and nothing else - a block whose words changed is put back."""
    from xbsl.translation import rewrap

    source = (
        "// ─── A frame that must survive ───────────────────────────────────────────────\n"
        "// The first line of a paragraph that the translation made longer than the limit\n"
        "// and a second line of the same paragraph.\n"
        "//   a table cell   another cell\n"
        "// - a list item\n"
        "//   its continuation\n"
        "метод Тест()\n"
        ";\n"
    )
    translated = source.replace(
        "The first line of a paragraph that the translation made longer than the limit",
        "The first line of a paragraph that the translation made a great deal longer than the limit it is given",
    )
    out = rewrap.rewrap_comments(translated, source)

    words = lambda t: "".join("".join(s.lstrip().lstrip("/").split()) for s in t.splitlines())
    assert words(out) == words(translated), "перенос изменил текст комментария"
    assert all(len(s) <= 120 for s in out.splitlines() if s.lstrip().startswith("//") and "─" not in s)


def test_a_file_that_opens_with_a_byte_order_mark_is_re_wrapped_too():
    """The mark stands before the indent, and it is not code: the first line keeps its paragraph."""
    from xbsl.translation import rewrap

    source = "﻿// A short first line.\n// A second line of the same paragraph.\n"
    longer = source.replace(
        "A short first line.",
        "A first line that the translation made much longer than the limit allows it to be here",
    )
    out = rewrap.rewrap_comments(longer, source, limit=60)
    assert out != longer, "строка под меткой порядка байтов осталась без переноса"
    assert out.startswith("﻿//"), "метка порядка байтов потерялась"
    assert "A second line of the same paragraph." in out.replace("\n// ", " ")


def test_a_route_template_carries_its_parameter_names(tmp_path: Path):
    """The handler reads a parameter BY NAME - the template and the code move together or not at all."""
    out, _ = _yaml(
        "ВидЭлемента: HttpСервис\n"
        "ШаблоныUrl:\n"
        "    -\n"
        "        Имя: Задача\n"
        "        Шаблон: /task/{слаг}/step/{номер}\n",
        tokens={"Задача": "Task", "слаг": "slug", "номер": "number"},
        name="Сервис.yaml",
    )
    assert "Template: /task/{slug}/step/{number}" in out
    assert "/task/" in out and "/step/" in out   # the path itself is what a visitor types


def test_a_route_template_without_names_is_left_alone():
    out, _ = _yaml(
        "ВидЭлемента: HttpСервис\n"
        "ШаблоныUrl:\n"
        "    -\n"
        "        Имя: Пинг\n"
        "        Шаблон: /ping\n",
        tokens={"Пинг": "Ping"},
        name="Сервис.yaml",
    )
    assert "Template: /ping" in out


def test_a_new_dictionary_file_gets_a_neutral_head_line(tmp_path: Path):
    """The writer must not sign the file for a surface it knows nothing about.

    A file written from the MCP tool used to arrive announcing that it came from the editor
    panel, and the line was corrected by hand after every such batch.
    """
    from xbsl.translation import entries

    folder = tmp_path / "xbsl-translation"
    folder.mkdir()
    entries.write_entries(folder, [{"key": "Шаги", "value": "Steps", "kind": "token"}],
                          target="046-icons.yaml")

    head = (folder / "046-icons.yaml").read_text(encoding="utf-8")
    assert entries.DEFAULT_COMMENT in head
    assert "редактор" not in head


def test_the_caller_names_the_head_line_of_a_new_file(tmp_path: Path):
    from xbsl.translation import entries

    folder = tmp_path / "xbsl-translation"
    folder.mkdir()
    entries.write_entries(folder, [{"key": "Шаги", "value": "Steps", "kind": "token"}],
                          target="046-icons.yaml", comment="Имена значков возможностей.")

    head = (folder / "046-icons.yaml").read_text(encoding="utf-8")
    assert "# Имена значков возможностей." in head
    assert entries.DEFAULT_COMMENT not in head


def test_the_head_line_is_written_only_when_the_file_is_new(tmp_path: Path):
    """An existing file keeps its own head line - a second batch must not restamp it."""
    from xbsl.translation import entries

    folder = tmp_path / "xbsl-translation"
    folder.mkdir()
    entries.write_entries(folder, [{"key": "Шаги", "value": "Steps", "kind": "token"}],
                          target="046-icons.yaml", comment="Первая порция.")
    entries.write_entries(folder, [{"key": "Отбор", "value": "Filter", "kind": "token"}],
                          target="046-icons.yaml", comment="Вторая порция.")

    head = (folder / "046-icons.yaml").read_text(encoding="utf-8")
    assert "# Первая порция." in head
    assert "Вторая порция" not in head


def test_the_kind_of_a_dispatched_block_is_translated():
    """A schedule kind is neither a type, nor a property, nor an enumeration value: no term
    dictionary pairs it, and the value used to stay Russian while the report called it a gap
    of the platform data. The metamodel annotation states both spellings."""
    text = (
        "ВидЭлемента: ЗапланированноеЗадание\n"
        "Ид: cf45e060-3049-480b-9cea-fb780a2a8ef9\n"
        "Имя: Обновление\n"
        "Расписание:\n"
        "    -\n"
        "        Вид: Ежедневно\n"
        "        ЗапуститьВ: 04:00\n"
        "ПовторыПриОшибке:\n"
        "    Вид: Интервал\n"
        "    Попытки: 3\n"
    )

    out, report = _yaml(text, tokens={"Обновление": "Refresh"}, name="Обновление.yaml")

    assert "Kind: Daily" in out and "Kind: Interval" in out
    assert "Ежедневно" not in out and "Интервал" not in out
    # And the run no longer reports what it has just translated.
    assert not report.platform_tokens


def test_a_method_name_collision_is_reported_by_the_project_pass(tmp_path: Path):
    """Two methods of one module under one English name is a module the compiler refuses.

    Met live: two Russian words that English spells alike, and the translated tree went out
    with two handlers named the same while every check called the translation complete.
    """
    from xbsl.translation import project as project_module

    root = tmp_path / "acme" / "Проба"
    root.mkdir(parents=True)
    (root / "Проект.yaml").write_text(
        "Ид: 11111111-2222-3333-4444-555555555555\nИмя: Проба\nВерсия: 1.0\nПоставщик: acme\n",
        encoding="utf-8",
    )
    (root / "Форма.yaml").write_text(
        "ВидЭлемента: ОбщийМодуль\nИд: 66666666-2222-3333-4444-555555555555\nИмя: Форма\n",
        encoding="utf-8",
    )
    (root / "Форма.xbsl").write_text(
        "метод УслугаИзменена()\n;\n\nметод СервисИзменен()\n;\n", encoding="utf-8",
    )
    dictionary = _dictionary({
        "Проба": "Trial", "Форма": "Form",
        "УслугаИзменена": "ServiceChanged", "СервисИзменен": "ServiceChanged",
    })

    report = project_module.translate_project(root, dictionary, None)

    assert any("ServiceChanged" in problem for problem in report.problems), report.problems


def test_writing_a_value_already_taken_is_reported(tmp_path: Path):
    """The same answer at the moment a person types the word, one lookup instead of a project pass."""
    from xbsl.translation import entries

    folder = tmp_path / "xbsl-translation"
    folder.mkdir()
    (folder / "010.yaml").write_text(
        "version: 1\nlanguage: en\n\ntokens:\n    Услуга: Service\n", encoding="utf-8",
    )

    taken = entries.write_entries(folder, [{"key": "Сервис", "value": "Service", "kind": "token"}])
    free = entries.write_entries(folder, [{"key": "Прочее", "value": "Other", "kind": "token"}])

    assert taken["collisions"] == [{"key": "Сервис", "value": "Service", "taken": ["Услуга"]}]
    assert free["collisions"] == []
    # The entry is written all the same: a qualified key is how one word serves two owners.
    assert taken["added"] == 1


def test_query_literal_undefined_is_not_null():
    """`!= НЕОПРЕДЕЛЕНО` of a query is `UNDEFINED`; `NULL` is a reserved word of its own.

    The compiler takes both, so nothing fails at build time - a condition against `NULL` is
    simply never true, and the query comes back empty on the running application. Met live:
    a translated site stopped recalculating a register and stopped showing a whole page block.
    """
    out, _report = _code(
        "пер Выборка = Запрос{ ВЫБРАТЬ Ссылка ИЗ Задачи КАК Т ГДЕ Т.Родитель != НЕОПРЕДЕЛЕНО }\n",
        tokens={"Задачи": "Tasks", "Родитель": "Parent", "Выборка": "Selection"},
    )

    assert "T.Parent != UNDEFINED" in out
    assert "NULL" not in out


@pytest.mark.needs_data
def test_a_platform_member_with_no_english_is_the_platform_s_gap(tmp_path: Path):
    """`Перевернуть` is a method of `Array` that no table of the data spells in English.

    Written into the dictionary it would be a guess, and a guessed English name for a platform
    member is refused by the compiler - so it belongs to the platform gaps, where the counter
    and the list of gaps agree about it.
    """
    from xbsl.translation import entries

    root = tmp_path / "Acme" / "Demo"
    _write(root / "Модуль.xbsl", """метод Проверка()
    пер список = Массив<Строка>{}
    список.Перевернуть()
;
""")
    report = translate_project(root, _dictionary({"Проверка": "Check", "список": "items"}), None)
    assert "Перевернуть" in report.merged_platform_gaps()
    assert "Перевернуть" not in report.merged_missing_tokens()
    # And the table of the panel does not offer it either - there is nothing to type there.
    assert all(gap.key != "Перевернуть" for gap in entries.gaps_of_report(report))


@pytest.mark.needs_data
def test_a_name_the_project_declares_stays_the_project_s_gap(tmp_path: Path):
    """The gate wins: a project method spelled like a platform member is the project's own."""
    root = tmp_path / "Acme" / "Demo"
    _write(root / "Модуль.xbsl", """метод Перевернуть()
;
метод Проверка()
    Модуль.Перевернуть()
;
""")
    report = translate_project(root, _dictionary({"Проверка": "Check"}), None)
    assert "Перевернуть" in report.merged_missing_tokens()
    assert "Перевернуть" not in report.merged_platform_gaps()


# --- one structure is one namespace ---------------------------------------------------------


def test_a_qualified_entry_renames_a_field_its_uses_and_its_json_key(tmp_path: Path):
    """`<Structure>.<Field>` reaches everything the field binds - the point of a scoped entry.

    Two fields of one structure whose Russian names translate into one English word is a
    structure the compiler refuses. Renaming the Russian source is not the cure: the name is
    right in Russian. The dictionary says which of the two takes another word, and the
    declaration, every use through a typed receiver and the json key follow it together.
    """
    root = tmp_path / "Acme" / "Demo"
    _write(root / "Модуль.xbsl", """структура ДанныеЗаписи
    пер Сервисы: Массив<Строка>
    пер Услуги: Массив<Строка>
;

метод Разобрать(Корень: ДанныеЗаписи): Число
    возврат Корень.Сервисы.Количество() + Корень.Услуги.Количество()
;
""")
    _write(root / "Данные.json", '{"Сервисы": [], "Услуги": []}\n')
    dictionary = _dictionary({
        "Модуль": "Module", "ДанныеЗаписи": "RecordData", "Разобрать": "Parse",
        "Корень": "Root", "Сервисы": "Services", "Услуги": "Services",
        "ДанныеЗаписи.Услуги": "Offerings",
    })
    out = tmp_path / "en"
    report = translate_project(root, dictionary, out)

    module = (out / "Module.xbsl").read_text(encoding="utf-8")
    assert "var Offerings: Array<String>" in module
    assert "Root.Offerings.Count()" in module
    assert (out / "Data.json").read_text(encoding="utf-8") == (
        '{"Services": [], "Offerings": []}\n'
    )
    assert not report.problems


def test_two_fields_of_one_structure_under_one_word_are_a_problem(tmp_path: Path):
    """Without the scoped entry the collision is REPORTED - until now only the compiler saw it."""
    root = tmp_path / "Acme" / "Demo"
    _write(root / "Модуль.xbsl", """структура ДанныеЗаписи
    пер Сервисы: Массив<Строка>
    пер Услуги: Массив<Строка>
;
""")
    report = translate_project(root, _dictionary({
        "Модуль": "Module", "ДанныеЗаписи": "RecordData",
        "Сервисы": "Services", "Услуги": "Services",
    }), None)
    assert any("structure:ДанныеЗаписи" in problem for problem in report.problems)
    assert any("Сервисы, Услуги" in problem for problem in report.problems)


def test_the_receiver_as_written_answers_before_its_type(tmp_path: Path):
    """An entry qualified by the VARIABLE keeps answering - projects already write those."""
    root = tmp_path / "Acme" / "Demo"
    _write(root / "Модуль.xbsl", """структура ДанныеЗаписи
    пер Ссылка: Строка
;

метод Разобрать(Событие: ДанныеЗаписи): Строка
    возврат Событие.Ссылка
;
""")
    out = tmp_path / "en"
    translate_project(root, _dictionary({
        "Модуль": "Module", "ДанныеЗаписи": "RecordData", "Разобрать": "Parse",
        "Событие": "Event", "Ссылка": "Reference", "Событие.Ссылка": "Link",
        "ДанныеЗаписи.Ссылка": "Href",
    }), out)
    module = (out / "Module.xbsl").read_text(encoding="utf-8")
    # The declaration belongs to the structure, the use answers to the variable it is written on.
    assert "var Href: String" in module
    assert "return Event.Link" in module


@pytest.mark.needs_data
def test_a_verified_member_spelling_wins_over_the_owner_table(tmp_path: Path):
    """`Символ` of a String is `CharAt`; the owner table says `Symbol`, which the compiler refuses."""
    root = tmp_path / "Acme" / "Demo"
    _write(root / "Модуль.xbsl", """метод Разобрать(Тело: Строка): Строка
    возврат Тело.Символ(1)
;
""")
    out = tmp_path / "en"
    translate_project(root, _dictionary({"Модуль": "Module", "Разобрать": "Parse", "Тело": "Body"}), out)
    assert "Body.CharAt(1)" in (out / "Module.xbsl").read_text(encoding="utf-8")


def test_new_entry_in_the_same_file_keeps_the_removal(tmp_path: Path):
    """A new entry aimed at the file the batch also edits does not undo those edits.

    New entries are merged into the target file's text, corrections and removals into the
    text of the file the entry lives in. When the two are the SAME file, the merge must lie
    on top of the text already planned - otherwise the report announces a removal that never
    reached the disk.
    """
    from xbsl.translation import entries

    folder = _dict_dir(tmp_path)
    plan = entries.plan_entries(folder, [
        {"key": "строка комментария", "value": "", "kind": "phrase"},  # removed
        {"key": "Шаги", "value": "Steps", "kind": "token"},             # added to the same file
        {"key": "Задачи", "value": "Jobs", "kind": "token"},            # corrected in the same file
    ], target="010-objects.yaml")
    assert plan["added"] == 1 and plan["changed"] == 1 and plan["removed"] == 1
    edited = plan["files"][str(folder / "010-objects.yaml")]
    assert "    Шаги: Steps" in edited
    assert "    Задачи: Jobs" in edited
    assert "строка комментария" not in edited


def test_the_dictionary_catalog_is_not_a_source_of_the_project(tmp_path: Path):
    """A run rooted ABOVE the project sees the dictionary next to it - and must not read it.

    Its files are yaml of the same shape as a project's, so the pass counted their own
    comments as untranslated prose: a run from the repository root of the site project
    reported 871 phrase gaps and 99.2% coverage where the project itself is at 100%. The
    figure looks trustworthy and sends the reader after a hole that is not there.
    """
    from xbsl.translation import entries
    from xbsl.translation.dictionary import DICTIONARY_DIR
    from xbsl.translation.project import translate_project

    root = tmp_path / "Acme"
    _write(root / "Demo" / "Модуль.xbsl", "// пояснение\nметод Считать()\n    возврат 1\n;\n")
    _write(root / DICTIONARY_DIR / "010-objects.yaml",
           "version: 1\nlanguage: en\n\n# Записи, добавленные из редактора\ntokens:\n"
           "    Считать: Read\n"
           "phrases:\n"
           '    "пояснение": "an explanation"\n')

    report = translate_project(root, _dictionary({"Считать": "Read", "Модуль": "Module"},
                                                {"пояснение": "an explanation"}), None)

    assert report.merged_missing_phrases() == {}
    assert [gap.key for gap in entries.gaps_of_report(report)] == []
