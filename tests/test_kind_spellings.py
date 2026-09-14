"""The kind spellings the platform's serializer writes into `ElementKind:` of an English project.

Three places carry the table: the distribution's own (`terms.kinds_table`, in a dataset
generated with 0.54.1 or later), the engine constant `metamodel._KNOWN_KIND_SPELLINGS` for a
dataset without that section or no dataset at all, and the extension's
`SERIALIZER_KIND_SPELLINGS`, which has no dataset to lean on. The constant once lost one pair,
`SoapServiceClient`, while the other two carried it: an English SOAP service client then kept
its English kind wherever the constant was the only source - the project overview listed it
apart from its Russian twin and a filter by the kind missed it.
"""

import re
from pathlib import Path

import pytest

from xbsl import engine  # noqa: F401 - loads the rules before scaffold (import order)
from xbsl import metamodel, scaffold, terms
from xbsl.rules.yaml_schema import object_kind
from xbsl.translation import platform_map

EXTENSION_TABLE = (
    Path(__file__).resolve().parents[1] / "editors" / "vscode" / "src" / "metadataCore.ts"
)


def _extension_spellings() -> dict[str, str]:
    """{Russian kind: English spelling} as the extension's table lists them."""
    text = EXTENSION_TABLE.read_text(encoding="utf-8")
    head, found, tail = text.partition("export const SERIALIZER_KIND_SPELLINGS")
    assert found, "the extension no longer declares SERIALIZER_KIND_SPELLINGS"
    block = tail.split("]);", 1)[0]
    return {russian: english for english, russian in re.findall(r'\["(\w+)", "(\w+)"\]', block)}


@pytest.fixture
def constant_only(monkeypatch):
    """The engine as it runs on a dataset generated before the serializer table joined.

    Such a dataset has no `kinds` section, and its metamodel was built from a hand-written
    list of kinds that never named the SOAP service client - so neither source answers for
    it and the constant is the only one left. Without any dataset the state is the same.
    """
    monkeypatch.setattr(terms, "kinds_table", dict)
    monkeypatch.setattr(metamodel, "kinds", tuple)
    metamodel._english_kinds.cache_clear()
    yield
    metamodel._english_kinds.cache_clear()


def test_engine_constant_matches_the_extension_table():
    extension = _extension_spellings()
    assert len(extension) >= 40, "the extension table was not read"
    assert metamodel._KNOWN_KIND_SPELLINGS == extension


@pytest.mark.needs_data
def test_engine_constant_carries_every_pair_of_the_dataset_table():
    table = terms.kinds_table()
    if not table:
        pytest.skip("the dataset was extracted without the kind table")
    missing = {ru: en for ru, en in table.items() if metamodel._KNOWN_KIND_SPELLINGS.get(ru) != en}
    assert not missing, f"serializer pairs the constant does not carry: {missing}"


def test_soap_client_kind_resolves_from_the_constant(constant_only):
    assert metamodel.canonical_kind("SoapServiceClient") == "КлиентSoapСервиса"
    assert metamodel.canonical_kind("SoapService") == "SoapСервис"
    assert object_kind({"ElementKind": "SoapServiceClient"}) == "КлиентSoapСервиса"
    # the way back: translating a Russian project writes the serializer's spelling
    assert platform_map.kind_english("КлиентSoapСервиса") == "SoapServiceClient"


def _english_project(root: Path) -> None:
    (root / "Project.yaml").write_text(
        "Id: 6f0b6a44-0000-4000-8000-000000000301\nVendor: Acme\nName: Rates\nVersion: 1.0.0\n",
        encoding="utf-8",
    )
    main = root / "Main"
    main.mkdir()
    (main / "Subsystem.yaml").write_text("Name: Main\n", encoding="utf-8")
    (main / "CurrencyRates.yaml").write_text(
        "ElementKind: SoapServiceClient\n"
        "Id: 6f0b6a44-0000-4000-8000-000000000302\n"
        "Name: CurrencyRates\n",
        encoding="utf-8",
    )
    (main / "CurrencyRates.Wsdl.1.wsdl").write_text("<definitions/>\n", encoding="utf-8")
    (main / "Orders.yaml").write_text(
        "ElementKind: SoapService\n"
        "Id: 6f0b6a44-0000-4000-8000-000000000303\n"
        "Name: Orders\n",
        encoding="utf-8",
    )


@pytest.mark.needs_data
def test_project_overview_names_the_english_soap_client_by_its_kind(tmp_path, constant_only):
    _english_project(tmp_path)
    info = scaffold.project_info(tmp_path)
    assert info["object_counts"] == {"SoapСервис": 1, "КлиентSoapСервиса": 1}
    listed = scaffold.project_info(tmp_path, kind="КлиентSoapСервиса")["objects"]
    assert [(o["name"], o["kind"]) for o in listed] == [("CurrencyRates", "КлиентSoapСервиса")]
