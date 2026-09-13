"""The WSDL descriptions of a SOAP service client travel with it: move, rename, delete.

A SOAP service client (`ВидЭлемента: КлиентSoapСервиса`, `ElementKind: SoapServiceClient` in an
English project) declares no operations of its own: the platform generates them from a WSDL
description kept beside the element as `<Имя>.Wsdl.1.wsdl`, and a description the first one
refers to is `<Имя>.Wsdl.2.wsdl`. The platform finds a description by that file name alone, so a
client moved or renamed without its descriptions fails to apply, and a deleted one leaves them
behind as orphans.

The fixture is the project `Демо::Учет` with the subsystem `Склад`: the client `КлиентКурсовВалют`
with two descriptions, a namesake with a continuation `КлиентКурсовВалютАрхив` with a description
of its own, and a package `Партии`. The first description names the second by its file name -
the documentation tells to replace a reference the platform cannot resolve with the name of the
file loaded into the project - and it is written with a BOM and CRLF line ends, so a test can
compare it byte for byte.
"""

import json
from pathlib import Path

import pytest

from xbsl import cli, scaffold
from xbsl.scaffold import apply_result

CLIENT = "КлиентКурсовВалют"
DESCRIPTIONS = (f"{CLIENT}.Wsdl.1.wsdl", f"{CLIENT}.Wsdl.2.wsdl")
FAMILY = (f"{CLIENT}.yaml", *DESCRIPTIONS)
NAMESAKE_DESCRIPTION = f"{CLIENT}Архив.Wsdl.1.wsdl"

#: The first description: an import of the second one by its file name, and an address and two
#: longer names around the client's one, which a rename must leave as they are. The trailing
#: spaces make a text rule fire should the description ever be linted as a source.
FIRST = (
    '<?xml version="1.0" encoding="UTF-8"?>\r\n'
    '<definitions xmlns="http://schemas.xmlsoap.org/wsdl/" name="Rates">   \r\n'
    f"    <documentation>http://example.com/{CLIENT}?wsdl {CLIENT}Архив.Wsdl.1"
    f" Старый{CLIENT}.Wsdl.1</documentation>\r\n"
    f'    <import namespace="urn:rates:types" location="{CLIENT}.Wsdl.2"/>\r\n'
    "</definitions>\r\n"
)
SECOND = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<definitions xmlns="http://schemas.xmlsoap.org/wsdl/" name="RatesTypes"/>\n'
)
BOM = b"\xef\xbb\xbf"

PROJECT_FILES: dict[str, bytes] = {
    "Проект.yaml": "Поставщик: Демо\nИмя: Учет\nВерсия: 1.0.0\n".encode(),
    "Склад/Подсистема.yaml": "Интерфейс:\n    ВключатьВАвтоИнтерфейс: Ложь\n".encode(),
    f"Склад/{CLIENT}.yaml": (
        "ВидЭлемента: КлиентSoapСервиса\nИд: 6f0b6a44-0000-4000-8000-000000000401\n"
        f"Имя: {CLIENT}\nОбластьВидимости: ВПроекте\n"
        "UrlПоУмолчанию: http://example.com/rates\nВерсияSoap: Soap_1_1\n"
    ).encode(),
    f"Склад/{DESCRIPTIONS[0]}": BOM + FIRST.encode(),
    f"Склад/{DESCRIPTIONS[1]}": SECOND.encode(),
    f"Склад/{CLIENT}Архив.yaml": (
        "ВидЭлемента: КлиентSoapСервиса\nИд: 6f0b6a44-0000-4000-8000-000000000402\n"
        f"Имя: {CLIENT}Архив\nОбластьВидимости: ВПроекте\n"
    ).encode(),
    f"Склад/{NAMESAKE_DESCRIPTION}": SECOND.encode(),
    "Склад/Партии/ПартииТоваров.yaml": (
        "ВидЭлемента: Справочник\nИд: 6f0b6a44-0000-4000-8000-000000000403\n"
        "Имя: ПартииТоваров\nОбластьВидимости: ВПроекте\n"
    ).encode(),
}


def _project(tmp_path: Path, extra: dict[str, bytes] | None = None) -> Path:
    """Write the fixture byte for byte; returns the folder of the subsystem `Склад`."""
    project_dir = tmp_path / "Демо" / "Учет"
    for rel, data in {**PROJECT_FILES, **(extra or {})}.items():
        path = project_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return project_dir / "Склад"


def _run_cli(capsys, *argv) -> tuple[int, dict]:
    code = cli.main([str(a) for a in argv])
    return code, json.loads(capsys.readouterr().out.strip())


def _lsp_features() -> dict:
    pytest.importorskip("pygls", reason="LSP-методы проверяются при установленном extra [lsp]")
    from xbsl import lsp as lsp_module

    server = lsp_module._make_server()
    fm = getattr(server.lsp, "fm", None) or getattr(server.lsp, "_features", None)
    return getattr(fm, "features", fm)


# --- the family ------------------------------------------------------------------------------


def test_the_family_of_a_soap_client_holds_its_wsdl_descriptions(tmp_path):
    stock = _project(tmp_path, {f"Склад/{CLIENT}.Wsdl.10.wsdl": SECOND.encode()})

    family = scaffold.object_family(stock / f"{CLIENT}.yaml", CLIENT)

    # Every number is the client's, the tenth included; the namesake keeps its description.
    assert sorted(path.name for path in family) == sorted([*FAMILY, f"{CLIENT}.Wsdl.10.wsdl"])


# --- the operations --------------------------------------------------------------------------


def test_a_moved_soap_client_takes_its_descriptions_along(tmp_path):
    stock = _project(tmp_path)
    target = stock / "Партии"
    contents = {name: (stock / name).read_bytes() for name in DESCRIPTIONS}

    result = scaffold.op_move_object(tmp_path, stock / f"{CLIENT}.yaml", target)

    assert sorted((r.old_path.name, r.new_path) for r in result.renames) == sorted(
        (name, target / name) for name in FAMILY
    )
    apply_result(result)
    for name, data in contents.items():
        assert (target / name).read_bytes() == data
        assert not (stock / name).exists()
    assert (stock / NAMESAKE_DESCRIPTION).is_file()


def test_a_renamed_soap_client_renames_its_descriptions_keeping_the_numbers(tmp_path):
    stock = _project(tmp_path)

    result = scaffold.op_rename_object(tmp_path, CLIENT, "КлиентКотировок")

    assert {r.old_path.name: r.new_path.name for r in result.renames} == {
        f"{CLIENT}.yaml": "КлиентКотировок.yaml",
        f"{CLIENT}.Wsdl.1.wsdl": "КлиентКотировок.Wsdl.1.wsdl",
        f"{CLIENT}.Wsdl.2.wsdl": "КлиентКотировок.Wsdl.2.wsdl",
    }
    apply_result(result)
    # The import names the second description by its file name, so it follows the rename; the
    # address and the namesake's description keep their spelling, and so do the BOM and CRLF.
    renamed_first = FIRST.replace(
        f'location="{CLIENT}.Wsdl.2"', 'location="КлиентКотировок.Wsdl.2"'
    )
    assert renamed_first != FIRST
    assert (stock / "КлиентКотировок.Wsdl.1.wsdl").read_bytes() == BOM + renamed_first.encode()
    assert (stock / "КлиентКотировок.Wsdl.2.wsdl").read_bytes() == SECOND.encode()
    assert not any((stock / name).exists() for name in FAMILY)
    assert (stock / NAMESAKE_DESCRIPTION).read_bytes() == SECOND.encode()


def test_a_deleted_soap_client_takes_its_descriptions_with_it(tmp_path):
    stock = _project(tmp_path)

    result = scaffold.op_delete_object(tmp_path, CLIENT)

    assert sorted(path.name for path in result.deletes) == sorted(FAMILY)
    apply_result(result)
    assert not any((stock / name).exists() for name in FAMILY)
    assert (stock / NAMESAKE_DESCRIPTION).is_file()


def test_the_dry_runs_of_the_cli_name_the_descriptions_and_write_nothing(tmp_path, capsys):
    stock = _project(tmp_path)
    client = stock / f"{CLIENT}.yaml"

    code, moved = _run_cli(capsys, "move-object", tmp_path, client, stock / "Партии", "--dry-run")
    assert code == 0
    assert sorted(Path(r["to"]).name for r in moved["renames"]) == sorted(FAMILY)

    code, renamed = _run_cli(
        capsys, "rename-object", tmp_path, CLIENT, "КлиентКотировок", "--dry-run"
    )
    assert code == 0
    assert {Path(r["from"]).name: Path(r["to"]).name for r in renamed["renames"]} == {
        name: name.replace(CLIENT, "КлиентКотировок", 1) for name in FAMILY
    }

    code, deleted = _run_cli(capsys, "delete-object", tmp_path, "--path", client, "--dry-run")
    assert code == 0 and deleted["dry-run"] is True
    assert sorted(Path(p).name for p in deleted["deletes"]) == sorted(FAMILY)

    assert all((stock / name).is_file() for name in FAMILY)
    assert not (stock / "Партии" / DESCRIPTIONS[0]).exists()
    assert not (stock / "КлиентКотировок.Wsdl.1.wsdl").exists()


def test_the_lsp_computes_the_deletion_plan_without_deleting(tmp_path):
    """The editor's tree deletes what this request plans, the descriptions included."""
    features = _lsp_features()
    stock = _project(tmp_path)

    plan = features["xbsl/metaDeleteObject"](
        {"root": str(tmp_path), "path": str(stock / f"{CLIENT}.yaml")}
    )

    assert sorted(Path(p).name for p in plan["deletes"]) == sorted(FAMILY)
    assert any(CLIENT in note for note in plan["notes"])
    assert all((stock / name).is_file() for name in FAMILY)
    refused = features["xbsl/metaDeleteObject"](
        {"root": str(tmp_path), "path": str(stock / "Нет.yaml")}
    )
    assert "не найден" in refused["error"]


# --- an English project and the lint of written files -----------------------------------------


ENGLISH_FILES: dict[str, bytes] = {
    "Проект.yaml": (
        "Id: 6f0b6a44-0000-4000-8000-000000000410\nVendor: Acme\nName: Rates\nVersion: 1.0.0\n"
    ).encode(),
    "Main/Подсистема.yaml": "Interface:\n    IncludeInAutoInterface: True\n".encode(),
    "Main/CurrencyRatesClient.yaml": (
        "ElementKind: SoapServiceClient\nId: 6f0b6a44-0000-4000-8000-000000000411\n"
        "Name: CurrencyRatesClient\n"
    ).encode(),
    "Main/CurrencyRatesClient.Wsdl.1.wsdl": (
        '<definitions xmlns="http://schemas.xmlsoap.org/wsdl/">\n'
        '    <import location="CurrencyRatesClient.Wsdl.2.wsdl"/>\n</definitions>\n'
    ).encode(),
    "Main/CurrencyRatesClient.Wsdl.2.wsdl": SECOND.encode(),
    "Main/Batches/GoodsBatches.yaml": (
        "ElementKind: Catalog\nId: 6f0b6a44-0000-4000-8000-000000000412\nName: GoodsBatches\n"
    ).encode(),
}


@pytest.mark.needs_data  # the English keys and the serializer's spelling of the kind are data
def test_an_english_soap_client_takes_its_descriptions_along(tmp_path):
    main = tmp_path / "Acme" / "Rates" / "Main"
    for rel, data in ENGLISH_FILES.items():
        path = main.parent / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    client = main / "CurrencyRatesClient.yaml"
    family = ["CurrencyRatesClient.yaml", "CurrencyRatesClient.Wsdl.1.wsdl",
              "CurrencyRatesClient.Wsdl.2.wsdl"]
    assert scaffold.element_kind(client.read_text(encoding="utf-8")) == "КлиентSoapСервиса"

    moved = scaffold.op_move_object(tmp_path, client, main / "Batches")
    assert sorted(r.new_path.name for r in moved.renames) == sorted(family)
    assert all(r.new_path.parent == main / "Batches" for r in moved.renames)

    renamed = scaffold.op_rename_object(tmp_path, "CurrencyRatesClient", "RatesClient")
    assert {r.old_path.name: r.new_path.name for r in renamed.renames} == {
        name: name.replace("CurrencyRatesClient", "RatesClient") for name in family
    }
    first = next(c.content for c in renamed.changes if c.path.name == "RatesClient.Wsdl.1.wsdl")
    assert 'location="RatesClient.Wsdl.2.wsdl"' in first

    deleted = scaffold.op_delete_object(tmp_path, "CurrencyRatesClient")
    assert sorted(path.name for path in deleted.deletes) == sorted(family)


@pytest.mark.needs_data  # the file rules read the language data
def test_the_lint_after_a_rename_reads_the_sources_and_not_the_description(tmp_path, capsys):
    stock = _project(tmp_path)

    code, out = _run_cli(capsys, "rename-object", tmp_path, CLIENT, "КлиентКотировок")

    assert code == 0
    written = [Path(f["path"]) for f in out["files"]]
    assert stock / "КлиентКотировок.Wsdl.1.wsdl" in written
    assert out["lint"]["summary"]["files"] == sum(1 for p in written if p.suffix != ".wsdl")
    assert not [d for d in out["lint"]["diagnostics"] if d["path"].endswith(".wsdl")]


@pytest.mark.needs_data  # the file rules read the language data
def test_the_mcp_rename_lints_the_sources_and_not_the_description(mcp_module, tmp_path):
    stock = _project(tmp_path)

    out = mcp_module.meta_rename_object(str(tmp_path), CLIENT, "КлиентКотировок")

    assert (stock / "КлиентКотировок.Wsdl.1.wsdl").is_file()
    written = [f["path"] for f in out["files"]]
    assert any(path.endswith("КлиентКотировок.Wsdl.1.wsdl") for path in written)
    assert out["lint"]["summary"]["files"] == sum(1 for p in written if not p.endswith(".wsdl"))
    assert not [d for d in out["lint"]["diagnostics"] if d["path"].endswith(".wsdl")]
