from pathlib import Path

from xbsl.translation import dictionary


def test_terms_section_is_loaded(tmp_path: Path):
    (tmp_path / "terms.yaml").write_text(
        "terms:\n"
        "    Программа: Program\n"
        "    Абонент: Subscriber\n",
        encoding="utf-8",
    )
    loaded = dictionary.load(tmp_path)
    assert loaded.terms == {"Программа": "Program", "Абонент": "Subscriber"}


def test_a_dictionary_without_terms_has_an_empty_mapping(tmp_path: Path):
    (tmp_path / "names.yaml").write_text(
        "tokens:\n    АдресСайта: SiteAddress\n", encoding="utf-8")
    assert dictionary.load(tmp_path).terms == {}


def test_terms_do_not_leak_into_the_token_plan(tmp_path: Path):
    (tmp_path / "both.yaml").write_text(
        "terms:\n    Программа: Program\n"
        "tokens:\n    АдресСайта: SiteAddress\n",
        encoding="utf-8",
    )
    loaded = dictionary.load(tmp_path)
    assert "Программа" not in loaded.tokens
    assert loaded.terms == {"Программа": "Program"}
