"""LSP server helpers: the word under the cursor, parameter parsing, the hover cards."""

import argparse

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


# --- a standalone query file over the wire ---------------------------------------------------

_QUERY_CATALOG = """\
ВидЭлемента: Справочник
Ид: 3f1c9a80-5b26-4d7e-9a13-6c2b8e4d0f57
Имя: Задачи
Реквизиты:
    -
        Ид: 8a2d6b41-0c93-47e5-bf18-25d7c3a90e64
        Имя: Срок
        Тип: Дата
"""

_QUERY_FILE = """\
ВЫБРАТЬ
    З.Ссылка КАК Ссылка,
    З.Срок КАК Срок
ИЗ
    Задачи КАК З
"""


@pytest.mark.needs_data
def test_completion_in_a_query_file_over_the_wire(tmp_path):
    """The paired file of a virtual table is all query: the dot after a table alias must
    answer with the fields of that table."""
    from types import SimpleNamespace

    from pygls import uris

    (tmp_path / "Задачи.yaml").write_text(_QUERY_CATALOG, encoding="utf-8")
    target = tmp_path / "ЗадачиТаблица.xbql"
    target.write_text(_QUERY_FILE, encoding="utf-8")
    features = _server_on(tmp_path)
    root, lookup = lsp.STATE.root, lsp.STATE.lookup
    lsp.STATE.root, lsp.STATE.lookup = tmp_path, None
    try:
        uri = uris.from_fs_path(str(target))
        params = SimpleNamespace(
            text_document=SimpleNamespace(uri=uri),
            position=SimpleNamespace(line=2, character=6),  # right after `З.` of `З.Срок`
        )
        got = features[lsp.lsp.TEXT_DOCUMENT_COMPLETION](params)
        labels = [i.label for i in (got.items if got else [])]
        assert "Срок" in labels, "the attribute of the table the alias names"
        assert "Наименование" in labels, "a standard field of the kind"
    finally:
        lsp.STATE.root, lsp.STATE.lookup = root, lookup


def test_project_sources_match_what_the_cli_collects(tmp_path):
    """The editor's whole-project pass reads the same set of files as the CLI.

    The query file of a virtual table used to be missing from the editor's set alone, so one
    and the same finding was visible or not depending on who asked.
    """
    from xbsl.cli import discover

    (tmp_path / "Товары.yaml").write_text("ВидЭлемента: Справочник\nИмя: Товары\n", encoding="utf-8")
    (tmp_path / "Товары.xbsl").write_text("метод Ф()\n;\n", encoding="utf-8")
    (tmp_path / "ТоварыТаблица.xbql").write_text("ВЫБРАТЬ\n    Т.Ссылка\nИЗ\n    Товары КАК Т\n",
                                                 encoding="utf-8")

    got = {p.name for p in lsp.project_sources(tmp_path)}

    assert "ТоварыТаблица.xbql" in got
    assert got == {p.name for p in discover([str(tmp_path)])}


# --- the rule set of the CI job, in the editor ---------------------------------------------------


def _ci_args(**kwargs) -> argparse.Namespace:
    base = {"project_root": None, "as_ci": "", "as_ci_job": None, "baseline": None}
    return argparse.Namespace(**{**base, **kwargs})


def _restore_state():
    """The server state is a module singleton - a test must give it back as it found it."""
    saved = (lsp.STATE.select, lsp.STATE.ignore, lsp.STATE.enable, lsp.STATE.baseline_arg,
             lsp.STATE.ci)

    def undo():
        (lsp.STATE.select, lsp.STATE.ignore,
         lsp.STATE.enable, lsp.STATE.baseline_arg, lsp.STATE.ci) = saved
    return undo


def test_the_editor_judges_by_the_rule_set_of_the_ci_job(tmp_path, monkeypatch, capsys):
    """The panel used to judge by the defaults while the merge request was gated by the job."""
    (tmp_path / ".gitlab-ci.yml").write_text(
        "xbsl-lint:\n  script:\n"
        "    - xbsl src --enable code/unused-method --baseline .xbsllint-baseline\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    undo = _restore_state()
    try:
        lsp.STATE.select = lsp.STATE.ignore = lsp.STATE.enable = None
        lsp.STATE.baseline_arg = None
        lsp._adopt_ci(_ci_args())

        assert lsp.STATE.enable == {"code/unused-method"}
        assert lsp.STATE.baseline_arg == str(tmp_path / ".xbsllint-baseline")
        assert "xbsl-lint" in capsys.readouterr().err  # the server says what it took
    finally:
        undo()


def test_the_settings_own_rules_stay_on_top_of_the_job(tmp_path, monkeypatch):
    """A rule being tried out in the editor is not lost to the pipeline's set."""
    (tmp_path / ".gitlab-ci.yml").write_text(
        "lint:\n  script:\n    - xbsl src --enable code/unused-method\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    undo = _restore_state()
    try:
        lsp.STATE.select = lsp.STATE.ignore = None
        lsp.STATE.enable = {"typography/yo-in-text"}
        lsp.STATE.baseline_arg = None
        lsp._adopt_ci(_ci_args())

        assert lsp.STATE.enable == {"typography/yo-in-text", "code/unused-method"}
    finally:
        undo()


def test_the_named_job_is_the_one_the_editor_takes(tmp_path, monkeypatch):
    """A pipeline that checks a second tree runs the linter twice, by two different sets."""
    (tmp_path / ".gitlab-ci.yml").write_text(
        "xbsl-lint:\n  script:\n    - xbsl src --baseline .xbsllint-baseline\n"
        "English to S3:\n  script:\n"
        "    - xbsl build/en --no-baseline --ignore code/undefined-name\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    undo = _restore_state()
    try:
        lsp.STATE.select = lsp.STATE.ignore = lsp.STATE.enable = None
        lsp.STATE.baseline_arg = None
        lsp._adopt_ci(_ci_args(as_ci=None, as_ci_job="english"))

        assert lsp.STATE.ignore == {"code/undefined-name"}
        # the job trusts nothing frozen - the editor must not mute what the pipeline reports
        assert lsp.STATE.baseline_arg is None
    finally:
        undo()


def test_a_project_without_a_pipeline_keeps_editing_alive(tmp_path, monkeypatch, capsys):
    """The CLI refuses and loses one run; a refusal here would lose the whole session."""
    monkeypatch.chdir(tmp_path)
    undo = _restore_state()
    try:
        lsp.STATE.select = lsp.STATE.ignore = None
        lsp.STATE.enable = {"typography/yo-in-text"}
        lsp.STATE.baseline_arg = "own-baseline"
        lsp._adopt_ci(_ci_args())

        assert lsp.STATE.enable == {"typography/yo-in-text"}  # the settings' set stands
        assert lsp.STATE.baseline_arg == "own-baseline"
        assert ".gitlab-ci.yml" in capsys.readouterr().err  # ...and the reason is said out loud
    finally:
        undo()


def test_the_server_answers_which_job_it_judges_by(tmp_path, monkeypatch, capsys):
    """The editor's only trace of the adoption was a line in the output channel.

    Nobody reads that channel while judging a finding, so the request exists: the status bar
    asks the server what came of `--as-ci` and says it where the verdict is looked at.
    """
    (tmp_path / ".gitlab-ci.yml").write_text("include: ci/lint.yml\n", encoding="utf-8")
    (tmp_path / "ci").mkdir()
    (tmp_path / "ci" / "lint.yml").write_text(
        "xbsl-lint:\n  script:\n    - xbsl src --enable code/unused-method\n"
        "English to S3:\n  script:\n    - xbsl build/en --no-baseline\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    undo = _restore_state()
    try:
        lsp.STATE.select = lsp.STATE.ignore = lsp.STATE.enable = None
        lsp.STATE.baseline_arg = None
        lsp._adopt_ci(_ci_args())
        capsys.readouterr()

        answer = _server_on(tmp_path)["xbsl/ciStatus"](None)

        assert answer["enabled"] and answer["adopted"]
        assert answer["job"] == "xbsl-lint"
        assert answer["file"] == str(tmp_path / ".gitlab-ci.yml")
        assert answer["source"] == str(tmp_path / "ci" / "lint.yml")  # what to open
        assert answer["jobs"] == ["English to S3"]
        assert "xbsl-lint" in answer["line"] and "--as-ci-job" in answer["hint"]
    finally:
        undo()


def test_the_server_says_when_the_job_set_was_not_taken(tmp_path, monkeypatch, capsys):
    """The silent half of the fallback: the panel judges by the settings, and says so."""
    monkeypatch.chdir(tmp_path)
    undo = _restore_state()
    try:
        lsp.STATE.select = lsp.STATE.ignore = lsp.STATE.enable = None
        lsp.STATE.baseline_arg = None
        lsp._adopt_ci(_ci_args())
        capsys.readouterr()

        answer = _server_on(tmp_path)["xbsl/ciStatus"](None)

        assert answer["enabled"] and not answer["adopted"]
        assert ".gitlab-ci.yml" in answer["error"]  # the reason, in the server's own words
    finally:
        undo()


def test_a_server_never_asked_for_the_parity_answers_that_it_is_off(tmp_path):
    """Nothing was requested, nothing is shown - the indicator stays out of the way."""
    undo = _restore_state()
    try:
        lsp.STATE.ci = None

        answer = _server_on(tmp_path)["xbsl/ciStatus"](None)

        assert answer == {"enabled": False, "adopted": False}
    finally:
        undo()


def test_an_explicit_baseline_outranks_the_job(tmp_path, monkeypatch):
    """The editor's own baseline file is the one the exclusion action just wrote."""
    (tmp_path / ".gitlab-ci.yml").write_text(
        "lint:\n  script:\n    - xbsl src --baseline ci-baseline\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    undo = _restore_state()
    try:
        lsp.STATE.select = lsp.STATE.ignore = lsp.STATE.enable = None
        lsp.STATE.baseline_arg = "mine"
        lsp._adopt_ci(_ci_args(baseline="mine"))

        assert lsp.STATE.baseline_arg == "mine"
    finally:
        undo()
