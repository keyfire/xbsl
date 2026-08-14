"""Event handlers of the form designer: the paired module model and stub generation.

Implements the engine half of hook 1 (docs/DESIGNER.md): the properties panel lists the
methods of the component's paired module (same stem, `.xbsl`) and creates handler stubs
with the right signature. Kept separate from formedits.py on purpose: the yaml operations
there are single-file text edits over the form model, while a handler spans TWO files and
needs the full XBSL parser (xbsl.parser) - a different dependency set.

Surfaces (the same trio as the rest of the designer):
    - LSP `xbsl/moduleHandlers` and `xbsl/addHandler` (lsp.py) - compute only, the editor
      applies a multi-file WorkspaceEdit;
    - MCP `meta_add_handler` (mcp_server.py) - applies to disk and lints what it wrote;
    - CLI `xbsl form-handlers` (cli.py) - the list mode and the writing mode.

Documented decisions:
    - The module is parsed with the full engine parser (xbsl.parser.parse_text); only
      TOP-LEVEL methods are listed - methods of structures and enumerations are not
      handler candidates. The parser recovers from errors, so a half-written module still
      yields its methods; the error count is reported alongside.
    - Stub parameters are named the way the builtin code templates name them (templates_builtin.py "кнопкаНажатие"): the first parameter is
      `Источник` (the component that fired the event), the second is `Событие`;
      a hypothetical third and beyond become `ПараметрN`. Parameter types are written.
    - The generated stub carries NO annotation: handlers are bound by name from the yaml
      and the builtin template spells them without one (`@НаКлиенте` on a handler is legal but not the accepted convention).
    - Generic event signatures are grounded through the node's own type: the formal type
      parameters of the signature's first argument (`ПолеВвода<ТипДанных>`) are mapped to
      the actual arguments of the node's `Тип:` (`ПолеВвода<Строка>`) and substituted
      across all parameter and return types. Unresolvable formals are left as written.
    - The default method name is `<Имя узла | Тип узла><КлючСобытия>` (КнопкаОплатить +
      ПриНажатии -> КнопкаОплатитьПриНажатии), uniquified with a number against the
      module's methods. An explicitly passed name that already exists in the module means
      "bind to it": only the yaml changes.
    - A missing module file is created with the stub as its whole content - the same
      shape scaffold._add_operation_handler writes; a new file takes the newline style of
      the paired yaml, an existing one keeps its own.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from xbsl import dataset, engine, formedits, terms, uischema
from xbsl.formmodel import Node, _dominant_nl, get_component, parse_form
from xbsl.parser import Method, parse_text
from xbsl.scaffold import FileChange, ScaffoldResult, TextEdit, _cursor_at

#: Visibility annotations of module members (the XBSL counterpart of "export"), both
#: spellings: the module being read may be written either way.
@lru_cache(maxsize=1)
def _visibility_forms() -> frozenset[str]:
    return frozenset(terms.key_forms("Локально", "ВПодсистеме", "ВПроекте", "Глобально"))


dataset.register_reset(_visibility_forms.cache_clear)

_WORD = r"[\wА-Яа-яЁё]"
#: A bare method name in an event property (anything else - an expression, a binding - is
#: unbound without touching the module).
_NAME_RE = re.compile(rf"[A-Za-zА-Яа-яЁё_]{_WORD}*")
_METHOD_KW_RE = "(?:метод|method)"


# --- the module model -----------------------------------------------------------------


def module_methods(text: str) -> tuple[list[dict], int]:
    """Top-level methods of a module as JSON-simple dicts, plus the parse error count.

    Every entry: {"name", "static", "abstract", "annotations": [names], "visibility"
    (Локально/ВПодсистеме/ВПроекте/Глобально or None), "params": [{"name", "type"}],
    "returnType", "span": {start, end} (annotations included), "nameSpan": {start, end}
    (the method name token - the jump target; None when it cannot be located)}.
    """
    module, errors = parse_text(text)
    methods: list[dict] = []
    for member in module.members:
        if not isinstance(member, Method) or not member.name:
            continue
        annotations = [a.name for a in member.annotations if a.name]
        visibility = next((a for a in annotations if a in _visibility_forms()), None)
        methods.append({
            "name": member.name,
            "static": member.is_static,
            "abstract": member.is_abstract,
            "annotations": annotations,
            "visibility": visibility,
            "params": [
                {"name": p.name, "type": p.type.text if p.type else None}
                for p in member.params
            ],
            "returnType": member.return_type.text if member.return_type else None,
            "span": {"start": member.start, "end": member.end},
            "nameSpan": _name_span(text, member),
        })
    return methods, len(errors)


def _name_span(text: str, member: Method) -> dict | None:
    """The span of the method name token (skipping the annotations)."""
    search_start = member.annotations[-1].end if member.annotations else member.start
    m = re.search(
        rf"{_METHOD_KW_RE}[ \t]+({re.escape(member.name)})(?!{_WORD})",
        text[search_start:member.end],
    )
    if m is None:
        return None
    return {"start": search_start + m.start(1), "end": search_start + m.end(1)}


def module_path_for(yaml_path: Path) -> Path:
    """The paired module of a component: the same stem with the .xbsl suffix."""
    return Path(yaml_path).with_suffix(".xbsl")


# --- event signatures -------------------------------------------------------------------


def _depth_step(prev: str, ch: str, depth: int) -> int:
    """Nesting depth over <> and (); the ">" of a "->" arrow is not a bracket."""
    if ch in "<(":
        return depth + 1
    if ch == ")" or (ch == ">" and prev != "-"):
        return depth - 1
    return depth


def _split_top(s: str) -> list[str]:
    """Split by commas at the top nesting level of <> and ()."""
    parts: list[str] = []
    depth = 0
    prev = ""
    current = []
    for ch in s:
        depth = _depth_step(prev, ch, depth)
        if ch == "," and depth == 0:
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
        prev = ch
    tail = "".join(current).strip()
    if tail:
        parts.append(tail)
    return parts


def _is_wrapped(s: str) -> bool:
    """Whether the leading "(" closes only at the very end (the whole string is wrapped)."""
    depth = 0
    prev = ""
    for i, ch in enumerate(s):
        new_depth = _depth_step(prev, ch, depth)
        if new_depth < depth and new_depth == 0:
            return i == len(s) - 1
        depth = new_depth
        prev = ch
    return False


def parse_event_signature(signature: str) -> tuple[list[str], str | None]:
    """(argument types, return type) of a ui-schema event signature.

    Accepts the extractor's normalized forms: "(Кнопка, СобытиеПриНажатии)->ничто" and
    the nullable wrapping "((ОписаниеЗадания)->Булево)?". An unparseable string yields
    ([], None) - the stub degrades to a parameterless method rather than failing.
    """
    s = (signature or "").strip()
    if s.endswith("?"):
        s = s[:-1].strip()
    if s.startswith("(") and s.endswith(")") and _is_wrapped(s):
        inner = s[1:-1].strip()
        if "->" in inner:
            s = inner
    if not s.startswith("("):
        return [], None
    depth = 0
    prev = ""
    args_end = -1
    for i, ch in enumerate(s):
        new_depth = _depth_step(prev, ch, depth)
        if new_depth < depth and new_depth == 0:
            args_end = i
            break
        depth = new_depth
        prev = ch
    if args_end < 0 or s[args_end + 1: args_end + 3] != "->":
        return [], None
    args = _split_top(s[1:args_end])
    ret = s[args_end + 3:].strip() or None
    return args, ret


def _generic_map(first_arg: str, node_type_full: str | None) -> dict[str, str]:
    """Formal type parameters of the signature's first argument -> the node's actuals.

    "(ПолеВвода<ТипДанных>, ...)" on a node of type ПолеВвода<Строка> yields
    {ТипДанных: Строка}. No mapping when the roots differ, either side has no generic
    arguments or the argument counts do not match.
    """
    if not node_type_full or not first_arg:
        return {}
    fa, nt = first_arg.strip(), node_type_full.strip()
    fa_open, nt_open = fa.find("<"), nt.find("<")
    if fa_open < 0 or nt_open < 0 or not fa.endswith(">") or not nt.endswith(">"):
        return {}
    if fa[:fa_open].strip() != nt[:nt_open].strip():
        return {}
    formals = _split_top(fa[fa_open + 1:-1])
    actuals = _split_top(nt[nt_open + 1:-1])
    if len(formals) != len(actuals):
        return {}
    return {
        f: a for f, a in zip(formals, actuals)
        if re.fullmatch(rf"{_WORD}+", f) and a
    }


def _substitute(type_text: str, mapping: dict[str, str]) -> str:
    if not mapping or not type_text:
        return type_text
    pattern = re.compile(
        "|".join(rf"(?<!{_WORD}){re.escape(k)}(?!{_WORD})" for k in mapping)
    )
    return pattern.sub(lambda m: mapping[m.group(0)], type_text)


def event_signature_for(node_type: str | None, key: str) -> str | None:
    """The event signature of the component's property from the ui schema, if available.

    Degrades silently to None: without the generated dataset (a public checkout) the
    stub is simply parameterless.
    """
    if not node_type or not key:
        return None
    try:
        rec = uischema.component(node_type)
    except Exception:  # noqa: BLE001 - a broken dataset must not break the operation
        return None
    comp = rec.get("component") if rec.get("available") else None
    if not comp:
        return None
    sig = ((comp.get("props") or {}).get(key) or {}).get("event")
    return str(sig) if sig else None


# --- stub generation ----------------------------------------------------------------------


def _return_placeholder(return_type: str) -> str:
    root = return_type.split("<")[0].strip().rstrip("?")
    if root == "Булево":
        return "Истина"
    if root.startswith("Число"):
        return "0"
    if root == "Строка":
        return '""'
    return "Неопределено"


def _stub_text(
    method: str, params: list[tuple[str, str | None]], return_type: str | None, nl: str
) -> str:
    """The method stub itself: `метод Имя(П: Тип)` plus a TODO body and a placeholder return."""
    written = [f"{name}: {type_}" if type_ else name for name, type_ in params]
    returns = return_type and return_type != "ничто"
    ret = f": {return_type}" if returns else ""
    lines = [f"метод {method}({', '.join(written)}){ret}", "    // TODO: действия обработчика"]
    if returns:
        lines.append(f"    возврат {_return_placeholder(return_type)}")
    lines.append(";")
    return nl.join(lines) + nl


def _handler_stub(method: str, arg_types: list[str], return_type: str | None, nl: str) -> str:
    """The handler method stub, in the shape of the builtin code templates.

    No annotation on purpose: handlers are bound by name from the yaml (see the module
    docstring). A non-"ничто" return type gets a placeholder return so the module stays
    compilable.
    """
    names = ("Источник", "Событие")
    params = []
    for i, t in enumerate(arg_types):
        name = names[i] if i < len(names) else f"Параметр{i + 1}"
        params.append((name, t or None))
    return _stub_text(method, params, return_type, nl)


def default_handler_name(node: Node, key: str) -> str:
    """<Имя узла | Тип узла><КлючСобытия>; the key alone when the node has neither."""
    base = node.name or node.type or ""
    return f"{base}{key}"


# --- the two-file operation -----------------------------------------------------------------


@dataclass
class HandlerPlan:
    """The computed changes of add_handler; offsets are relative to the input texts."""

    method: str
    created: bool  # the module FILE is created from scratch (new_module_text is its content)
    method_added: bool  # a stub was appended (False - bound to an existing method)
    yaml_edits: list[TextEdit]  # empty when the yaml already binds the key to the method
    new_yaml_text: str
    module_edits: list[TextEdit]  # edits of the EXISTING module text (empty when created)
    new_module_text: str
    cursor_offset: int  # offset of the method name in new_module_text (the jump target)
    notes: list[str] = field(default_factory=list)


def add_handler(
    yaml_text: str,
    module_text: str | None,
    node_id: str,
    key: str,
    method_name: str | None = None,
    event_signature: str | None = None,
) -> HandlerPlan:
    """Bind an event property to a handler method, generating the stub when needed.

    Computes edits of BOTH files of the pair: the yaml gets `key: Метод` (through
    formedits.set_property - the same guarantees), the module gets a stub appended at
    the end of the file. module_text=None means the module file does not exist - the
    plan carries the full content of the new file (created=True).

    method_name: an explicit handler name; when it already exists in the module, only
    the yaml changes. Without it the name is `<Имя|Тип узла><Ключ>` uniquified with a
    number, and a stub is always appended.

    event_signature: the "(Тип, СобытиеТипа)->ничто" string from the ui schema; None -
    looked up in the local dataset by the node's type, and when that is unavailable the
    stub is parameterless. Generic formals of the signature are substituted from the
    node's own `Тип:` arguments.
    """
    form = parse_form(yaml_text)
    node = get_component(form, node_id)
    formedits._check_property_key(key)
    methods, _errors = module_methods(module_text) if module_text is not None else ([], 0)
    existing = {m["name"]: m for m in methods}
    notes: list[str] = []

    if method_name:
        method = formedits._check_name(method_name)
        method_added = method not in existing
    else:
        base = default_handler_name(node, key)
        if not base:
            raise formedits.FormModelError(
                f"У узла {node_id} нет ни имени, ни типа – укажите имя метода явно"
            )
        formedits._check_name(base)
        method = formedits._unique_name(base, set(existing)) if base in existing else base
        method_added = True

    # --- the yaml half: key: Метод ---------------------------------------------------------
    pair = node.pairs.get(key)
    current = None
    if pair is not None and pair.scalar_span is not None:
        current = yaml_text[pair.scalar_span.start: pair.scalar_span.end].strip()
    if current == method:
        yaml_edits: list[TextEdit] = []
        new_yaml_text = yaml_text
    else:
        res = formedits.set_property(yaml_text, node_id, key, value=method)
        yaml_edits, new_yaml_text = res.edits, res.new_text

    # --- the module half --------------------------------------------------------------------
    created = module_text is None
    if not method_added:
        name_span = existing[method].get("nameSpan") or existing[method]["span"]
        notes.append(f"Метод {method} уже есть в модуле – создана только привязка в yaml")
        return HandlerPlan(
            method=method, created=False, method_added=False,
            yaml_edits=yaml_edits, new_yaml_text=new_yaml_text,
            module_edits=[], new_module_text=module_text,
            cursor_offset=name_span["start"], notes=notes,
        )

    signature = event_signature
    if signature is None:
        signature = event_signature_for(node.type, key)
        if signature is None:
            notes.append(
                f"Сигнатура события {key} не найдена в ui-схеме – заготовка без параметров"
            )
    arg_types, return_type = parse_event_signature(signature) if signature else ([], None)
    if signature and not arg_types and return_type is None:
        notes.append(f"Сигнатура события не разобрана: {signature} – заготовка без параметров")
    mapping = _generic_map(arg_types[0], node.type_full) if arg_types else {}
    arg_types = [_substitute(t, mapping) for t in arg_types]
    if return_type:
        return_type = _substitute(return_type, mapping)

    nl = _dominant_nl(module_text) if module_text else form.nl
    stub = _handler_stub(method, arg_types, return_type, nl)
    if created:
        module_edits = []
        new_module_text = stub
        insert_offset = 0
    else:
        pos = len(module_text)
        prefix = "" if not module_text or module_text.endswith(("\n", "\r")) else nl
        addition = prefix + (nl if module_text else "") + stub
        module_edits = [TextEdit(pos, pos, addition)]
        new_module_text = module_text + addition
        insert_offset = pos + len(prefix) + (len(nl) if module_text else 0)
    name_rel = stub.index(f"метод {method}") + len("метод ")
    return HandlerPlan(
        method=method, created=created, method_added=True,
        yaml_edits=yaml_edits, new_yaml_text=new_yaml_text,
        module_edits=module_edits, new_module_text=new_module_text,
        cursor_offset=insert_offset + name_rel, notes=notes,
    )


@dataclass
class MethodPlan:
    """The computed changes of add_module_method; offsets are relative to the input text."""

    method: str
    created: bool  # the module FILE is created from scratch (new_module_text is its content)
    method_added: bool  # a stub was appended (False - the module already had the method)
    module_edits: list[TextEdit]  # edits of the EXISTING module text (empty when created)
    new_module_text: str
    cursor_offset: int  # offset of the method name in new_module_text (the jump target)
    notes: list[str] = field(default_factory=list)


def signature_like(
    yaml_text: str, key: str, methods: list[dict], exclude: str = ""
) -> tuple[list[tuple[str, str | None]], str | None, str]:
    """The signature of a handler ALREADY bound to the same key elsewhere in the yaml.

    A metadata handler is not an event of the ui schema: nothing declares what the platform
    passes to it. The working code does, though - the other handlers of the same element are
    written against the same contract, so a new stub is shaped after its neighbours (an HTTP
    service, for instance, hands every handler its request). Returns the parameters, the
    return type and the name of the method they were taken from; an empty name means no
    neighbour was found and the caller gets a parameterless stub.
    """
    by_name = {m.get("name"): m for m in methods if m.get("name")}
    pattern = re.compile(rf"^\s*(?:-\s*)?{re.escape(key)}\s*:\s*(\S+)\s*$", re.MULTILINE)
    for match in pattern.finditer(yaml_text or ""):
        name = match.group(1).strip().strip("\"'")
        if not name or name == exclude or name.startswith("="):
            continue
        found = by_name.get(name)
        if not found:
            continue
        params = [(p.get("name") or "", p.get("type")) for p in found.get("params") or []]
        return params, found.get("returnType"), name
    return [], None, ""


def add_module_method(
    module_text: str | None,
    method: str,
    params: list[tuple[str, str | None]] | None = None,
    return_type: str | None = None,
) -> MethodPlan:
    """Append a method stub to a module (or make it the whole new file).

    The half of add_handler that touches the MODULE, addressed by nothing but the module
    itself: the metadata panel writes its own yaml property (a metadata handler sits at a
    yaml offset, not at a component node), and asks the engine for the code alone. A method
    the module already has is not written twice - the plan then only points at it.
    """
    formedits._check_name(method)
    methods, _errors = module_methods(module_text) if module_text is not None else ([], 0)
    existing = {m["name"]: m for m in methods}
    if method in existing:
        name_span = existing[method].get("nameSpan") or existing[method]["span"]
        return MethodPlan(
            method=method, created=False, method_added=False,
            module_edits=[], new_module_text=module_text or "",
            cursor_offset=name_span["start"],
            notes=[f"Метод {method} уже есть в модуле – код не менялся"],
        )
    nl = _dominant_nl(module_text) if module_text else "\n"
    stub = _stub_text(method, list(params or []), return_type, nl)
    created = module_text is None
    if created:
        module_edits: list[TextEdit] = []
        new_module_text = stub
        insert_offset = 0
    else:
        pos = len(module_text)
        prefix = "" if not module_text or module_text.endswith(("\n", "\r")) else nl
        addition = prefix + (nl if module_text else "") + stub
        module_edits = [TextEdit(pos, pos, addition)]
        new_module_text = module_text + addition
        insert_offset = pos + len(prefix) + (len(nl) if module_text else 0)
    name_rel = stub.index(f"метод {method}") + len("метод ")
    return MethodPlan(
        method=method, created=created, method_added=True,
        module_edits=module_edits, new_module_text=new_module_text,
        cursor_offset=insert_offset + name_rel,
    )


@dataclass
class RemovalPlan:
    """The computed changes of remove_handler; offsets are relative to the input texts."""

    method: str | None  # the method the key was bound to (None - the key held no name)
    yaml_edits: list[TextEdit]
    new_yaml_text: str
    module_edits: list[TextEdit]  # empty when the method is kept or the module has none
    new_module_text: str | None
    method_removed: bool
    notes: list[str] = field(default_factory=list)


def remove_handler(
    yaml_text: str,
    module_text: str | None,
    node_id: str,
    key: str,
    drop_method: bool = False,
) -> RemovalPlan:
    """Unbind an event property, optionally deleting its method from the module.

    The mirror of add_handler: the yaml half is formedits.reset_property (the key leaves
    the node), the module half deletes the whole method - its annotations included, the
    span module_methods reports - together with the blank line that separated it, so the
    file is left as if the method had never been written. drop_method=False touches the
    module not at all.

    A key bound to an expression rather than a plain name, and a method the module does
    not have, unbind just as well: there is simply nothing to delete, and a note says so.
    """
    form = parse_form(yaml_text)
    node = get_component(form, node_id)
    formedits._check_property_key(key)
    notes: list[str] = []

    pair = node.pairs.get(key)
    method: str | None = None
    if pair is not None and pair.scalar_span is not None:
        candidate = yaml_text[pair.scalar_span.start: pair.scalar_span.end].strip()
        if candidate and _NAME_RE.fullmatch(candidate):
            method = candidate

    res = formedits.reset_property(yaml_text, node_id, key)
    yaml_edits, new_yaml_text = res.edits, res.new_text

    if not drop_method or method is None or module_text is None:
        if drop_method and method is None:
            notes.append(f"Свойство {key} не ссылается на метод модуля – удалять нечего")
        return RemovalPlan(
            method=method, yaml_edits=yaml_edits, new_yaml_text=new_yaml_text,
            module_edits=[], new_module_text=module_text, method_removed=False, notes=notes,
        )

    methods, _errors = module_methods(module_text)
    target = next((m for m in methods if m["name"] == method), None)
    if target is None:
        notes.append(f"Метода {method} в модуле нет – удалена только привязка в yaml")
        return RemovalPlan(
            method=method, yaml_edits=yaml_edits, new_yaml_text=new_yaml_text,
            module_edits=[], new_module_text=module_text, method_removed=False, notes=notes,
        )

    start, end = _method_cut(module_text, target["span"]["start"], target["span"]["end"])
    module_edits = [TextEdit(start, end, "")]
    new_module_text = module_text[:start] + module_text[end:]
    return RemovalPlan(
        method=method, yaml_edits=yaml_edits, new_yaml_text=new_yaml_text,
        module_edits=module_edits, new_module_text=new_module_text,
        method_removed=True, notes=notes,
    )


def _method_cut(text: str, start: int, end: int) -> tuple[int, int]:
    """The range to delete for a method: its span grown to whole lines and one separator.

    A method is written as a block between blank lines, so cutting the span alone would
    leave either two blank lines in a row or a stray indent. The cut starts at the
    beginning of the method's own line and swallows the blank lines AFTER it; when the
    method is the last thing in the file, the blank lines BEFORE it go instead.
    """
    line_start = text.rfind("\n", 0, start) + 1
    if not text[line_start:start].strip():
        start = line_start
    after = end
    while after < len(text) and text[after] in " \t":
        after += 1
    while after < len(text) and text[after] in "\r\n":
        after += 1
        # a following blank line belongs to the method's own separation
        probe = after
        while probe < len(text) and text[probe] in " \t":
            probe += 1
        if probe >= len(text) or text[probe] not in "\r\n":
            break
        after = probe
    if after >= len(text):
        # Nothing follows the method: the blank lines BEFORE it go instead, leaving exactly
        # one line break after whatever the previous content was.
        probe = start
        while probe > 0 and text[probe - 1] in " \t\r\n":
            probe -= 1
        if probe == 0:
            start = 0
        else:
            nl = text.find("\n", probe)
            if 0 <= nl < start:
                start = nl + 1
    return start, after


@dataclass
class HandlerOutcome:
    result: ScaffoldResult  # the file changes; the caller applies (MCP/CLI) or serializes
    plan: HandlerPlan
    module_path: Path


def op_add_handler(
    yaml_path: Path,
    node_id: str,
    key: str,
    *,
    method: str | None = None,
    signature: str | None = None,
    reader=None,
) -> HandlerOutcome:
    """Run add_handler against the file pair (or their dirty buffers) as a ScaffoldResult.

    The module change carries a cursor at the handler method name. When nothing changes
    (the key already binds the requested existing method), the result has no changes and
    says so in notes.
    """
    yaml_path = Path(yaml_path)
    if not yaml_path.is_file():
        raise formedits.FormModelError(f"Файл не найден: {yaml_path}")
    read = reader if reader is not None else (lambda p: engine.load(p).text)
    yaml_text = read(yaml_path)
    module_path = module_path_for(yaml_path)
    module_text = read(module_path) if module_path.is_file() else None
    plan = add_handler(
        yaml_text, module_text, node_id, key,
        method_name=method, event_signature=signature,
    )
    result = ScaffoldResult(notes=list(plan.notes))
    if plan.yaml_edits:
        result.changes.append(FileChange(yaml_path, plan.new_yaml_text, created=False))
    if plan.method_added:
        cursor = _cursor_at(plan.new_module_text, plan.cursor_offset)
        result.changes.append(FileChange(
            module_path, plan.new_module_text, created=plan.created, cursor=cursor,
        ))
    if not result.changes:
        result.notes.append(f"Изменений нет: свойство {key} уже ссылается на метод {plan.method}")
    return HandlerOutcome(result=result, plan=plan, module_path=module_path)
