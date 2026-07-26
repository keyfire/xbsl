"""XBSL lexer checks."""

from xbsl.lexer import tokenize


def _kinds(text):
    return [t.kind for t in tokenize(text)]


def test_keywords_bilingual_with_canonical():
    toks = tokenize("метод Ф(): Строка\n    возврат 1\n;\n")
    canon = {t.canonical for t in toks if t.kind == "KEYWORD"}
    assert "METHOD" in canon
    assert "RETURN" in canon


def test_string_and_comment_recognized():
    kinds = _kinds('// коммент\nзнч s = "привет"\n')
    assert "COMMENT" in kinds
    assert "STRING" in kinds


def test_number_with_dot_is_single_token():
    nums = [t for t in tokenize("знч x = 1.5\n") if t.kind == "NUMBER"]
    assert len(nums) == 1
    assert nums[0].value == "1.5"


def test_positions_are_1_indexed():
    first = tokenize("метод Ф()\n;\n")[0]
    assert (first.line, first.col) == (1, 1)


def test_operators_do_not_produce_unknown():
    toks = tokenize("знч x = a ?? b?.c\nзнч f = (п) -> п\n")
    assert not any(t.kind == "UNKNOWN" for t in toks)


def test_capitalized_form_still_keyword_token():
    # 'Выбор' is lexically a form of the CASE keyword (context-based distinction is up to rules)
    toks = [t for t in tokenize("знч Выбор = 1\n") if t.kind == "KEYWORD"]
    assert any(t.canonical == "CASE" for t in toks)
