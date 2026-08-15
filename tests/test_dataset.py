"""Checks of versioned data access (self-containedness, version selection)."""

import pytest

from xbsl import dataset


@pytest.mark.needs_data
def test_default_is_available():
    assert dataset.available_versions()
    assert dataset.default_version() in dataset.available_versions()


@pytest.mark.needs_data
def test_load_language_and_stdlib():
    lang = dataset.load_json("language.json")
    assert lang["keywords"]["METHOD"]["forms"]
    std = dataset.load_json("stdlib.json")
    assert "Массив" in std["names"]


@pytest.mark.needs_data
def test_data_stamped_with_element_version():
    lang = dataset.load_json("language.json")
    assert lang["meta"]["element_version"] == dataset.default_version()


def test_invalid_version_raises():
    with pytest.raises(dataset.DatasetError):
        dataset.resolve_version("0.0.0-нет-такой")


# --- чтение собственных json: терпимость к BOM, имя файла в ошибке -------------------------


def test_index_with_a_bom_is_read(tmp_path):
    """PowerShell 5.1 (Out-File -Encoding utf8) пишет BOM - индекс обязан читаться."""
    (tmp_path / "index.json").write_bytes(
        b'\xef\xbb\xbf{"available": ["1.0"], "default": "1.0"}'
    )
    dataset.set_data_root(tmp_path)
    try:
        assert dataset.available_versions() == ["1.0"]
        assert dataset.default_version() == "1.0"
    finally:
        dataset.set_data_root(None)


def test_a_broken_json_names_the_file(tmp_path):
    """Голый JSONDecodeError валил все шаги одинаково и не называл файл - диагноз стоил
    отдельного прогона."""
    (tmp_path / "index.json").write_text("{оборванный", encoding="utf-8")
    dataset.set_data_root(tmp_path)
    try:
        with pytest.raises(dataset.DatasetError, match=r"index\.json"):
            dataset.default_version()
    finally:
        dataset.set_data_root(None)


# --- inheritance expansion (dataset._expand_inherited), no distribution data needed --------

def _own_dataset():
    """A tiny stdlib.json in the own-members form: Наследник extends База extends Объект."""
    return {
        "meta": {"members": "own"},
        "bases": {"Наследник": ["База", "Объект"], "База": ["Объект"], "Объект": []},
        "type_members": {
            "Объект": {"methods": ["ВСтроку"]},
            "База": {"properties": ["Поле"], "methods": ["Метод"]},
            "Наследник": {"properties": ["Своё"]},
        },
        "member_types": {
            "Объект": {"ВСтроку": "Строка"},
            "База": {"Поле": "Число"},
            "Наследник": {"Своё": "Булево"},
        },
        "member_signatures": {
            "Объект": {"ВСтроку": ["ВСтроку(): Строка"]},
            "База": {"Метод": ["Метод(Имя: Строка): Булево"]},
        },
    }


def test_expand_inherited_completes_members_by_hierarchy():
    full = dataset._expand_inherited(_own_dataset())["type_members"]
    # Наследник gets its own member plus every ancestor's own.
    assert set(full["Наследник"]["properties"]) == {"Своё", "Поле"}
    assert set(full["Наследник"]["methods"]) == {"Метод", "ВСтроку"}
    assert set(full["База"]["methods"]) == {"Метод", "ВСтроку"}


def test_expand_inherited_completes_member_types():
    full = dataset._expand_inherited(_own_dataset())["member_types"]
    assert full["Наследник"] == {"Своё": "Булево", "Поле": "Число", "ВСтроку": "Строка"}


def test_expand_inherited_keeps_an_overridden_result_type():
    data = _own_dataset()
    data["member_types"]["Наследник"]["ВСтроку"] = "Представление"  # override the object's
    full = dataset._expand_inherited(data)["member_types"]
    assert full["Наследник"]["ВСтроку"] == "Представление"  # own wins over the ancestor's


def test_expand_inherited_completes_member_signatures():
    """An heir shows the signature of the method it inherits - the card says what to pass."""
    full = dataset._expand_inherited(_own_dataset())["member_signatures"]
    assert full["Наследник"] == {
        "ВСтроку": ["ВСтроку(): Строка"],
        "Метод": ["Метод(Имя: Строка): Булево"],
    }


def test_a_dataset_without_signatures_gains_no_such_section():
    """Data generated before the signatures existed still loads - the card just has none."""
    data = _own_dataset()
    del data["member_signatures"]
    assert "member_signatures" not in dataset._expand_inherited(data)


def test_expand_inherited_leaves_full_datasets_untouched():
    full_form = {
        "meta": {},  # no "members": "own" marker - an older, already-full dataset
        "bases": {"Наследник": ["Объект"]},
        "type_members": {"Наследник": {"properties": ["Своё"]}},
    }
    assert dataset._expand_inherited(full_form)["type_members"] == {"Наследник": {"properties": ["Своё"]}}


# --- bilingual key expansion (dataset._add_english_keys) -----------------------------------

def _ru_only_dataset():
    """A catalog stored under Russian keys only, marked for English expansion."""
    return {
        "meta": {"members": "own", "bilingual_keys": "expand"},
        "bases": {"Запрос": ["Объект"], "Объект": []},
        "type_members": {"Запрос": {"methods": ["Выполнить"]}, "Объект": {"methods": ["ВСтроку"]}},
        "member_types": {"Запрос": {"Выполнить": "РезультатЗапроса"}},
    }


PAIRS = {"Запрос": "Query", "Объект": "Object", "Выполнить": "Execute"}


def test_add_english_keys_copies_the_russian_entry():
    data = dataset._add_english_keys(_ru_only_dataset(), PAIRS)
    assert data["type_members"]["Query"] == data["type_members"]["Запрос"]
    assert data["bases"]["Query"] == ["Объект"]  # bases stay Russian - they are values, not keys
    assert data["member_types"]["Query"] == {"Выполнить": "РезультатЗапроса"}


def test_english_type_inherits_like_the_russian_one():
    # the English keys are added BEFORE the inheritance expansion, so Query inherits too
    full = dataset._expand_inherited(dataset._add_english_keys(_ru_only_dataset(), PAIRS))
    assert set(full["type_members"]["Query"]["methods"]) == {"Выполнить", "ВСтроку"}
    assert full["type_members"]["Query"] == full["type_members"]["Запрос"]


def test_bilingual_expansion_skipped_without_marker_or_terms():
    no_marker = _ru_only_dataset()
    no_marker["meta"].pop("bilingual_keys")
    assert "Query" not in dataset._add_english_keys(no_marker, PAIRS)["type_members"]
    # marker present but terms.json absent (empty pairs) - Russian still works, no crash
    assert "Query" not in dataset._add_english_keys(_ru_only_dataset(), {})["type_members"]


# --- in-place regeneration is picked up without a restart (no distribution data needed) -----

def _write_root(tmp_path, marker: str):
    (tmp_path / "index.json").write_text(
        '{"available": ["1.0"], "default": "1.0"}', encoding="utf-8"
    )
    version_dir = tmp_path / "1.0"
    version_dir.mkdir(exist_ok=True)
    (version_dir / "language.json").write_text(
        '{"meta": {"element_version": "1.0"}, "marker": "%s"}' % marker, encoding="utf-8"
    )
    return version_dir / "language.json"


def test_regenerated_file_is_picked_up_without_a_restart(tmp_path):
    # The LSP and MCP servers live long: data regenerated IN PLACE used to keep answering
    # from the process cache until a restart, discovered only by diverging answers.
    import os

    data_file = _write_root(tmp_path, "before")
    resets = []
    dataset.register_reset(lambda: resets.append(1))
    dataset.set_data_root(tmp_path)
    try:
        assert dataset.load_json("language.json")["marker"] == "before"
        baseline_resets = len(resets)
        data_file.write_text(
            '{"meta": {"element_version": "1.0"}, "marker": "after"}', encoding="utf-8"
        )
        # the stamp is st_mtime_ns: force a distinct one, a fast write can land in the
        # same filesystem timestamp tick
        stamp = data_file.stat()
        os.utime(data_file, ns=(stamp.st_atime_ns, stamp.st_mtime_ns + 1_000_000))
        assert dataset.load_json("language.json")["marker"] == "after"
        # the derived caches (register_reset) were dropped along with the data
        assert len(resets) > baseline_resets
    finally:
        dataset._RESET_HOOKS.pop()
        dataset.set_data_root(None)


def test_unchanged_files_stay_cached(tmp_path):
    data_file = _write_root(tmp_path, "stable")
    dataset.set_data_root(tmp_path)
    try:
        first = dataset.load_json("language.json")
        assert dataset.load_json("language.json") is first
    finally:
        dataset.set_data_root(None)


def test_generic_arguments_are_split_at_the_top_level():
    """A comma inside an inner argument does not split the outer list."""
    assert dataset.generic_args("Соответствие<Строка, Массив<Каталог.Ссылка>>") == [
        "Строка", "Массив<Каталог.Ссылка>",
    ]
    assert dataset.generic_args("Строка") == []


def test_an_inherited_result_type_reaches_a_type_with_none_of_its_own():
    """A collection declares no result type of its own - `First` belongs to its bases.

    Walking only the types that HAVE own result types left such a type without a single one,
    and a chain over any of its methods ended there.
    """
    data = dataset._expand_inherited({
        "meta": {"members": "own"},
        "bases": {"Массив": ["Обходимое", "Объект"]},
        "type_members": {"Массив": {"methods": ["Первый"]}, "Обходимое": {"methods": ["Первый"]}},
        "member_types": {"Обходимое": {"Первый": "ТипЭлемента"}},
    })

    assert data["member_types"]["Массив"]["Первый"] == "ТипЭлемента"
