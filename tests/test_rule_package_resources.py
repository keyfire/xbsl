"""code/package-resources-missing: `ПакетРесурсов.Текущий()` in a package without resources.

`Текущий()` returns the resources of the current namespace, and a module of a package lives in
the namespace of the package, not of its subsystem. A module that read icons by a computed name
was moved into a package that keeps no resources folder, and a fresh seeding left every record
without its icon - no error anywhere, the same module at the root of the subsystem found them
all. The rule looks the folder up on disk, so the fixtures are written to a temporary folder;
the mapper tokenizes the module, which needs the language data.
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


def _write(root: Path, files: dict[str, str]) -> list[Path]:
    written = []
    for rel, text in files.items():
        path = root / BASE / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
        written.append(path)
    return written


def _project(root: Path, module_dir: str, code: str = READER, extra: dict | None = None) -> list:
    files = {
        "Проект.yaml": "Поставщик: Демо\nИмя: Учет\nВерсия: 1.0.0\n",
        "Склад/Подсистема.yaml": "Интерфейс:\n    ВключатьВАвтоИнтерфейс: Ложь\n",
        "Склад/Ресурсы/Партия.svg": "<svg/>",
        f"{module_dir}/Значки.yaml": "ВидЭлемента: ОбщийМодуль\nИмя: Значки\n",
        f"{module_dir}/Значки.xbsl": code,
    }
    files.update(extra or {})
    return [p for p in _write(root, files) if p.suffix in (".yaml", ".xbsl")]


def _lint(paths: list[Path]):
    return engine.run(paths, select={RULE})


def test_a_package_without_resources_is_reported(tmp_path):
    diags = _lint(_project(tmp_path, "Склад/Партии"))
    assert [(Path(d.path).name, d.line, d.col, d.severity.value) for d in diags] == [
        ("Значки.xbsl", 2, 13, "warning")
    ]
    assert "'Склад::Партии'" in diags[0].message and "Ресурс{...}" in diags[0].message


def test_a_package_with_a_folder_of_its_own_is_silent(tmp_path):
    for folder in ("Ресурсы", "Resources"):
        root = tmp_path / folder
        extra = {f"Склад/Партии/{folder}/Партия.svg": "<svg/>"}
        assert _lint(_project(root, "Склад/Партии", extra=extra)) == [], folder


def test_the_root_of_a_subsystem_reads_its_own_folder(tmp_path):
    assert _lint(_project(tmp_path, "Склад")) == []


def test_a_nested_package_needs_a_folder_of_its_own(tmp_path):
    """The folder of the enclosing package is not the folder of the nested one."""
    extra = {"Склад/Партии/Ресурсы/Партия.svg": "<svg/>"}
    diags = _lint(_project(tmp_path, "Склад/Партии/Архив", extra=extra))
    assert len(diags) == 1 and "'Склад::Партии::Архив'" in diags[0].message


def test_the_english_spelling_of_the_call_is_read(tmp_path):
    code = READER.replace("ПакетРесурсов.Текущий()", "ResourcesPackage.Current()")
    assert len(_lint(_project(tmp_path, "Склад/Партии", code))) == 1


def test_a_mention_outside_the_code_and_a_literal_are_silent(tmp_path):
    code = (
        "// ПакетРесурсов.Текущий() здесь не нужен\n"
        "метод Значок(): ДвоичныйОбъект.Ссылка?\n"
        "    знч Подсказка = \"ПакетРесурсов.Текущий()\"\n"
        "    возврат Ресурс{Партия.svg}.Ссылка\n"
        ";\n"
    )
    assert _lint(_project(tmp_path, "Склад/Партии", code)) == []


def test_a_module_that_is_not_on_disk_is_not_judged():
    files = {
        "Демо/Учет/Проект.yaml": "Поставщик: Демо\nИмя: Учет\n",
        "Демо/Учет/Склад/Партии/Значки.yaml": "ВидЭлемента: ОбщийМодуль\nИмя: Значки\n",
        "Демо/Учет/Склад/Партии/Значки.xbsl": READER,
    }
    sources = [engine.load_text(name, text) for name, text in files.items()]
    assert engine.run_sources(sources, select={RULE}) == []


def test_the_english_message_names_the_platform_in_english(tmp_path):
    paths = _project(tmp_path, "Склад/Партии")
    i18n.set_lang("en")
    try:
        diags = _lint(paths)
    finally:
        i18n.set_lang("ru")
    assert len(diags) == 1
    assert "ResourcesPackage.Current()" in diags[0].message and "Resource{...}" in diags[0].message
