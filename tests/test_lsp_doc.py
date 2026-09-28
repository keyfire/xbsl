"""Documentation comments in the editor (xbsl/lsp_doc.py): the hover, the signature help and
the completion of a `///` block.

The pieces that only read text - the list of parameters, the Markdown of a block - need no
data; the call under the cursor, the completion and the answers of the server tokenize or
parse the module and carry `needs_data`.
"""

from types import SimpleNamespace

import pytest

from xbsl import lsp, lsp_doc
from xbsl.lsp_nav import IndexLookup, _hover_method

_DOC = (
    "Цена со скидкой.\n\n@параметр Цена - Цена без скидки.\n@параметр Скидка - Скидка в "
    "процентах.\n\n@возвращает Цена со скидкой."
)
_METHOD = {
    "name": "ЦенаСоСкидкой", "module": "Цены", "path": "Цены.xbsl", "line": 7,
    "params": "(Цена: Число, Скидка: Число = 0)", "returns": "Число", "doc": _DOC,
    "annotations": [],
}


def _lookup() -> IndexLookup:
    return IndexLookup({"methods": [_METHOD]})


# --- text alone -------------------------------------------------------------------------------

def test_the_parameters_of_a_signature_are_split_at_the_top_level():
    params = '(Коды: Массив<Строка>, Отбор: (Строка)->Булево, Текст: Строка = "а, б")'
    spans = lsp_doc.split_params(params)
    assert [params[first:last] for first, last in spans] == [
        "Коды: Массив<Строка>", "Отбор: (Строка)->Булево", 'Текст: Строка = "а, б"',
    ]
    assert lsp_doc.split_params("()") == []
    assert lsp_doc.param_name("@Аннотация(1) Коды: Массив<Строка>") == "Коды"


def test_the_hover_of_a_method_renders_its_tags_as_sections():
    card = _hover_method(_METHOD)
    assert "Цена со скидкой.\n\n**Параметры:**\n\n- **Цена** - Цена без скидки." in card
    assert "**Возвращает:** Цена со скидкой." in card
    assert "@параметр" not in card


# --- the call under the cursor ----------------------------------------------------------------

@pytest.mark.needs_data
@pytest.mark.parametrize(("prefix", "expected"), (
    ("пер Х = Цены.ЦенаСоСкидкой(", (["Цены", "ЦенаСоСкидкой"], 0)),
    ("пер Х = Цены.ЦенаСоСкидкой(Округлить(1, 2), ", (["Цены", "ЦенаСоСкидкой"], 1)),
    ("пер Х = ЦенаСоСкидкой(100,\n    ", (["ЦенаСоСкидкой"], 1)),
    ("пер Х = Цены.ЦенаСоСкидкой(Округлить(1, ", (["Округлить"], 1)),
    ("пер Х = новый Цены(1, ", None),
    ("пер Х = [1, ", None),
    ("пер Х = Цены.ЦенаСоСкидкой(1) + ", None),
))
def test_the_call_the_cursor_stands_in(prefix, expected):
    assert lsp_doc.call_at(prefix) == expected


@pytest.mark.needs_data
def test_the_signature_help_shows_the_tag_of_the_parameter_under_the_cursor():
    found = lsp_doc.signature_help(_lookup(), "пер Х = Цены.ЦенаСоСкидкой(100, ", "Касса")
    assert found["label"] == "ЦенаСоСкидкой(Цена: Число, Скидка: Число = 0): Число"
    assert found["active"] == 1
    first, second = found["parameters"]
    assert found["label"][first["label"][0]:first["label"][1]] == "Цена: Число"
    assert second["documentation"] == "Скидка в процентах."
    assert found["documentation"] == "Цена со скидкой.\n\n**Возвращает:** Цена со скидкой."
    assert lsp_doc.signature_help(_lookup(), "Цены.Другой(", "Касса") is None


# --- the completion ---------------------------------------------------------------------------

_MODULE = (
    "/// Остаток на складе.\n///\n/// @параметр Код - Код товара.\n/// @\n@НаСервере\n"
    "метод Остаток(Код: Строка, Склад: Строка): Число\n    возврат 0\n;\n"
)


@pytest.mark.needs_data
def test_the_tag_words_in_the_language_of_the_module():
    items, exclusive = lsp_doc.doc_completions(_MODULE, "Склады.xbsl", 3, len("/// @"))
    assert exclusive
    assert [item["label"] for item in items] == ["@параметр", "@возвращает", "@выбрасывает", "@см"]
    assert items[0]["range"] == (4, 5) and items[0]["new_text"] == "@параметр "
    english = "/// Stock.\n/// @\nmethod Stock(Code: String): Number\n    return 0\n;\n"
    items, _exclusive = lsp_doc.doc_completions(english, "Stores.xbsl", 1, len("/// @"))
    assert [item["label"] for item in items] == ["@parameter", "@returns", "@throws", "@see"]


@pytest.mark.needs_data
def test_above_a_field_only_a_reference_tag_is_offered():
    text = "/// Лимит.\n/// @\nконст ЛИМИТ = 10\n"
    items, _exclusive = lsp_doc.doc_completions(text, "Склады.xbsl", 1, len("/// @"))
    assert [item["label"] for item in items] == ["@см"]


@pytest.mark.needs_data
def test_the_parameters_the_block_has_not_described_yet():
    text = _MODULE.replace("/// @\n", "/// @параметр \n")
    items, exclusive = lsp_doc.doc_completions(text, "Склады.xbsl", 3, len("/// @параметр "))
    assert exclusive and [item["label"] for item in items] == ["Склад"]
    assert items[0]["new_text"] == "Склад - " and items[0]["detail"] == "Строка"


@pytest.mark.needs_data
def test_the_template_on_the_only_line_of_a_block_and_on_an_empty_line():
    text = "///\nметод Остаток(Код: Строка): Число\n    возврат 0\n;\n"
    items, exclusive = lsp_doc.doc_completions(text, "Склады.xbsl", 0, 3)
    assert exclusive and items[0]["snippet"]
    assert items[0]["new_text"] == (
        "/// ${1:Документирующий комментарий}\n///\n/// @параметр Код - ${2:Параметр}\n"
        "///\n/// @возвращает ${3:Результат}"
    )
    empty = "\nметод Сбросить(Режим: Число): ничто\n;\n"
    items, exclusive = lsp_doc.doc_completions(empty, "Склады.xbsl", 0, 0)
    assert not exclusive and len(items) == 1
    assert "@возвращает" not in items[0]["new_text"]


@pytest.mark.needs_data
def test_nothing_outside_a_documentation_comment():
    assert lsp_doc.doc_completions("пер А = 1 // обычный\n", "Склады.xbsl", 0, 12) == ([], False)
    assert lsp_doc.doc_completions("пер А = 1\n", "Склады.xbsl", 0, 5) == ([], False)
    # A line of a block that is being written gets no items of the code.
    assert lsp_doc.doc_completions(_MODULE, "Склады.xbsl", 0, 8) == ([], True)


# --- the server -------------------------------------------------------------------------------

_PRICES = """/// Цена со скидкой.
///
/// @параметр Цена - Цена без скидки.
/// @параметр Скидка - Скидка в процентах.
///
/// @возвращает Цена со скидкой.
метод ЦенаСоСкидкой(Цена: Число, Скидка: Число): Число
    возврат Цена * (100 - Скидка) / 100
;

метод Касса(): Число
    возврат ЦенаСоСкидкой(100, 5)
;
"""


def _server_on(tmp_path):
    pytest.importorskip("pygls", reason="LSP-методы проверяются при установленном extra [lsp]")
    from pygls import uris
    from pygls.workspace import Workspace

    server = lsp._make_server()
    server.lsp._workspace = Workspace(uris.from_fs_path(str(tmp_path)))
    fm = getattr(server.lsp, "fm", None) or getattr(server.lsp, "_features", None)
    return getattr(fm, "features", fm)


@pytest.mark.needs_data
def test_the_server_answers_the_hover_the_signature_and_the_completion(tmp_path):
    from pygls import uris

    target = tmp_path / "Цены.xbsl"
    target.write_bytes(_PRICES.encode("utf-8"))
    features = _server_on(tmp_path)
    root, lookup = lsp.STATE.root, lsp.STATE.lookup
    lsp.STATE.root, lsp.STATE.lookup = tmp_path, None
    try:
        document = SimpleNamespace(uri=uris.from_fs_path(str(target)))

        def at(line, character, **more):
            return SimpleNamespace(text_document=document,
                                   position=SimpleNamespace(line=line, character=character),
                                   **more)

        call = _PRICES.split("\n")[11]
        hover = features[lsp.lsp.TEXT_DOCUMENT_HOVER](at(11, call.index("ЦенаСоСкидкой") + 2))
        assert "**Параметры:**" in hover.contents.value
        signature = features[lsp.lsp.TEXT_DOCUMENT_SIGNATURE_HELP](at(11, call.index("5")))
        assert signature.active_parameter == 1
        assert signature.signatures[0].parameters[1].documentation.value == "Скидка в процентах."
        completion = features[lsp.lsp.TEXT_DOCUMENT_COMPLETION](
            at(2, len("/// @"), context=SimpleNamespace(trigger_character="@")))
        assert [item.label for item in completion.items][:2] == ["@параметр", "@возвращает"]
        # "@" typed in the code asks for nothing.
        silent = features[lsp.lsp.TEXT_DOCUMENT_COMPLETION](
            at(10, 0, context=SimpleNamespace(trigger_character="@")))
        assert silent is None
    finally:
        lsp.STATE.root, lsp.STATE.lookup = root, lookup
