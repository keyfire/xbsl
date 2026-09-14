"""The translation dictionary is not a use of anything in the "never used" rules.

A dictionary names every method and every element it translates, in its keys, its comments and
often its values - a phrase keeps a qualified name verbatim. A run over the folder that holds the
project and its dictionary (the way a repository is linted in CI) used to count those words as
mentions, and the rules fell silent there while a run over the project alone reported the same
dead code. Each case below puts a dictionary naming the dead thing next to the project and expects
the finding a run without the dictionary gives.
"""

import re

import pytest

from xbsl import engine
from xbsl.cli import discover

pytestmark = pytest.mark.needs_data

UNUSED_METHOD = "code/unused-method"
UNUSED_COMPONENT = "yaml/unused-component"
CLIENT_UNUSED = "code/client-available-unused"

_MODULE_YAML = "ВидЭлемента: ОбщийМодуль\nИмя: Склады\nОкружение: Сервер\n"
_DEAD_METHOD = "@НаСервере\nметод ПересчитатьОстатки()\n    возврат\n;\n"
#: The shape of a real dictionary part: the name as a key, in a comment and inside a phrase.
_DICTIONARY = (
    "version: 1\nlanguage: en\n\n"
    "# ПересчитатьОстатки переводится по месту\n"
    "tokens:\n    Склады: Warehouses\n    ПересчитатьОстатки: RecalculateStock\n"
    "phrases:\n    'вызывает ПересчитатьОстатки из Склады': 'calls ПересчитатьОстатки from Склады'\n"
)


def _run(folder, rule_id: str, files: dict[str, str]) -> list:
    for name, content in files.items():
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    diags = engine.run(discover([str(folder)]), select={rule_id})
    return [d for d in diags if d.rule_id == rule_id]


def _names(diags) -> set[str]:
    return {m.group(1) for d in diags for m in [re.search(r"'([^']+)'", d.message)] if m}


# --- code/unused-method --------------------------------------------------------------------

def test_a_dictionary_folder_does_not_keep_a_dead_method_alive(tmp_path):
    hits = _run(tmp_path, UNUSED_METHOD, {
        "site/Склады.yaml": _MODULE_YAML, "site/Склады.xbsl": _DEAD_METHOD,
        "xbsl-translation/020-tokens.yaml": _DICTIONARY,
    })
    assert _names(hits) == {"ПересчитатьОстатки"}
    assert hits[0].path.endswith("Склады.xbsl")


def test_a_single_file_dictionary_does_not_either(tmp_path):
    hits = _run(tmp_path, UNUSED_METHOD, {
        "site/Склады.yaml": _MODULE_YAML, "site/Склады.xbsl": _DEAD_METHOD,
        "xbsl-translation.yaml": _DICTIONARY,
    })
    assert _names(hits) == {"ПересчитатьОстатки"}


def test_the_run_with_the_dictionary_agrees_with_the_run_over_the_project(tmp_path):
    files = {"site/Склады.yaml": _MODULE_YAML, "site/Склады.xbsl": _DEAD_METHOD,
             "xbsl-translation/020-tokens.yaml": _DICTIONARY}
    both = _run(tmp_path, UNUSED_METHOD, files)
    project = [d for d in engine.run(discover([str(tmp_path / "site")]), select={UNUSED_METHOD})
               if d.rule_id == UNUSED_METHOD]
    assert _names(both) == _names(project) == {"ПересчитатьОстатки"}


def test_a_real_call_next_to_the_dictionary_still_counts(tmp_path):
    hits = _run(tmp_path, UNUSED_METHOD, {
        "site/Склады.yaml": _MODULE_YAML, "site/Склады.xbsl": _DEAD_METHOD,
        "site/Отчёт.xbsl": "метод Собрать()\n    Склады.ПересчитатьОстатки()\n;\n",
        "xbsl-translation/020-tokens.yaml": _DICTIONARY,
    })
    assert "ПересчитатьОстатки" not in _names(hits)


# --- yaml/unused-component -----------------------------------------------------------------

_PROJECT = "Поставщик: acme\nИмя: demo\nВерсия: 1.0.0\n"


def test_a_name_kept_in_a_dictionary_phrase_does_not_place_a_component(tmp_path):
    """A phrase of the dictionary may keep a component name verbatim in its English value, and
    that value is not markup."""
    dictionary = (
        "version: 1\nlanguage: en\n\nphrases:\n"
        "    'открывается из КарточкаПартии.': 'opened from КарточкаПартии.'\n"
    )
    hits = _run(tmp_path, UNUSED_COMPONENT, {
        "site/Проект.yaml": _PROJECT,
        "site/КарточкаПартии.yaml": "ВидЭлемента: КомпонентИнтерфейса\nИмя: КарточкаПартии\n",
        "xbsl-translation/030-phrases.yaml": dictionary,
    })
    assert "КарточкаПартии" in _names(hits)


def test_an_english_dictionary_value_does_not_place_an_english_component(tmp_path):
    dictionary = "version: 1\nlanguage: en\n\ntokens:\n    КарточкаПартии: BatchCard\n"
    hits = _run(tmp_path, UNUSED_COMPONENT, {
        "site/Project.yaml": "Vendor: acme\nName: demo\nVersion: 1.0.0\n",
        "site/BatchCard.yaml": "ElementKind: InterfaceComponent\nName: BatchCard\n",
        "xbsl-translation/020-tokens.yaml": dictionary,
    })
    assert "BatchCard" in _names(hits)


# --- code/client-available-unused: the dictionary never counted ----------------------------

def test_client_available_unused_is_not_silenced_by_the_dictionary(tmp_path):
    hits = _run(tmp_path, CLIENT_UNUSED, {
        "site/Склады.yaml": _MODULE_YAML,
        "site/Склады.xbsl": "@НаСервере @ДоступноСКлиента\nметод ПересчитатьОстатки()\n"
                            "    возврат\n;\n",
        "xbsl-translation/020-tokens.yaml": _DICTIONARY,
    })
    assert _names(hits) == {"ПересчитатьОстатки"}
