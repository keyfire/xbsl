"""style/redundant-scope: a scope that is the only statement of its block.

The platform IDE warns that such a scope coincides with the scope of the block around it. Its
language server confirmed the variants below on probe projects: every kind of block (the body of a
method and of a full lambda, the branches of `если` and `выбор`, the loops, the blocks of
`попытка`), an empty scope, a scope with only a comment or only `исп`, a comment next to the scope -
and the quiet case, a scope with a statement next to it.

The rule parses the module, so the tests need the Element data.
"""

from pathlib import Path

import pytest

from xbsl import cli, engine, i18n

pytestmark = pytest.mark.needs_data

RULE = "style/redundant-scope"


def _lint(content: str, name: str = "Проба.xbsl"):
    return engine.run_sources([engine.load_text(name, content)], select={RULE})


def _fixed(text: str, found) -> str:
    fix = found.fix
    assert fix is not None, found.message
    return text[:fix.start] + fix.new + text[fix.end:]


def _method(*lines: str, params: str = "Флаг: Булево, Числа: Массив<Число>") -> str:
    return "\n".join([f"метод Проба({params})", *lines, ";", ""])


# --- what is reported -------------------------------------------------------------------------

def test_a_scope_alone_in_a_branch_is_reported_with_its_removal():
    text = _method(
        "    если Флаг",
        "        область",
        "            знч Итог = Числа.Размер()",
        "            Итог.ВСтроку()",
        "        ;",
        "    ;",
    )
    found = _lint(text)

    assert len(found) == 1, [d.message for d in found]
    assert (found[0].line, found[0].col) == (3, 9)
    assert found[0].severity.value == "warning"
    assert _fixed(text, found[0]) == _method(
        "    если Флаг",
        "        знч Итог = Числа.Размер()",
        "        Итог.ВСтроку()",
        "    ;",
    )


_SCOPE = ["        область", "            Проба(Ложь, Числа)", "        ;"]
_DEEP_SCOPE = ["            область", "                Проба(Ложь, Числа)", "            ;"]


@pytest.mark.parametrize("block", [
    ["    если Флаг", "        Проба(Ложь, Числа)", "    иначе", *_SCOPE, "    ;"],
    ["    если Флаг", "        Проба(Ложь, Числа)", "    иначе если Числа.Размер() > 0", *_SCOPE, "    ;"],
    ["    для Число из Числа", *_SCOPE, "    ;"],
    ["    для Индекс = 1 по 2", *_SCOPE, "    ;"],
    ["    пока Флаг", *_SCOPE, "    ;"],
    ["    попытка", *_SCOPE, "    поймать Ошибка: Исключение", "        Проба(Ложь, Числа)", "    ;"],
    ["    попытка", "        Проба(Ложь, Числа)", "    поймать Ошибка: Исключение", *_SCOPE, "    ;"],
    ["    попытка", "        Проба(Ложь, Числа)", "    вконце", *_SCOPE, "    ;"],
    ["    выбор Числа.Размер()", "        когда 1", *_DEEP_SCOPE, "    ;"],
    ["    выбор Числа.Размер()", "        когда 1", "            Проба(Ложь, Числа)", "        иначе",
     *_DEEP_SCOPE, "    ;"],
    ["    Числа.ДляКаждого(метод(Число) ->", *_SCOPE, "    ;)"],
])
def test_every_kind_of_block_is_judged(block):
    found = _lint(_method(*block))

    assert len(found) == 1, (block, [d.message for d in found])
    assert found[0].fix is not None


def test_the_body_of_a_method_and_of_a_structure_method_is_judged():
    text = "\n".join([
        "структура Счетчик",
        "    пер Значение: Число = 0",
        "",
        "    метод Увеличить()",
        "        область",
        "            Значение += 1",
        "        ;",
        "    ;",
        ";",
        "",
        "метод Проба()",
        "    область",
        "        знч Счет = новый Счетчик()",
        "        Счет.Увеличить()",
        "    ;",
        ";",
        "",
    ])

    assert [(d.line, d.col) for d in _lint(text)] == [(5, 9), (12, 5)]


def test_a_scope_inside_a_scope_is_reported_as_well_as_the_outer_one():
    text = _method(
        "    область",
        "        область",
        "            Проба(Ложь, Числа)",
        "        ;",
        "    ;",
    )

    assert [(d.line, d.col) for d in _lint(text)] == [(2, 5), (3, 9)]


@pytest.mark.parametrize("inside", [
    [],
    ["            // только пояснение"],
    ["            исп КонтекстДоступа.Привилегированный()"],
])
def test_an_empty_scope_or_one_with_a_comment_or_a_use_is_reported(inside):
    text = _method("    если Флаг", "        область", *inside, "        ;", "    ;")
    found = _lint(text)

    assert len(found) == 1
    assert _fixed(text, found[0]) == _method("    если Флаг", *[line[4:] for line in inside], "    ;")


def test_a_comment_next_to_the_scope_does_not_save_it():
    text = _method("    если Флаг", "        // пояснение", "        область", "            Проба(Ложь, Числа)",
                   "        ;", "    ;")

    assert len(_lint(text)) == 1


# --- what is not reported ---------------------------------------------------------------------

def test_a_scope_with_a_statement_next_to_it_is_not_reported():
    text = _method(
        "    знч Размер = Числа.Размер()",
        "    область",
        "        знч Итог = Размер + 1",
        "        Итог.ВСтроку()",
        "    ;",
    )
    assert _lint(text) == []


def test_a_module_that_does_not_parse_is_not_judged():
    text = _method("    область", "        Проба(Ложь, Числа)", "    ;") + "метод Сломан(\n"
    assert _lint(text) == []


def test_the_english_keyword_is_read():
    text = "method Probe()\n    scope\n        val Total = 1\n    ;\n;\n"
    found = _lint(text, "Probe.xbsl")

    assert len(found) == 1
    assert _fixed(text, found[0]) == "method Probe()\n    val Total = 1\n;\n"


def test_the_english_message_names_the_keyword_in_english():
    i18n.set_lang("en")
    try:
        found = _lint(_method("    область", "        Проба(Ложь, Числа)", "    ;"))
    finally:
        i18n.set_lang("ru")

    assert "'scope'" in found[0].message


# --- the fix ----------------------------------------------------------------------------------

def test_comments_on_the_lines_of_the_scope_keep_lines_of_their_own():
    text = _method("    если Флаг", "        область // открытие", "            Проба(Ложь, Числа)",
                   "        ; // закрытие", "    ;")
    found = _lint(text)

    assert _fixed(text, found[0]) == _method("    если Флаг", "        // открытие", "        Проба(Ложь, Числа)",
                                             "        // закрытие", "    ;")


def test_tabs_are_moved_by_one_tab():
    text = _method("\tесли Флаг", "\t\tобласть", "\t\t\tПроба(Ложь, Числа)", "", "\t\t\tПроба(Ложь, Числа)",
                   "\t\t;", "\t;")
    found = _lint(text)

    assert _fixed(text, found[0]) == _method("\tесли Флаг", "\t\tПроба(Ложь, Числа)", "",
                                             "\t\tПроба(Ложь, Числа)", "\t;")


@pytest.mark.parametrize("lines", [
    # code on the line of the keyword
    ["    область Проба(Ложь, Числа) ;"],
    # a block comment on the line of the keyword
    ["    область /* блок */", "        Проба(Ложь, Числа)", "    ;"],
    # a body line indented less than the first one
    ["    область", "            Проба(Ложь, Числа)", "        Проба(Ложь, Числа)", "    ;"],
    # a string spanning lines would carry its text along
    ["    область", '        знч Текст = "первая', '            вторая"', "    ;"],
])
def test_an_unusual_layout_keeps_the_finding_without_a_fix(lines):
    found = _lint(_method(*lines))

    assert len(found) == 1
    assert found[0].fix is None


def test_fix_rewrites_the_file_by_its_own_offsets(tmp_path: Path):
    target = tmp_path / "Проба.xbsl"
    lines = [
        "метод Проба(Флаг: Булево)",
        "    если Флаг",
        "        область",
        "            знч Итог = 1",
        "",
        "            Итог.ВСтроку()",
        "        ;",
        "    ;",
        ";",
        "",
    ]
    target.write_bytes(b"\xef\xbb\xbf" + "\r\n".join(lines).encode("utf-8"))

    code = cli.main([str(tmp_path), "--select", RULE, "--no-baseline", "--fix"])

    assert code == 0
    raw = target.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    assert raw[3:].decode("utf-8") == "\r\n".join([
        "метод Проба(Флаг: Булево)",
        "    если Флаг",
        "        знч Итог = 1",
        "",
        "        Итог.ВСтроку()",
        "    ;",
        ";",
        "",
    ])
