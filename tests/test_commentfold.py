"""Folding the comments of an element description (`xbsl fold-comments`, xbsl/commentfold.py).

Which node has room for a description comes from the metamodel and the ui schema, so the whole
module needs the data bundle (listed in conftest._DATA_DEPENDENT).
"""

import json

import yaml

from xbsl import cli, commentfold, engine, i18n
from xbsl.rules import yaml_doc_comments

_COMPONENT = """ВидЭлемента: КомпонентИнтерфейса
Ид: 33333333-3333-3333-3333-333333333333
Имя: КарточкаПробы
ОбластьВидимости: ВПодсистеме
Наследует:
    Тип: Группа
    Содержимое:
        -
            Тип: Надпись
            Имя: Заголовок
            Значение: =Заголовок
    Видимость: Истина
Свойства:
    -
        Имя: Заголовок
        Тип: Строка
"""

_NOTE = _COMPONENT.replace(
    "    Видимость: Истина\n", "    # Группа видна всегда.\n    Видимость: Истина\n",
)


def _fold(text: str, **kwargs) -> commentfold.FileFold:
    return commentfold.fold_text(text, "КарточкаПробы.yaml", **kwargs)


def _findings(text: str) -> list:
    source = engine.load_text("КарточкаПробы.yaml", text)
    return [
        diagnostic
        for want_doc in (False, True)
        for diagnostic in yaml_doc_comments._judge(source, want_doc)
    ]


def test_a_note_about_a_property_goes_into_its_node_as_a_named_item():
    fold = _fold(_NOTE)

    assert fold.changed and fold.audit == []
    assert "    ## * `Видимость`:\n    ##   Группа видна всегда.\n    Тип: Группа\n" in fold.text
    assert "# Группа видна всегда.\n    Видимость" not in fold.text
    assert _findings(fold.text) == []


def test_a_note_about_a_property_of_a_nested_node_goes_into_that_node():
    text = _COMPONENT.replace(
        "            Значение: =Заголовок\n",
        "            Значение: =Заголовок\n            # Текст приходит свойством.\n"
        "            Подсказка: Заголовок\n",
    )
    fold = _fold(text)

    assert fold.changed and fold.audit == []
    assert "            ## * `Подсказка`:\n            ##   Текст приходит свойством.\n" in fold.text


def test_the_first_block_after_the_head_becomes_the_description():
    text = _COMPONENT.replace("Наследует:\n", "# Карточка с заголовком.\nНаследует:\n")
    fold = _fold(text)

    assert fold.changed
    assert fold.text.startswith("## Карточка с заголовком.\nВидЭлемента:")
    assert all(move.subject is None for move in fold.moves if move.kind == "description")


def test_a_block_above_a_key_outside_the_head_is_only_proposed():
    """It may describe the element or only that key: the wave of a project had both."""
    text = _COMPONENT.replace("Свойства:\n", "# Заголовок задают снаружи.\nСвойства:\n")
    fold = _fold(text)

    (move,) = fold.moves
    assert move.action == "proposed" and move.reason == "fold.reason.first-block"
    assert not fold.changed

    taken = _fold(text, take_proposed=True)
    assert taken.changed and taken.audit == []


def test_a_note_at_the_end_of_the_file_is_left_where_it_is():
    fold = _fold(_COMPONENT + "# Заметка без хозяина.\n")

    (move,) = fold.moves
    assert move.action == "left" and move.kind == "end"
    assert not fold.changed


def test_a_heading_of_a_section_is_only_proposed():
    text = _COMPONENT.replace(
        "    Видимость: Истина\n", "    # --- Видимость ---\n    Видимость: Истина\n",
    )
    fold = _fold(text)

    (move,) = [move for move in fold.moves if move.kind != "fix"]
    assert move.action == "proposed" and move.reason == "fold.reason.separator"
    assert i18n.t(move.reason)


def test_new_items_follow_the_description_already_there():
    """The paragraphs of a description stay first, the named items go after them."""
    text = _NOTE.replace(
        "Наследует:\n    Тип: Группа\n",
        "Наследует:\n    ## Группа карточки.\n    ##\n    ## * `Содержимое`:\n"
        "    ##   Одна надпись.\n    Тип: Группа\n",
    )
    fold = _fold(text)

    assert fold.changed and fold.audit == []
    block = fold.text.split("Наследует:\n", 1)[1].split("    Тип: Группа", 1)[0]
    assert block == (
        "    ## Группа карточки.\n    ##\n    ## * `Содержимое`:\n    ##   Одна надпись.\n"
        "    ## * `Видимость`:\n    ##   Группа видна всегда.\n"
    )


def test_a_comment_after_a_value_names_its_key():
    text = _COMPONENT.replace(
        "    Видимость: Истина\n", "    Видимость: Истина  # видна всегда\n",
    )
    fold = _fold(text)

    assert fold.changed and fold.audit == []
    assert "    Видимость: Истина\n" in fold.text
    assert "## * `Видимость`:\n    ##   видна всегда\n" in fold.text


def test_the_fix_of_the_rule_goes_first():
    """A block at the head of a node with room only changes its marker."""
    text = _COMPONENT.replace(
        "    Тип: Группа\n", "    # Группа карточки.\n    Тип: Группа\n",
    )
    fold = _fold(text)

    assert fold.changed
    assert "    ## Группа карточки.\n    Тип: Группа\n" in fold.text
    assert [move.kind for move in fold.moves] == ["fix"]


def test_line_ends_and_the_byte_order_mark_are_kept():
    fold = _fold("\ufeff" + _NOTE.replace("\n", "\r\n"))

    assert fold.changed and fold.audit == []
    assert fold.text.startswith("\ufeff")
    assert "\r\n" in fold.text and "\n" not in fold.text.replace("\r\n", "")


def test_a_second_pass_has_nothing_to_move():
    text = _NOTE.replace("Наследует:\n", "# Карточка с заголовком.\nНаследует:\n")
    once = _fold(text)
    again = _fold(once.text)

    assert once.changed and not again.changed
    assert yaml.safe_load(once.text) == yaml.safe_load(text)


def test_the_command_shows_the_plan_and_writes_only_when_asked(tmp_path, capsys):
    path = tmp_path / "КарточкаПробы.yaml"
    path.write_bytes(_NOTE.encode("utf-8"))

    assert cli.main(["fold-comments", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "`Видимость`" in out and "+    ## * `Видимость`:" in out
    assert path.read_bytes().decode("utf-8") == _NOTE  # a dry run writes nothing

    assert cli.main(["fold-comments", str(tmp_path), "--write", "--format", "json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["written"] == 1
    assert "## * `Видимость`:" in path.read_bytes().decode("utf-8")
