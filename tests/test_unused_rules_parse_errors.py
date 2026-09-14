"""The "never used" rules keep counting the mentions of a file that does not parse.

Such a rule reports a name that nothing else in the project mentions, so every file it drops
from the count is a false finding waiting for the name it mentioned. A module with a syntax
error still has words - the lexer reads them, the parser is needed only for what the module
declares - and a yaml that does not parse still has its text. The cases below pair the broken
file that mentions the name (silent) with the same broken file without the mention (reported):
without the second half a silent rule would pass for a working one.
"""

import re

import pytest

from xbsl import engine
from xbsl.cli import discover
from xbsl.parser import parse_text

pytestmark = pytest.mark.needs_data

CLIENT_UNUSED = "code/client-available-unused"
UNUSED_METHOD = "code/unused-method"
UNUSED_COMPONENT = "yaml/unused-component"

_SERVER_YAML = "ВидЭлемента: ОбщийМодуль\nИмя: Склады\nОкружение: Сервер\n"
_SERVER_XBSL = (
    "@НаСервере @ДоступноСКлиента\n"
    "метод ОстатокПартии(): Число\n"
    "    возврат 0\n"
    ";\n"
)
_CLIENT_YAML = "ВидЭлемента: ОбщийМодуль\nИмя: Партии\nОкружение: КлиентИСервер\n"
#: A client method calls the server one; below it a method of the module's own, open to the
#: client (that is what makes the rule parse the module), carries an unclosed parenthesis.
_BROKEN_CLIENT_XBSL = (
    "@НаКлиенте\n"
    "метод Показать()\n"
    "    Склады.ОстатокПартии()\n"
    ";\n"
    "\n"
    "@НаСервере @ДоступноСКлиента\n"
    "метод Пересчитать()\n"
    "    пер Сумма = (1 +\n"
    ";\n"
)
_CALL = "    Склады.ОстатокПартии()\n"
_NO_CALL = "    пер Сообщение = \"\"\n"


def _run(folder, rule_id: str, files: dict[str, str]) -> list:
    folder.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (folder / name).write_text(content, encoding="utf-8")
    diags = engine.run(discover([str(folder)]), select={rule_id})
    return [d for d in diags if d.rule_id == rule_id]


def _names(diags) -> set[str]:
    return {m.group(1) for d in diags for m in [re.search(r"'([^']+)'", d.message)] if m}


def test_the_fixture_module_does_not_parse():
    """The guard of the cases below: a module that parses would prove nothing about them."""
    assert parse_text(_BROKEN_CLIENT_XBSL)[1]
    assert parse_text(_BROKEN_CLIENT_XBSL.replace(_CALL, _NO_CALL))[1]


# --- code/client-available-unused ---------------------------------------------------------

def _client_project(client_module: str) -> dict[str, str]:
    return {"Склады.yaml": _SERVER_YAML, "Склады.xbsl": _SERVER_XBSL,
            "Партии.yaml": _CLIENT_YAML, "Партии.xbsl": client_module}


def test_a_call_from_a_module_that_does_not_parse_still_counts(tmp_path):
    hits = _run(tmp_path, CLIENT_UNUSED, _client_project(_BROKEN_CLIENT_XBSL))
    assert "ОстатокПартии" not in _names(hits)


def test_the_same_broken_module_without_the_call_leaves_the_method_reported(tmp_path):
    hits = _run(tmp_path, CLIENT_UNUSED,
                _client_project(_BROKEN_CLIENT_XBSL.replace(_CALL, _NO_CALL)))
    assert _names(hits) == {"ОстатокПартии"}
    assert hits[0].path.endswith("Склады.xbsl") and hits[0].line == 1


def test_the_declarations_of_a_module_that_does_not_parse_are_not_judged(tmp_path):
    """Nothing names the open method of the broken module itself, yet that module did not
    parse: the parse failure is the finding there, and a declaration read out of a broken tree
    could be a wrong one."""
    hits = _run(tmp_path, CLIENT_UNUSED, _client_project(_BROKEN_CLIENT_XBSL))
    assert "Пересчитать" not in _names(hits)


def test_a_call_from_an_english_module_that_does_not_parse_still_counts(tmp_path):
    call = "    Warehouses.BatchBalance()\n"
    client = (
        "@OnClient\nmethod Show()\n" + call + ";\n\n"
        "@OnServer @AvailableFromClient\nmethod Recalculate()\n    var Total = (1 +\n;\n"
    )
    assert parse_text(client)[1]
    files = {
        "Warehouses.yaml": "ElementKind: CommonModule\nName: Warehouses\nEnvironment: Server\n",
        "Warehouses.xbsl": "@OnServer @AvailableFromClient\nmethod BatchBalance(): Number\n"
                           "    return 0\n;\n",
        "Batches.yaml": "ElementKind: CommonModule\nName: Batches\nEnvironment: ClientAndServer\n",
    }
    silent = _run(tmp_path / "call", CLIENT_UNUSED, {**files, "Batches.xbsl": client})
    no_call = client.replace(call, "    var Message = \"\"\n")
    reported = _run(tmp_path / "no-call", CLIENT_UNUSED, {**files, "Batches.xbsl": no_call})
    assert "BatchBalance" not in _names(silent)
    assert _names(reported) == {"BatchBalance"}


# --- code/unused-method: the mentions were text all along ----------------------------------

def test_unused_method_counts_a_call_from_a_module_that_does_not_parse(tmp_path):
    """A guard for the family: this rule counts the words of the text and never parsed."""
    silent = _run(tmp_path / "call", UNUSED_METHOD, _client_project(_BROKEN_CLIENT_XBSL))
    reported = _run(tmp_path / "no-call", UNUSED_METHOD,
                    _client_project(_BROKEN_CLIENT_XBSL.replace(_CALL, _NO_CALL)))
    assert "ОстатокПартии" not in _names(silent)
    assert "ОстатокПартии" in _names(reported)


# --- yaml/unused-component -----------------------------------------------------------------

_PROJECT = "Поставщик: acme\nИмя: demo\nВерсия: 1.0.0\n"
_COMPONENT = "ВидЭлемента: КомпонентИнтерфейса\nИмя: {name}\n"
#: A page placing the card, with a tab in the indentation of a later line - PyYAML refuses it.
_BROKEN_PAGE = (
    "ВидЭлемента: КомпонентИнтерфейса\nИмя: Страница\n"
    "Наследует:\n    Тип: Группа\n    Содержимое:\n        -\n            Тип: Карточка\n"
    "\t    Заголовок: [\n"
)


def _component_project(page: str) -> dict[str, str]:
    return {"Проект.yaml": _PROJECT, "Карточка.yaml": _COMPONENT.format(name="Карточка"),
            "Страница.yaml": page}


def test_the_fixture_yaml_does_not_parse():
    yaml = pytest.importorskip("yaml")
    with pytest.raises(yaml.YAMLError):
        yaml.safe_load(_BROKEN_PAGE)


def test_a_placement_in_a_yaml_that_does_not_parse_still_counts(tmp_path):
    hits = _run(tmp_path, UNUSED_COMPONENT, _component_project(_BROKEN_PAGE))
    assert "Карточка" not in _names(hits)


def test_the_same_broken_yaml_without_the_placement_leaves_the_component_reported(tmp_path):
    page = _BROKEN_PAGE.replace("Тип: Карточка", "Тип: Надпись")
    hits = _run(tmp_path, UNUSED_COMPONENT, _component_project(page))
    assert "Карточка" in _names(hits)
