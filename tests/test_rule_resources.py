"""Checks of the resource rules: code/resource-bare-name and code/unknown-resource.

The platform image library is stubbed, so the tests need no documentation data: either the
whole library or its two sources, the documentation page and the table of pairs. The tests
marked needs_data check that the real library is read and holds the documented names.
"""

import types

import pytest

from xbsl import dataset, docs, engine
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


def _project(tmp_path, module_text, resource_names=("Своя.svg",), folder="Ресурсы"):
    root = tmp_path / "acme" / "Проба"
    (root / "Основное" / folder).mkdir(parents=True)
    (root / "Проект.yaml").write_text(_PROJECT_YAML, encoding="utf-8")
    for name in resource_names:
        path = root / "Основное" / folder / name  # a name may carry a subfolder
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("<svg/>", encoding="utf-8")
    (root / "Основное" / "М.xbsl").write_text(module_text, encoding="utf-8")
    return tmp_path


def _run(tmp_path, module_text, select, resource_names=("Своя.svg",), folder="Ресурсы"):
    _project(tmp_path, module_text, resource_names, folder)
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
    # the file is not in the project - the platform ships it
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


def _scoped_project(tmp_path, module_text, folders, compatibility="9.0"):
    """A neutral project with resources owned by subsystem/package namespace keys."""
    root = tmp_path / "acme" / "Demo"
    (root / "Project.yaml").parent.mkdir(parents=True, exist_ok=True)
    project = "Vendor: acme\nName: Demo\nVersion: 1.0.0\n"
    if compatibility is not None:
        project += f"CompatibilityMode: {compatibility}\n"
    (root / "Project.yaml").write_text(project, encoding="utf-8")
    subsystems = {namespace.split("::", 1)[0] for namespace in folders} | {"Main"}
    for subsystem in subsystems:
        descriptor = root / subsystem / "Subsystem.yaml"
        descriptor.parent.mkdir(parents=True, exist_ok=True)
        descriptor.write_text(f"Name: {subsystem}\n", encoding="utf-8")
    for namespace, (keys, public) in folders.items():
        resources_dir = root.joinpath(*namespace.split("::"), "Resources")
        resources_dir.mkdir(parents=True, exist_ok=True)
        if public:
            (resources_dir / "Resources.yaml").write_text(
                "VisibilityScope: InProject\n", encoding="utf-8",
            )
        for key in keys:
            resource = resources_dir / key
            resource.parent.mkdir(parents=True, exist_ok=True)
            resource.write_text("<svg/>\n", encoding="utf-8")
    module = root / "Main" / "Probe.xbsl"
    module.write_text(module_text, encoding="utf-8")
    return tmp_path


def _resource_module(key, *imports):
    prefix = "".join(f"import {name}\n" for name in imports)
    return prefix + _english_method(f"Resource{{{key}}}.Link")


def _run_scoped(tmp_path, module_text, folders, library):
    return engine.run(discover([str(_scoped_project(tmp_path, module_text, folders))]),
                      select={_UNKNOWN})


def test_a_local_resource_has_priority_over_an_imported_namesake(tmp_path, library):
    found = _run_scoped(
        tmp_path,
        _resource_module("Shared.svg", "Foreign::Pack"),
        {"Main": (("Shared.svg",), False), "Foreign::Pack": (("Shared.svg",), True)},
        library,
    )

    assert found == []


def test_two_local_namespaces_make_a_bare_resource_ambiguous(tmp_path, library):
    found = _run_scoped(
        tmp_path,
        _resource_module("Shared.svg"),
        {"Main::One": (("Shared.svg",), False), "Main::Two": (("Shared.svg",), False)},
        library,
    )

    assert len(found) == 1
    assert found[0].data["resolution"] == "ambiguous"


def test_an_imported_private_resource_is_reported_as_hidden(tmp_path, library):
    found = _run_scoped(
        tmp_path,
        _resource_module("Shared.svg", "Foreign::Pack"),
        {"Foreign::Pack": (("Shared.svg",), False)},
        library,
    )

    assert len(found) == 1
    assert found[0].data["resolution"] == "hidden"


def test_an_imported_public_resource_is_visible(tmp_path, library):
    found = _run_scoped(
        tmp_path,
        _resource_module("Shared.svg", "Foreign::Pack"),
        {"Foreign::Pack": (("Shared.svg",), True)},
        library,
    )

    assert found == []


def test_a_foreign_unimported_resource_does_not_make_the_bare_key_known(tmp_path, library):
    found = _run_scoped(
        tmp_path,
        _resource_module("Shared.svg"),
        {"Foreign::Pack": (("Shared.svg",), True)},
        library,
    )

    assert len(found) == 1
    assert found[0].data["resolution"] == "unknown"


def test_a_qualified_private_resource_is_reported_as_hidden(tmp_path, library):
    found = _run_scoped(
        tmp_path,
        _resource_module("Foreign::Pack::Shared.svg", "Foreign::Pack"),
        {"Foreign::Pack": (("Shared.svg",), False)},
        library,
    )

    assert len(found) == 1
    assert found[0].data["resolution"] == "hidden"


def test_two_imported_public_namespaces_make_a_bare_resource_ambiguous(tmp_path, library):
    found = _run_scoped(
        tmp_path,
        _resource_module("Shared.svg", "Foreign::One", "Foreign::Two"),
        {
            "Foreign::One": (("Shared.svg",), True),
            "Foreign::Two": (("Shared.svg",), True),
        },
        library,
    )

    assert len(found) == 1
    assert found[0].data["resolution"] == "ambiguous"


def test_a_descriptorless_resource_is_public_before_compatibility_8(tmp_path, library):
    project = _scoped_project(
        tmp_path,
        _resource_module("Shared.svg", "Foreign::Pack"),
        {"Foreign::Pack": (("Shared.svg",), False)},
        compatibility="7.0",
    )

    assert engine.run(discover([str(project)]), select={_UNKNOWN}) == []


def test_descriptorless_visibility_is_left_unproven_without_a_compatibility_mode(
        tmp_path, library):
    project = _scoped_project(
        tmp_path,
        _resource_module("Shared.svg", "Foreign::Pack"),
        {"Foreign::Pack": (("Shared.svg",), False)},
        compatibility=None,
    )

    assert engine.run(discover([str(project)]), select={_UNKNOWN}) == []


def test_the_platform_library_is_only_a_fallback_after_local_ambiguity(tmp_path, library):
    found = _run_scoped(
        tmp_path,
        _resource_module("Настройки.svg"),
        {
            "Main::One": (("Настройки.svg",), False),
            "Main::Two": (("Настройки.svg",), False),
        },
        library,
    )

    assert len(found) == 1
    assert found[0].data["resolution"] == "ambiguous"


def test_malformed_resources_descriptor_does_not_prove_private_visibility(tmp_path, library):
    project = _scoped_project(
        tmp_path,
        _resource_module("Shared.svg", "Foreign::Pack"),
        {"Foreign::Pack": (("Shared.svg",), True)},
    )
    descriptor = (tmp_path / "acme" / "Demo" / "Foreign" / "Pack"
                  / "Resources" / "Resources.yaml")
    descriptor.write_text("VisibilityScope: [broken\n", encoding="utf-8")

    assert engine.run(discover([str(project)]), select={_UNKNOWN}) == []


def test_a_fully_qualified_resource_in_another_loaded_project_is_not_false_unknown(
        tmp_path, library):
    project = _scoped_project(
        tmp_path,
        _resource_module("Other::App::Assets::Shared.svg"),
        {},
    )
    external = tmp_path / "Other" / "App"
    files = {
        "Project.yaml": "Vendor: Other\nName: App\nVersion: 1.0.0\nCompatibilityMode: 9.0\n",
        "Assets/Subsystem.yaml": "Name: Assets\n",
        "Assets/Resources/Resources.yaml": "VisibilityScope: InProject\n",
        "Assets/Resources/Shared.svg": "<svg/>\n",
    }
    for rel, text in files.items():
        path = external / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    assert engine.run(discover([str(project)]), select={_UNKNOWN}) == []


@pytest.mark.needs_data
def test_real_image_library_is_read():
    resources._platform_images.cache_clear()
    library = resources._platform_images()
    assert len(library) > 100
    assert {"Настройки.svg", "ГалочкаВКруге.svg", "Грузовик.svg"} <= library


@pytest.mark.needs_data
def test_real_table_of_pairs_adds_the_english_names():
    if not (dataset.load_json("uiterms.json") or {}).get("resource_paths"):
        pytest.skip("the data was extracted before the table of pictures")
    resources._platform_images.cache_clear()
    library = resources._platform_images()
    assert {"Settings.svg", "CheckInCircle.svg", "Truck.svg"} <= library
    assert {"Настройки.svg", "Грузовик.svg"} <= library


# --- the library in both spellings --------------------------------------------------------

#: The documentation page names the pictures of the library in Russian only.
_LIBRARY_PAGE = "<ul> <li> Грузовик.svg</li> <li> Настройки.svg</li> </ul>"
#: The table of pairs as the extractor files it (uiterms.resource_paths): a picture by its
#: place in the jar, the Russian library against the English one.
_PICTURE_PAIRS = {
    "Icons/Стд/Ресурсы/Грузовик.svg": "Icons/Std/Resources/Truck.svg",
    "Icons/Стд/Ресурсы/Настройки.svg": "Icons/Std/Resources/Settings.svg",
}


@pytest.fixture
def library_sources(monkeypatch):
    """Both sources of the library stubbed: `page` is the html of the documentation page (None -
    no documentation data), `table` the table of pairs (None - data extracted before it)."""
    sources = types.SimpleNamespace(page=_LIBRARY_PAGE, table=dict(_PICTURE_PAIRS))
    original = dataset.load_json

    def page(doc_id, version=None):
        if doc_id != "topics/image-library" or sources.page is None:
            return None
        return {"id": doc_id, "html": sources.page}

    def load_json(name, *args, **kwargs):
        if name != "uiterms.json":
            return original(name, *args, **kwargs)
        return {} if sources.table is None else {"resource_paths": dict(sources.table)}

    monkeypatch.setattr(docs, "page", page)
    monkeypatch.setattr(dataset, "load_json", load_json)
    resources._platform_images.cache_clear()
    yield sources
    monkeypatch.undo()
    dataset.set_data_root(None)  # the reset hooks drop every table read from the stubs
    resources._platform_images.cache_clear()


def _library_with(sources, **changes):
    """The library after the sources change, read afresh."""
    for name, value in changes.items():
        setattr(sources, name, value)
    resources._platform_images.cache_clear()
    return resources._platform_images()


def _english_method(body):
    return f"// M\n\nmethod M(): BinaryObject.Reference\n    return {body}\n;\n"


@pytest.mark.parametrize("key", ["Truck.svg", "Std::Truck.svg", "Стд::Truck.svg"],
                         ids=["bare", "std", "russian-namespace"])
def test_english_name_of_a_library_picture_is_known(tmp_path, library_sources, key):
    # the translator writes the English name of a picture of the library, and the platform's
    # own sources use both forms of it: `Resource{Std::...}` and the bare English name
    assert not _run(tmp_path, _english_method(f"Resource{{{key}}}.Link"), _UNKNOWN)


@pytest.mark.parametrize("key", ["Грузовик.svg", "Стд::Грузовик.svg"], ids=["bare", "std"])
def test_russian_name_stays_known_next_to_the_table(tmp_path, library_sources, key):
    assert not _run(tmp_path, _method(f"Ресурс{{{key}}}.Ссылка"), _UNKNOWN)


@pytest.mark.parametrize("key", ["Truck3.svg", "Std::Truck3.svg"])
def test_unknown_english_name_is_still_flagged(tmp_path, library_sources, key):
    d = _run(tmp_path, _english_method(f"Resource{{{key}}}.Link"), _UNKNOWN)
    assert len(d) == 1 and d[0].rule_id == _UNKNOWN
    assert f"'{key}'" in d[0].message


def test_without_the_table_an_english_name_is_unknown(tmp_path, library_sources):
    # data extracted before the table: only the documentation names the library, in Russian
    _library_with(library_sources, table=None)
    assert len(_run(tmp_path, _english_method("Resource{Std::Truck.svg}.Link"), _UNKNOWN)) == 1
    assert not _run(tmp_path / "ru", _method("Ресурс{Стд::Грузовик.svg}.Ссылка"), _UNKNOWN)


def test_the_table_alone_does_not_make_the_library(tmp_path, library_sources):
    # without the documentation page the rule stays silent, whatever the table holds
    assert _library_with(library_sources, page=None) == frozenset()
    assert not _run(tmp_path, _english_method("Resource{Std::Truck3.svg}.Link"), _UNKNOWN)


@pytest.mark.parametrize("russian,english,key", [
    # a folder of the library below the resources folder stays part of the key
    ("Icons/Стд/Ресурсы/Папка/Грузовик.svg", "Icons/Std/Resources/Folder/Truck.svg",
     "Folder/Truck.svg"),
    # either spelling of the resources folder is the resources folder
    ("Icons/Стд/Ресурсы/Грузовик.svg", "Icons/Std/Ресурсы/Truck.svg", "Truck.svg"),
    # a row that does not lie below a resources folder names no key
    ("Icons/Стд/Картинки/Грузовик.svg", "Icons/Std/Pictures/Truck.svg", None),
    ("Грузовик.svg", "Truck.svg", None),
], ids=["subfolder", "either-folder-spelling", "other-folder", "no-place"])
def test_a_row_of_the_table_gives_the_key_below_the_resources_folder(
        library_sources, russian, english, key):
    library = _library_with(library_sources, table={russian: english})
    assert library - {"Грузовик.svg", "Настройки.svg"} == ({key} if key else set())


def test_library_is_read_again_when_the_data_changes(library_sources):
    """Pinning another root or version drops the library the rule read before."""
    assert "Truck.svg" not in _library_with(library_sources, table=None)
    library_sources.table = dict(_PICTURE_PAIRS)
    dataset.set_data_root(None)
    assert "Truck.svg" in resources._platform_images()


# --- both spellings of the resources folder ----------------------------------------------

def test_english_resources_folder_resolves(tmp_path, library):
    """A file under `Resources` is a resource: the platform accepts that name too.

    Probed on the local server with one and the same form: the reference resolves when the
    file lies in `Resources` (the build succeeds), fails with "Неизвестный ресурс" when the
    file is missing, and fails the same way when the very same file sits in a folder named
    anything else - so the name matters and the English one is legal.
    """
    d = _run(tmp_path, _method("Ресурс{Своя.svg}.Ссылка"), "code/unknown-resource",
             folder="Resources")
    assert not [x for x in d if x.rule_id == "code/unknown-resource"]


def test_english_folder_spelled_out_in_the_key_is_reported(tmp_path):
    # the key is relative to the resources folder, whatever its spelling
    d = _run(tmp_path, _method("Ресурс{Resources/Своя.svg}.Ссылка"), "code/resource-bare-name",
             folder="Resources")
    hits = [x for x in d if x.rule_id == "code/resource-bare-name"]
    assert len(hits) == 1 and "Своя.svg" in hits[0].message


def test_folder_of_another_name_is_not_a_resource_folder(tmp_path, library):
    # the negative control of the probe: any other name holds no resources
    d = _run(tmp_path, _method("Ресурс{Своя.svg}.Ссылка"), "code/unknown-resource",
             folder="Картинки")
    assert [x for x in d if x.rule_id == "code/unknown-resource"]
