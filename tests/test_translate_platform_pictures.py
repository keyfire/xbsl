"""The pictures of the platform's library are named the way the library names them in English.

The platform ships a library of pictures a project uses without keeping any file of its own:
the documentation names such a picture by the subsystem of the library or bare
(`Изображение: Стд::Аккаунт.svg`, `Изображение: Аккаунт.svg`, `Ресурс{Стд::Грузовик.svg}`).
The English library holds the same drawings under English names, and the extractor pairs the
two by their bytes (`uiterms.resource_paths`). Before that table a reference was left Russian
in a yaml and reported as a file of the project, and in the code it took the flat compiler
dictionary word by word: `Команда.svg` came out `Command.svg` while the library calls it
`Team.svg`, `Перечитать.svg` came out `Table.svg` instead of `Refresh.svg`.

A reference is what the compiler resolves - the value of a picture property and the body of
`Ресурс{...}`. A string is not one: at run time a path is read by `ПакетРесурсов.Текущий()`,
the resource package of the current namespace, which cannot see the library at all.

The data of the tests is a copy of the generated data with a table of a few pairs of the
library - or without the table, the way data extracted before it looks.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from xbsl import dataset
from xbsl.translation import dictionary as dict_module
from xbsl.translation.project import translate_project

pytestmark = pytest.mark.needs_data

#: Pairs of the library as the extractor files them. Five of them are drawings the flat compiler
#: dictionary spells otherwise - `Команда.svg` as `Command.svg`, `Перечитать.svg` as `Table.svg`,
#: `Письмо.svg` as `Email.svg`, `Вход.svg` as `Enter.svg`, `Сохранить.svg` as `Keep.svg`; the
#: other two it spells the way the library does.
LIBRARY = {
    f"Icons/Стд/Ресурсы/{russian}.svg": f"Icons/Std/Resources/{english}.svg"
    for russian, english in (
        ("Команда", "Team"), ("Перечитать", "Refresh"), ("Письмо", "Mail"), ("Вход", "Login"),
        ("Сохранить", "Save"), ("Время", "Time"), ("Папка", "Folder"),
    )
}


def picture_data_root(root: Path, pictures: dict | None) -> Path:
    """A copy of the generated data of the current version with the given table of pictures,
    or with no table at all when `pictures` is None."""
    version = dataset.resolve_version()
    target = root / version
    target.mkdir(parents=True)
    for path in (dataset.data_root() / version).glob("*.json"):
        shutil.copyfile(path, target / path.name)
    uiterms = json.loads((target / "uiterms.json").read_text(encoding="utf-8"))
    if pictures is None:
        uiterms.pop("resource_paths", None)
    else:
        uiterms["resource_paths"] = dict(pictures)
    (target / "uiterms.json").write_text(json.dumps(uiterms, ensure_ascii=False), encoding="utf-8")
    (root / "index.json").write_text(
        json.dumps({"available": [version], "default": version}), encoding="utf-8")
    return root


@pytest.fixture(scope="module")
def picture_roots(tmp_path_factory) -> dict[str, Path]:
    base = tmp_path_factory.mktemp("pictures")
    return {
        "library": picture_data_root(base / "library", LIBRARY),
        "before": picture_data_root(base / "before", None),
    }


@pytest.fixture()
def with_library(picture_roots):
    dataset.set_data_root(picture_roots["library"])
    yield
    dataset.set_data_root(None)


@pytest.fixture()
def before_the_library(picture_roots):
    dataset.set_data_root(picture_roots["before"])
    yield
    dataset.set_data_root(None)


def _dictionary(tokens: dict | None = None) -> dict_module.Dictionary:
    return dict_module.Dictionary(tokens=dict(tokens or {}), phrases={}, literals={})


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _project(tmp_path: Path) -> Path:
    """Every form a picture is named in, next to a file of the project named like a picture of
    the library and to paths the library does not hold."""
    root = tmp_path / "Acme" / "Demo"
    _write(root / "Задачи" / "Ресурсы" / "Сохранить.svg", "<svg/>\n")
    buttons = (
        ("Первая", "Команда.svg"),
        ("Вторая", "Стд::Перечитать.svg"),
        ("Третья", '"Письмо.svg"'),
        ("Четвертая", "Сохранить.svg"),
        ("Пятая", "Иконки/Команда.svg"),
    )
    content = "".join(
        "            -\n"
        "                Тип: Кнопка\n"
        f"                Имя: {name}\n"
        f"                Изображение: {picture}\n"
        for name, picture in buttons
    )
    # A caption is text a person reads - the schema types it "Строка" - and one that happens to
    # read like a name of the library is data all the same.
    content += (
        "            -\n"
        "                Тип: Кнопка\n"
        "                Имя: Шестая\n"
        "                Заголовок: Время.svg\n"
    )
    _write(root / "Задачи" / "Карточка.yaml", (
        "ВидЭлемента: КомпонентИнтерфейса\n"
        "Имя: Карточка\n"
        "Наследует:\n"
        "    Тип: ПроизвольныйКомпонент\n"
        "    Содержимое:\n"
        "        Тип: Группа\n"
        "        Содержимое:\n"
        f"{content}"
    ))
    _write(root / "Задачи" / "Картинки.xbsl", (
        "метод Картинки()\n"
        "    знч Первая = Ресурс{Команда.svg}\n"
        "    знч Вторая = Ресурс{Стд::Перечитать.svg}\n"
        "    знч Третья = Ресурс{Сохранить.svg}\n"
        '    знч Четвертая = "Вход.svg"\n'
        '    знч Пятая = "Стд::Письмо.svg"\n'
        "    знч Шестая = Ресурс{Сайт::Команда.svg}\n"
        '    знч Седьмая = "Иконки/Команда.svg"\n'
        ";\n"
    ))
    return root


def _translate(tmp_path: Path, tokens: dict | None = None):
    root = _project(tmp_path)
    out = tmp_path / "en"
    report = translate_project(root, _dictionary({"Задачи": "Tasks", **(tokens or {})}), out,
                               swap_localization=False)
    card = (out / "Tasks" / "Карточка.yaml").read_text(encoding="utf-8")
    module = (out / "Tasks" / "Картинки.xbsl").read_text(encoding="utf-8")
    return card, module, report


def test_a_picture_of_the_library_takes_its_english_name_in_every_form(tmp_path, with_library):
    card, module, report = _translate(tmp_path)

    assert "Image: Team.svg" in card
    assert "Image: Std::Refresh.svg" in card
    assert 'Image: "Mail.svg"' in card
    assert "val Первая = Resource{Team.svg}" in module
    assert "val Вторая = Resource{Std::Refresh.svg}" in module
    # None of them is a file of the project, and none waits for an entry.
    missing = report.merged_missing_tokens()
    for word in ("Команда", "Перечитать", "Письмо", "Стд"):
        assert not (missing.get(word) or {}).get("resource"), (word, missing.get(word))


def test_a_file_of_the_project_named_like_a_picture_of_the_library_is_the_project_s(
        tmp_path, with_library):
    card, module, report = _translate(tmp_path)

    assert "Image: Сохранить.svg" in card
    assert "val Третья = Resource{Сохранить.svg}" in module
    assert report.merged_missing_tokens()["Сохранить"].get("resource")

    card, module, _report = _translate(tmp_path / "entry", {"Сохранить": "SaveIcon"})

    assert "Image: SaveIcon.svg" in card
    assert "val Третья = Resource{SaveIcon.svg}" in module
    assert (tmp_path / "entry" / "en" / "Tasks" / "Resources" / "SaveIcon.svg").is_file()


def test_the_qualified_form_means_the_library_beside_a_file_of_the_same_name(
        tmp_path, with_library):
    """`Стд::Сохранить.svg` names the library even where the project keeps `Сохранить.svg`.

    The namespace is the whole difference between the two references, so reading it off before
    the project is asked makes the qualified form mean whatever the bare one means - and the
    project's file, which the library has no idea about, wins over the library that is named
    right there.
    """
    root = tmp_path / "Acme" / "Demo"
    _write(root / "Задачи" / "Ресурсы" / "Сохранить.svg", "<svg/>\n")
    _write(root / "Задачи" / "Карточка.yaml", (
        "ВидЭлемента: КомпонентИнтерфейса\n"
        "Имя: Карточка\n"
        "Наследует:\n"
        "    Тип: ПроизвольныйКомпонент\n"
        "    Содержимое:\n"
        "        Тип: Кнопка\n"
        "        Имя: Первая\n"
        "        Изображение: Стд::Сохранить.svg\n"
    ))
    _write(root / "Задачи" / "Картинки.xbsl", (
        "метод Картинки()\n"
        "    знч Первая = Ресурс{Стд::Сохранить.svg}\n"
        "    знч Вторая = Ресурс{Сохранить.svg}\n"
        ";\n"
    ))
    out = tmp_path / "en"
    translate_project(root, _dictionary({"Задачи": "Tasks", "Сохранить": "SaveIcon"}), out,
                      swap_localization=False)
    card = (out / "Tasks" / "Карточка.yaml").read_text(encoding="utf-8")
    module = (out / "Tasks" / "Картинки.xbsl").read_text(encoding="utf-8")

    assert "Image: Std::Save.svg" in card
    assert "val Первая = Resource{Std::Save.svg}" in module
    # The bare form still asks the project first, and the project has that file.
    assert "val Вторая = Resource{SaveIcon.svg}" in module


def test_a_string_never_names_a_picture_of_the_library(tmp_path, with_library):
    """A string reaches the resources of its OWN namespace and no further.

    What reads a path at run time is `ПакетРесурсов.Текущий()`, the resource package of the
    current namespace, so no string of a project - and no value the schema types as text -
    can address the library. A string spelled exactly like a name of the library is data that
    happens to read like one, and the library must not answer for it; a path-shaped string
    goes on being read as a path into the project's own resources, as it was before the
    library table existed.
    """
    card, module, report = _translate(tmp_path)

    assert 'val Четвертая = "Enter.svg"' in module
    assert 'val Пятая = "Стд::Письмо.svg"' in module
    assert "Время.svg" in card and "Time.svg" not in card
    # The name of the caption is the project's word to name, and it says so.
    assert (report.merged_missing_tokens().get("Время") or {}).get("resource")
    assert "Стд::Письмо.svg" in report.merged_missing_literals()


def test_a_path_the_library_does_not_hold_is_not_named_by_its_last_word(tmp_path, with_library):
    card, module, _report = _translate(tmp_path)

    assert "Image: Иконки/Команда.svg" in card
    for line in module.splitlines():
        if "Шестая" in line or "Седьмая" in line:
            assert "Team" not in line, line


def test_an_entry_does_not_rename_a_picture_of_the_library(tmp_path, with_library):
    """The library names its pictures itself: an entry written for a word of the project is not
    asked about the picture, and one that spells the picture the same way is a workaround the
    platform now repeats."""
    root = _project(tmp_path)
    module_path = root / "Задачи" / "Картинки.xbsl"
    module_path.write_text(module_path.read_text(encoding="utf-8") + (
        "\n"
        "метод Выполнить(Команда: Строка)\n"
        ";\n"
    ), encoding="utf-8")
    out = tmp_path / "en"
    report = translate_project(root, _dictionary({
        "Задачи": "Tasks", "Команда": "Command", "Письмо": "Letter", "Вход": "Login",
        "Перечитать": "Refresh",
    }), out, swap_localization=False)
    card = (out / "Tasks" / "Карточка.yaml").read_text(encoding="utf-8")
    module = (out / "Tasks" / "Картинки.xbsl").read_text(encoding="utf-8")

    assert "Image: Team.svg" in card and 'Image: "Mail.svg"' in card
    assert "Resource{Team.svg}" in module
    assert "method Выполнить(Command: String)" in module
    # An entry that spells the picture the way the library does is a workaround the platform
    # now repeats; one it spells otherwise is not judged at all, because a picture never asks
    # the dictionary.
    assert report.echoed.get("Перечитать") == "Refresh"
    assert "Письмо" not in report.echoed
    # The string is no picture: there the entry is the only answer, and it is load-bearing -
    # without it the word would go the way the platform spells it (`Enter`).
    assert '"Login.svg"' in module and "Вход" not in report.echoed


def test_an_english_reference_to_the_library_stays_as_written(tmp_path, with_library):
    root = tmp_path / "Acme" / "Demo"
    _write(root / "Задачи" / "Английские.xbsl", (
        "метод Английские()\n"
        "    знч Первая = Resource{Std::Refresh.svg}\n"
        '    знч Вторая = "Login.svg"\n'
        "    знч Третья = Ресурс{Team.svg}\n"
        ";\n"
    ))
    out = tmp_path / "en"
    translate_project(root, _dictionary({"Задачи": "Tasks"}), out, swap_localization=False)
    module = (out / "Tasks" / "Английские.xbsl").read_text(encoding="utf-8")

    assert " = Resource{Std::Refresh.svg}\n" in module
    assert ' = "Login.svg"\n' in module
    assert " = Resource{Team.svg}\n" in module


@pytest.mark.parametrize("descriptor", [False, True], ids=["fragment", "project"])
def test_the_gap_rule_knows_the_files_of_the_project(tmp_path, with_library, descriptor):
    """`conventions/missing-translation` reads the tree with the same eyes as the rewrite.

    The rule builds its own resolver, and one built without the files of the project has the
    library answer for every name the library holds - so a file of the project named like a
    picture of the library asked for no entry, and the rewrite that DOES know the file then
    left the name Russian with nothing in the editor to say why.

    Both shapes the rule meets: a project with a descriptor, and a fragment without one, where
    the dictionary says which tree to look in.
    """
    from xbsl import engine
    from xbsl.cli import discover

    root = tmp_path / "Acme" / "Demo"
    if descriptor:
        _write(root / "Проект.yaml",
               "ВидЭлемента: Проект\nИд: 11111111-2222-3333-4444-555555555555\nИмя: Demo\n"
               "Версия: 1.0\nПоставщик: acme\n")
    _write(root / "Задачи" / "Ресурсы" / "Сохранить.svg", "<svg/>\n")
    _write(root / "Задачи" / "Карточка.yaml", (
        "ВидЭлемента: КомпонентИнтерфейса\n"
        "Имя: Карточка\n"
        "Наследует:\n"
        "    Тип: ПроизвольныйКомпонент\n"
        "    Содержимое:\n"
        "        Тип: Кнопка\n"
        "        Имя: Первая\n"
        "        Изображение: Сохранить.svg\n"
    ))
    _write(root / "xbsl-translation" / "010-tokens.yaml",
           "version: 1\nlanguage: en\ntokens:\n    Задачи: Tasks\n    Карточка: Card\n"
           "    Первая: First\n")

    found = [d for d in engine.run(discover([str(root)]),
                                   enable={"conventions/missing-translation"})
             if d.rule_id == "conventions/missing-translation"]

    assert any("Сохранить" in d.message for d in found), [d.message for d in found]


def test_data_without_the_table_keeps_the_previous_reading(tmp_path, before_the_library):
    card, module, report = _translate(tmp_path)

    assert "Image: Команда.svg" in card
    assert report.merged_missing_tokens()["Команда"].get("resource")
    assert not any(word in module for word in ("Team", "Refresh", "Login", "Mail"))
