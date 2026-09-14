"""Whole-project constant usage, including translation-only mentions."""

import pytest

from xbsl import engine, i18n
from xbsl.cli import discover

pytestmark = pytest.mark.needs_data
RULE = "code/unused-constant"


def _run(folder, files):
    for name, text in files.items():
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return [d for d in engine.run(discover([str(folder)]), select={RULE}) if d.rule_id == RULE]


@pytest.mark.parametrize("dictionary", ["xbsl-translation/010.yaml", "xbsl-translation.yaml"])
def test_dictionary_does_not_keep_a_constant_alive(tmp_path, dictionary):
    files = {
        "app/Settings.xbsl": "конст ВСЕ_СТРАНИЦЫ = 1\n",
        dictionary: "version: 1\nlanguage: en\n# ВСЕ_СТРАНИЦЫ\ntokens:\n"
                    "    ВСЕ_СТРАНИЦЫ: ALL_PAGES\nphrases:\n"
                    "    '{{ВСЕ_СТРАНИЦЫ}}': '{{ВСЕ_СТРАНИЦЫ}}'\n",
    }
    hits = _run(tmp_path, files)
    assert len(hits) == 1
    assert (hits[0].line, hits[0].col) == (1, 7)
    without_dictionary = engine.run(discover([str(tmp_path / "app")]), select={RULE})
    assert [(d.rule_id, d.line, d.col, d.message) for d in hits] == [
        (d.rule_id, d.line, d.col, d.message) for d in without_dictionary
    ]


@pytest.mark.parametrize("name, text", [
    ("Caller.xbsl", "метод Взять(): Число\n    возврат Settings.ВСЕ_СТРАНИЦЫ\n;\n"),
    ("Form.yaml", "Значение: =Settings.ВСЕ_СТРАНИЦЫ\n"),
    ("Bridge.xbsl", 'конст ШАБЛОН = "{{ВСЕ_СТРАНИЦЫ}}"\n'),
    ("Comment.xbsl", "// ВСЕ_СТРАНИЦЫ used by the bridge\n"),
])
def test_real_mentions_still_count(tmp_path, name, text):
    hits = _run(tmp_path, {"Settings.xbsl": "конст ВСЕ_СТРАНИЦЫ = 1\n", name: text})
    assert not any("'ВСЕ_СТРАНИЦЫ'" in d.message for d in hits)


def test_same_module_read_and_initializer_read(tmp_path):
    hits = _run(tmp_path, {"Settings.xbsl": "конст БАЗА = 1\nконст ИТОГ = БАЗА + 1\n"
                         "метод Взять(): Число\n    возврат ИТОГ\n;\n"})
    assert hits == []


@pytest.mark.parametrize("annotation", ["@Глобально", "@СвояАннотация", "@Устарело"])
def test_external_surface_is_not_reported(tmp_path, annotation):
    assert _run(tmp_path, {"Settings.xbsl": f"{annotation}\nконст ВСЕ_СТРАНИЦЫ = 1\n"}) == []


def test_internal_annotation_keeps_correct_position(tmp_path):
    hits = _run(tmp_path, {"Settings.xbsl": "@ВПроекте\nконст ВСЕ_СТРАНИЦЫ = 1\n"})
    assert len(hits) == 1
    assert (hits[0].line, hits[0].col) == (2, 7)


def test_english_constant_and_message(tmp_path):
    i18n.set_lang("en")
    hits = _run(tmp_path, {"Settings.xbsl": "const ALL_PAGES = 1\n"})
    assert len(hits) == 1
    assert hits[0].message.startswith("Constant 'ALL_PAGES'")


def test_locals_and_structure_fields_are_not_module_constants(tmp_path):
    hits = _run(tmp_path, {"Settings.xbsl": "структура Настройки\n    знч Размер: Число\n;\n"
                         "метод Взять()\n    знч Локальная = 1\n;\n"})
    assert hits == []


def test_rule_requires_explicit_selection():
    registered = next(r for r in engine.RULES if r.id == RULE)
    assert registered.scope == "project"
    assert not registered.enabled_by_default
