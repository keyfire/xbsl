"""Tier D: the partial encoding of Url query parameter values.

The code/url-params-partial-encoding rule. The chain `новый Url(...).СПараметрамиЗапроса(...)`
encodes a parameter VALUE only partially: "&" and "=" inside the value stay separators, so a
value that is itself an address arrives cut at its first "&" - the receiving side reads the
tail as parameters of the OUTER address. The same dictionary encoded by its own
`ПараметрыUrl.ВКодированнуюСтроку()` comes out whole, which is also the cure: build the query
string with the parameters object and glue it to the base address (the leading "?" is part of
what the method returns).

The live probe of 2026-08, value `https://site.example/app?p=article&id=42`:

* `новый ПараметрыUrl({...}).ВКодированнуюСтроку()` gives `?return_to=https%3A%2F%2F...%3Fp%3Darticle%26id%3D42` - encoded in full;
* the same dictionary through `новый Url(...).СПараметрамиЗапроса(Пар).ВКодированнуюСтроку()`
  gives `?return_to=https%3A%2F%2F...%3Fp=article&id=42` - the separators stayed, and the
  receiving page saw the value cut at the first "&".

What is judged is every call of the method by name - an identifier between a dot and an
opening parenthesis, in either spelling (the English one comes from the dictionary, never
from a guess). The receiver is not resolved: the name belongs to one stdlib type, and a project
method of the same name would be a shadowing finding of its own.

The rule stays info and OFF by default: whether a value can carry "&" is invisible to a
static check, and a call whose values are known to be plain - an OAuth state, a fixed scope,
a random token - is legitimate and common. Enable it point-wise when an address (a return
link, a page reference) can end up among the values.
"""

from __future__ import annotations

from collections.abc import Iterable
from functools import lru_cache

from xbsl import dataset, i18n
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, rule
from xbsl.rules._syntax import code_tokens

MESSAGES = {
    "code/url-params-partial-encoding.title": {
        "ru": "Параметры запроса Url кодируются частично",
        "en": "Url query parameters are encoded partially",
    },
    "code/url-params-partial-encoding.call": {
        "ru": "'{method}' кодирует значение параметра частично: '&' и '=' внутри значения "
              "остаются разделителями, и значение-адрес приходит обрезанным по первому '&'. "
              "Если среди значений может оказаться адрес – соберите строку самим "
              "'ПараметрыUrl.ВКодированнуюСтроку()' и приклейте к базовому адресу "
              "(ведущий '?' метод отдаёт сам).",
        "en": "'{method}' encodes a parameter value only partially: '&' and '=' inside the "
              "value stay separators, and a value that is an address arrives cut at its "
              "first '&'. When an address can end up among the values, build the string "
              "with 'UrlParameters.ToEncodedString()' itself and glue it to the base "
              "address (the leading '?' is part of what it returns).",
    },
}
i18n.register(MESSAGES)

#: The method whose value encoding is partial; the Russian name is the catalog key.
_METHOD = "СПараметрамиЗапроса"


@lru_cache(maxsize=1)
def _spellings() -> tuple[str, ...]:
    """Both spellings of the method name; the English one from the dictionary.

    Without the Element data the tuple holds the Russian name alone: guessing the
    English form is exactly what the data rules of this repository forbid.
    """
    names = [_METHOD]
    try:
        from xbsl import terms

        english = terms.common_english(_METHOD)
    except Exception:  # noqa: BLE001 - no data is an answer, not a failure
        english = None
    if english and english != _METHOD:
        names.append(english)
    return tuple(names)


dataset.register_reset(_spellings.cache_clear)


@rule(
    "code/url-params-partial-encoding", "code/url-params-partial-encoding.title", "D",
    severity=Severity.INFO, enabled_by_default=False,
    off_reason="code/url-params-partial-encoding.off",
)
def url_params_partial_encoding(source: SourceFile) -> Iterable[Diagnostic]:
    if source.kind != "xbsl":
        return
    if not any(name in source.text for name in _spellings()):
        return
    toks = code_tokens(source)
    for index, tok in enumerate(toks):
        if tok.kind != "IDENT" or tok.value not in _spellings():
            continue
        previous = toks[index - 1] if index else None
        following = toks[index + 1] if index + 1 < len(toks) else None
        if previous is None or previous.kind != "OP" or previous.value != ".":
            continue  # not a member access - a declaration or a bare name
        if following is None or following.kind != "OP" or following.value != "(":
            continue  # a member read, not a call
        yield Diagnostic(
            source.rel, tok.line, tok.col, "code/url-params-partial-encoding",
            Severity.INFO,
            i18n.t("code/url-params-partial-encoding.call", method=tok.value),
        )
