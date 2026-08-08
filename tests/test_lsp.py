"""LSP server helpers: the word under the cursor, parameter parsing, the hover cards."""

import pytest

from xbsl import lsp


def test_word_at():
    line = "знч Список = новый Массив()"
    assert lsp._word_at(line, 0) == "знч"
    assert lsp._word_at(line, 6) == "Список"      # middle of the word
    assert lsp._word_at(line, 20) == "Массив"
    assert lsp._word_at(line, 10) == "Список"      # trailing edge of the word (cursor at its end)
    assert lsp._word_at(line, 11) == ""            # on the '=' operator


def test_word_at_edges():
    assert lsp._word_at("", 0) == ""
    assert lsp._word_at("Массив", 100) == "Массив"  # cursor past the end of the line
    assert lsp._word_at("A.Поле", 2) == "Поле"      # a dot is a word boundary
    assert lsp._word_at("Тип_1", 0) == "Тип_1"       # underscore and digit are part of the name


def test_param_dict_and_object():
    assert lsp._param({"query": "массив"}, "query") == "массив"
    assert lsp._param({"query": "x"}, "limit", 20) == 20
    assert lsp._param(None, "query", "def") == "def"

    class P:
        query = "z"

    assert lsp._param(P(), "query") == "z"
    assert lsp._param(P(), "missing", 5) == 5


def test_doc_key_meets_both_uri_spellings(tmp_path):
    """The editor sends file:///d%3A/..., the server builds file:///d:/... - the key must match.

    While uri strings were compared directly, project findings of an open file were getting
    lost: the key they were stored under could not be found by the key from the editor.
    """
    import os
    import re
    from pathlib import Path

    import pytest

    uris = pytest.importorskip("pygls.uris")
    f = tmp_path / "М.yaml"
    f.write_text("ВидЭлемента: Справочник\n", encoding="utf-8")

    серверный = uris.from_fs_path(str(f))
    # exactly the way the editor's spelling differs on Windows
    редакторский = re.sub(r"^file:///([A-Za-z]):", r"file:///\1%3A", серверный)
    if os.name == "nt":
        assert серверный != редакторский  # otherwise the test checks nothing

    ключ = lambda u: lsp._doc_key(Path(uris.to_fs_path(u)), u)
    assert ключ(серверный) == ключ(редакторский)


def test_doc_key_without_path_falls_back_to_uri():
    assert lsp._doc_key(None, "untitled:Untitled-1") == "untitled:Untitled-1"


def test_resolve_templates_path(tmp_path):
    """Without --templates the server falls back to the panel's file at the workspace
    root: what the panel saves, the next Ctrl+Space must see."""
    from pathlib import Path

    from xbsl.templates import DEFAULT_FILE

    assert lsp._resolve_templates_path(None, tmp_path) == tmp_path / DEFAULT_FILE
    assert lsp._resolve_templates_path(None, None) is None
    assert lsp._resolve_templates_path("own.json", tmp_path) == tmp_path / "own.json"
    absolute = str(tmp_path / "t.json")
    assert lsp._resolve_templates_path(absolute, tmp_path) == Path(absolute)


# --- completion follows the project's own language ------------------------------------------


def _project(tmp_path, development_language):
    (tmp_path / "Проект.yaml").write_text(
        "ВидПроекта: Приложение\nИмя: Проба\nПоставщик: acme\n"
        f"ЯзыкРазработки: {development_language}\n",
        encoding="utf-8",
    )
    lsp._project_language.cache_clear()
    return str(tmp_path)


def test_project_language_is_read_from_the_project_file(tmp_path):
    assert lsp._project_language(_project(tmp_path, "Русский")) == "ru"


def test_project_language_english(tmp_path):
    assert lsp._project_language(_project(tmp_path, "English")) == "en"


def test_project_language_defaults_to_russian(tmp_path):
    # the platform standard asks for Russian, so an unreadable project is treated as such
    lsp._project_language.cache_clear()
    assert lsp._project_language(str(tmp_path)) == "ru"
    assert lsp._project_language(None) == "ru"


def test_own_language_names_are_offered_first():
    russian = {"kind": "member", "label": "Ссылка"}
    english = {"kind": "member", "label": "Reference"}
    assert lsp._sort_text(russian, "ru") < lsp._sort_text(english, "ru")
    assert lsp._sort_text(english, "en") < lsp._sort_text(russian, "en")


def test_templates_stay_ahead_of_every_name():
    template = {"kind": "snippet", "label": "если"}
    name = {"kind": "member", "label": "Ссылка"}
    assert lsp._sort_text(template, "ru") < lsp._sort_text(name, "ru")


# --- hover over platform members (the server needs the dataset and pygls) ---------------

def _hover_text(tmp_path, code: str, line: int, character: int):
    """Hover text the server answers for a position in a file on disk."""
    pytest.importorskip("pygls", reason="LSP-методы проверяются при установленном extra [lsp]")
    from types import SimpleNamespace

    from pygls import uris
    from pygls.workspace import Workspace

    path = tmp_path / "Модуль.xbsl"
    path.write_text(code, encoding="utf-8")
    server = lsp._make_server()
    # A bare server has no workspace until the client initializes it; the hover reads the
    # document through it, and an unopened file is read from disk.
    server.lsp._workspace = Workspace(uris.from_fs_path(str(tmp_path)))
    fm = getattr(server.lsp, "fm", None) or getattr(server.lsp, "_features", None)
    features = getattr(fm, "features", fm)
    lsp.STATE.lookup = lsp.IndexLookup({})
    params = SimpleNamespace(
        text_document=SimpleNamespace(uri=uris.from_fs_path(str(path))),
        position=SimpleNamespace(line=line, character=character),
    )
    got = features[lsp.lsp.TEXT_DOCUMENT_HOVER](params)
    return got.contents.value if got else None


CODE = "\n".join([
    "@НаСервере",
    "метод Проба()",
    "    знч Клиент = новый КлиентHttp()",
    "    знч Ответ = Клиент.ЗапросPost(\"/x\").Выполнить()",
    "    возврат Ответ.КодСтатуса",
    ";",
    "",
])


@pytest.mark.needs_data
def test_hover_of_a_platform_method(tmp_path):
    # `Клиент.ЗапросPost` - the owner comes from the variable's inferred type, the card from
    # the dataset: without it the navigation core (project index only) answered nothing.
    # The signature comes from the dataset too - what to pass, not only what comes back.
    text = _hover_text(tmp_path, CODE, 3, 24)
    assert text is not None and "метод КлиентHttp.ЗапросPost(Url: Url|Строка): ЗапросHttp" in text


@pytest.mark.needs_data
def test_hover_of_a_platform_property(tmp_path):
    text = _hover_text(tmp_path, CODE, 4, 20)
    assert text is not None and "свойство ОтветHttp.КодСтатуса: Число" in text


GLOBALS_CODE = "\n".join([
    "@НаКлиенте",
    "метод Проба()",
    "    Сообщить(\"привет\")",
    "    знч Клиент = новый КлиентHttp()",
    "    знч Ответ = Клиент.Неизвестное",
    ";",
    "",
])


@pytest.mark.needs_data
def test_hover_of_a_global_function(tmp_path):
    # `Сообщить` lives in the GLOBAL catalogue, not inside a type, so the member branch -
    # which needs a receiver - never saw it and the card was empty.
    text = _hover_text(tmp_path, GLOBALS_CODE, 2, 6)
    assert text is not None and "глобальная функция Сообщить()" in text
    assert "доступно: Клиент" in text  # the table the global-unavailable rule is judged by


@pytest.mark.needs_data
def test_hover_of_a_global_type(tmp_path):
    text = _hover_text(tmp_path, GLOBALS_CODE, 3, 26)
    assert text is not None and "тип платформы КлиентHttp" in text


@pytest.mark.needs_data
def test_an_unknown_member_is_not_answered_as_a_global(tmp_path):
    """Negative control: a word AFTER a dot is a member, whatever the global catalogue holds."""
    assert _hover_text(tmp_path, GLOBALS_CODE, 4, 26) is None


# --- navigation before the first background pass ----------------------------------------

EVENT_YAML = "\n".join([
    "ВидЭлемента: ГлобальноеКлиентскоеСобытие",
    "Имя: ЗадачаЗакрыта",
    "ОбластьВидимости: ВПроекте",
    "",
])

EVENT_USE = "\n".join([
    "@НаКлиенте",
    "метод Проба()",
    "    ЗадачаЗакрыта.Оповестить()",
    ";",
    "",
])


def _project_with_event(tmp_path):
    (tmp_path / "ЗадачаЗакрыта.yaml").write_text(EVENT_YAML, encoding="utf-8")
    (tmp_path / "КарточкаЗадачи.xbsl").write_text(EVENT_USE, encoding="utf-8")
    return tmp_path / "ЗадачаЗакрыта.yaml"


def _server_on(tmp_path):
    """A server whose workspace is tmp_path and whose index has NOT been built yet."""
    pytest.importorskip("pygls", reason="LSP-методы проверяются при установленном extra [lsp]")
    from pygls import uris
    from pygls.workspace import Workspace

    server = lsp._make_server()
    server.lsp._workspace = Workspace(uris.from_fs_path(str(tmp_path)))
    fm = getattr(server.lsp, "fm", None) or getattr(server.lsp, "_features", None)
    return getattr(fm, "features", fm)


@pytest.mark.needs_data  # the index keeps an object only when its element kind is known
def test_references_are_answered_before_the_first_project_pass(tmp_path):
    """A find-usages right after startup must not answer "nothing found".

    The index used to be built at the END of the project lint, so until that pass finished
    navigation answered None - the editor shows that exactly like "there are no usages", and
    the feature reads as missing (the report was about a global client event).
    """
    from types import SimpleNamespace

    from pygls import uris

    target = _project_with_event(tmp_path)
    features = _server_on(tmp_path)
    root, lookup = lsp.STATE.root, lsp.STATE.lookup
    lsp.STATE.root, lsp.STATE.lookup = tmp_path, None  # the background pass has not run yet
    try:
        params = SimpleNamespace(
            text_document=SimpleNamespace(uri=uris.from_fs_path(str(target))),
            position=SimpleNamespace(line=1, character=8),  # the name on the `Имя:` line
            context=SimpleNamespace(include_declaration=False),
        )
        got = features[lsp.lsp.TEXT_DOCUMENT_REFERENCES](params)
        assert got is not None, "no usages, though the index can be built on demand"
        assert [u.uri for u in got] == [uris.from_fs_path(str(tmp_path / "КарточкаЗадачи.xbsl"))]
        assert got[0].range.start.line == 2
    finally:
        lsp.STATE.root, lsp.STATE.lookup = root, lookup


@pytest.mark.needs_data
def test_definition_is_answered_before_the_first_project_pass(tmp_path):
    """The same for go-to-definition: the usage in the module points at the yaml."""
    from types import SimpleNamespace

    from pygls import uris

    _project_with_event(tmp_path)
    features = _server_on(tmp_path)
    root, lookup = lsp.STATE.root, lsp.STATE.lookup
    lsp.STATE.root, lsp.STATE.lookup = tmp_path, None
    try:
        params = SimpleNamespace(
            text_document=SimpleNamespace(uri=uris.from_fs_path(str(tmp_path / "КарточкаЗадачи.xbsl"))),
            position=SimpleNamespace(line=2, character=8),
        )
        got = features[lsp.lsp.TEXT_DOCUMENT_DEFINITION](params)
        assert got is not None
        assert got.uri == uris.from_fs_path(str(tmp_path / "ЗадачаЗакрыта.yaml"))
    finally:
        lsp.STATE.root, lsp.STATE.lookup = root, lookup
