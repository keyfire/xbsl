"""The source translator: the dictionary model, code and yaml rewriting, the project walk."""

from __future__ import annotations

from pathlib import Path

import pytest

from xbsl import engine
from xbsl.translation import dictionary as dict_module
from xbsl.translation.code import Resolver, translate_code
from xbsl.translation.project import translate_project
from xbsl.translation.reporting import FileReport
from xbsl.translation.yamlfile import translate_yaml


def _dictionary(tokens: dict | None = None, phrases: dict | None = None) -> dict_module.Dictionary:
    return dict_module.Dictionary(tokens=dict(tokens or {}), phrases=dict(phrases or {}))


def _code(text: str, tokens=None, phrases=None) -> tuple[str, FileReport]:
    source = engine.load_text("Модуль.xbsl", text)
    report = FileReport(path="Модуль.xbsl")
    out = translate_code(source, Resolver(_dictionary(tokens, phrases)), report)
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
    assert any("БезПеревода" in problem or "Untranslated" in problem for problem in report.problems)

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
    from xbsl.translation.names import structure_fields

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
    fields = structure_fields(source)
    assert fields == {"Шаги", "Задачи"}

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
    out = translate_json('{"Шаги": 1}\n', _dictionary(), frozenset({"Шаги"}), report)
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
    """A pattern has slashes and named groups; its groups are code, not files."""
    out, _ = _code(
        'метод Разобрать()\n'
        '    возврат Образец{"<a[^>]*>(?<Заголовок>.*?)</a>"}\n'
        ';\n',
        tokens={"Разобрать": "Parse", "Заголовок": "Title"},
    )
    assert '"<a[^>]*>(?<Заголовок>.*?)</a>"' in out


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
