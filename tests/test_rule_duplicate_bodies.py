"""Checks of code/duplicate-method-body (one body written twice in different files)."""

from xbsl import dataset, engine
from xbsl.cli import discover

import pytest

pytestmark = pytest.mark.skipif(
    not dataset.available_versions(),
    reason="нет данных Элемента – сгенерируйте: python tools/extract.py --dist ...",
)

RULE = "code/duplicate-method-body"

BODY = (
    "метод Собрать(): Строка\n"
    "    пер Итог = \"\"\n"
    "    Итог = Итог + \"а\"\n"
    "    Итог = Итог + \"б\"\n"
    "    Итог = Итог + \"в\"\n"
    "    возврат Итог\n"
    ";\n"
)
SHORT = (
    "метод Коротко(): Строка\n"
    "    пер Итог = \"\"\n"
    "    возврат Итог\n"
    ";\n"
)


def _lint(tmp_path, files: dict[str, str], enable: bool = True):
    for name, content in files.items():
        (tmp_path / name).write_text(content, encoding="utf-8")
    diags = engine.run(discover([str(tmp_path)]), enable={RULE} if enable else None)
    return [d for d in diags if d.rule_id == RULE]


def test_the_same_body_in_two_files_is_reported_on_both(tmp_path):
    hits = _lint(tmp_path, {"Первый.xbsl": BODY, "Второй.xbsl": BODY})

    assert len(hits) == 2
    assert {d.path.split("\\")[-1].split("/")[-1] for d in hits} == {"Первый.xbsl", "Второй.xbsl"}
    assert "Собрать" in hits[0].message


def test_a_body_shorter_than_the_threshold_is_left_alone(tmp_path):
    assert not _lint(tmp_path, {"Первый.xbsl": SHORT, "Второй.xbsl": SHORT})


def test_two_copies_inside_one_file_are_left_alone(tmp_path):
    """There the duplication is visible while reading the file, and the cure is local."""
    twice = BODY + BODY.replace("метод Собрать", "метод СобратьЕщё")
    assert not _lint(tmp_path, {"Первый.xbsl": twice})


def test_a_platform_hook_is_left_alone(tmp_path):
    """The platform calls the hook in every object that declares it - the same body is normal."""
    hook = "@Обработчик\n" + BODY.replace("метод Собрать", "метод ПослеСоздания")
    assert not _lint(tmp_path, {"Первый.xbsl": hook, "Второй.xbsl": hook})


def test_a_hand_written_wrapper_of_the_same_shape_is_judged(tmp_path):
    """The guard is the annotation, not the name: a wrapper without it is an ordinary method."""
    wrapper = BODY.replace("метод Собрать", "метод ВыполнитьЗаписать")
    assert len(_lint(tmp_path, {"Первый.xbsl": wrapper, "Второй.xbsl": wrapper})) == 2


def test_comments_and_indentation_do_not_hide_a_copy(tmp_path):
    reformatted = (
        "метод Собрать(): Строка\n"
        "        // пояснение, которого нет во втором файле\n"
        "        пер Итог = \"\"\n"
        "\n"
        "        Итог = Итог  +  \"а\"\n"
        "        Итог = Итог + \"б\"\n"
        "        Итог = Итог + \"в\"\n"
        "        возврат Итог\n"
        ";\n"
    )
    assert len(_lint(tmp_path, {"Первый.xbsl": BODY, "Второй.xbsl": reformatted})) == 2


def test_different_bodies_are_not_a_copy(tmp_path):
    other = BODY.replace("\"в\"", "\"г\"")
    assert not _lint(tmp_path, {"Первый.xbsl": BODY, "Второй.xbsl": other})


def test_rule_is_off_by_default(tmp_path):
    """The SHIPPED default is off - a project plugin may turn it on for its own corpus."""
    from xbsl import plugins

    if RULE in plugins.severity_overrides():
        pytest.skip("правило включено профилем установленного плагина")
    assert not _lint(tmp_path, {"Первый.xbsl": BODY, "Второй.xbsl": BODY}, enable=False)


def test_the_message_counts_the_remaining_places(tmp_path):
    hits = _lint(tmp_path, {"Первый.xbsl": BODY, "Второй.xbsl": BODY, "Третий.xbsl": BODY})

    assert len(hits) == 3
    assert "ещё в 1" in hits[0].message


def test_the_named_place_does_not_depend_on_the_walk_order(tmp_path):
    """The message names one of the other places, and a baseline entry is keyed by the
    message: the choice must not change between two runs over the same project."""
    files = {"А.xbsl": BODY, "Б.xbsl": BODY, "В.xbsl": BODY}
    for name, content in files.items():
        (tmp_path / name).write_text(content, encoding="utf-8")
    paths = [str(tmp_path / name) for name in files]

    def messages(order):
        diags = engine.run(discover(order), enable={RULE})
        return {d.path: d.message for d in diags if d.rule_id == RULE}

    assert messages(paths) == messages(list(reversed(paths)))
