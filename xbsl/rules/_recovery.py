"""Conservative views of recovered syntax for declaration-only rules.

The cached parser result is never modified. A damaged method is excluded in full;
its healthy siblings retain original offsets. A structure or enum may keep healthy
members only when every error belongs to a child, rather than to its own header or
declaration list. Rules requiring complete cross-member facts must not use this view.
"""
from dataclasses import replace
from xbsl import parser as P

def healthy_module(source):
    module, errors = P.parse(source)
    if not errors:
        return module
    def keep(node):
        inside = [error for error in errors if node.start <= error.start <= node.end]
        if not inside:
            return node
        children = (node.members if isinstance(node, P.Structure)
                    else node.methods if isinstance(node, P.Enum) else None)
        if children is None or any(
            not any(child.start <= error.start <= child.end for child in children)
            for error in inside
        ):
            return None
        kept = [filtered for child in children if (filtered := keep(child)) is not None]
        key = "members" if isinstance(node, P.Structure) else "methods"
        return replace(node, **{key: kept})
    return replace(module, members=[kept for node in module.members
                                    if (kept := keep(node)) is not None])
