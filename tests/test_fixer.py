"""Mechanical fix applier (--fix): fixer.py and its rules.

The pure parts of the fixer (fix_source/encode/is_fixable) operate on ready-made Diagnostic
objects and need no Element data. Tests of the fix-producing rules (typography/whitespace)
go through the lexer and the data, so they are marked skipif like in the other rule files.
"""

import pytest

from xbsl import dataset, engine, fixer
from xbsl.cli import discover
from xbsl.diagnostics import Diagnostic, Severity, TextEdit


def _src(name, content):
    return engine.load_text(name, content)


def _diag(path, offset, end, new, rule="whitespace/trailing"):
    return Diagnostic(path, 1, 1, rule, Severity.WARNING, "x", fix=TextEdit(offset, end, new))


# --- Pure fixer mechanics (no Element data) --------------------------------------------

def test_span_edits_applied_right_to_left():
    src = _src("М.xbsl", "абвгде")
    diags = [
        _diag("М.xbsl", 0, 1, "A"),   # а -> A
        _diag("М.xbsl", 4, 6, ""),    # delete "де"
    ]
    res = fixer.fix_source(src, diags)
    assert res.text == "Aбвг"
    assert res.applied == 2 and res.changed


def test_overlapping_edits_earliest_wins():
    src = _src("М.xbsl", "абвгде")
    diags = [
        _diag("М.xbsl", 0, 3, "X"),   # covers абв
        _diag("М.xbsl", 2, 4, "Y"),   # overlaps - dropped
    ]
    res = fixer.fix_source(src, diags)
    assert res.text == "Xгде"
    assert res.applied == 1


def test_no_fix_no_change():
    src = _src("М.xbsl", "абв")
    res = fixer.fix_source(src, [Diagnostic("М.xbsl", 1, 1, "r", Severity.WARNING, "x")])
    assert not res.changed and res.applied == 0


def test_mixed_newline_normalized_to_dominant():
    # CRLF ×2, LF ×1 -> CRLF dominates
    src = _src("М.xbsl", "а\r\nб\r\nв\n")
    diag = Diagnostic("М.xbsl", 1, 1, "whitespace/mixed-newline", Severity.WARNING, "x")
    res = fixer.fix_source(src, [diag])
    assert res.text == "а\r\nб\r\nв\r\n"
    assert res.applied == 1 and res.changed


def test_mixed_newline_after_trailing_edit():
    # the trailing whitespace is removed, then the newlines are normalized
    src = _src("М.xbsl", "а  \r\nб\n")
    diags = [
        _diag("М.xbsl", 1, 3, ""),  # two spaces after "а"
        Diagnostic("М.xbsl", 1, 1, "whitespace/mixed-newline", Severity.WARNING, "x"),
    ]
    res = fixer.fix_source(src, diags)
    assert res.text == "а\r\nб\r\n"
    assert res.applied == 2


def test_encode_preserves_bom():
    src = engine.make_source(__import__("pathlib").Path("М.xbsl"), "﻿абв".encode("utf-8"))
    assert src.had_bom
    data = fixer.encode(src, "абвг")
    assert data.startswith(b"\xef\xbb\xbf") and data.decode("utf-8-sig") == "абвг"


def test_is_fixable():
    assert fixer.is_fixable(_diag("М.xbsl", 0, 1, ""))
    assert fixer.is_fixable(
        Diagnostic("М.xbsl", 1, 1, "whitespace/mixed-newline", Severity.WARNING, "x"))
    assert not fixer.is_fixable(Diagnostic("М.xbsl", 1, 1, "structure/xbsl-pair", Severity.WARNING, "x"))


# --- Fix-producing rules (Element data required) ---------------------------------------

_needs_data = pytest.mark.skipif(
    not dataset.available_versions(),
    reason="нет данных Элемента – сгенерируйте: python tools/extract.py --dist ...",
)


@_needs_data
def test_trailing_rule_carries_fix():
    src = _src("М.xbsl", "метод Ф(): Число\n    возврат 1  \n;\n")
    diags = [d for d in engine.run_sources([src], select={"whitespace/trailing"})
             if d.rule_id == "whitespace/trailing"]
    assert diags and diags[0].fix is not None
    assert fixer.fix_source(src, diags).text == "метод Ф(): Число\n    возврат 1\n;\n"


@_needs_data
def test_typography_rules_carry_fixes():
    src = _src("М.xbsl", "// “цитата” и многоточие… и тире —\nметод Ф()\n;\n")
    diags = engine.run_sources([src], select={"typography"})
    fixed = fixer.fix_source(src, diags).text
    assert '"цитата"' in fixed
    assert "многоточие..." in fixed
    assert "тире –" in fixed  # en dash U+2013
    assert "—" not in fixed and "“" not in fixed and "…" not in fixed


@_needs_data
def test_cli_fix_writes_and_reports(tmp_path, capsys):
    from xbsl import cli

    f = tmp_path / "М.xbsl"
    f.write_text("// многоточие…\nметод Ф(): Число\n    возврат 1  \n;\n", encoding="utf-8")
    code = cli.main(["--fix", "--ignore", "structure/xbsl-pair", str(f)])
    err = capsys.readouterr().err
    assert code == 0
    assert "Исправлено замечаний: 2" in err
    text = f.read_text(encoding="utf-8")
    assert "многоточие..." in text and "возврат 1\n" in text


@_needs_data
def test_cli_fix_rejects_stdin(capsys):
    from xbsl import cli

    code = cli.main(["--fix", "--stdin", "--filename", "М.xbsl"])
    assert code == 2 and "--stdin" in capsys.readouterr().err


@_needs_data
def test_cli_fix_rejects_write_baseline(tmp_path, capsys):
    from xbsl import cli

    f = tmp_path / "М.xbsl"
    f.write_text("метод Ф()\n;\n", encoding="utf-8")
    code = cli.main(["--fix", "--write-baseline", str(tmp_path / "b.json"), str(f)])
    assert code == 2 and "--write-baseline" in capsys.readouterr().err


@_needs_data
@pytest.mark.parametrize("explicit", [False, True])
def test_cli_fix_preserves_baseline_across_overlapping_passes(tmp_path, capsys, explicit):
    import json
    from xbsl import baseline, cli

    source = tmp_path / "Sample.xbsl"
    source.write_bytes(("метод Ф(Х: Строка)\r\n"
                        "    знч Перед = 1 как Число\r\n"
                        "    знч А = Х как Строка\r\n"
                        "    знч Б = (Х как Строка) как Строка\r\n;\r\n").encode("utf-8-sig"))
    rule = "code/redundant-cast"
    findings = engine.run([source], select={rule})
    assert len(findings) == 4
    frozen = tmp_path / baseline.DEFAULT_NAME
    baseline.write(frozen, findings[1:2])
    before = frozen.read_bytes()
    flags = ["--baseline", str(frozen)] if explicit else []
    code = cli.main([str(source), "--select", rule, "--fix", "--format", "json", *flags])
    assert code == 0
    result = json.loads(capsys.readouterr().out)
    assert source.read_bytes() == ("метод Ф(Х: Строка)\r\n"
                                   "    знч Перед = 1\r\n"
                                   "    знч А = Х как Строка\r\n"
                                   "    знч Б = Х\r\n;\r\n").encode("utf-8-sig")
    assert frozen.read_bytes() == before
    assert result["diagnostics"] == []
    assert result["summary"]["baselined"] == 1
    assert result["summary"]["fixed"] == 3
    assert result["summary"]["files_changed"] == 1


@_needs_data
def test_fix_does_not_overlap_an_accepted_cast(tmp_path):
    from xbsl import baseline

    source = tmp_path / "Sample.xbsl"
    original = "метод Ф(Х: Строка)\n    знч А = (Х как Строка) как Строка\n;\n"
    source.write_text(original, encoding="utf-8", newline="")
    rule = "code/redundant-cast"
    findings = engine.run([source], select={rule})
    frozen = tmp_path / "accepted.json"
    baseline.write(frozen, findings[:1])
    remaining, summary, accepted = fixer.fix_paths([source], select={rule}, baseline_path=frozen)
    assert source.read_text(encoding="utf-8") == original
    assert len(baseline.apply(remaining, baseline.load(frozen), frozen.parent)[0]) == 1
    assert summary == {"fixed": 0, "files_changed": 0}


@_needs_data
def test_cli_fix_invalid_baseline_leaves_sources_untouched(tmp_path, capsys):
    from xbsl import cli

    source = tmp_path / "Sample.xbsl"
    original = b"// example  \n"
    source.write_bytes(original)
    frozen = tmp_path / "accepted.json"
    frozen.write_bytes(b"invalid json")
    assert cli.main([str(source), "--fix", "--baseline", str(frozen)]) == 2
    assert source.read_bytes() == original
    assert frozen.read_bytes() == b"invalid json"
    assert str(frozen) in capsys.readouterr().err


@_needs_data
def test_fix_paths_edits_only_requested_files(tmp_path):
    requested = tmp_path / "Requested.xbsl"
    context = tmp_path / "Context.xbsl"
    for source in (requested, context):
        source.write_bytes(b"// example  \n")
    diagnostics, summary, accepted = fixer.fix_paths(
        [requested, context], select={"whitespace/trailing"}, requested=[requested],
    )
    assert requested.read_bytes() == b"// example\n"
    assert context.read_bytes() == b"// example  \n"
    assert diagnostics == []
    assert summary == {"fixed": 1, "files_changed": 1}


@_needs_data
def test_fix_keeps_original_accepted_occurrence_when_an_earlier_fix_creates_its_identity(tmp_path, capsys):
    import json
    from xbsl import baseline, cli

    source = tmp_path / "Sample.xbsl"
    source.write_text("// first \u2014\n// frozen \u2013\n", encoding="utf-8", newline="")
    rules = {"typography/em-dash", "typography/en-dash-comment"}
    findings = engine.run([source], select=rules)
    frozen = tmp_path / "accepted.json"
    baseline.write(frozen, [d for d in findings if d.line == 2])
    before = frozen.read_bytes()
    assert cli.main([str(source), "--fix", "--baseline", str(frozen), "--select", ",".join(rules), "--format", "json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert source.read_text(encoding="utf-8") == "// first -\n// frozen \u2013\n"
    assert frozen.read_bytes() == before
    assert result["summary"]["fixed"] == 2
    assert result["summary"]["baselined"] == 1
    assert result["diagnostics"] == []


@_needs_data
def test_cli_fix_rejects_prune_before_writing_anything(tmp_path, capsys):
    from xbsl import baseline, cli

    source = tmp_path / "Sample.xbsl"
    source.write_bytes(b"// example  \n")
    frozen = tmp_path / "accepted.json"
    baseline.write(frozen, engine.run([source], select={"whitespace/trailing"}))
    before = frozen.read_bytes()
    assert cli.main([str(source), "--fix", "--baseline", str(frozen), "--prune-baseline"]) == 2
    assert source.read_bytes() == b"// example  \n"
    assert frozen.read_bytes() == before
    assert "--prune-baseline" in capsys.readouterr().err


@_needs_data
@pytest.mark.parametrize("value", ["one", True, -1, 1.5, {}, {"count": "one"}, {"count": 1, "reason": 2}])
def test_fix_rejects_malformed_nested_baseline_before_writing(tmp_path, capsys, value):
    import json
    from xbsl import baseline, cli

    source = tmp_path / "Sample.xbsl"
    source.write_bytes(b"// example  \n")
    frozen = tmp_path / "accepted.json"
    data = baseline.build(engine.run([source], select={"whitespace/trailing"}), tmp_path)
    messages = data["files"]["Sample.xbsl"]["whitespace/trailing"]
    messages[next(iter(messages))] = value
    frozen.write_text(json.dumps(data), encoding="utf-8")
    before = frozen.read_bytes()
    assert cli.main([str(source), "--fix", "--baseline", str(frozen)]) == 2
    assert source.read_bytes() == b"// example  \n"
    assert frozen.read_bytes() == before


@_needs_data
def test_fix_keeps_accepted_import_when_its_message_line_number_changes(tmp_path, capsys):
    import json
    from xbsl import baseline, cli

    source = tmp_path / "Sample.xbsl"
    source.write_bytes(b"import Alpha\nimport Alpha\nimport Beta\nimport Beta\n")
    rule = "code/duplicate-import"
    findings = engine.run([source], select={rule})
    frozen = tmp_path / "accepted.json"
    baseline.write(frozen, [d for d in findings if d.line == 4])
    before = frozen.read_bytes()
    assert cli.main([str(source), "--fix", "--baseline", str(frozen), "--select", rule, "--format", "json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert source.read_bytes() == b"import Alpha\nimport Beta\nimport Beta\n"
    assert frozen.read_bytes() == before
    assert result["diagnostics"] == []
    assert result["summary"]["baselined"] == 1
    assert result["summary"]["baseline_stale"] == 0


@pytest.mark.parametrize("value", [0, 1, {"count": 1}, {"count": 2, "reason": "accepted"}])
def test_strict_baseline_load_accepts_legacy_and_reasoned_counts(tmp_path, value):
    import json
    from xbsl import baseline

    data = {"files": {"Sample.xbsl": {"whitespace/trailing": {"message": value}}}}
    frozen = tmp_path / "accepted.json"
    frozen.write_text(json.dumps(data), encoding="utf-8")
    assert baseline.load(frozen, strict=True) == data


@pytest.mark.parametrize("data", [
    {"files": {"Sample.xbsl": []}},
    {"files": {"Sample.xbsl": {"whitespace/trailing": []}}},
    {"files": {}, "meta": None},
    {"files": {}, "meta": {"format": 2}},
    {"files": {}, "meta": {"format": True}},
    {"files": {}, "meta": {"tool": []}},
])
def test_strict_baseline_load_rejects_malformed_containers(tmp_path, data):
    import json
    from xbsl import baseline

    frozen = tmp_path / "accepted.json"
    frozen.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(baseline.BaselineError):
        baseline.load(frozen, strict=True)


@_needs_data
@pytest.mark.parametrize("lang", ["ru", "en"])
def test_ordinary_lint_after_fix_keeps_legacy_duplicate_import_baseline(tmp_path, capsys, lang):
    import json
    from xbsl import baseline, cli, i18n

    i18n.set_lang(lang)
    source = tmp_path / "Sample.xbsl"
    source.write_bytes(b"import Alpha1\nimport Alpha1\nimport Beta2\nimport Beta2\n")
    rule = "code/duplicate-import"
    findings = engine.run([source], select={rule})
    accepted = next(d for d in findings if d.line == 4)
    frozen = tmp_path / "accepted.json"
    legacy = {"files": {source.name: {rule: {accepted.message: {"count": 1, "reason": "retained"}}}}}
    baseline.save(frozen, legacy)
    before = frozen.read_bytes()
    flags = [str(source), "--baseline", str(frozen), "--select", rule, "--lang", lang, "--format", "json"]
    assert cli.main([*flags, "--fix"]) == 0
    capsys.readouterr()
    assert source.read_bytes() == b"import Alpha1\nimport Beta2\nimport Beta2\n"
    assert cli.main(flags) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["diagnostics"] == []
    assert result["summary"]["baselined"] == 1
    assert result["summary"]["baseline_stale"] == 0
    assert frozen.read_bytes() == before
    current = engine.run([source], select={rule})
    assert len(current) == 1 and current[0].message != accepted.message
    assert "2" in current[0].message
    with source.open("ab") as stream:
        stream.write(b"import Gamma3\nimport Gamma3\n")
    assert cli.main(flags) == 0
    result = json.loads(capsys.readouterr().out)
    assert len(result["diagnostics"]) == 1
    assert "Gamma3" in result["diagnostics"][0]["message"]
    assert result["summary"]["baselined"] == 1
