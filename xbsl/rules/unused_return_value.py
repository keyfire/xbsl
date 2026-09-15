"""Report discarded calls whose platform method requires using its return value."""

from collections.abc import Iterable
from functools import lru_cache

from xbsl import dataset, i18n, terms, typeinfer
from xbsl import parser as P
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, rule
from xbsl.lexer import linemap

RULE = "code/unused-return-value"
MESSAGES = {
    f"{RULE}.title": {
        "ru": "Возвращаемое значение метода не используется",
        "en": "Method return value is not used",
    },
    f"{RULE}.found": {
        "ru": "Возвращаемое значение метода '{method}' не используется. Сохраните или передайте результат вызова.",
        "en": "The return value of method '{method}' is not used. Store or pass the result of the call.",
    },
}
i18n.register(MESSAGES)


@lru_cache(maxsize=1)
def _checked_methods() -> dict[str, frozenset[str]]:
    """Per-receiver method spellings, already expanded with override guards by extraction."""
    try:
        data = dataset.load_json("stdlib.json").get("checked_return_methods") or {}
    except (dataset.DatasetError, KeyError, ValueError):
        return {}
    return {owner: frozenset(spelling for name in names
                            for spelling in (name, terms.member_english_of(owner, name)) if spelling)
            for owner, names in data.items()}


@lru_cache(maxsize=1)
def _checked_names() -> frozenset[str]:
    return frozenset(name for methods in _checked_methods().values() for name in methods)


dataset.register_reset(_checked_methods.cache_clear)
dataset.register_reset(_checked_names.cache_clear)


@rule(RULE, f"{RULE}.title", "D", severity=Severity.ERROR)
def unused_return_value(source: SourceFile) -> Iterable[Diagnostic]:
    """Only a standalone call on a known platform receiver drops a proven checked result.

    The short lambda body is an expression, not an ExprStmt. Compound expressions are
    left to statement-no-effect. Unknown/union receivers and old datasets remain silent.
    """
    checked = _checked_methods()
    names = _checked_names()
    if source.kind != "xbsl" or not any(name in source.text for name in names):
        return
    typing = typeinfer.file_typing(source)
    if typing is None:
        return
    statements = {id(node.expr) for node in typeinfer.walk_nodes(typing.tree)
                  if isinstance(node, P.ExprStmt) and isinstance(node.expr, P.Call)}
    if not statements:
        return
    lines = linemap(source)
    for site in typing.calls(names):
        if id(site.node) not in statements or not isinstance(site.owner, typeinfer.TypeSet):
            continue
        owner = site.owner
        if owner.size != 1 or owner.undefined or owner.null or not owner.names:
            continue
        head, _args = typeinfer.split_nominal(next(iter(owner.names)))
        canonical = typeinfer.platform_head(head)
        member = site.node.callee
        if canonical is None or member.name not in checked.get(canonical, ()):
            continue
        line, col = lines.linecol(member.end - len(member.name))
        yield Diagnostic(source.rel, line, col, RULE, Severity.ERROR,
                         i18n.t(f"{RULE}.found", method=member.name))
