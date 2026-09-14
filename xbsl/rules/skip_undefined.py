"""SkipUndefined cannot remove values from a collection with a non-nullable element.

The platform declares the operation on Iterable<T> and Sequence<T>. It materializes an
Array<T> for an iterable, while a sequence retains Sequence<T>. Consequently the iterable
fix replaces filtering with ToArray, rather than removing allocation or changing Set<T>
into the result type. A sequence receives a warning without an automatic rewrite.

File inference covers declarations, literals, local calls and stream chains. Unknown
receivers/elements and user-defined methods remain unjudged; project-only type facts are
not guessed. English spellings and inherited members come from the platform catalog.
"""

from __future__ import annotations

from collections.abc import Iterable
from functools import lru_cache

from xbsl import dataset, i18n, terms, typeinfer
from xbsl.diagnostics import Diagnostic, Severity, TextEdit
from xbsl.engine import SourceFile, rule
from xbsl.lexer import linemap
from xbsl.rules.redundant_checks import display

RULE = "code/redundant-skip-undefined"
_SKIP = "ПропуститьНеопределено"
_TO_ARRAY = "ВМассив"
_SEQUENCE = "Последовательность"

MESSAGES = {
    f"{RULE}.title": {
        "ru": "Лишнее исключение Неопределено из коллекции",
        "en": "Redundant exclusion of Undefined from a collection",
    },
    f"{RULE}.array": {
        "ru": "Тип элемента '{type}' не содержит '{n[Неопределено]}': '{method}()' ничего "
              "не исключает. Для получения массива используйте '{replacement}()'.",
        "en": "Element type '{type}' excludes '{n[Неопределено]}': '{method}()' removes "
              "nothing. Use '{replacement}()' to materialize the array.",
    },
    f"{RULE}.sequence": {
        "ru": "Тип элемента '{type}' не содержит '{n[Неопределено]}': '{method}()' ничего "
              "не исключает. Проверьте необходимость этого шага последовательности.",
        "en": "Element type '{type}' excludes '{n[Неопределено]}': '{method}()' removes "
              "nothing. Review whether this sequence step is needed.",
    },
}
i18n.register(MESSAGES)


@lru_cache(maxsize=1)
def _names() -> frozenset[str]:
    return frozenset({_SKIP, *terms.member_spellings(_SKIP)})


dataset.register_reset(_names.cache_clear)


def _shown(owner: str, member: str) -> str:
    if i18n.current_lang() == "en":
        return terms.member_english_of(owner, member) or member
    return member


def _element(site: typeinfer.CallSite, typing: typeinfer.ModuleTyping):
    owner = site.owner
    if (not isinstance(owner, typeinfer.TypeSet) or owner.size != 1 or not owner.names
            or owner.undefined or owner.null or site.args or site.node.callee.safe
            or site.node.type_args):
        return None
    written = next(iter(owner.names))
    head, args = typeinfer.split_nominal(written)
    if typeinfer.platform_head(head) is None:
        return None
    result = typing.catalog.platform_member(written, site.node.callee.name, True, 0)
    if result is None:
        return None
    # Sequence<T> declares its own operation and does not inherit Iterable<T>.
    if not (head == _SEQUENCE and len(args) == 1) and typing.catalog.element_of(owner) is None:
        return None
    # File inference preserves unresolved project names; a warning needs proof instead.
    element = typeinfer.parse_type(args[0], typing.catalog.resolver(None, strict=True))
    if element is None or not element.names or element.undefined or element.null:
        return None
    return written, head, element, result


def _array_fix(source: SourceFile, site: typeinfer.CallSite, typing: typeinfer.ModuleTyping,
               owner: str, head: str, result: typeinfer.TypeSet) -> TextEdit | None:
    member = site.node.callee
    replacement = (_TO_ARRAY if member.name == _SKIP
                   else terms.member_english_of(head, _TO_ARRAY))
    if not replacement or typing.catalog.platform_member(owner, replacement, True, 0) != result:
        return None
    start = member.end - len(member.name)
    if source.text[start:member.end] != member.name:
        return None
    # Replacing only the identifier leaves receiver precedence and every comment intact.
    return TextEdit(start, member.end, replacement)


@rule(RULE, f"{RULE}.title", "D", severity=Severity.WARNING)
def redundant_skip_undefined(source: SourceFile) -> Iterable[Diagnostic]:
    """Judge only a platform call whose element type is statically known without Undefined."""
    names = _names()
    if source.kind != "xbsl" or not any(name in source.text for name in names):
        return
    typing = typeinfer.file_typing(source)
    if typing is None:
        return
    lines = linemap(source)
    for site in typing.calls(names):
        judged = _element(site, typing)
        if judged is None:
            continue
        owner, head, element, result = judged
        fix = _array_fix(source, site, typing, owner, head, result)
        member = site.node.callee
        line, col = lines.linecol(member.end - len(member.name))
        fields = {"type": display(element), "method": _shown(head, _SKIP)}
        shape = "array" if fix is not None else "sequence"
        if fix is not None:
            fields["replacement"] = _shown(head, _TO_ARRAY)
        yield Diagnostic(source.rel, line, col, RULE, Severity.WARNING,
                         i18n.t(f"{RULE}.{shape}", **fields), fix=fix)
