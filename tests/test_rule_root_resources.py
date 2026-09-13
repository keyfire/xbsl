"""code/package-resources-missing at the root of a subsystem without a resources folder.

`ResourcesPackage.Current()` returns the resources of the current namespace. A probe run at the
first apply of a project showed what that means at the root of a subsystem with no resources
folder: nothing is found - `GetAll()` itself throws `ResourceNotFoundException` - neither a file
of a package of that subsystem nor a file of another subsystem, while the same reader at the root
of a subsystem that keeps the folder finds its file. The rule used to leave the root alone.

The rule looks the folder up on disk, so the fixtures are written to a temporary folder; the
mapper tokenizes the module, which needs the language data.
"""

from pathlib import Path

import pytest

from xbsl import engine, i18n

RULE = "code/package-resources-missing"
BASE = Path("Демо") / "Учет"

pytestmark = pytest.mark.needs_data  # the lexer reads the operators and keywords from the data

READER = (
    "метод Значок(Код: Строка): ДвоичныйОбъект.Ссылка?\n"
    "    возврат ПакетРесурсов.Текущий().Получить(\"%{Код}.svg\").Ссылка\n"
    ";\n"
)


def _project(root: Path, files: dict[str, str]) -> list[Path]:
    files = {
        "Проект.yaml": "Поставщик: Демо\nИмя: Учет\nВерсия: 1.0.0\n",
        "Склад/Подсистема.yaml": "Интерфейс:\n    ВключатьВАвтоИнтерфейс: Ложь\n",
        "Продажи/Подсистема.yaml": "Использование:\n    - Склад\n",
        "Продажи/Ресурсы/Заказ.svg": "<svg/>",
        **files,
    }
    written = []
    for rel, text in files.items():
        path = root / BASE / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
        written.append(path)
    return [p for p in written if p.suffix in (".yaml", ".xbsl")]


def _reader(folder: str, code: str = READER) -> dict[str, str]:
    return {
        f"{folder}/Значки.yaml": "ВидЭлемента: ОбщийМодуль\nИмя: Значки\n",
        f"{folder}/Значки.xbsl": code,
    }


def _lint(paths: list[Path]):
    return engine.run(paths, select={RULE})


def test_the_root_of_a_subsystem_without_resources_is_reported(tmp_path):
    diags = _lint(_project(tmp_path, _reader("Склад")))
    assert [(Path(d.path).name, d.line, d.col, d.severity.value) for d in diags] == [
        ("Значки.xbsl", 2, 13, "warning")
    ]
    assert "модуле корня подсистемы 'Склад'" in diags[0].message
    assert diags[0].data == {"namespace": "Склад"}


def test_the_resources_of_a_package_do_not_serve_the_root(tmp_path):
    extra = {**_reader("Склад"), "Склад/Партии/Ресурсы/Партия.svg": "<svg/>"}
    assert len(_lint(_project(tmp_path, extra))) == 1


def test_a_root_with_a_folder_of_its_own_is_silent(tmp_path):
    for folder in ("Ресурсы", "Resources"):
        root = tmp_path / folder
        extra = {**_reader("Склад"), f"Склад/{folder}/Партия.svg": "<svg/>"}
        assert _lint(_project(root, extra)) == [], folder


def test_a_package_keeps_its_own_message(tmp_path):
    diags = _lint(_project(tmp_path, {**_reader("Склад/Партии"), "Склад/Ресурсы/Партия.svg": "<svg/>"}))
    assert len(diags) == 1 and "'Склад::Партии'" in diags[0].message
    assert "корня" not in diags[0].message


def test_the_project_module_is_not_judged(tmp_path):
    paths = _project(tmp_path, {"Проект.xbsl": READER})
    assert _lint(paths) == []


def test_the_english_message_for_the_root(tmp_path):
    paths = _project(tmp_path, _reader("Склад"))
    i18n.set_lang("en")
    try:
        diags = _lint(paths)
    finally:
        i18n.set_lang("ru")
    assert len(diags) == 1
    assert "at the root of subsystem 'Склад'" in diags[0].message
    assert "GetAll()" in diags[0].message
