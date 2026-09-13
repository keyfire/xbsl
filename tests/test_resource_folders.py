"""Folders of resources: moving a resource, renaming and deleting a folder, and their surfaces.

A resource is a file under the `Resources` folder of a subsystem or a package, and its key is the
path under that folder: `Resource{Styles/main.css}` in a module or a yaml binding, the bare value
of an image property in a yaml, a namespace in front when the file lies in another subsystem.
The folders inside that folder are the author's grouping, so moving a file between them or
renaming one changes every key that names the files - op_move_resource and
op_rename_resource_folder rewrite the static references where they resolve to the folder, and
list the string literals a lookup at run time reads (`ResourcesPackage.Current().Get()`);
op_delete_resource_folder lists both and edits nothing.

The fixture is one project, `Демо::Учет`: subsystem `Склад` keeps its resources with a folder
`Стили` and a module and a form that name them in every shape; subsystem `Продажи` reaches them
by a namespace, by an import, and in one module by nothing at all.
"""

import json
from pathlib import Path

import pytest

from xbsl import cli, engine, scaffold
from xbsl.scaffold import ScaffoldError, apply_result

PROJECT_FILES = {
    "Проект.yaml": "Поставщик: Демо\nИмя: Учет\nВерсия: 1.0.0\n",
    "Склад/Подсистема.yaml": "Интерфейс:\n    ВключатьВАвтоИнтерфейс: Ложь\n",
    "Склад/Ресурсы/Ресурсы.yaml": "ОбластьВидимости: ВПроекте\n",
    "Склад/Ресурсы/logo.svg": "<svg xmlns=\"http://www.w3.org/2000/svg\"/>\n",
    "Склад/Ресурсы/Стили/a.css": "body { margin: 0; }\n",
    "Склад/Ресурсы/Стили/b.js": "void 0;\n",
    "Склад/Ресурсы/Стили/flag.svg": "<svg xmlns=\"http://www.w3.org/2000/svg\"/>\n",
    "Склад/Остатки.yaml": (
        "ВидЭлемента: ОбщийМодуль\nИд: 6f0b6a44-0000-4000-8000-000000000301\n"
        "Имя: Остатки\nОбластьВидимости: ВПроекте\n"
    ),
    "Склад/Остатки.xbsl": (
        "// Разметка берёт стили из Ресурс{Стили/a.css}\n"
        "метод Разметка(): Строка\n"
        "    знч Ссылка = Ресурс{Стили/a.css}.Ссылка\n"
        "    знч Скрипт = ПакетРесурсов.Текущий().Получить(\"Стили/b.js\")\n"
        "    знч Имя = \"b.js\"\n"
        "    знч Любой = ПакетРесурсов.Текущий().Получить(\"Стили/%Имя\")\n"
        "    знч Логотип = Ресурс{logo.svg}\n"
        "    возврат \"НеСтили/a.css\"\n"
        ";\n"
    ),
    "Склад/ФормаОстатков.yaml": (
        "ВидЭлемента: КомпонентИнтерфейса\nИд: 6f0b6a44-0000-4000-8000-000000000302\n"
        "Имя: ФормаОстатков\nНаследует:\n    Тип: Группа\n    Содержимое:\n"
        "        -\n            Тип: Картинка\n            Изображение: Стили/flag.svg\n"
        "        -\n            Тип: Кнопка\n            Значок: =Ресурс{Стили/flag.svg}.Ссылка\n"
        "            Текст: =ОформлениеСклада.Подключить(\"Стили/a.css\")\n"
    ),
    "Продажи/Подсистема.yaml": "Использование:\n    - Склад\n",
    "Продажи/Заказы.yaml": (
        "ВидЭлемента: ОбщийМодуль\nИд: 6f0b6a44-0000-4000-8000-000000000303\nИмя: Заказы\n"
    ),
    "Продажи/Заказы.xbsl": (
        "импорт Склад\n\n"
        "метод Картинки(): Массив<ДвоичныйОбъект.Ссылка>\n"
        "    возврат [Ресурс{Стили/flag.svg}.Ссылка, Ресурс{Склад::Стили/flag.svg}.Ссылка,\n"
        "        Ресурс{Демо::Учет::Склад::Стили/a.css}.Ссылка]\n"
        ";\n"
    ),
    "Продажи/Отчеты.yaml": (
        "ВидЭлемента: ОбщийМодуль\nИд: 6f0b6a44-0000-4000-8000-000000000304\nИмя: Отчеты\n"
    ),
    # No import and no namespace: a bare key of another subsystem names nothing here.
    "Продажи/Отчеты.xbsl": "метод Флаг(): Ресурс\n    возврат Ресурс{Стили/flag.svg}\n;\n",
    "Продажи/ФормаЗаказа.yaml": (
        "ВидЭлемента: КомпонентИнтерфейса\nИд: 6f0b6a44-0000-4000-8000-000000000305\n"
        "Имя: ФормаЗаказа\nНаследует:\n    Тип: Картинка\n"
        "    Изображение: Склад::Стили/flag.svg\n"
    ),
}


def _project(tmp_path: Path, extra: dict[str, str] | None = None) -> Path:
    project_dir = tmp_path / "Демо" / "Учет"
    for rel, text in {**PROJECT_FILES, **(extra or {})}.items():
        path = project_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    return project_dir


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _content(result, path: Path) -> str:
    return next(c.content for c in result.changes if c.path == path)


def _changed(result) -> set[str]:
    return {c.path.name for c in result.changes}


# --- renaming a folder ----------------------------------------------------------------------------


def test_renaming_a_resource_folder_rewrites_the_keys_that_resolve_to_it(tmp_path):
    project = _project(tmp_path)
    stock = project / "Склад"
    result = scaffold.op_rename_resource_folder(tmp_path, stock / "Ресурсы" / "Стили", "Оформление")

    assert {(r.old_path.name, r.new_path) for r in result.renames} == {
        (name, stock / "Ресурсы" / "Оформление" / name) for name in ("a.css", "b.js", "flag.svg")
    }
    module = _content(result, stock / "Остатки.xbsl")
    # The literal in the code and the one a comment documents are the same reference.
    assert "// Разметка берёт стили из Ресурс{Оформление/a.css}" in module
    assert "знч Ссылка = Ресурс{Оформление/a.css}.Ссылка" in module
    # A string is read at run time: listed, never edited; a word that merely ends the same way stays.
    assert 'Получить("Стили/b.js")' in module and '"НеСтили/a.css"' in module
    form = _content(result, stock / "ФормаОстатков.yaml")
    assert "Изображение: Оформление/flag.svg" in form
    assert "Значок: =Ресурс{Оформление/flag.svg}.Ссылка" in form
    assert 'Текст: =ОформлениеСклада.Подключить("Стили/a.css")' in form
    orders = _content(result, project / "Продажи" / "Заказы.xbsl")
    assert "Ресурс{Оформление/flag.svg}.Ссылка, Ресурс{Склад::Оформление/flag.svg}.Ссылка" in orders
    assert "Ресурс{Демо::Учет::Склад::Оформление/a.css}" in orders
    assert "Изображение: Склад::Оформление/flag.svg" in _content(
        result, project / "Продажи" / "ФормаЗаказа.yaml")
    # A bare key of another subsystem without an import does not reach the folder.
    assert "Отчеты.xbsl" not in _changed(result)

    listing = "\n".join(result.notes)
    assert "Ссылки на ресурсы переписаны (файлов: 4, замен: 8)" in listing
    strings = next(n for n in result.notes if n.startswith("Обращения по строке"))
    assert "Склад/Остатки.xbsl (строки 4, 6)" in strings
    assert "Склад/ФормаОстатков.yaml (строка 13)" in strings
    # The operation computes: nothing is written.
    assert (stock / "Ресурсы" / "Стили" / "a.css").is_file()
    assert not (stock / "Ресурсы" / "Оформление").exists()


def test_a_renamed_resource_folder_leaves_no_old_folder_behind(tmp_path):
    project = _project(tmp_path)
    resources = project / "Склад" / "Ресурсы"
    apply_result(scaffold.op_rename_resource_folder(tmp_path, resources / "Стили", "Оформление"))

    assert not (resources / "Стили").exists()
    assert (resources / "Оформление" / "flag.svg").is_file()
    assert "Ресурс{Оформление/a.css}.Ссылка" in _read(project / "Склад" / "Остатки.xbsl")


@pytest.mark.needs_data  # code/unknown-resource knows the platform library from the documentation
def test_after_a_rename_only_the_key_that_never_reached_the_folder_is_unknown(tmp_path):
    project = _project(tmp_path)

    def findings() -> set[tuple[str, int]]:
        sources = engine.find_sources(tmp_path, "*.yaml") + engine.find_sources(tmp_path, "*.xbsl")
        found = engine.run(sources, select={"code/unknown-resource", "code/resource-bare-name"})
        return {(Path(d.path).name, d.line) for d in found}

    before = findings()
    apply_result(scaffold.op_rename_resource_folder(
        tmp_path, project / "Склад" / "Ресурсы" / "Стили", "Оформление"))
    # The bare key of another subsystem with neither an import nor a namespace was not a
    # reference to the folder, so the rename leaves it; the rule matches a key against the
    # files of every folder at once, which is why it said nothing about that key before.
    assert findings() - before == {("Отчеты.xbsl", 2)}


# --- moving a resource ----------------------------------------------------------------------------


def test_moving_a_resource_into_a_new_folder_creates_it_with_the_file(tmp_path):
    project = _project(tmp_path)
    resources = project / "Склад" / "Ресурсы"
    result = scaffold.op_move_resource(tmp_path, resources / "logo.svg", resources / "Эмблемы")

    assert [(r.old_path, r.new_path) for r in result.renames] == [
        (resources / "logo.svg", resources / "Эмблемы" / "logo.svg")]
    assert "знч Логотип = Ресурс{Эмблемы/logo.svg}" in _content(result, project / "Склад" / "Остатки.xbsl")
    assert _changed(result) == {"Остатки.xbsl"}

    apply_result(result)
    assert (resources / "Эмблемы" / "logo.svg").is_file() and not (resources / "logo.svg").exists()


def test_moving_a_resource_file_lists_the_strings_that_read_its_folder(tmp_path):
    project = _project(tmp_path)
    resources = project / "Склад" / "Ресурсы"
    result = scaffold.op_move_resource(tmp_path, resources / "Стили" / "b.js", resources)

    assert result.renames[0].new_path == resources / "b.js"
    assert not result.changes
    listing = "\n".join(result.notes)
    assert "Ссылок на эти файлы" in listing
    # The exact path, and the lookup with a computed name in the file's old folder.
    assert "Обращения по строке с путём 'Стили/b.js'" in listing and "(строка 4)" in listing
    computed = next(n for n in result.notes if n.startswith("Строки с папкой 'Стили'"))
    assert "Склад/Остатки.xbsl (строка 6)" in computed


def test_moving_a_resource_folder_carries_every_file_and_key(tmp_path):
    project = _project(tmp_path, {"Склад/Ресурсы/Темы/dark.css": "body {}\n"})
    resources = project / "Склад" / "Ресурсы"
    result = scaffold.op_move_resource(tmp_path, resources / "Стили", resources / "Темы")

    assert {r.new_path for r in result.renames} == {
        resources / "Темы" / "Стили" / name for name in ("a.css", "b.js", "flag.svg")}
    assert "Ресурс{Темы/Стили/a.css}.Ссылка" in _content(result, project / "Склад" / "Остатки.xbsl")
    with pytest.raises(ScaffoldError, match="в неё саму"):
        scaffold.op_move_resource(tmp_path, resources / "Стили", resources / "Стили" / "Вложенная")


def test_a_taken_name_in_the_target_folder_is_refused(tmp_path):
    project = _project(tmp_path, {"Склад/Ресурсы/Темы/a.css": "body {}\n"})
    resources = project / "Склад" / "Ресурсы"
    with pytest.raises(ScaffoldError, match="уже занято"):
        scaffold.op_move_resource(tmp_path, resources / "Стили" / "a.css", resources / "Темы")
    with pytest.raises(ScaffoldError, match="уже существует"):
        scaffold.op_rename_resource_folder(tmp_path, resources / "Стили", "Темы")
    with pytest.raises(ScaffoldError, match="уже лежит"):
        scaffold.op_move_resource(tmp_path, resources / "Стили" / "a.css", resources / "Стили")


def test_a_move_into_the_resources_of_another_namespace_is_refused(tmp_path):
    project = _project(tmp_path, {
        "Продажи/Ресурсы/sale.svg": "<svg/>\n",
        "Склад/Партии/Ресурсы/lot.svg": "<svg/>\n",
    })
    source = project / "Склад" / "Ресурсы" / "logo.svg"
    for target in (project / "Продажи" / "Ресурсы", project / "Склад" / "Партии" / "Ресурсы",
                   project / "Склад"):
        with pytest.raises(ScaffoldError, match="только между папками своего каталога Ресурсы"):
            scaffold.op_move_resource(tmp_path, source, target)


def test_the_resources_folder_itself_its_description_and_bad_names_are_refused(tmp_path):
    project = _project(tmp_path)
    resources = project / "Склад" / "Ресурсы"
    with pytest.raises(ScaffoldError, match="сам каталог ресурсов"):
        scaffold.op_rename_resource_folder(tmp_path, resources, "Картинки")
    with pytest.raises(ScaffoldError, match="сам каталог ресурсов"):
        scaffold.op_delete_resource_folder(tmp_path, resources)
    with pytest.raises(ScaffoldError, match="описание ресурсов"):
        scaffold.op_move_resource(tmp_path, resources / "Ресурсы.yaml", resources / "Стили")
    with pytest.raises(ScaffoldError, match="не годится"):
        scaffold.op_rename_resource_folder(tmp_path, resources / "Стили", ".скрытая")
    with pytest.raises(ScaffoldError, match="не годится"):
        scaffold.op_move_resource(tmp_path, resources / "logo.svg", resources / "а{б}")
    with pytest.raises(ScaffoldError, match="code/resource-bare-name"):
        scaffold.op_rename_resource_folder(tmp_path, resources / "Стили", "Ресурсы")
    with pytest.raises(ScaffoldError, match="регистром"):
        scaffold.op_rename_resource_folder(tmp_path, resources / "Стили", "стили")
    with pytest.raises(ScaffoldError, match="не лежит в каталоге Ресурсы"):
        scaffold.op_delete_resource_folder(tmp_path, project / "Склад")


def test_a_key_two_visible_folders_hold_is_named_rather_than_rewritten(tmp_path):
    project = _project(tmp_path, {
        # The package keeps a namesake: from the subsystem both folders are in reach.
        "Склад/Партии/Ресурсы/Стили/a.css": "p {}\n",
    })
    resources = project / "Склад" / "Ресурсы"
    result = scaffold.op_rename_resource_folder(tmp_path, resources / "Стили", "Оформление")

    assert "Остатки.xbsl" not in _changed(result)
    ambiguous = next(n for n in result.notes if n.startswith("Не переписаны"))
    assert "Склад/Остатки.xbsl:3 Стили/a.css" in ambiguous
    # A namespace settles it: the qualified reference of the other subsystem is rewritten.
    assert "Ресурс{Демо::Учет::Склад::Оформление/a.css}" in _content(
        result, project / "Продажи" / "Заказы.xbsl")


def test_a_new_resource_folder_of_a_project_with_a_dictionary_is_reminded_of_the_pair(tmp_path):
    project = _project(tmp_path)
    (tmp_path / "xbsl-translation.yaml").write_text(
        "version: 1\nlanguage: en\ntokens:\n    Стили: Inserts\n", encoding="utf-8",
    )
    resources = project / "Склад" / "Ресурсы"
    result = scaffold.op_rename_resource_folder(tmp_path, resources / "Стили", "Оформление")
    assert any("словаре перевода" in n and "папки ресурсов Оформление" in n for n in result.notes)
    moved = scaffold.op_move_resource(tmp_path, resources / "logo.svg", resources / "Стили")
    assert not any("словаре перевода" in n for n in moved.notes)


# --- deleting a folder ----------------------------------------------------------------------------


def test_deleting_a_resource_folder_lists_what_names_its_files_and_edits_nothing(tmp_path):
    project = _project(tmp_path)
    resources = project / "Склад" / "Ресурсы"
    result = scaffold.op_delete_resource_folder(tmp_path, resources / "Стили")

    assert sorted(p.name for p in result.deletes) == ["a.css", "b.js", "flag.svg"]
    assert not result.changes and not result.renames
    assert result.notes[0].startswith("Удаляется файлов: 3 – папка Стили")
    assert "Ссылок на удаляемые файлы: 8" in result.notes[1]
    # Paths in the notes are counted from the root the references were looked for under.
    assert "Демо/Учет/Склад/Остатки.xbsl:3: Стили/a.css" in result.notes
    assert "Демо/Учет/Продажи/ФормаЗаказа.yaml:6: Склад::Стили/flag.svg" in result.notes
    assert not any("Отчеты.xbsl" in n for n in result.notes)
    assert any(n.startswith("Обращений по строке с путём 'Стили': 3") for n in result.notes)
    assert ('Демо/Учет/Склад/Остатки.xbsl:4: знч Скрипт = '
            'ПакетРесурсов.Текущий().Получить("Стили/b.js")') in result.notes

    apply_result(result)
    assert not (resources / "Стили").exists()
    assert (resources / "logo.svg").is_file()
    assert "Ресурс{Стили/a.css}" in _read(project / "Склад" / "Остатки.xbsl")


def test_emptied_dirs_are_the_folders_of_the_deleted_files_deepest_first(tmp_path):
    deleted = [tmp_path / "А" / "Б" / "В" / "х.svg", tmp_path / "А" / "у.svg", tmp_path / "А" / "Б" / "В" / "ц.svg"]
    assert scaffold.emptied_dirs(deleted) == [tmp_path / "А" / "Б" / "В", tmp_path / "А"]


# --- finding what names a resource ------------------------------------------------------------


def _places(answer: dict, project: Path) -> list[tuple[str, int, str, str]]:
    """(file under the project, line, kind, the text the range covers) of every place."""
    places = []
    for ref in answer["references"]:
        start, end = ref["range"]["start"], ref["range"]["end"]
        assert start["line"] == end["line"]
        places.append((
            Path(ref["path"]).relative_to(project).as_posix(), start["line"] + 1, ref["kind"],
            ref["text"][start["character"]:end["character"]],
        ))
    return places


def test_resource_references_name_the_places_a_move_would_touch(tmp_path):
    project = _project(tmp_path)
    resources = project / "Склад" / "Ресурсы"
    answer = scaffold.resource_references(tmp_path, resources / "Стили" / "a.css")

    assert (answer["resource"], answer["folder"], answer["resourcesDir"]) == (
        "Стили/a.css", False, str(resources))
    assert answer["total"] == 5
    assert _places(answer, project) == [
        ("Продажи/Заказы.xbsl", 5, "reference", "Демо::Учет::Склад::Стили/a.css"),
        # The literal a comment documents is the same reference, as a rename treats it.
        ("Склад/Остатки.xbsl", 1, "reference", "Стили/a.css"),
        ("Склад/Остатки.xbsl", 3, "reference", "Стили/a.css"),
        # A string with the folder and a computed name may read the file at run time.
        ("Склад/Остатки.xbsl", 6, "computed", "Стили/%Имя"),
        ("Склад/ФормаОстатков.yaml", 13, "string", "Стили/a.css"),
    ]
    # The line comes whole, so the range reads the place out of it.
    assert answer["references"][2]["text"] == "    знч Ссылка = Ресурс{Стили/a.css}.Ссылка"

    flag = _places(scaffold.resource_references(tmp_path, resources / "Стили" / "flag.svg"), project)
    assert ("Продажи/ФормаЗаказа.yaml", 6, "reference", "Склад::Стили/flag.svg") in flag
    assert ("Склад/ФормаОстатков.yaml", 9, "reference", "Стили/flag.svg") in flag
    # A bare key of another subsystem without an import does not reach the folder.
    assert not any(place[0] == "Продажи/Отчеты.xbsl" for place in flag)


def test_resource_references_of_a_folder_take_every_file_and_the_strings_of_its_path(tmp_path):
    project = _project(tmp_path)
    answer = scaffold.resource_references(tmp_path, project / "Склад" / "Ресурсы" / "Стили")

    assert answer["folder"] is True and answer["total"] == 11
    # A string that goes through the folder is spanned up to the file it leads to.
    assert [place for place in _places(answer, project) if place[2] != "reference"] == [
        ("Склад/Остатки.xbsl", 4, "string", "Стили/b.js"),
        ("Склад/Остатки.xbsl", 6, "string", "Стили/%Имя"),
        ("Склад/ФормаОстатков.yaml", 13, "string", "Стили/a.css"),
    ]


def test_a_resource_reference_whose_key_two_folders_hold_is_marked_ambiguous(tmp_path):
    project = _project(tmp_path, {"Склад/Партии/Ресурсы/Стили/a.css": "p {}\n"})
    places = _places(
        scaffold.resource_references(tmp_path, project / "Склад" / "Ресурсы" / "Стили" / "a.css"), project)
    assert ("Склад/Остатки.xbsl", 3, "ambiguous", "Стили/a.css") in places
    # A namespace settles it.
    assert ("Продажи/Заказы.xbsl", 5, "reference", "Демо::Учет::Склад::Стили/a.css") in places


def test_a_resource_reference_range_counts_characters_the_way_an_editor_does(tmp_path):
    # A character outside the basic plane is two UTF-16 code units: an editor counts it so.
    project = _project(tmp_path, {"Склад/Метки.xbsl": 'знч Метка = "\U0001F600" + Ресурс{logo.svg}\n'})
    answer = scaffold.resource_references(tmp_path, project / "Склад" / "Ресурсы" / "logo.svg")
    ref = next(r for r in answer["references"] if r["path"].endswith("Метки.xbsl"))
    column = len('знч Метка = "') + 2 + len('" + Ресурс{')
    assert ref["range"] == {"start": {"line": 0, "character": column},
                            "end": {"line": 0, "character": column + len("logo.svg")}}


def test_resource_references_refuse_what_no_key_names(tmp_path):
    project = _project(tmp_path)
    resources = project / "Склад" / "Ресурсы"
    (resources / "Пустая").mkdir()
    with pytest.raises(ScaffoldError, match="сам каталог ресурсов"):
        scaffold.resource_references(tmp_path, resources)
    with pytest.raises(ScaffoldError, match="описание ресурсов"):
        scaffold.resource_references(tmp_path, resources / "Ресурсы.yaml")
    with pytest.raises(ScaffoldError, match="нет файлов"):
        scaffold.resource_references(tmp_path, resources / "Пустая")
    with pytest.raises(ScaffoldError, match="Ресурс не найден"):
        scaffold.resource_references(tmp_path, resources / "нет.svg")


# --- surfaces -------------------------------------------------------------------------------------


def _run_cli(capsys, *argv) -> tuple[int, dict]:
    code = cli.main([str(a) for a in argv])
    return code, json.loads(capsys.readouterr().out.strip())


def test_cli_resource_commands_dry_run_writes_nothing(tmp_path, capsys):
    project = _project(tmp_path)
    resources = project / "Склад" / "Ресурсы"

    code, plan = _run_cli(capsys, "rename-resource-folder", tmp_path, resources / "Стили",
                          "Оформление", "--dry-run")
    assert code == 0 and len(plan["renames"]) == 3
    assert any(f["path"].endswith("Остатки.xbsl") and "Ресурс{Оформление/a.css}" in f["content"]
               for f in plan["files"])
    code, plan = _run_cli(capsys, "move-resource", tmp_path, resources / "logo.svg",
                          resources / "Эмблемы", "--dry-run")
    assert code == 0 and plan["renames"][0]["to"].endswith("logo.svg")
    # Deletion is irreversible: without --apply the plan is the answer, --dry-run or not.
    code, plan = _run_cli(capsys, "delete-resource-folder", tmp_path, resources / "Стили")
    assert code == 0 and plan["dry-run"] is True and len(plan["deletes"]) == 3
    assert (resources / "Стили" / "a.css").is_file() and (resources / "logo.svg").is_file()
    assert not (resources / "Эмблемы").exists()

    code, err = _run_cli(capsys, "move-resource", tmp_path, resources / "logo.svg",
                         project / "Продажи", "--dry-run")
    assert code == 2 and "своего каталога Ресурсы" in err["error"]


def test_cli_delete_resource_folder_applies(tmp_path, capsys):
    project = _project(tmp_path)
    resources = project / "Склад" / "Ресурсы"
    code, out = _run_cli(capsys, "delete-resource-folder", tmp_path, resources / "Стили", "--apply")
    assert code == 0 and "dry-run" not in out and len(out["deletes"]) == 3
    assert not (resources / "Стили").exists()


@pytest.mark.needs_data  # the written module is linted
def test_cli_move_resource_applies_and_lints(tmp_path, capsys):
    project = _project(tmp_path)
    resources = project / "Склад" / "Ресурсы"
    code, out = _run_cli(capsys, "move-resource", tmp_path, resources / "logo.svg", resources / "Эмблемы")
    assert code == 0 and out["renames"] and "lint" in out
    assert (resources / "Эмблемы" / "logo.svg").is_file()


@pytest.mark.needs_data  # the written modules are linted
def test_mcp_meta_resource_tools(mcp_module, tmp_path):
    project = _project(tmp_path)
    resources = project / "Склад" / "Ресурсы"

    plan = mcp_module.meta_rename_resource_folder(
        str(tmp_path), "Демо/Учет/Склад/Ресурсы/Стили", "Оформление", dry_run=True)
    assert plan["root"] == str(tmp_path) and all("content" not in f for f in plan["files"])
    assert (resources / "Стили").is_dir()

    renamed = mcp_module.meta_rename_resource_folder(
        str(tmp_path), "Демо/Учет/Склад/Ресурсы/Стили", "Оформление")
    assert renamed["renames"] and "lint" in renamed
    assert (resources / "Оформление" / "a.css").is_file()

    moved = mcp_module.meta_move_resource(
        str(tmp_path), "Демо/Учет/Склад/Ресурсы/logo.svg", "Демо/Учет/Склад/Ресурсы/Оформление")
    assert moved["renames"][0]["to"] == str(resources / "Оформление" / "logo.svg")
    assert "Ресурс{Оформление/logo.svg}" in _read(project / "Склад" / "Остатки.xbsl")

    plan = mcp_module.meta_delete_resource_folder(str(tmp_path), "Демо/Учет/Склад/Ресурсы/Оформление")
    assert plan["dry-run"] is True and (resources / "Оформление").is_dir()
    deleted = mcp_module.meta_delete_resource_folder(
        str(tmp_path), "Демо/Учет/Склад/Ресурсы/Оформление", dry_run=False)
    assert len(deleted["deletes"]) == 4 and not (resources / "Оформление").exists()

    err = mcp_module.meta_rename_resource_folder(str(tmp_path), "Демо/Учет/Склад/Ресурсы", "Картинки")
    assert "сам каталог ресурсов" in err["error"] and err["root"] == str(tmp_path)


def test_mcp_resource_tools_are_registered(mcp_module):
    for name in ("meta_move_resource", "meta_rename_resource_folder", "meta_delete_resource_folder",
                 "meta_resource_references"):
        assert name in mcp_module.mcp.tools


def test_lsp_resource_requests_compute_only(tmp_path):
    pytest.importorskip("pygls", reason="LSP-методы проверяются при установленном extra [lsp]")
    from xbsl import lsp as lsp_module

    server = lsp_module._make_server()
    fm = getattr(server.lsp, "fm", None) or getattr(server.lsp, "_features", None)
    features = getattr(fm, "features", fm)
    project = _project(tmp_path)
    resources = project / "Склад" / "Ресурсы"

    moved = features["xbsl/metaMoveResource"](
        {"root": str(tmp_path), "path": str(resources / "logo.svg"), "targetDir": str(resources / "Эмблемы")})
    assert moved["renames"] and "Ресурс{Эмблемы/logo.svg}" in moved["files"][0]["content"]
    renamed = features["xbsl/metaRenameResourceFolder"](
        {"root": str(tmp_path), "folderDir": str(resources / "Стили"), "newName": "Оформление"})
    assert len(renamed["renames"]) == 3
    deleted = features["xbsl/metaDeleteResourceFolder"](
        {"root": str(tmp_path), "folderDir": str(resources / "Стили")})
    assert len(deleted["deletes"]) == 3
    refused = features["xbsl/metaRenameResourceFolder"](
        {"root": str(tmp_path), "folderDir": str(resources), "newName": "Картинки"})
    assert "сам каталог ресурсов" in refused["error"]
    assert (resources / "logo.svg").is_file() and (resources / "Стили" / "a.css").is_file()


def test_cli_resource_references_answer_json_without_a_dry_run(tmp_path, capsys):
    project = _project(tmp_path)
    resources = project / "Склад" / "Ресурсы"
    code, answer = _run_cli(capsys, "resource-references", tmp_path, resources / "Стили" / "a.css")
    assert code == 0 and answer["total"] == 5 and answer["references"][0]["kind"] == "reference"
    code, err = _run_cli(capsys, "resource-references", tmp_path, resources)
    assert code == 2 and "сам каталог ресурсов" in err["error"]
    # A reading command has nothing to rehearse.
    with pytest.raises(SystemExit):
        cli.main(["resource-references", str(tmp_path), str(resources / "logo.svg"), "--dry-run"])


def test_mcp_meta_resource_references(mcp_module, tmp_path):
    project = _project(tmp_path)
    answer = mcp_module.meta_resource_references(str(tmp_path), "Демо/Учет/Склад/Ресурсы/Стили", limit=2)
    assert answer["root"] == str(tmp_path) and answer["total"] == 11
    assert len(answer["references"]) == 2
    assert answer["references"][0]["path"] == str(project / "Продажи" / "Заказы.xbsl")
    err = mcp_module.meta_resource_references(str(tmp_path), "Демо/Учет/Склад/Ресурсы")
    assert "сам каталог ресурсов" in err["error"] and err["root"] == str(tmp_path)


def test_lsp_resource_references_request(tmp_path):
    pytest.importorskip("pygls", reason="LSP-методы проверяются при установленном extra [lsp]")
    from xbsl import lsp as lsp_module

    server = lsp_module._make_server()
    fm = getattr(server.lsp, "fm", None) or getattr(server.lsp, "_features", None)
    features = getattr(fm, "features", fm)
    resources = _project(tmp_path) / "Склад" / "Ресурсы"

    answer = features["xbsl/metaResourceReferences"](
        {"root": str(tmp_path), "path": str(resources / "Стили" / "flag.svg")})
    assert answer["total"] == 6 and {ref["kind"] for ref in answer["references"]} == {"reference", "computed"}
    refused = features["xbsl/metaResourceReferences"]({"root": str(tmp_path), "path": str(resources)})
    assert "сам каталог ресурсов" in refused["error"]
