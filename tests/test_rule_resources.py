"""Checks of the resource rules: code/resource-bare-name and code/unknown-resource.

The platform image library is stubbed, so the tests need no documentation data; one test
marked needs_data checks that the real library is read and holds the documented names.
"""

import pytest

from xbsl import engine
from xbsl.cli import discover
from xbsl.rules import resources

_BARE = "code/resource-bare-name"
_UNKNOWN = "code/unknown-resource"

_PROJECT_YAML = (
    "Ид: 9a1b2c3d-4e5f-6071-8293-a4b5c6d7e8f9\nВерсия: 1.0.0\nВидПроекта: Приложение\n"
    "Имя: Проба\nПоставщик: acme\nПредставление: Проба\nРежимСовместимости: 9.0\n"
)


@pytest.fixture
def library(monkeypatch):
    """A stubbed image library: one name, as if the platform shipped exactly that."""
    monkeypatch.setattr(resources, "_platform_images", lambda: frozenset({"Настройки.svg"}))


def _project(tmp_path, module_text, resource_names=("Своя.svg",)):
    root = tmp_path / "acme" / "Проба"
    (root / "Основное" / "Ресурсы").mkdir(parents=True)
    (root / "Проект.yaml").write_text(_PROJECT_YAML, encoding="utf-8")
    for name in resource_names:
        path = root / "Основное" / "Ресурсы" / name  # a name may carry a subfolder
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("<svg/>", encoding="utf-8")
    (root / "Основное" / "М.xbsl").write_text(module_text, encoding="utf-8")
    return tmp_path


def _run(tmp_path, module_text, select, resource_names=("Своя.svg",)):
    _project(tmp_path, module_text, resource_names)
    return engine.run(discover([str(tmp_path)]), select={select})


def _method(body):
    return f"// М\n\nметод М(): ДвоичныйОбъект.Ссылка\n    возврат {body}\n;\n"


# --- code/resource-bare-name (file scope, no data needed) ---------------------------------


def test_path_with_folder_flagged(tmp_path):
    d = _run(tmp_path, _method("Ресурс{Ресурсы/Своя.svg}.Ссылка"), _BARE)
    assert len(d) == 1 and d[0].rule_id == _BARE
    assert d[0].severity.name == "ERROR"
    assert "Ресурс{Своя.svg}" in d[0].message
    assert (d[0].line, d[0].col) == (4, 20)  # the first character inside the braces


def test_backslash_path_flagged(tmp_path):
    d = _run(tmp_path, _method("Ресурс{Ресурсы\\Своя.svg}.Ссылка"), _BARE)
    assert len(d) == 1


def test_bare_name_not_flagged(tmp_path):
    assert not _run(tmp_path, _method("Ресурс{Своя.svg}.Ссылка"), _BARE)


def test_qualified_name_not_flagged(tmp_path):
    # Стд::Грузовик.svg is the documented form of a library image, not a path
    assert not _run(tmp_path, _method("Ресурс{Стд::Грузовик.svg}.Ссылка"), _BARE)


def test_mention_in_a_comment_not_flagged(tmp_path):
    text = "// Ресурс{Ресурсы/Своя.svg} – так писать нельзя\n" + _method("Ресурс{Своя.svg}.Ссылка")
    assert not _run(tmp_path, text, _BARE)


def test_uploaded_inbase_not_flagged(tmp_path):
    # inbase/<uuid> addresses a resource uploaded into the application base (the web
    # editor names them so) - the compiler resolves the form by lookup,
    # the slash is not a folder spelling
    assert not _run(
        tmp_path,
        _method("Ресурс{inbase/0daefecc-5430-4d35-b146-648afe7f9e75.png}.Ссылка"),
        _BARE,
    )


def test_subfolder_key_not_flagged(tmp_path):
    # a key is a path relative to Ресурсы - the subfolder form compiles
    assert not _run(
        tmp_path,
        _method("Ресурс{Подкаталог/Вложенная.svg}.Ссылка"),
        _BARE,
        resource_names=("Подкаталог/Вложенная.svg",),
    )


def test_resources_prefixed_subfolder_advice_keeps_the_subfolder(tmp_path):
    # the fix strips the Ресурсы segment ONLY - the subfolder stays in the key
    d = _run(
        tmp_path,
        _method("Ресурс{Ресурсы/Подкаталог/Вложенная.svg}.Ссылка"),
        _BARE,
        resource_names=("Подкаталог/Вложенная.svg",),
    )
    assert len(d) == 1
    assert "Ресурс{Подкаталог/Вложенная.svg}" in d[0].message


# --- code/unknown-resource (project scope, needs the library) -----------------------------


def test_unknown_name_flagged(tmp_path, library):
    d = _run(tmp_path, _method("Ресурс{Настройки3.svg}.Ссылка"), _UNKNOWN)
    assert len(d) == 1 and d[0].rule_id == _UNKNOWN
    assert (d[0].line, d[0].col) == (4, 20)


def test_project_resource_not_flagged(tmp_path, library):
    assert not _run(tmp_path, _method("Ресурс{Своя.svg}.Ссылка"), _UNKNOWN)


def test_platform_library_name_not_flagged(tmp_path, library):
    # the file is not in the project – the platform ships it
    assert not _run(tmp_path, _method("Ресурс{Настройки.svg}.Ссылка"), _UNKNOWN)


def test_qualified_library_name_not_flagged(tmp_path, library):
    assert not _run(tmp_path, _method("Ресурс{Стд::Настройки.svg}.Ссылка"), _UNKNOWN)


def test_path_left_to_the_other_rule(tmp_path, library):
    # one mistake is not reported twice
    assert not _run(tmp_path, _method("Ресурс{Ресурсы/Своя.svg}.Ссылка"), _UNKNOWN)


def test_uploaded_inbase_out_of_static_reach(tmp_path, library):
    # whether the uploaded uuid exists is a fact of the application base - neither rule
    # may guess; the compiler verifies it at apply
    assert not _run(
        tmp_path,
        _method("Ресурс{inbase/0daefecc-5430-4d35-b146-648afe7f9e75.png}.Ссылка"),
        _UNKNOWN,
    )


def test_subfolder_key_known(tmp_path, library):
    # the known set keeps relative paths - a subfolder ref to an existing file is silent
    assert not _run(
        tmp_path,
        _method("Ресурс{Подкаталог/Вложенная.svg}.Ссылка"),
        _UNKNOWN,
        resource_names=("Подкаталог/Вложенная.svg",),
    )


def test_bare_name_of_a_subfoldered_file_flagged(tmp_path, library):
    # a bare name reaches only the Ресурсы root - for a file inside a subfolder
    # it fails at apply, and the rule now says so ahead of the compiler
    d = _run(
        tmp_path,
        _method("Ресурс{Вложенная.svg}.Ссылка"),
        _UNKNOWN,
        resource_names=("Подкаталог/Вложенная.svg",),
    )
    assert len(d) == 1 and d[0].rule_id == _UNKNOWN


def test_missing_subfolder_flagged(tmp_path, library):
    d = _run(
        tmp_path,
        _method("Ресурс{НетТакого/Вложенная.svg}.Ссылка"),
        _UNKNOWN,
        resource_names=("Подкаталог/Вложенная.svg",),
    )
    assert len(d) == 1 and d[0].rule_id == _UNKNOWN


def test_backslash_spelling_skipped(tmp_path, library):
    # the backslash form is unproven - skipped rather than judged
    assert not _run(
        tmp_path,
        _method("Ресурс{Подкаталог\\Вложенная.svg}.Ссылка"),
        _UNKNOWN,
        resource_names=("Подкаталог/Вложенная.svg",),
    )


def test_without_the_library_silent(tmp_path, monkeypatch):
    # no documentation data: guessing without the library is what produces false positives
    monkeypatch.setattr(resources, "_platform_images", frozenset)
    assert not _run(tmp_path, _method("Ресурс{Настройки3.svg}.Ссылка"), _UNKNOWN)


def test_without_a_project_file_silent(tmp_path, library):
    src = tmp_path / "acme"
    src.mkdir()
    (src / "М.xbsl").write_text(_method("Ресурс{Настройки3.svg}.Ссылка"), encoding="utf-8")
    assert not engine.run(discover([str(tmp_path)]), select={_UNKNOWN})


@pytest.mark.needs_data
def test_real_image_library_is_read():
    resources._platform_images.cache_clear()
    library = resources._platform_images()
    assert len(library) > 100
    assert {"Настройки.svg", "ГалочкаВКруге.svg", "Грузовик.svg"} <= library
