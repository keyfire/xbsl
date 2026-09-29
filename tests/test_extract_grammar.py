"""The grammar step (xbsl/extract/grammar.py) reads the distribution and writes into the data root alone.

The step used to copy InternalBsl.g and InternalBsl.tokens into a cache next to the package
code, whatever --data-dir said, and the manager passed it no option to move that cache: an
extraction with an external data root still wrote into the package, an installed one included.
The package directory is swapped for an empty one here, so a write into it cannot go unseen.
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

from xbsl import extract
from xbsl.extract import _distro, grammar

# A synthetic grammar in the shape of the real one: a keyword rule with its two spellings
# (escaped the way the generated grammar writes Cyrillic), an operator rule and the token table.
GRAMMAR = (
    "RULE_IF_KW : ('if'|'\\u0435\\u0441\\u043B\\u0438');\n"
    "RULE_IF_KW_UP : ('If'|'\\u0415\\u0441\\u043B\\u0438');\n"
    "RULE_PLUS : '+';\n"
)
TOKENS = "'!='=117\nRULE_IF_KW=5\n"


def _distribution(root: Path, grammar_text: str = GRAMMAR) -> Path:
    """A distribution directory whose server .car carries the language jar with the grammar."""
    jar = io.BytesIO()
    with zipfile.ZipFile(jar, "w") as inner:
        inner.writestr("org/example/parser/antlr/internal/InternalBsl.g", grammar_text)
        inner.writestr("org/example/parser/antlr/internal/InternalBsl.tokens", TOKENS)
    dist = root / "dist"
    dist.mkdir()
    car = dist / "acme-element-server-with-ide-1.2.3-20260731.125205+4-w.car"
    with zipfile.ZipFile(car, "w") as outer:
        outer.writestr("plugins/com.e1c.g5rt.xbsl.language-1.2.3.jar", jar.getvalue())
    return dist


@pytest.fixture()
def package(tmp_path, monkeypatch):
    """An empty stand-in for the package directory: whatever lands in it is a write into the package."""
    fake = tmp_path / "package"
    fake.mkdir()
    monkeypatch.setattr(_distro, "REPO", fake)
    yield fake
    _distro.set_data_root(None)


def _files(root: Path) -> list[str]:
    return sorted(str(p.relative_to(root)) for p in root.rglob("*"))


def _language(data: Path, version: str) -> dict:
    return json.loads((data / version / "language.json").read_text(encoding="utf-8"))


def test_the_step_reads_the_grammar_from_the_distribution_without_writing_into_the_package(
        tmp_path, package):
    dist = _distribution(tmp_path)
    data = tmp_path / "data"

    assert grammar.main(["--dist", str(dist), "--data-dir", str(data)]) == 0

    assert _files(package) == []
    language = _language(data, "1.2.3")
    assert language["keywords"]["IF"]["forms"] == ["if", "если", "If", "Если"]
    assert "+" in language["operators"] and "!=" in language["operators"]


def test_the_manager_leaves_the_package_alone_as_well(tmp_path, package):
    """`xbsl extract` passes the grammar step --dist and --data-dir and nothing else: the step
    must keep to the data root on those two alone."""
    dist = _distribution(tmp_path)
    data = tmp_path / "data"

    assert extract.main(["--dist", str(dist), "--data-dir", str(data), "--only", "grammar"]) == 0

    assert _files(package) == []
    assert _language(data, "1.2.3")["keywords"]["IF"]["forms"][:2] == ["if", "если"]
    index = json.loads((data / "index.json").read_text(encoding="utf-8"))
    assert index["default"] == "1.2.3"


def test_a_grammar_directory_still_works_without_a_distribution(tmp_path, package):
    """The control: --grammar-dir reads the files where they lie, and no distribution is needed."""
    folder = tmp_path / "grammar"
    folder.mkdir()
    (folder / "InternalBsl.g").write_text(GRAMMAR, encoding="utf-8")
    (folder / "InternalBsl.tokens").write_text(TOKENS, encoding="utf-8")
    data = tmp_path / "data"

    code = grammar.main(["--grammar-dir", str(folder), "--element-version", "1.2.3",
                         "--data-dir", str(data)])

    assert code == 0
    assert _files(package) == []
    assert "IF" in _language(data, "1.2.3")["keywords"]


def test_without_a_distribution_or_a_directory_there_is_no_grammar(tmp_path, package):
    """No cached copy stands in for a missing source: the step names the two options instead."""
    with pytest.raises(SystemExit) as raised:
        grammar.main(["--element-version", "1.2.3", "--data-dir", str(tmp_path / "data")])

    assert "--dist" in str(raised.value) and "--grammar-dir" in str(raised.value)
    assert _files(package) == []
