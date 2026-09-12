"""Prose inside a resource file: what the translator reads there and what it must not touch.

A `.css`, `.js`, `.html` or `.svg` used to be copied byte for byte, so a Russian comment went
into the English tree untouched while the coverage called the file complete. These checks hold
the reading to both halves of the promise: the prose moves, and the code around it does not.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from xbsl.translation import dictionary as dict_module
from xbsl.translation import entries as entries_module
from xbsl.translation.project import translate_project
from xbsl.translation.reporting import FileReport
from xbsl.translation.resourcefile import resource_payloads, translate_resource


def _dictionary(phrases: dict | None = None, tokens: dict | None = None):
    return dict_module.Dictionary(tokens=dict(tokens or {}), phrases=dict(phrases or {}))


def _run(text: str, suffix: str, phrases: dict | None = None) -> tuple[str, FileReport]:
    report = FileReport(path=f"resource{suffix}")
    out = translate_resource(text, suffix, _dictionary(phrases), report)
    return out, report


def _payloads(suffix: str, text: str) -> list[str]:
    return [payload for _start, _end, payload in resource_payloads(suffix, text)]


#: A whole-pass check reads the platform data (term pairs, the metamodel, the ui schema),
#: and a public checkout has none - those tests are skipped there rather than failed.
_needs_data = pytest.mark.needs_data


# --- css ------------------------------------------------------------------------------------


def test_a_stylesheet_comment_is_a_phrase_like_any_other():
    text = (
        "/* Шапка страницы */\n"
        ".header {\n"
        "    color: red; /* цвет заголовка */\n"
        "}\n"
    )
    out, report = _run(text, ".css", {
        "Шапка страницы": "Page header", "цвет заголовка": "the heading colour",
    })
    assert out == (
        "/* Page header */\n"
        ".header {\n"
        "    color: red; /* the heading colour */\n"
        "}\n"
    )
    assert report.phrases_done == 2 and report.phrases_missing == 0


def test_a_stylesheet_keeps_its_selectors_properties_and_values():
    """Only the payload of a comment moves - the rest of the file is byte for byte the same."""
    text = (
        "/* Карточка */\n"
        ".card--wide > .card__title:hover {\n"
        "    font-family: \"Робото\", sans-serif;\n"
        "    content: \"/* это не комментарий */\";\n"
        "    background: url(http://example.test/a/*b*/c.png);\n"
        "}\n"
    )
    out, _report = _run(text, ".css", {"Карточка": "Card"})
    assert out == text.replace("/* Карточка */", "/* Card */")


def test_a_stylesheet_comment_without_an_entry_is_a_gap():
    _out, report = _run("/* Подвал */\n.footer {}\n", ".css")
    assert report.phrases_missing == 1
    assert report.missing_phrases == {"Подвал": [(1, 4)]}
    assert not report.covered and report.coverage() == 0.0


def test_an_english_comment_is_not_counted_as_a_surface():
    """Nothing to translate there, and counting it would sink the coverage of every file."""
    _out, report = _run("/* the page header */\n.header {}\n", ".css")
    assert report.phrases_done == 0 and report.phrases_missing == 0


# --- js -------------------------------------------------------------------------------------


def test_both_comment_shapes_of_a_script_are_read():
    text = (
        "// Счётчик кликов\n"
        "let clicks = 0;\n"
        "/* Обработчик нажатия\n"
        "   на кнопку оплаты */\n"
        "function onClick() { clicks += 1; }\n"
    )
    assert _payloads(".js", text) == [
        "Счётчик кликов", "Обработчик нажатия", "на кнопку оплаты",
    ]


def test_a_marker_inside_a_string_a_pattern_or_a_template_opens_no_comment():
    """The one mistake a pattern-matching reader makes: `/[/*]/` swallows the rest of the file."""
    text = (
        "const re = /[/*]/;\n"
        "const url = \"https://example.test//a\";\n"
        "const tpl = `путь // не комментарий`;\n"
        "// Настоящий комментарий\n"
    )
    assert _payloads(".js", text) == ["Настоящий комментарий"]


def test_a_comment_inside_a_template_substitution_is_still_a_comment():
    text = "const tpl = `итог ${ total /* сумма заказа */ } руб.`;\n"
    assert _payloads(".js", text) == ["сумма заказа"]


def test_a_script_keeps_its_code():
    text = (
        "// Подсчёт\n"
        "const s = 'строка со /* звёздочкой */';\n"
        "let x = a / b / c;\n"
    )
    out, _report = _run(text, ".js", {"Подсчёт": "The count"})
    assert out == text.replace("// Подсчёт", "// The count")


# --- html and svg ----------------------------------------------------------------------------


def test_a_markup_comment_is_read_and_an_attribute_that_spells_one_is_not():
    text = (
        "<!-- Блок с ценами -->\n"
        "<div title=\"<!-- это значение атрибута -->\">Текст страницы</div>\n"
    )
    out, report = _run(text, ".html", {"Блок с ценами": "The price block"})
    assert out == text.replace("Блок с ценами", "The price block")
    assert report.phrases_done == 1 and report.phrases_missing == 0


def test_the_text_of_a_page_stays_as_written():
    """A page's own words are data: the platform translates them by its own localization."""
    text = "<p>Оплатите счёт до конца месяца</p>\n"
    _out, report = _run(text, ".html", {})
    assert report.phrases_done == 0 and report.phrases_missing == 0


def test_the_title_and_desc_of_a_drawing_are_read():
    """Those two are not comments - they are what a screen reader speaks over the picture."""
    text = (
        "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 16 16\">\n"
        "    <title>Значок оплаты</title>\n"
        "    <desc>Карта и стрелка</desc>\n"
        "    <!-- нарисовано вручную -->\n"
        "    <path d=\"M0 0 L16 16\" fill=\"#ff0000\"/>\n"
        "</svg>\n"
    )
    out, report = _run(text, ".svg", {
        "Значок оплаты": "Payment icon", "Карта и стрелка": "A card and an arrow",
        "нарисовано вручную": "drawn by hand",
    })
    assert out == (
        "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 16 16\">\n"
        "    <title>Payment icon</title>\n"
        "    <desc>A card and an arrow</desc>\n"
        "    <!-- drawn by hand -->\n"
        "    <path d=\"M0 0 L16 16\" fill=\"#ff0000\"/>\n"
        "</svg>\n"
    )
    assert report.phrases_done == 3


def test_a_drawing_keeps_its_geometry_and_attribute_names():
    text = (
        "<svg><title>Стрелка</title>"
        "<path id=\"Контур\" d=\"M0 0 L1 1\" stroke-width=\"2\"/></svg>\n"
    )
    out, _report = _run(text, ".svg", {"Стрелка": "Arrow"})
    assert out == text.replace(">Стрелка<", ">Arrow<")


def test_the_comments_of_an_embedded_style_and_script_are_read():
    text = (
        "<html><head><style>\n"
        "/* Отступ слева */\n"
        ".a { margin-left: 4px; }\n"
        "</style><script>\n"
        "// Кнопка закрытия\n"
        "close();\n"
        "</script></head></html>\n"
    )
    assert _payloads(".html", text) == ["Отступ слева", "Кнопка закрытия"]


# --- the borders ------------------------------------------------------------------------------


def test_a_licence_comment_is_left_alone():
    """Legal wording says in a translation something the original does not."""
    text = (
        "/*! Copyright (c) Кто-то. Все права защищены. */\n"
        "/* Шапка */\n"
        ".header {}\n"
    )
    assert _payloads(".css", text) == ["Шапка"]


def test_a_minified_stylesheet_is_left_alone_whole():
    """Build output: nobody edits it, and its one comment is the banner the minifier kept."""
    text = "/* Шапка */\n.a{" + "color:red;" * 60 + "}\n"
    assert len(max(text.splitlines(), key=len)) > 500
    assert _payloads(".css", text) == []


@_needs_data
def test_a_binary_resource_is_copied_as_it_was(tmp_path: Path):
    root = tmp_path / "Acme" / "Задачник"
    _mini_project(root)
    raw = b"\x89PNG\r\n\x1a\n\xff\xfe not text at all"
    icon = root / "Основное" / "Ресурсы" / "Значок.png"
    icon.parent.mkdir(parents=True, exist_ok=True)
    icon.write_bytes(raw)
    out = tmp_path / "out"
    translate_project(root, _dictionary(tokens={
        "Задачник": "TaskBook", "Основное": "Main", "Ресурсы": "Resources", "Значок": "Icon",
    }), out)
    assert (out / "Main" / "Resources" / "Icon.png").read_bytes() == raw


# --- the code of the file is untouched ---------------------------------------------------------


#: Files written the way the awkward cases are written, for the one check that reads them all.
_CORPUS = [
    (".css", "@media (min-width: 40rem) {\n"
             "    /* Широкий экран */\n"
             "    .grid { grid-template-columns: repeat(3, 1fr); }\n"
             "}\n"
             ".a::before { content: \"// не комментарий\"; }\n"
             ".b { background: url(data:image/svg+xml;base64,PHN2Zy8+); }\n"),
    (".js", "/* Модуль корзины */\n"
            "import { add } from './cart.js';\n"
            "const path = /^\\/api\\/v1\\//;\n"
            "const glyphs = /[/*]/g;\n"
            "const text = `строка ${ a / b } и ещё ${ c /* хвост */ }`;\n"
            "let ratio = width / height; // Пропорция\n"),
    (".html", "<!DOCTYPE html>\n"
              "<!-- Вставка тарифов -->\n"
              "<div class=\"plan\" data-note=\"<!-- тут значение -->\">\n"
              "    <p>Тариф ПРОФ</p>\n"
              "</div>\n"
              "<style>/* Поля карточки */ .plan { padding: 8px; }</style>\n"
              "<script>const x = 1; // Счётчик\n</script>\n"),
    (".svg", "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
             "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 24 24\">\n"
             "    <title>Лупа</title>\n"
             "    <desc>Поиск по сайту</desc>\n"
             "    <!-- окружность и ручка -->\n"
             "    <circle cx=\"11\" cy=\"11\" r=\"7\" fill=\"none\" stroke=\"#222\"/>\n"
             "    <path d=\"M16 16 L21 21\" stroke-linecap=\"round\"/>\n"
             "</svg>\n"),
]


def test_every_edit_lands_inside_a_payload_and_nowhere_else():
    """The whole promise of the code half, checked without trusting the reader's own spans.

    Each payload is translated into ITSELF plus a marker word. Take the marker back out of
    the result and the file has to be byte for byte what it was - any edit that had landed on
    a selector, an attribute or a line of code would survive that removal and show up here.
    """
    for suffix, text in _CORPUS:
        payloads = {payload for _s, _e, payload in resource_payloads(suffix, text)}
        assert payloads, suffix
        out = translate_resource(
            text, suffix, _dictionary({payload: payload + " MARK" for payload in payloads}))
        assert out != text, suffix
        assert out.replace(" MARK", "") == text, suffix


def test_a_translated_drawing_keeps_its_element_tree():
    """Read back as xml: the same elements, the same attributes, the same geometry."""
    import xml.etree.ElementTree as ET

    suffix, text = _CORPUS[-1]
    out = translate_resource(text, suffix, _dictionary({
        "Лупа": "Magnifier", "Поиск по сайту": "Site search",
        "окружность и ручка": "the circle and the handle",
    }))

    def shape(node):
        return [(child.tag, dict(child.attrib), shape(child)) for child in node]

    before, after = ET.fromstring(text), ET.fromstring(out)
    assert shape(before) == shape(after)
    assert after.find("{http://www.w3.org/2000/svg}title").text == "Magnifier"


# --- the whole pass ---------------------------------------------------------------------------


def _mini_project(root: Path) -> None:
    _write(root / "Проект.yaml", (
        "Ид: ffeacdec-02d6-4f08-bcfa-be89e9a1861a\n"
        "Поставщик: Acme\n"
        "Имя: Задачник\n"
        "Версия: 1.0.0\n"
        "Представление: \"Задачник\"\n"
    ))
    _write(root / "Основное" / "Подсистема.yaml", "Интерфейс: ВключатьВАвтоИнтерфейс\n")


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _project_with_a_stylesheet(tmp_path: Path) -> Path:
    root = tmp_path / "Acme" / "Задачник"
    _mini_project(root)
    _write(root / "Основное" / "Ресурсы" / "Стиль.css", "/* Шапка страницы */\n.header {}\n")
    return root


def _tokens() -> dict:
    return {"Задачник": "TaskBook", "Основное": "Main", "Ресурсы": "Resources", "Стиль": "Style"}


@_needs_data
def test_the_pass_writes_the_translated_stylesheet_and_counts_it(tmp_path: Path):
    root = _project_with_a_stylesheet(tmp_path)
    out = tmp_path / "out"
    report = translate_project(
        root, _dictionary({"Шапка страницы": "Page header"}, _tokens()), out)

    written = (out / "Main" / "Resources" / "Style.css").read_text(encoding="utf-8")
    assert written == "/* Page header */\n.header {}\n"
    assert report.totals()["missing"] == 0


@_needs_data
def test_a_stylesheet_comment_without_an_entry_makes_the_pass_not_ready(tmp_path: Path):
    """`--strict` reads this verdict: an untranslated comment in a resource now fails it."""
    from xbsl.translation import cli as translate_cli

    root = _project_with_a_stylesheet(tmp_path)
    report = translate_project(root, _dictionary({}, _tokens()), None)
    assert report.merged_missing_phrases()["Шапка страницы"]["count"] == 1
    assert not translate_cli._ready(report)

    ready = translate_project(root, _dictionary({"Шапка страницы": "Page header"}, _tokens()), None)
    assert translate_cli._ready(ready)


@_needs_data
def test_the_gap_of_a_stylesheet_comment_names_its_file_and_line(tmp_path: Path):
    root = _project_with_a_stylesheet(tmp_path)
    gaps = entries_module.gaps_of_project(root, _dictionary({}, _tokens()))
    phrase = next(gap for gap in gaps if gap.kind == "phrase")
    assert phrase.key == "Шапка страницы"
    assert phrase.places == [(str(Path("Основное") / "Ресурсы" / "Стиль.css"), 1)]


def test_a_pair_written_from_a_stylesheet_comment_is_not_an_orphan(tmp_path: Path):
    """The orphan pass reads a resource with the same module, or `--prune` would delete this."""
    root = _project_with_a_stylesheet(tmp_path)
    path = tmp_path / "xbsl-translation.yaml"
    path.write_text(
        "version: 1\nlanguage: en\nphrases:\n"
        "    \"Шапка страницы\": \"Page header\"\n"
        "    \"Подвал страницы\": \"Page footer\"\n",
        encoding="utf-8")
    loaded = dict_module.load(path)
    orphans = {entry.key for entry in entries_module.unused_entries(root, path, loaded)}
    assert orphans == {"Подвал страницы"}
