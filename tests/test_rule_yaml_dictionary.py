"""The translation dictionary is not a description of an element (yaml/id-uuid and neighbours).

Data-free by construction: the gate answers before any metamodel lookup on a file that carries
no element kind, so the module runs in a checkout without the platform data.
"""

from xbsl import engine
from xbsl.rules.yaml_schema import is_translation_dictionary

DICTIONARY = """version: 1
language: en

tokens:
    Значок: Icon
    Ид: Id
"""


def _lint(name, content, **kw):
    return engine.run_sources([engine.load_text(name, content)], **kw)


def _ids(diags):
    return [d.rule_id for d in diags]


def test_dictionary_translation_pair_is_not_an_id():
    source = engine.load_text("022-tokens-rest.yaml", DICTIONARY)
    assert is_translation_dictionary(source)
    assert _lint("022-tokens-rest.yaml", DICTIONARY, select={"yaml/id-uuid"}) == []


def test_dictionary_without_language_is_still_a_dictionary():
    content = """version: 1

phrases:
    Ид: Id
"""
    assert is_translation_dictionary(engine.load_text("070-phrases.yaml", content))
    assert _lint("070-phrases.yaml", content, select={"yaml/id-uuid"}) == []


def test_versioned_file_without_dictionary_planes_is_judged():
    content = """version: 1
Ид: nope
"""
    assert not is_translation_dictionary(engine.load_text("Прочее.yaml", content))
    assert _ids(_lint("Прочее.yaml", content, select={"yaml/id-uuid"})) == ["yaml/id-uuid"]


def test_object_description_is_still_judged():
    content = """Ид: nope
Имя: Объект
"""
    assert not is_translation_dictionary(engine.load_text("Объект.yaml", content))
    assert _ids(_lint("Объект.yaml", content, select={"yaml/id-uuid"})) == ["yaml/id-uuid"]


def test_broken_dictionary_is_still_reported_as_invalid_yaml():
    content = """version: 1
language: en

tokens:
  Значок: Icon
   Ид: Id
"""
    assert not is_translation_dictionary(engine.load_text("Битый.yaml", content))
    assert _ids(_lint("Битый.yaml", content, select={"yaml/valid"})) == ["yaml/valid"]
