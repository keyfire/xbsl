"""Typography in the resource files of a project (.css, .js, .svg, .html).

A subsystem ships what lies in its `Resources` folder to the browser as it is, so the prose
there is read by the same people as the prose of a module and holds to the same typography.
What the rules judge is the comments of all four formats plus the text a user reads on the
screen; what they leave alone is code - selectors, identifiers, attribute values and the
string literals of a script.
"""

import pytest

from xbsl import engine, fixer
from xbsl.cli import discover

EM_DASH = "typography/em-dash"
ELLIPSIS = "typography/ellipsis"
CURLY = "typography/curly-quotes"
GUILLEMETS = "typography/guillemets-comment"
YO = "typography/yo-in-text"

ALL_TYPOGRAPHY = (EM_DASH, ELLIPSIS, CURLY, GUILLEMETS, YO)


def _write(tmp_path, name: str, text: str):
    folder = tmp_path / "Ресурсы"
    folder.mkdir(exist_ok=True)
    path = folder / name
    # Bytes, not write_text: on Windows the text mode turns every line break into CRLF, and
    # a test about offsets into the file would then be measuring the platform.
    path.write_bytes(text.encode("utf-8"))
    return path


def _lint(tmp_path, name: str, text: str, select=ALL_TYPOGRAPHY):
    _write(tmp_path, name, text)
    return engine.run(discover([str(tmp_path)]), select=set(select))


def _ids(diags):
    return sorted(d.rule_id for d in diags)


# --- CSS ----------------------------------------------------------------------------------

def test_css_comment_is_judged(tmp_path):
    diags = _lint(tmp_path, "site.css", "/* ширина — по контейнеру */\n.a { color: red; }\n")

    assert _ids(diags) == [EM_DASH]
    assert diags[0].line == 1


def test_css_selector_and_string_are_left_alone(tmp_path):
    # The em dash inside a class name and inside a `content` value is code, not prose;
    # a `/*` inside that string does not open a comment either.
    diags = _lint(
        tmp_path, "site.css",
        '.a—b { content: "/* — не комментарий … */"; }\n',
    )

    assert diags == []


# --- JS ------------------------------------------------------------------------------------

def test_js_line_and_block_comments_are_judged(tmp_path):
    diags = _lint(
        tmp_path, "site.js",
        "// первый — комментарий\n/* второй … комментарий */\n",
    )

    assert _ids(diags) == [ELLIPSIS, EM_DASH]


def test_js_strings_are_left_alone(tmp_path):
    # A URL carries `//` and a string may carry any character at all: neither opens a comment
    # and neither is prose the rules judge.
    diags = _lint(
        tmp_path, "site.js",
        'var u = "http://x//y — z"; var q = \'…\'; var t = `— … “”`;\n',
    )

    assert diags == []


def test_js_regular_expression_is_not_read_as_a_comment(tmp_path):
    # The live case: a minified bundle replaces runs of dots with the ellipsis character, and
    # the pattern itself holds slashes. A scanner without regular-expression literals reports
    # the tail of the line as a comment.
    diags = _lint(
        tmp_path, "site.js",
        'a = a.replace(/([?!])…/g, "$1..").replace(/\\/\\/x/g, "—");\n',
    )

    assert diags == []


def test_js_comment_inside_a_template_interpolation_is_judged(tmp_path):
    diags = _lint(
        tmp_path, "site.js",
        "const s = `цена ${ value /* с учётом скидки — без НДС */ } руб`;\n",
    )

    assert _ids(diags) == [EM_DASH]


# --- SVG -----------------------------------------------------------------------------------

_SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">{body}</svg>\n')


def test_svg_title_desc_and_text_are_judged(tmp_path):
    diags = _lint(tmp_path, "Схема.svg", _SVG.format(
        body="<title>Схема — общая</title><desc>Описание …</desc><text>Итого —</text>",
    ))

    assert _ids(diags) == [ELLIPSIS, EM_DASH, EM_DASH]


def test_svg_comment_is_judged(tmp_path):
    diags = _lint(tmp_path, "Схема.svg", _SVG.format(body="<!-- лампа — из заглушек -->"))

    assert _ids(diags) == [EM_DASH]


def test_svg_attributes_and_style_are_left_alone(tmp_path):
    diags = _lint(tmp_path, "Схема.svg", _SVG.format(
        body='<style>.a—b{content:"—"}</style><rect id="блок—1" data-hint="Итого — всё"/>',
    ))

    assert diags == []


def test_svg_text_outside_a_text_element_is_not_prose(tmp_path):
    # Character data between shapes is whitespace and stray markup, never a phrase.
    diags = _lint(tmp_path, "Схема.svg", _SVG.format(body="<g>—</g><path d='M0 0'/>"))

    assert diags == []


# --- HTML ----------------------------------------------------------------------------------

def test_html_text_node_and_comment_are_judged(tmp_path):
    diags = _lint(
        tmp_path, "page.html",
        "<!-- вводка — черновик -->\n<p>Сервис — это удобно …</p>\n",
    )

    assert _ids(diags) == [ELLIPSIS, EM_DASH, EM_DASH]


def test_html_script_body_and_attributes_are_left_alone(tmp_path):
    diags = _lint(
        tmp_path, "page.html",
        '<script>var s = "—"; // …\n</script>\n<a href="?a—b" title="Итого — всё">x</a>\n',
    )

    assert diags == []


# --- what belongs where --------------------------------------------------------------------

def test_guillemets_are_reported_in_a_comment_and_allowed_in_the_text(tmp_path):
    diags = _lint(
        tmp_path, "page.html",
        "<!-- про «1С» -->\n<p>Сервис «1С:Предприятие» через Интернет</p>\n",
    )

    assert _ids(diags) == [GUILLEMETS, GUILLEMETS]
    assert all(d.line == 1 for d in diags)


def test_the_letter_yo_is_reported_in_the_text_and_not_in_a_comment(tmp_path):
    diags = _lint(
        tmp_path, "page.html",
        "<!-- жёлтая заглушка -->\n<p>Показать удалённые</p>\n",
    )

    assert _ids(diags) == [YO]
    assert diags[0].line == 2
    assert "удалённые" in diags[0].message and "удаленные" in diags[0].message


def test_the_message_names_the_place_the_character_sits_in(tmp_path):
    diags = _lint(
        tmp_path, "page.html", "<!-- а — б -->\n<p>в — г</p>\n", select=(EM_DASH,),
    )

    by_line = {d.line: d.message for d in diags}
    assert "комментарии" in by_line[1]
    assert "читает пользователь" in by_line[2]


def test_curly_quotes_are_reported_in_the_text(tmp_path):
    diags = _lint(tmp_path, "page.html", "<p>он сказал “да”</p>\n", select=(CURLY,))

    assert len(diags) == 2


# --- the fix --------------------------------------------------------------------------------

def test_the_fix_replaces_the_character_in_place(tmp_path):
    path = _write(tmp_path, "page.html", "<!-- а — б -->\n<p>Сервис — это “удобно” …</p>\n")
    diags = engine.run(discover([str(tmp_path)]), select=set(ALL_TYPOGRAPHY))

    source = engine.load(path)
    result = fixer.fix_source(source, diags)

    assert result.changed
    assert result.text == "<!-- а – б -->\n<p>Сервис – это \"удобно\" ...</p>\n"


def test_the_fix_lands_on_the_characters_of_the_file(tmp_path):
    path = _write(tmp_path, "Схема.svg", _SVG.format(body="<text>Итого — удалённые</text>"))
    diags = engine.run(discover([str(tmp_path)]), select={EM_DASH, YO})

    written = path.read_bytes().decode("utf-8")
    spans = {written[d.fix.start:d.fix.end] for d in diags if d.fix is not None}
    assert spans == {"—", "ё"}


# --- the boundary of the check ---------------------------------------------------------------

def test_a_resource_file_is_collected_only_from_the_resources_folder(tmp_path):
    (tmp_path / "build").mkdir()
    (tmp_path / "build" / "vendor.js").write_text("// чужой — код\n", encoding="utf-8")
    _write(tmp_path, "site.js", "// свой — код\n")

    diags = engine.run(discover([str(tmp_path)]), select={EM_DASH})

    assert [d.path.endswith("site.js") for d in diags] == [True]


def test_the_english_spelling_of_the_folder_is_collected_too(tmp_path):
    folder = tmp_path / "Resources"
    folder.mkdir()
    (folder / "site.css").write_text("/* цвет — фирменный */\n", encoding="utf-8")

    diags = engine.run(discover([str(tmp_path)]), select={EM_DASH})

    assert len(diags) == 1


@pytest.mark.parametrize("name, text", [
    ("site.css", ".a { color: red; }   \n"),
    ("page.html", "<p>x</p>   \r\n<p>y</p>\n"),
])
def test_only_typography_looks_at_a_resource_file(tmp_path, name, text):
    # Trailing spaces and mixed newlines are a module's business: a stylesheet is laid out by
    # its author, and half the resources of a live project arrive from a vendor minified.
    diags = _lint(tmp_path, name, text, select=("whitespace", "encoding", "style"))

    assert diags == []
