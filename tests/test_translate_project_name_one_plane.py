"""A name the project gave something is spelled by one plane at every place it stands.

The translator lets the project dictionary answer the names a project declares and keeps the
platform tables away from them, so that a declaration and its uses move together. Two kinds of
places still asked the platform while their other half asked the dictionary alone:

- a resource file: the file of the tree and the path in the code took the compiler dictionary's
  word for a stem like a platform method (`CreateCopy.svg`), while the form referring to the file
  went on naming the Russian one, and the build found no such resource;
- a method of an interface component of the project, called through a node of a form: the call
  took the platform's built-in command of the same spelling (`Refresh`) while the declaration in
  the component's module waited for an entry.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from xbsl import dataset, engine
from xbsl.translation import dictionary as dict_module
from xbsl.translation import names
from xbsl.translation.project import translate_project


def _dictionary(tokens: dict | None = None) -> dict_module.Dictionary:
    return dict_module.Dictionary(tokens=dict(tokens or {}), phrases={}, literals={})


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _files(root: Path) -> set[str]:
    return {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}


# --- resources ------------------------------------------------------------------------------


def _resource_project(tmp_path: Path) -> Path:
    root = tmp_path / "Acme" / "Demo"
    _write(root / "Задачи" / "Ресурсы" / "СоздатьКопию.svg", "<svg/>\n")
    _write(root / "Задачи" / "Ресурсы" / "Значки" / "Флаг.svg", "<svg/>\n")
    _write(root / "Задачи" / "Ресурсы" / "Ресурсы.yaml", "ОбластьВидимости: ВПроекте\n")
    _write(root / "Задачи" / "КарточкаЗадачи.yaml", (
        "ВидЭлемента: КомпонентИнтерфейса\n"
        "Имя: КарточкаЗадачи\n"
        "Наследует:\n"
        "    Тип: ПроизвольныйКомпонент\n"
        "    Содержимое:\n"
        "        Тип: Картинка\n"
        "        Имя: Значок\n"
        "        Изображение: СоздатьКопию.svg\n"
    ))
    _write(root / "Задачи" / "Пиктограммы.xbsl", (
        "метод ЗначокКопии(): Строка\n"
        "    знч Первый = Ресурс{СоздатьКопию.svg}\n"
        "    знч Второй = Ресурс{Задачи::СоздатьКопию.svg}\n"
        "    знч Флаг = Ресурс{Значки/Флаг.svg}\n"
        '    возврат "Значки/Флаг.svg"\n'
        ";\n"
    ))
    return root


def test_a_resource_named_like_a_platform_word_waits_for_the_dictionary_everywhere(tmp_path: Path):
    root = _resource_project(tmp_path)
    out = tmp_path / "en"
    report = translate_project(root, _dictionary({"Задачи": "Tasks"}), out, swap_localization=False)
    project = out

    files = _files(project)
    assert "Tasks/Resources/СоздатьКопию.svg" in files, files
    assert "Tasks/Resources/Значки/Флаг.svg" in files, files
    assert "Image: СоздатьКопию.svg" in (project / "Tasks" / "КарточкаЗадачи.yaml").read_text(encoding="utf-8")
    module = (project / "Tasks" / "Пиктограммы.xbsl").read_text(encoding="utf-8")
    assert "Resource{СоздатьКопию.svg}" in module
    assert "Resource{Tasks::СоздатьКопию.svg}" in module
    assert "Resource{Значки/Флаг.svg}" in module
    assert 'return "Значки/Флаг.svg"' in module
    # Not the platform's gap and not a silent guess: the project's own names, listed as files.
    missing = report.merged_missing_tokens()
    assert {"СоздатьКопию", "Значки", "Флаг"} <= set(missing)


def test_a_resource_entry_renames_the_file_and_every_reference_to_it(tmp_path: Path):
    root = _resource_project(tmp_path)
    out = tmp_path / "en"
    translate_project(root, _dictionary({
        "Задачи": "Tasks", "СоздатьКопию": "CopyIcon", "Значки": "Icons", "Флаг": "Flag",
    }), out, swap_localization=False)
    project = out

    files = _files(project)
    assert {"Tasks/Resources/CopyIcon.svg", "Tasks/Resources/Icons/Flag.svg"} <= files, files
    # The descriptor of the folder is the platform's own file name.
    assert "Tasks/Resources/Resources.yaml" in files, files
    assert "Image: CopyIcon.svg" in (project / "Tasks" / "КарточкаЗадачи.yaml").read_text(encoding="utf-8")
    module = (project / "Tasks" / "Пиктограммы.xbsl").read_text(encoding="utf-8")
    assert "Resource{CopyIcon.svg}" in module
    assert "Resource{Tasks::CopyIcon.svg}" in module
    assert "Resource{Icons/Flag.svg}" in module
    assert 'return "Icons/Flag.svg"' in module


def test_a_path_through_the_folder_of_resources_renames_only_what_lies_below_it(tmp_path: Path):
    root = tmp_path / "Acme" / "Demo"
    _write(root / "Задачи" / "Ресурсы" / "СоздатьКопию.svg", "<svg/>\n")
    _write(root / "Задачи" / "Пути.xbsl", (
        "метод Путь(): Строка\n"
        '    возврат "Задачи/Ресурсы/СоздатьКопию.svg"\n'
        ";\n"
    ))
    out = tmp_path / "en"
    translate_project(root, _dictionary({"Задачи": "Tasks"}), out, swap_localization=False)
    module = (out / "Tasks" / "Пути.xbsl").read_text(encoding="utf-8")
    # The subsystem and the folder go the way names of the structure go; the file below them
    # is the project's resource and keeps its name until the dictionary gives it one.
    assert 'return "Tasks/Resources/СоздатьКопию.svg"' in module


def _library_pictures_project(tmp_path: Path):
    root = tmp_path / "Acme" / "Demo"
    _write(root / "Задачи" / "Ресурсы" / "СоздатьКопию.svg", "<svg/>\n")
    _write(root / "Задачи" / "Картинки.xbsl", (
        # A field spelled like the picture: the word is a name the project declares, and the
        # picture of the library must still not be read as that name.
        "структура Отметка\n"
        "    пер Время: Строка\n"
        ";\n"
        "\n"
        "метод Часы(): Строка\n"
        "    знч Своя = Ресурс{СоздатьКопию.svg}\n"
        "    знч Библиотеки = Ресурс{Время.svg}\n"
        '    знч Путь = "Время.svg"\n'
        '    знч Папка = "Папка.svg"\n'
        ";\n"
    ))
    out = tmp_path / "en"
    report = translate_project(root, _dictionary({"Задачи": "Tasks"}), out, swap_localization=False)
    return (out / "Tasks" / "Картинки.xbsl").read_text(encoding="utf-8"), report


@pytest.fixture(scope="module")
def picture_roots(tmp_path_factory) -> dict[str, Path]:
    from test_translate_platform_pictures import LIBRARY, picture_data_root

    base = tmp_path_factory.mktemp("pictures")
    return {"library": picture_data_root(base / "library", LIBRARY),
            "before": picture_data_root(base / "before", None)}


def test_a_picture_of_the_platform_library_is_not_a_resource_of_the_project(tmp_path: Path,
                                                                            picture_roots):
    dataset.set_data_root(picture_roots["library"])
    try:
        module, report = _library_pictures_project(tmp_path)
    finally:
        dataset.set_data_root(None)
    assert "Resource{СоздатьКопию.svg}" in module
    # The project has no such files: the names belong to the platform's library of pictures,
    # which carries its own English names, and every place that names the picture takes them.
    assert "Resource{Time.svg}" in module
    assert '"Time.svg"' in module
    assert '"Folder.svg"' in module
    # The field is the project's gap; the picture is never listed as a file of the project.
    missing = report.merged_missing_tokens()
    assert not (missing.get("Время") or {}).get("resource"), missing.get("Время")
    assert missing["СоздатьКопию"].get("resource")


def test_data_without_the_library_keeps_the_reading_each_place_had(tmp_path: Path, picture_roots):
    dataset.set_data_root(picture_roots["before"])
    try:
        module, report = _library_pictures_project(tmp_path)
    finally:
        dataset.set_data_root(None)
    assert "Resource{СоздатьКопию.svg}" in module
    # The root of the literal reads the type, a path in a string reads a name - and the name
    # the project declares waits for its entry.
    assert "Resource{Time.svg}" in module
    assert '"Время.svg"' in module
    assert '"Folder.svg"' in module
    missing = report.merged_missing_tokens()
    assert not (missing.get("Время") or {}).get("resource"), missing.get("Время")


# --- a method of a component of the project -------------------------------------------------


def _component_project(tmp_path: Path) -> Path:
    root = tmp_path / "Acme" / "Demo"
    _write(root / "ЛентаЗадач.yaml", (
        "ВидЭлемента: КомпонентИнтерфейса\n"
        "Имя: ЛентаЗадач\n"
        "Свойства:\n"
        "    -\n"
        "        Имя: Заголовок\n"
        "        Тип: Строка\n"
        "Наследует:\n"
        "    Тип: ПроизвольныйКомпонент\n"
    ))
    _write(root / "ЛентаЗадач.xbsl", "метод Обновить()\n;\n")
    _write(root / "КарточкаСклада.yaml", (
        "ВидЭлемента: КомпонентИнтерфейса\n"
        "Имя: КарточкаСклада\n"
        "Наследует:\n"
        "    Тип: ПроизвольныйШаблонФормы\n"
        "    Содержимое:\n"
        "        Тип: Группа\n"
        "        Содержимое:\n"
        "            -\n"
        "                Тип: ЛентаЗадач\n"
        "                Имя: Лента\n"
        "            -\n"
        "                Тип: ПроизвольныйСписок<ДинамическийСписок<Задачи.Ссылка>>\n"
        "                Имя: Партии\n"
    ))
    _write(root / "КарточкаСклада.xbsl", (
        "метод Перечитать()\n"
        "    Компоненты.Лента.Обновить()\n"
        "    Компоненты.Партии.Обновить()\n"
        ";\n"
    ))
    return root


def test_a_method_of_a_project_component_called_through_its_node_is_the_project_s(tmp_path: Path):
    root = _component_project(tmp_path)
    out = tmp_path / "en"
    report = translate_project(root, _dictionary(), out, swap_localization=False)
    form = (out / "КарточкаСклада.xbsl").read_text(encoding="utf-8")
    # The component of the project declares the method: without an entry the call waits with it.
    assert "method Обновить()" in (out / "ЛентаЗадач.xbsl").read_text(encoding="utf-8")
    assert "Components.Лента.Обновить()" in form
    # The platform's list keeps its own command, whatever the project declares elsewhere.
    assert "Components.Партии.Refresh()" in form
    assert "Обновить" in report.merged_missing_tokens()

    out = tmp_path / "en2"
    translate_project(root, _dictionary({"Обновить": "Reload"}), out, swap_localization=False)
    form = (out / "КарточкаСклада.xbsl").read_text(encoding="utf-8")
    assert "method Reload()" in (out / "ЛентаЗадач.xbsl").read_text(encoding="utf-8")
    assert "Components.Лента.Reload()" in form
    assert "Components.Партии.Refresh()" in form


def test_the_nodes_of_a_form_are_read_without_the_declared_properties(tmp_path: Path):
    root = _component_project(tmp_path)
    _write(root / "ЛентаЗадач.xbsl", "метод Обновить()\n;\n")
    nodes = names.form_nodes(root / "КарточкаСклада.xbsl", engine.load)
    assert nodes == {"Лента": "ЛентаЗадач", "Партии": "ПроизвольныйСписок"}
    # A property of a component names a type too, and it is not a node.
    assert names.form_nodes(root / "ЛентаЗадач.xbsl", engine.load) == {}
    assert names.component_methods(root, engine.load) == {
        "ЛентаЗадач": frozenset({"Обновить"}), "КарточкаСклада": frozenset({"Перечитать"}),
    }
