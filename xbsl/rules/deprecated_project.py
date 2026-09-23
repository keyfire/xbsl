"""Tier D: a use of a project declaration marked deprecated - `code/deprecated-project`.

A project marks its own method, property, constructor, parameter or enumeration value with
`@Устарело` (`@Deprecated`), and the editor of the platform warns at every use that binds to
it. The rule reports those uses when the declaration they bind to is certain:

- a call of a method: by the bare name inside its module or its structure, through the module
  name from another module, or on a receiver the project typing names as one structure. The
  call is reported when every overload of the name is deprecated;
- an argument for a deprecated parameter of such a call, when the name has one overload: the
  argument at the position of the parameter or the argument that names it;
- `новый Структура(...)` of a structure of the same module whose constructor is deprecated;
- a module field by its bare name inside its module or through the module name, a structure
  field by its bare name inside the structure or on a receiver typed as the structure;
- `Перечисление.Значение` of an enumeration of the same module or of a module named before it.

Local names, parameters and members that shadow a name leave the use silent, and so does a
name the project declares twice. The text of the annotation joins the message only when it is a
plain string literal.
"""

from __future__ import annotations

from collections.abc import Iterable
from functools import lru_cache

from xbsl import i18n, terms, typeinfer
from xbsl import parser as P
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, rule
from xbsl.lexer import linemap
from xbsl.rules.procedure_value import _method_shadows, _TextSource

RULE_ID = "code/deprecated-project"

MESSAGES = {
    f"{RULE_ID}.title": {
        "ru": "Используется устаревшее объявление проекта",
        "en": "A deprecated project declaration is used",
    },
    f"{RULE_ID}.found": {
        "ru": "Используется устаревшее объявление: {what}.{note}",
        "en": "A deprecated declaration is used: {what}.{note}",
    },
    f"{RULE_ID}.method": {"ru": "метод '{name}'", "en": "method '{name}'"},
    f"{RULE_ID}.param": {
        "ru": "параметр '{param}' метода '{name}'",
        "en": "parameter '{param}' of method '{name}'",
    },
    f"{RULE_ID}.ctor": {"ru": "конструктор '{name}'", "en": "constructor of '{name}'"},
    f"{RULE_ID}.field": {"ru": "свойство '{name}'", "en": "property '{name}'"},
    f"{RULE_ID}.value": {"ru": "значение '{name}'", "en": "value '{name}'"},
}
i18n.register(MESSAGES)


@lru_cache(maxsize=1)
def _annotation_names() -> frozenset[str]:
    """Both spellings of the deprecation annotation."""
    try:
        forms = terms.key_forms("Устарело")
    except Exception:  # noqa: BLE001 - without the dictionary the two spellings are known anyway
        forms = ()
    return frozenset(forms) | {"Устарело", "Deprecated"}


def _plain(text: str) -> str:
    """The text of a plain string literal; empty for an interpolated or odd one."""
    if len(text) < 2 or not (text.startswith('"') and text.endswith('"')):
        return ""
    inner = text[1:-1]
    if "%{" in inner or "${" in inner:
        return ""
    return inner.replace('""', '"').strip()


def _mark(annotations) -> str | None:
    """None when the declaration is not deprecated, otherwise the note of its annotation."""
    for annotation in annotations or ():
        if annotation.name in _annotation_names():
            first = annotation.args[0] if annotation.args else None
            if isinstance(first, P.Literal) and first.kind == "STRING":
                return _plain(first.text)
            return ""
    return None


def _overload(method: P.Method) -> list:
    return [_mark(method.annotations), [[param.name, _mark(param.annotations)]
                                        for param in method.params]]


def _methods(members) -> dict[str, list]:
    """{name: overloads} of the names where an overload or a parameter is deprecated."""
    overloads: dict[str, list] = {}
    for member in members:
        if isinstance(member, P.Method):
            overloads.setdefault(member.name, []).append(_overload(member))
    return {
        name: forms for name, forms in overloads.items()
        if any(form[0] is not None or any(note is not None for _p, note in form[1])
               for form in forms)
    }


def _fields(members) -> dict[str, str]:
    return {member.name: note for member in members
            if isinstance(member, P.ObjectField)
            and (note := _mark(member.annotations)) is not None}


def declarations(tree: object) -> dict:
    """The deprecated declarations of one parsed module; empty when there are none."""
    members = getattr(tree, "members", ()) or ()
    out: dict = {}
    methods = _methods(members)
    if methods:
        out["methods"] = methods
    fields = _fields(members)
    if fields:
        out["fields"] = fields
    enums = {}
    structures = {}
    for member in members:
        if isinstance(member, P.Enum):
            values = {item.name: note for item in member.items
                      if (note := _mark(getattr(item, "annotations", ()))) is not None}
            if values:
                enums[member.name] = values
        elif isinstance(member, P.Structure):
            entry: dict = {}
            ctors = [inner for inner in member.members if isinstance(inner, P.Constructor)]
            if ctors and all(_mark(ctor.annotations) is not None for ctor in ctors):
                entry["ctor"] = _mark(ctors[0].annotations)
            own_methods = _methods(member.members)
            if own_methods:
                entry["methods"] = own_methods
            own_fields = _fields(member.members)
            if own_fields:
                entry["fields"] = own_fields
            if entry:
                structures[member.name] = entry
    if enums:
        out["enums"] = enums
    if structures:
        out["structures"] = structures
    return out


def _wants_text(source: SourceFile) -> bool:
    """Every parsed module may use a declaration of another one, so every module is typed."""
    if source.kind != "xbsl":
        return False
    _module, errors = P.parse(source)
    return not errors


typeinfer.wants_text(_wants_text)


def _mapper(source: SourceFile) -> dict | None:
    """The shared typing fact plus this module's own deprecated declarations."""
    shared = typeinfer.project_fact(source)
    if shared is None:
        return None
    fact = dict(shared)
    if source.kind == "xbsl" and shared.get("k") == "xbsl":
        tree, errors = P.parse(source)
        found = declarations(tree) if not errors else {}
        if found:
            fact["deprecated"] = found
    return fact


class _Index:
    """The deprecated declarations of one project, by module name."""

    def __init__(self, facts: dict[str, dict]) -> None:
        self.modules: dict[str, dict] = {}
        counts: dict[str, int] = {}
        for fact in facts.values():
            if fact.get("k") == "xbsl":
                counts[fact["module"]] = counts.get(fact["module"], 0) + 1
                if fact.get("deprecated"):
                    self.modules[fact["module"]] = fact["deprecated"]
        # A module name that two files share binds to neither of them.
        for name, count in counts.items():
            if count > 1:
                self.modules.pop(name, None)
        self.names = {name for name, count in counts.items() if count == 1}

    def of(self, module: str) -> dict:
        return self.modules.get(module) or {}

    def structure(self, qualified: str) -> dict:
        module, _, name = qualified.rpartition(".")
        return ((self.of(module).get("structures") or {}).get(name)) or {}


def _what(kind: str, name: str, param: str = "") -> str:
    return i18n.t(f"{RULE_ID}.{kind}", name=name, param=param)


class _Uses:
    """The uses of one module that bind to a deprecated declaration: (offset, kind, name, param,
    note)."""

    def __init__(self, typing: typeinfer.ModuleTyping, index: _Index) -> None:
        self.typing = typing
        self.index = index
        self.module = typing.scope.module or ""
        self.own = index.of(self.module)
        self.found: list[tuple[int, str, str, str, str]] = []

    # -- what a name binds to -----------------------------------------------------------------

    def _other_module(self, name: str, shadows: frozenset[str]) -> dict | None:
        if name in shadows or name == self.module or name not in self.index.names:
            return None
        if name in self._own_names():
            return None
        return self.index.of(name)

    def _own_names(self) -> frozenset[str]:
        module = self.typing.catalog.modules.get(self.module) or {}
        return frozenset({
            *(module.get("methods") or {}), *(module.get("structures") or {}),
            *(module.get("enums") or {}), *(module.get("fields") or {}),
            *self.typing.scope.own_properties, *self.typing.scope.opaque,
        })

    # -- reporting ----------------------------------------------------------------------------

    def _add(self, offset: int, kind: str, name: str, note: str, param: str = "") -> None:
        self.found.append((offset, kind, name, param, note))

    def _call(self, call: P.Call, forms: list | None, name: str) -> None:
        """A call bound to a method name with the overloads `forms`."""
        if not forms:
            return
        if all(form[0] is not None for form in forms):
            notes = {form[0] for form in forms}
            self._add(call.start, "method", name, notes.pop() if len(notes) == 1 else "")
        if len(forms) != 1:
            return
        params = forms[0][1]
        by_name = {param_name: (param_name, note) for param_name, note in params}
        position = 0
        for argument in call.args:
            if argument.name:
                target = by_name.get(argument.name)
            else:
                target = tuple(params[position]) if position < len(params) else None
                position += 1
            if target is not None and target[1] is not None:
                start = argument.value.start if argument.value is not None else argument.start
                self._add(start, "param", name, target[1], param=target[0])

    # -- the walk -----------------------------------------------------------------------------

    def run(self) -> list[tuple[int, str, str, str, str]]:
        tree = self.typing.tree
        if not isinstance(tree, P.Module):
            return self.found
        for member in tree.members:
            if isinstance(member, P.Method):
                self._walk(member, _method_shadows(member), None)
            elif isinstance(member, P.ObjectField) and member.init is not None:
                self._walk(member.init, frozenset(), None)
            elif isinstance(member, P.Structure):
                fields = frozenset(inner.name for inner in member.members
                                   if isinstance(inner, P.ObjectField))
                for inner in member.members:
                    if isinstance(inner, P.Method):
                        self._walk(inner, frozenset(_method_shadows(inner) | fields), member)
                    elif isinstance(inner, P.ObjectField) and inner.init is not None:
                        self._walk(inner.init, fields, member)
        self._typed_members()
        return self.found

    def _walk(self, root: object, shadows: frozenset[str], owner: P.Structure | None) -> None:
        nodes = typeinfer.walk_nodes(root)
        callees = {id(node.callee) for node in nodes if isinstance(node, P.Call)}
        members = {id(node.obj) for node in nodes if isinstance(node, P.Member)}
        owner_entry = (self.own.get("structures") or {}).get(owner.name) if owner else None
        owner_methods = {inner.name for inner in owner.members
                         if isinstance(inner, P.Method)} if owner else set()
        for node in nodes:
            if isinstance(node, P.Call):
                self._visit_call(node, shadows, owner_entry, owner_methods)
            elif isinstance(node, P.New):
                self._visit_new(node, shadows)
            elif isinstance(node, P.Member) and id(node) not in callees:
                self._visit_member(node, shadows)
            elif isinstance(node, P.Name) and id(node) not in callees:
                self._visit_name(node, shadows, owner, owner_entry, id(node) in members)

    def _visit_call(self, call: P.Call, shadows, owner_entry, owner_methods) -> None:
        callee = call.callee
        if isinstance(callee, P.Name):
            name = callee.name
            if name in shadows or "::" in name:
                return
            if name in owner_methods:
                self._call(call, ((owner_entry or {}).get("methods") or {}).get(name), name)
                return
            self._call(call, (self.own.get("methods") or {}).get(name), name)
        elif (isinstance(callee, P.Member) and isinstance(callee.obj, P.Name)
              and not callee.safe):
            other = self._other_module(callee.obj.name, shadows)
            if other is not None:
                self._call(call, (other.get("methods") or {}).get(callee.name),
                           f"{callee.obj.name}.{callee.name}")

    def _visit_new(self, node: P.New, shadows) -> None:
        names = node.type.names if node.type is not None else []
        if len(names) != 1 or names[0] in shadows:
            return
        entry = (self.own.get("structures") or {}).get(names[0])
        if entry and "ctor" in entry:
            self._add(node.start, "ctor", names[0], entry["ctor"])

    def _visit_member(self, node: P.Member, shadows) -> None:
        obj = node.obj
        if isinstance(obj, P.Name):
            if obj.name in shadows:
                return
            values = (self.own.get("enums") or {}).get(obj.name)
            if values is not None:
                if node.name in values:
                    self._add(node.start, "value", f"{obj.name}.{node.name}", values[node.name])
                return
            other = self._other_module(obj.name, shadows)
            if other is not None and node.name in (other.get("fields") or {}):
                self._add(node.start, "field", f"{obj.name}.{node.name}",
                          other["fields"][node.name])
        elif isinstance(obj, P.Member) and isinstance(obj.obj, P.Name):
            other = self._other_module(obj.obj.name, shadows)
            values = ((other or {}).get("enums") or {}).get(obj.name)
            if values is not None and node.name in values:
                self._add(node.start, "value", f"{obj.obj.name}.{obj.name}.{node.name}",
                          values[node.name])

    def _visit_name(self, node: P.Name, shadows, owner, owner_entry, is_receiver) -> None:
        name = node.name
        if name in shadows and owner is not None and owner_entry:
            # Inside a structure a bare name is the structure's own field first.
            fields = owner_entry.get("fields") or {}
            if name in fields and name not in _local_names(shadows, owner):
                self._add(node.start, "field", name, fields[name])
            return
        if name in shadows or "::" in name:
            return
        fields = self.own.get("fields") or {}
        if name in fields:
            self._add(node.start, "field", name, fields[name])

    # -- members on typed receivers -----------------------------------------------------------

    def _typed_members(self) -> None:
        method_names: set[str] = set()
        field_names: set[str] = set()
        for declared in self._structures():
            method_names.update(declared.get("methods") or {})
            field_names.update(declared.get("fields") or {})
        if method_names:
            for call_site in self.typing.calls(frozenset(method_names)):
                target = self._receiver(call_site.owner)
                call = call_site.node
                if (target is not None and isinstance(call, P.Call)
                        and isinstance(call.callee, P.Member)):
                    name = call.callee.name
                    self._call(call, (target.get("methods") or {}).get(name), name)
        if field_names:
            for member_site in self.typing.members(frozenset(field_names)):
                target = self._receiver(member_site.owner)
                member = member_site.node
                if target is not None and isinstance(member, P.Member):
                    fields = target.get("fields") or {}
                    if member.name in fields:
                        self._add(member.start, "field", member.name, fields[member.name])

    def _structures(self) -> Iterable[dict]:
        for declared in self.index.modules.values():
            yield from (declared.get("structures") or {}).values()

    def _receiver(self, owner: object) -> dict | None:
        """The declarations of the one project structure a typed receiver is, else None."""
        if not isinstance(owner, typeinfer.TypeSet):
            return None
        names = owner.without_undefined().names
        if len(names) != 1:
            return None
        (qualified,) = names
        if "." not in qualified:
            return None
        return self.index.structure(qualified) or None


def _local_names(shadows: frozenset[str], owner: P.Structure) -> frozenset[str]:
    """The names of `shadows` that are not the structure's own fields: locals and parameters."""
    fields = {inner.name for inner in owner.members if isinstance(inner, P.ObjectField)}
    return frozenset(shadows - fields)


@rule(
    RULE_ID, f"{RULE_ID}.title", "D", scope="project", severity=Severity.WARNING,
    mapper=_mapper,
)
def deprecated_project(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    """A use bound to a project declaration marked deprecated."""
    typings = typeinfer.project_typings(facts)
    if not any(fact.get("deprecated") for fact in facts.values()):
        return
    for group in typeinfer._projects(facts).values():
        index = _Index(group)
        if not index.modules:
            continue
        for rel in sorted(group):
            typing = typings.get(rel)
            if typing is None:
                continue
            found = _Uses(typing, index).run()
            if not found:
                continue
            line_map = linemap(_TextSource(typing.text))
            seen: set[tuple[int, str]] = set()
            for offset, kind, name, param, note in sorted(found):
                if (offset, kind) in seen:
                    continue
                seen.add((offset, kind))
                line, column = line_map.linecol(offset)
                yield Diagnostic(
                    rel, line, column, RULE_ID, Severity.WARNING,
                    i18n.t(f"{RULE_ID}.found", what=_what(kind, name, param),
                           note=f" {note}" if note else ""),
                )
