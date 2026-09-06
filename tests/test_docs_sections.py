"""Splitting a documentation page into sections and summarizing it (xbsl/docs.py, no data).

The MCP page tools answer briefly or with one section on top of these pure functions. The
sample below mirrors a reference article the way the extractor cleans it: the h1 title, the
qualified name and the availability in code, the description, a bold caption block, then the
h2 sections with the members as h3 inside. Nothing here needs the data bundle; the live check
at the bottom is marked `needs_data`.
"""

import json

import pytest

from xbsl import docs

_HEAD = (
    "<h1>Группа</h1> "
    "<p><code>Стд::Интерфейс::Группы::Группа</code> <code>Доступность: Клиент</code></p> "
    "<p>Компонент группы, содержащей в себе другие компоненты. Может иметь рамку и заголовок. "
    "Может прокручиваться.</p> "
    "<p><strong>Сравнение</strong></p> <p>Ссылочное</p> "
)
_PAGE = _HEAD + (
    '<h2 id="иерархия-типа">Иерархия типа</h2> '
    '<p><em>Базовые типы:</em> <a href="#stdlib/demo/Component_ru">Компонент</a></p> <hr> '
    '<h2 id="конструкторы">Конструкторы</h2> <h3 id="группа-1">Группа</h3> '
    "<pre><code>Группа(\nЗаголовок: Строка,\nВидимость: Авто|Булево)</code></pre> "
    '<h2 id="свойства">Свойства</h2> <h3 id="заголовок">Заголовок</h3> '
    "<p><code>Строка</code></p> <p>Текст заголовка группы.</p> "
    '<h2 id="список-унаследованных-методов">Список унаследованных методов</h2> '
    '<h3 id="компонент">Компонент</h3> <p><a href="#stdlib/demo/Component_ru">Закрыть</a></p>'
)
_TITLES = [
    "Описание", "Иерархия типа", "Конструкторы", "Свойства", "Список унаследованных методов",
]
_RECORD = {
    "id": "stdlib/demo/Group_ru",
    "kind": "type",
    "title": "Группа",
    "qualified": "Стд::Интерфейс::Группы::Группа",
    "availability": "Клиент",
    "url": "https://host/docs/help/stdlib/demo/Group_ru/",
    "html": _PAGE,
}
_DESCRIPTION = (
    "Компонент группы, содержащей в себе другие компоненты. Может иметь рамку и заголовок. "
    "Может прокручиваться."
)


# --- the pure functions --------------------------------------------------------------------


def test_sections_split_at_h2_with_the_head_first():
    assert [title for title, _ in docs.sections(_PAGE)] == _TITLES


def test_the_head_excludes_the_title_and_stops_at_the_first_section():
    head = dict(docs.sections(_PAGE))["Описание"]
    assert head.startswith("<p><code>Стд::")
    assert "Компонент группы" in head
    assert "<h1>" not in head and "Иерархия" not in head


def test_a_section_runs_from_its_heading_to_the_next_one():
    properties = dict(docs.sections(_PAGE))["Свойства"]
    assert properties.startswith('<h2 id="свойства">')
    assert "Текст заголовка группы" in properties
    assert "Список унаследованных" not in properties and "Группа(" not in properties


def test_a_page_without_headings_is_its_head_alone():
    page = "<h1>Имя</h1> <p>Только описание.</p>"
    assert docs.sections(page) == [("Описание", "<p>Только описание.</p>")]
    assert docs.sections("") == [("Описание", "")]


def test_a_second_h1_opens_a_section_on_an_index_page():
    page = "<h1>Стд::Пакет</h1> <p>Типы пакета.</p> <h1>Типы</h1> <p>Список.</p>"
    assert [title for title, _ in docs.sections(page)] == ["Описание", "Типы"]


def test_find_section_ignores_case_and_takes_the_english_name():
    assert docs.find_section(_PAGE, "свойства")[0] == "Свойства"
    assert docs.find_section(_PAGE, "PROPERTIES")[0] == "Свойства"
    assert docs.find_section(_PAGE, "inherited methods")[0] == "Список унаследованных методов"
    assert docs.find_section(_PAGE, "description")[1] == dict(docs.sections(_PAGE))["Описание"]
    assert docs.find_section(_PAGE, "Методы") is None
    assert docs.find_section(_PAGE, "") is None


def test_description_drops_the_preamble_and_the_caption_blocks():
    assert docs.description(_PAGE) == _DESCRIPTION


def test_description_of_a_topic_comes_from_its_general_description_section():
    topic = (
        "<h1>Структура</h1><h2>Общее описание</h2>"
        "<p>Структура имеет фиксированный набор полей. Ещё.</p>"
    )
    assert docs.description(topic) == "Структура имеет фиксированный набор полей. Ещё."


def test_description_does_not_borrow_another_section_for_an_empty_head():
    page = "<h1>Имя</h1> <h2>Свойства</h2> <h3>Поле</h3> <p>Строка.</p>"
    assert docs.description(page) == ""


def test_summarize_keeps_whole_sentences_within_the_limit():
    first = "Компонент группы, содержащей в себе другие компоненты."
    assert docs.summarize(_PAGE, limit=60) == first
    assert docs.summarize(_PAGE, limit=95) == first + " Может иметь рамку и заголовок."
    assert docs.summarize(_PAGE) == _DESCRIPTION
    assert docs.summarize(_PAGE, limit=0) == _DESCRIPTION


def test_summarize_cuts_an_overlong_first_sentence_at_a_word_with_an_ellipsis():
    assert docs.summarize(_PAGE, limit=30) == "Компонент группы, содержащей..."
    assert docs.summarize("", limit=30) == ""


def test_plain_text_keeps_the_line_breaks_of_a_code_block():
    text = docs.plain_text(dict(docs.sections(_PAGE))["Конструкторы"])
    assert "Группа(\nЗаголовок: Строка,\nВидимость: Авто|Булево)" in text
    assert "<" not in text


# --- the MCP page tools over an in-memory page ------------------------------------------------


@pytest.fixture
def page_store(mcp_module, monkeypatch):
    """The MCP module over docs.page/for_symbol answering from memory - no database."""
    monkeypatch.setattr(
        docs, "page",
        lambda doc_id, version=None: dict(_RECORD) if doc_id == _RECORD["id"] else None,
    )
    monkeypatch.setattr(
        docs, "for_symbol",
        lambda name, version=None: _RECORD["id"] if name == _RECORD["title"] else None,
    )
    return mcp_module


def test_docs_page_whole_keeps_its_former_shape(page_store):
    answer = page_store.docs_page(_RECORD["id"])
    assert set(answer) == {"id", "kind", "title", "qualified", "availability", "url", "text"}
    assert "Текст заголовка группы" in answer["text"] and "<" not in answer["text"]


def test_docs_page_brief_answers_with_the_head_alone(page_store):
    answer = page_store.docs_page(_RECORD["id"], brief=True)
    assert set(answer) == {
        "id", "kind", "title", "qualified", "availability", "summary", "sections",
    }
    assert answer["summary"] == _DESCRIPTION
    assert answer["sections"] == _TITLES


def test_docs_page_section_answers_with_that_section_alone(page_store):
    answer = page_store.docs_page(_RECORD["id"], section="properties")
    assert answer["section"] == "Свойства"
    assert answer["title"] == _RECORD["title"] and answer["url"] == _RECORD["url"]
    assert "Текст заголовка группы" in answer["text"]
    assert "Иерархия" not in answer["text"] and "Закрыть" not in answer["text"]


def test_docs_page_section_wins_over_brief(page_store):
    answer = page_store.docs_page(_RECORD["id"], brief=True, section="Свойства")
    assert answer["section"] == "Свойства" and "summary" not in answer


def test_docs_page_unknown_section_names_the_sections_to_choose_from(page_store):
    answer = page_store.docs_page(_RECORD["id"], section="Методы")
    assert "Методы" in answer["error"]
    assert answer["id"] == _RECORD["id"]
    assert answer["sections"] == _TITLES


def test_docs_symbol_takes_the_same_modes(page_store):
    assert page_store.docs_symbol(_RECORD["title"], brief=True)["sections"] == _TITLES
    assert page_store.docs_symbol(_RECORD["title"], section="Constructors")["section"] == "Конструкторы"
    assert page_store.docs_symbol(_RECORD["title"])["text"].startswith(_RECORD["title"])


def test_a_missing_page_is_empty_in_every_mode(page_store):
    assert page_store.docs_page("нет") == {}
    assert page_store.docs_page("нет", brief=True) == {}
    assert page_store.docs_symbol("нет", section="Свойства") == {}


# --- the live documentation ------------------------------------------------------------------


def _size(answer: dict) -> int:
    return len(json.dumps(answer, ensure_ascii=False))


@pytest.mark.needs_data
def test_the_brief_and_the_section_answers_are_a_fraction_of_a_live_type_page(mcp_module):
    """The measure behind the modes: a type page is thousands of characters, its head is not."""
    if not docs.available():
        pytest.skip("the data bundle carries no docs.sqlite")
    whole = mcp_module.docs_symbol(_RECORD["title"])
    if not whole:
        pytest.skip("the documentation has no page for the sample type")
    brief = mcp_module.docs_symbol(_RECORD["title"], brief=True)
    properties = mcp_module.docs_symbol(_RECORD["title"], section="Properties")

    assert "Свойства" in brief["sections"]
    assert brief["summary"] and "Доступность" not in brief["summary"]
    assert properties["section"] == "Свойства"
    assert _size(brief) < _size(properties) < _size(whole)
    assert _size(brief) * 4 < _size(whole)
