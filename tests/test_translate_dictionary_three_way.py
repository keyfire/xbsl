import pytest

from xbsl.translation import dictionary


def sections(value):
    return {"tokens": [("Item", value, 1)]}


def test_unilateral_edit_and_removal_choose_working():
    assert dictionary.three_way([("a.yaml", sections("Two"))], [("a.yaml", sections("One"))],
                                [("a.yaml", sections("One"))], "main") == [("a.yaml", sections("Two"))]
    assert dictionary.three_way([], [("a.yaml", sections("One"))], [("a.yaml", sections("One"))], "main") == []


def test_equal_edits_and_independent_additions_survive():
    assert dictionary.three_way([("a.yaml", sections("Two"))], [("a.yaml", sections("One"))],
                                [("a.yaml", sections("Two"))], "main") == [("a.yaml", sections("Two"))]
    merged = dictionary.three_way([("left.yaml", sections("Left"))], [],
                                  [("right.yaml", sections("Right"))], "main")
    assert {name for name, _ in merged} == {"left.yaml", "main:right.yaml"}


def test_real_value_conflicts_keep_both_places():
    merged = dictionary.three_way([("a.yaml", sections("Left"))], [("a.yaml", sections("One"))],
                                 [("a.yaml", sections("Right"))], "main")
    conflicts, duplicates = dictionary.collisions(merged)
    assert duplicates == []
    assert [(p["file"], p["value"]) for p in conflicts[0]["places"]] == [
        ("a.yaml", "Left"), ("main:a.yaml", "Right"),
    ]


def test_delete_versus_edit_is_refused():
    with pytest.raises(dictionary.DictionaryError):
        dictionary.three_way([], [("a.yaml", sections("One"))], [("a.yaml", sections("Two"))], "main")


def test_rename_with_other_edit_keeps_renamed_working_identity():
    merged = dictionary.three_way([("moved.yaml", sections("Left"))], [("base.yaml", sections("One"))],
                                  [("base.yaml", sections("Right"))], "main",
                                  working_renames={"base.yaml": "moved.yaml"})
    assert [name for name, _ in merged] == ["moved.yaml", "main:base.yaml"]


def test_rename_only_plus_target_edit_does_not_resurrect_old_value():
    merged = dictionary.three_way([("moved.yaml", sections("One"))], [("base.yaml", sections("One"))],
                                 [("base.yaml", sections("Two"))], "main",
                                 working_renames={"base.yaml": "moved.yaml"})
    assert merged == [("main:base.yaml", sections("Two"))]
    assert dictionary.collisions(merged) == ([], [])


def test_independent_edits_in_one_file_do_not_duplicate_unchanged_keys():
    base = {"tokens": [("First", "One", 2), ("Second", "Two", 3)]}
    working = {"tokens": [("First", "ChangedFirst", 4), ("Second", "Two", 5)]}
    target = {"tokens": [("First", "One", 10), ("Second", "ChangedSecond", 11)]}
    merged = dictionary.three_way([("a.yaml", working)], [("a.yaml", base)], [("a.yaml", target)], "main")
    assert merged == [
        ("a.yaml", {"tokens": [("First", "ChangedFirst", 4)]}),
        ("main:a.yaml", {"tokens": [("Second", "ChangedSecond", 11)]}),
    ]
    assert dictionary.collisions(merged) == ([], [])


def test_line_numbers_are_not_edits_and_existing_duplicates_survive():
    base = {"tokens": [("Item", "One", 1), ("Item", "One", 2)]}
    working = {"tokens": [("Item", "One", 7), ("Item", "One", 8)]}
    merged = dictionary.three_way([("a.yaml", working)], [("a.yaml", base)], [("a.yaml", base)], "main")
    assert merged == [("a.yaml", working)]
    conflicts, duplicates = dictionary.collisions(merged)
    assert conflicts == []
    assert [p["line"] for p in duplicates[0]["places"]] == [7, 8]


def test_key_deletion_versus_edit_is_refused():
    with pytest.raises(dictionary.DictionaryError):
        dictionary.three_way([("a.yaml", {})], [("a.yaml", sections("One"))],
                             [("a.yaml", sections("Two"))], "main")


def test_renaming_one_base_to_different_destinations_is_refused():
    with pytest.raises(dictionary.DictionaryError):
        dictionary.three_way([("left.yaml", sections("One"))], [("a.yaml", sections("One"))],
                             [("right.yaml", sections("One"))], "main",
                             working_renames={"a.yaml": "left.yaml"}, other_renames={"a.yaml": "right.yaml"})
