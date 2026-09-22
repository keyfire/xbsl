"""Typed platform members keep the spelling their owner declares."""

from __future__ import annotations

from pathlib import Path

import pytest

from xbsl import engine
from xbsl.translation.code import Resolver, translate_code
from xbsl.translation.dictionary import Dictionary
from xbsl.translation.project import translate_project
from xbsl.translation.reporting import FileReport

pytestmark = pytest.mark.needs_data


def _translate(text: str, tokens: dict[str, str], *, project_names: frozenset[str] = frozenset()
               ) -> str:
    source = engine.load_text("Probe.xbsl", text)
    report = FileReport(path="Probe.xbsl")
    resolver = Resolver(
        Dictionary(tokens=tokens, phrases={}, literals={}), project_names=project_names,
    )
    return translate_code(source, resolver, report)


def test_a_typed_exception_member_uses_its_owner_spelling():
    out = _translate(
        "метод Проверить()\n"
        "    попытка\n"
        "    ;\n"
        "    поймать Ошибка: Исключение\n"
        "        знч Вложенное = Ошибка.Причина\n"
        "        знч Текст = Ошибка.Причина.Описание\n"
        "    ;\n"
        ";\n",
        {
            "Проверить": "Check", "Ошибка": "Error", "Вложенное": "Nested",
            "Текст": "Text", "Причина": "Reason", "Описание": "Description",
        },
    )

    assert "Error.Cause" in out
    assert "Error.Cause.Description" in out
    assert "Error.Reason" not in out


def test_a_project_member_with_the_same_name_keeps_its_dictionary_pair():
    out = _translate(
        "метод Проверить(Сведения: Запись)\n"
        "    возврат Сведения.Причина\n"
        ";\n",
        {
            "Проверить": "Check", "Сведения": "Details", "Запись": "Record",
            "Причина": "Reason",
        },
        project_names=frozenset(("Запись", "Причина")),
    )

    assert "return Details.Reason" in out


def test_an_exception_member_chain_keeps_its_owner_spelling(tmp_path: Path):
    root = tmp_path / "Acme" / "Demo"
    root.mkdir(parents=True)
    (root / "Project.yaml").write_text(
        "Vendor: Acme\nName: Demo\nVersion: 1.0.0\n", encoding="utf-8",
    )
    (root / "Проверка.xbsl").write_text(
        "метод Проверить()\n"
        "    попытка\n"
        "    ;\n"
        "    поймать Ошибка: Исключение\n"
        "        знч ПричинаПричины = Ошибка.Причина.Причина\n"
        "    ;\n"
        ";\n",
        encoding="utf-8",
    )

    translate_project(
        root,
        Dictionary(tokens={"Проверить": "Check", "Ошибка": "Error",
                           "ПричинаПричины": "NestedCause", "Причина": "Reason"},
                   phrases={}, literals={}),
        tmp_path / "en", swap_localization=False,
    )

    out = (tmp_path / "en" / "Validation.xbsl").read_text(encoding="utf-8")
    assert "Error.Cause.Cause" in out


def test_a_typed_exception_member_passes_the_strict_translation_gate(tmp_path: Path, capsys):
    from xbsl.translation import cli

    root = tmp_path / "Acme" / "Demo"
    root.mkdir(parents=True)
    (root / "Project.yaml").write_text(
        "Vendor: Acme\nName: Demo\nVersion: 1.0.0\n", encoding="utf-8",
    )
    (root / "Проверка.xbsl").write_text(
        "метод Проверить()\n"
        "    попытка\n"
        "    ;\n"
        "    поймать Ошибка: Исключение\n"
        "        знч ПричинаОшибки = Ошибка.Причина\n"
        "    ;\n"
        ";\n",
        encoding="utf-8",
    )
    dictionary = tmp_path / "dictionary.yaml"
    dictionary.write_text(
        "version: 1\nlanguage: en\ntokens:\n"
        "    Проверить: Check\n"
        "    Ошибка: Error\n"
        "    ПричинаОшибки: ErrorCause\n"
        "    Причина: Reason\n",
        encoding="utf-8",
    )

    assert cli.cli_main([str(root), "--dictionary", str(dictionary), "--strict", "--lang", "ru"]) == 0
    assert capsys.readouterr().out.rstrip("\n").splitlines()[-1] == "ГОТОВО"


def test_a_query_alias_does_not_take_a_method_parameter_entry():
    out = _translate(
        "метод НайтиПоНомеру(Номер: Строка)\n"
        "    исп Результат = Запрос{\n"
        "        ВЫБРАТЬ Запись.Номер КАК Номер\n"
        "        ИЗ Запись КАК Запись\n"
        "        УПОРЯДОЧИТЬ ПО Номер\n"
        "    }\n"
        ";\n",
        {"НайтиПоНомеру": "Lookup", "НайтиПоНомеру.Номер": "InvoiceNumber"},
    )

    assert "method Lookup(InvoiceNumber: String)" in out
    assert "Record.Number AS Number" in out
    assert "ORDER BY Number" in out
    assert "AS InvoiceNumber" not in out


def test_a_query_parameter_keeps_its_method_entry():
    out = _translate(
        "метод Найти(Номер: Строка)\n"
        "    исп Результат = Запрос{\n"
        "        ВЫБРАТЬ Т.Номер\n"
        "        ИЗ Запись КАК Т\n"
        "        ГДЕ Т.Номер == & Номер\n"
        "    }\n"
        ";\n",
        {"Найти": "Lookup", "Найти.Номер": "InvoiceNumber"},
    )

    assert "method Lookup(InvoiceNumber: String)" in out
    assert "WHERE T.Number == & InvoiceNumber" in out


def test_a_query_parameter_after_a_comment_keeps_its_method_entry():
    out = _translate(
        "метод Найти(Номер: Строка)\n"
        "    исп Результат = Запрос{\n"
        "        ВЫБРАТЬ Т.Номер\n"
        "        ИЗ Запись КАК Т\n"
        "        ГДЕ Т.Номер == & // parameter\n"
        "            Номер\n"
        "    }\n"
        ";\n",
        {"Найти": "Lookup", "Найти.Номер": "InvoiceNumber"},
    )

    assert "& // parameter\n            InvoiceNumber" in out
