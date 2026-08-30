"""Tier D: a force-unwrapped `ЗагрузитьОбъект()` on a reference taken from a field.

`СтрокаСервиса.Сервис!.ЗагрузитьОбъект()!` loads the record behind a reference stored in a
FIELD of another loaded record or of a tabular-section row - and unwraps the result with `!`.
The platform's own signature answers a nullable object - the stdlib reference pages spell it
`ЗагрузитьОбъект(Заблокировать: Булево = Ложь): Справочник.Объект?` - because a stored
reference may dangle. A catalog with `РежимУдаления: Немедленно` deletes its records
physically, and the deleted-items form removes a marked record for good (topic data-deletion),
while the fields that point at it keep the old reference. The load then answers Undefined, the
`!` throws a type check exception, and one broken row fails the WHOLE pass - a production list
of half a hundred records stopped reading because of a single dangling reference. The cure is
to check the load result for Undefined instead of unwrapping it.

The predicate is deliberately NARROW - only the receiver shape whose reference is stored data:

- the call result carries a `!` right after the parentheses;
- the receiver of the call is a MEMBER ACCESS - `X.Поле` or `X.Поле!` - i.e. the reference
  comes out of a field of some other value. A bare local variable or parameter
  (`Ссылка.ЗагрузитьОбъект()!`) is skipped: in the corpora every such reference is freshly
  answered by a query lookup a line above, with Undefined already sifted out, and flagging
  every force-unwrap measured at 17.5% precision (66 false findings on one corpus) against
  100% for this shape (14/14 true);
- the last member before the call is NOT the record's own reference member (`.Ссылка` /
  `.Reference`): the row's OWN reference (`ЗаписьКарточки.Ссылка.ЗагрузитьОбъект()!`) points
  at the record the query has just read, which is alive by construction.

Known misses, accepted rather than guessed at: a field reference copied into a local variable
before the call (would need local data flow) and a foreign reference FIELD named like the
own-reference member.

The walk is token-based over `code_tokens` - comments and `Запрос{}` blocks are excluded, so
a mention inside either does not fire. Both spellings come from the data: `LoadObject` from
the compiler dictionary (the common section of the full terms), `Reference` from the facet
table; without the dataset the rule degrades to the Russian spellings.
"""

from __future__ import annotations

from collections.abc import Iterable
from functools import lru_cache

from xbsl import dataset, i18n, terms
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, rule
from xbsl.rules._syntax import _skip_balanced, code_tokens

MESSAGES = {
    "code/load-object-unwrap.title": {
        "ru": "Разворот '!' результата ЗагрузитьОбъект() у ссылки из поля",
        "en": "The '!' unwrap of a LoadObject() result on a reference from a field",
    },
    "code/load-object-unwrap.found": {
        "ru": "Результат '{call}()' у ссылки из поля '{field}' развёрнут '!' – запись могли "
              "удалить физически (РежимУдаления: Немедленно, форма удаления помеченных), и "
              "разворот бросит исключение, роняя весь обход. Проверяйте результат на "
              "Неопределено.",
        "en": "The result of '{call}()' on the reference from the field '{field}' is unwrapped "
              "with '!' – the record may be deleted physically ({n[РежимУдаления]}: "
              "{n[Немедленно]}, the deleted-items form), and the unwrap throws, failing the "
              "whole pass. Check the result for Undefined.",
    },
}
i18n.register(MESSAGES)

#: The Russian spelling of the loading method and of the record's own reference field. The
#: English counterparts are looked up in the data - never invented here.
_LOAD_RUSSIAN = "ЗагрузитьОбъект"
_REFERENCE_RUSSIAN = "Ссылка"


@lru_cache(maxsize=1)
def _load_names() -> frozenset[str]:
    """Both spellings of the loading method; the Russian one alone without the dataset."""
    names = {_LOAD_RUSSIAN}
    english = terms.common_english(_LOAD_RUSSIAN)
    if english:
        names.add(english)
    return frozenset(names)


@lru_cache(maxsize=1)
def _own_reference_names() -> frozenset[str]:
    """Both spellings of the record's own reference field (the facet suffix pair)."""
    names = {_REFERENCE_RUSSIAN}
    english = terms.facet_suffix_english(_REFERENCE_RUSSIAN)
    if english:
        names.add(english)
    return frozenset(names)


dataset.register_reset(_load_names.cache_clear)
dataset.register_reset(_own_reference_names.cache_clear)


@rule("code/load-object-unwrap", "code/load-object-unwrap.title", "D")
def load_object_unwrap(source: SourceFile) -> Iterable[Diagnostic]:
    """`X.Поле!.ЗагрузитьОбъект()!` - the force-unwrap hides a dangling stored reference."""
    if source.kind != "xbsl":
        return
    load_names = _load_names()
    reference_names = _own_reference_names()
    toks = code_tokens(source)
    n = len(toks)
    for i, t in enumerate(toks):
        if t.kind != "IDENT" or t.value not in load_names:
            continue
        # The call: `( ... )` right after the name (the platform method takes at most the
        # optional lock argument), then the `!` on the RESULT. `!=` is a single token, so a
        # lone `!` is unambiguous.
        if not (i + 1 < n and toks[i + 1].kind == "OP" and toks[i + 1].value == "("):
            continue
        after_call = _skip_balanced(toks, i + 1, "(", ")")
        if not (after_call < n and toks[after_call].kind == "OP" and toks[after_call].value == "!"):
            continue
        # The receiver: a member access `X.Поле` or `X.Поле!` before the call's dot.
        if i < 1 or not (toks[i - 1].kind == "OP" and toks[i - 1].value == "."):
            continue
        k = i - 2
        if k >= 0 and toks[k].kind == "OP" and toks[k].value == "!":
            k -= 1
        if k < 1 or toks[k].kind != "IDENT":
            continue
        field = toks[k]
        if not (toks[k - 1].kind == "OP" and toks[k - 1].value == "."):
            continue  # a bare variable or parameter - the reference is not stored data
        if k < 2:
            continue
        before = toks[k - 2]
        # The member's dot must close an expression: a name, a call or indexing result, or a
        # force-unwrapped value. Anything else is not a member access.
        if not (before.kind in ("IDENT", "KEYWORD")
                or (before.kind == "OP" and before.value in (")", "]", "!"))):
            continue
        if field.value in reference_names:
            continue  # the row's own reference - alive by construction
        bang = toks[after_call]
        yield Diagnostic(
            source.rel, bang.line, bang.col, "code/load-object-unwrap", Severity.WARNING,
            i18n.t("code/load-object-unwrap.found", call=t.value, field=field.value),
        )
