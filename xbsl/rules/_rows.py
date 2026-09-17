"""Horizontal rows and what their children draw on the baseline.

The shared reading behind `yaml/insert-row-needs-align` and `yaml/component-row-needs-align`
(both in xbsl/rules/yaml_render.py). A horizontal group without an explicit vertical alignment
lines its children up on the baseline. A native button keeps that line on its caption and a
native picture on its bottom edge, so the two stand at different heights - 19 px on a live row.
The rules need three answers about such a group:

- WHEN it is a row: a literal horizontal layout always, a layout binding in the states where a
  branch of its ternary yields the horizontal value;
- WHAT a child draws on the line: a button with a visible caption, a picture, or something
  nothing was measured for (then the child takes no part);
- WHETHER two children are shown together while the group is a row.

Conditions (`Visible`, the ternary of a layout binding, a method of a component module) are read
into small propositional formulas - tuples, so a mapper can hand them to the reduce step:

    ("T",) / ("F",)          a constant
    ("and", a, b) / ("or", a, b) / ("not", a)
    ("eq", subject, literal, roots)   `subject == literal`; `!=` is its negation
    ("name", identifier)     a bare name - a component property when the component declares it
    ("call", identifier)     a call without arguments - a method of the component module
    ("atom", text, roots)    any other expression, compared by its text

Two children are compared only when the file can tell when they are shown together: one of them
is shown unconditionally, or both stand on the same conditions. Two DIFFERENT conditions of two
children may exclude each other in the program (a picture, or a button in its place) without the
file saying so, and such a pair gives no finding.

The satisfiability check then treats every distinct atom as a free variable. Two atoms with the
same text are one variable, which is how the layout binding of a page and the visibility of a
component inside it agree about the same common-module call. Two DIFFERENT atoms over the same
root name (`List.Count() > 0` and `List.Count() == 0`) may depend on each other in a way the text
does not show, so the check gives no answer there and the rules stay silent. Comparisons of one
subject with different constants are the one dependency read exactly: they exclude each other.

A project component is expanded only as far as it can be read statically:

- it draws a native button or picture UNCONDITIONALLY - the component inherits it, or its
  content leads to it through vertical groups with nothing else shown. The root of a custom
  component stands in the row itself, so its own alignment and visibility are read first;
- or it PICKS between a button and a picture by its own property. Every variant condition splits
  into the conjuncts that read the property (directly, or through a method of the component module
  whose whole body returns such a comparison) and the rest; the rest must be the same for every
  variant, so it decides whether the component draws anything at all, not which element it draws.
  The property value at the instance must be a literal (or the declared default, or the empty
  value of a nullable type), and any other content of the component must be hidden whenever the
  picked variant is shown.

Everything else is unresolvable, and an unresolvable child takes no part in a pair.
"""

from __future__ import annotations

import dataclasses
from functools import lru_cache
from itertools import combinations

from xbsl import dataset, lexer, terms, uischema
from xbsl import parser as P
from xbsl.rules.yaml_schema import _HAVE_YAML, _scalar_entries

if _HAVE_YAML:
    import yaml

BUTTON = "Кнопка"
PICTURE = "Картинка"
_GROUP = "Группа"
_CUSTOM = "ПроизвольныйКомпонент"

LAYOUT_KEY = "Компоновка"
ALIGN_KEY = "ВыравниваниеСодержимогоПоВертикали"
#: The vertical alignment a child sets for itself inside its group. The documentation says
#: conflicting alignments of neighbours resolve to the first one, so the outcome for a row is not
#: readable from the file - a child that sets it takes no part in a pair.
SELF_ALIGN_KEY = "ВыравниваниеВГруппеПоВертикали"
_VISIBLE_KEY = "Видимость"
_TITLE_KEY = "Заголовок"
_TITLE_DISPLAY_KEY = "ВидОтображенияЗаголовка"
_BUTTON_KIND_KEY = "Вид"
_CONTENT_KEYS = ("Содержимое", "Content")
INHERIT_KEYS = ("Наследует", "Inherits")
PROPERTIES_KEYS = ("Свойства", "Properties")

_LAYOUT_ENUM = "КомпоновкаСодержимого"
_HORIZONTAL = "Горизонтальная"
_VERTICAL = "Вертикальная"
_TITLE_DISPLAY_ENUM = "ВидОтображенияЗаголовка"
_ICON_ONLY = "Иконка"
_BUTTON_KIND_ENUM = "ВидКнопки"
_ACTION_ICON = "ИконкаДействия"

#: Plain yaml literals. The yaml keeps them as text, and other rules read the same pairs.
_TRUE_VALUES = frozenset({"Истина", "True", "true"})
_FALSE_VALUES = frozenset({"Ложь", "False", "false"})
_UNDEFINED_VALUES = frozenset({"Неопределено", "Undefined"})

#: More distinct conditions than this in one check is not a layout question any more; the check
#: gives no answer rather than walking a large truth table.
_MAX_ATOMS = 10

TRUE = ("T",)
FALSE = ("F",)


# --- spellings --------------------------------------------------------------------------------


def _value_forms(enum: str, value: str) -> frozenset[str]:
    """Both spellings of an enumeration value, from the platform's own dictionary."""
    return frozenset({value, uischema.enum_value_aliases(enum).get(value)} - {None})


@lru_cache(maxsize=1)
def _spellings() -> dict[str, frozenset[str]]:
    return {
        "horizontal": _value_forms(_LAYOUT_ENUM, _HORIZONTAL),
        "vertical": _value_forms(_LAYOUT_ENUM, _VERTICAL),
        "layout-type": frozenset(terms.forms(_LAYOUT_ENUM, "types")),
        "icon-only": _value_forms(_TITLE_DISPLAY_ENUM, _ICON_ONLY),
        "action-icon": _value_forms(_BUTTON_KIND_ENUM, _ACTION_ICON),
        "default-value": frozenset(terms.key_forms("ЗначениеПоУмолчанию")),
    }


@lru_cache(maxsize=1)
def _platform_components() -> frozenset[str]:
    schema = dataset.load_ui_schema()
    return frozenset((schema or {}).get("components") or ())


dataset.register_reset(_spellings.cache_clear)
dataset.register_reset(_platform_components.cache_clear)


# --- formulas ---------------------------------------------------------------------------------


def conjunction(*formulas: tuple) -> tuple:
    out = TRUE
    for formula in formulas:
        out = simplify(("and", out, formula))
    return out


def simplify(formula: tuple) -> tuple:
    """Constants folded away; a double negation removed."""
    tag = formula[0]
    if tag in ("and", "or"):
        left, right = simplify(formula[1]), simplify(formula[2])
        absorbing, neutral = (FALSE, TRUE) if tag == "and" else (TRUE, FALSE)
        if absorbing in (left, right):
            return absorbing
        if left == neutral:
            return right
        if right == neutral:
            return left
        return (tag, left, right)
    if tag == "not":
        inner = simplify(formula[1])
        if inner == TRUE:
            return FALSE
        if inner == FALSE:
            return TRUE
        if inner[0] == "not":
            return inner[1]
        return ("not", inner)
    return formula


def _keyword(word: str) -> str | None:
    return lexer._keyword_forms().get(word)


def _text(source: str, node) -> str:
    return " ".join(source[node.start:node.end].split())


def _roots(node) -> tuple[str, ...]:
    """The names every chain of the expression starts from: `A.B().C` -> `A`.

    Fields are read through `dataclasses.fields`: a node of the native build has no instance
    dictionary (tests/test_rules_native_safe.py).
    """
    found: set[str] = set()

    def walk(item) -> None:
        if isinstance(item, (list, tuple)):
            for element in item:
                walk(element)
        elif isinstance(item, P.Name):
            found.add(item.name)
        elif isinstance(item, P.Member):
            walk(item.obj)
        elif dataclasses.is_dataclass(item) and not isinstance(item, type):
            for field in dataclasses.fields(item):
                walk(getattr(item, field.name))

    walk(node)
    return tuple(sorted(found))


def _literal(node) -> tuple | None:
    """A constant: `Type.Value` of an enumeration, a boolean, the empty value, a number, a string."""
    if isinstance(node, P.Literal):
        if node.kind == "TRUE":
            return ("bool", True)
        if node.kind == "FALSE":
            return ("bool", False)
        if node.kind == "UNDEFINED":
            return ("undef",)
        if node.kind in ("NUMBER", "STRING"):
            return ("num" if node.kind == "NUMBER" else "str", node.text)
        return None
    if isinstance(node, P.Member) and isinstance(node.obj, P.Name) and not node.safe:
        return ("enum", node.obj.name, node.name)
    return None


def expression_formula(node, source: str) -> tuple:
    """The formula of a parsed condition; anything unknown becomes an atom."""
    if isinstance(node, P.Binary) and node.right is not None:
        word = _keyword(node.op)
        if word in ("AND", "OR"):
            tag = "and" if word == "AND" else "or"
            return (tag, expression_formula(node.left, source), expression_formula(node.right, source))
    if isinstance(node, P.Unary) and _keyword(node.op) == "NOT":
        return ("not", expression_formula(node.operand, source))
    if isinstance(node, P.Literal) and node.kind in ("TRUE", "FALSE"):
        return TRUE if node.kind == "TRUE" else FALSE
    if isinstance(node, P.Compare) and len(node.rest) == 1:
        operator, right = node.rest[0]
        if operator in ("==", "!=") and right is not None:
            left_value, right_value = _literal(node.first), _literal(right)
            if (left_value is None) != (right_value is None):
                subject = node.first if right_value is not None else right
                constant = right_value if right_value is not None else left_value
                equality = ("eq", _text(source, subject), constant, _roots(subject))
                return equality if operator == "==" else ("not", equality)
    if isinstance(node, P.Name):
        return ("name", node.name)
    if (isinstance(node, P.Call) and isinstance(node.callee, P.Name)
            and not node.args and not node.type_args):
        return ("call", node.callee.name)
    return ("atom", _text(source, node), _roots(node))


def _binding(value: str):
    """(expression, its text) of a `=...` scalar, or (None, "") when it does not parse."""
    stripped = value.strip()
    if not stripped.startswith("="):
        return None, ""
    text = stripped[1:]
    try:
        tokens = lexer.tokenize(text)
    except dataset.DatasetError:  # no language data: the binding is not readable
        return None, ""
    reader = P._Parser(tokens)
    expression = reader.expression()
    if reader.errors or not reader.at_end():
        return None, ""
    return expression, text


@lru_cache(maxsize=4096)
def binding_formula(value: str) -> tuple | None:
    """The condition a `=...` scalar computes, or None when it cannot be read."""
    expression, text = _binding(value)
    if expression is None:
        return None
    return simplify(expression_formula(expression, text))


dataset.register_reset(binding_formula.cache_clear)


def _atom_key(atom: tuple) -> tuple:
    return atom[:3] if atom[0] == "eq" else atom[:2]


def _atom_roots(atom: tuple) -> tuple[str, ...]:
    if atom[0] in ("eq", "atom"):
        return atom[-1]
    return (atom[1],)


def atoms(formula: tuple, out: dict | None = None) -> dict:
    """{key: atom} of every variable of the formula."""
    out = {} if out is None else out
    tag = formula[0]
    if tag in ("and", "or"):
        atoms(formula[1], out)
        atoms(formula[2], out)
    elif tag == "not":
        atoms(formula[1], out)
    elif tag not in ("T", "F"):
        out.setdefault(_atom_key(formula), formula)
    return out


def _evaluate(formula: tuple, state: dict) -> bool:
    tag = formula[0]
    if tag == "T":
        return True
    if tag == "F":
        return False
    if tag == "and":
        return _evaluate(formula[1], state) and _evaluate(formula[2], state)
    if tag == "or":
        return _evaluate(formula[1], state) or _evaluate(formula[2], state)
    if tag == "not":
        return not _evaluate(formula[1], state)
    return state[_atom_key(formula)]


def _distinct_constants(first: tuple, second: tuple) -> bool:
    """Whether one value cannot equal both constants."""
    if first == second:
        return False
    if "undef" in (first[0], second[0]):
        return True
    if first[0] != second[0]:
        return False
    if first[0] == "enum":
        return first[1] == second[1]
    return True


def satisfiable(*formulas: tuple) -> bool | None:
    """Whether one state makes every formula true; None when the conditions are not readable."""
    formula = conjunction(*formulas)
    if formula in (TRUE, FALSE):
        return formula == TRUE
    variables = atoms(formula)
    keys = list(variables)
    if len(keys) > _MAX_ATOMS:
        return None
    exclusive: list[tuple[int, int]] = []
    for (i, first), (j, second) in combinations(enumerate(keys), 2):
        one, other = variables[first], variables[second]
        if not set(_atom_roots(one)) & set(_atom_roots(other)):
            continue
        if (one[0] == "eq" and other[0] == "eq" and one[1] == other[1]
                and _distinct_constants(one[2], other[2])):
            exclusive.append((i, j))
            continue
        return None  # a dependency the text does not show
    for bits in range(1 << len(keys)):
        if any(bits >> i & 1 and bits >> j & 1 for i, j in exclusive):
            continue
        state = {key: bool(bits >> n & 1) for n, key in enumerate(keys)}
        if _evaluate(formula, state):
            return True
    return False


# --- rows and children ------------------------------------------------------------------------


def component_children(mapping) -> list:
    """Direct child components of a node: the mappings of its content key."""
    for key, value in mapping.value:
        if isinstance(key, yaml.ScalarNode) and key.value in _CONTENT_KEYS:
            if isinstance(value, yaml.SequenceNode):
                return [item for item in value.value if isinstance(item, yaml.MappingNode)]
            if isinstance(value, yaml.MappingNode):
                return [value]
            return []
    return []


def type_name(mapping) -> str | None:
    """The component type as written, without a namespace and without type arguments."""
    entry = _scalar_entries(mapping).get("Тип")
    if entry is None or not isinstance(entry[1], yaml.ScalarNode):
        return None
    head = entry[1].value.split("<", 1)[0].strip()
    return head.rsplit("::", 1)[-1] or None


def component_kind(mapping) -> str | None:
    """The canonical component name of a node, or None when it declares no type."""
    written = type_name(mapping)
    return uischema.canonical_component(written) if written else None


def _plain(entry) -> str | None:
    """The text of a plain or quoted scalar value, or None for a block or a structure."""
    if entry is None or not isinstance(entry[1], yaml.ScalarNode) or entry[1].style in ("|", ">"):
        return None
    return entry[1].value.strip()


def row_formula(entries: dict) -> tuple | None:
    """The states in which a group lays its children out in a row, or None when never.

    A binding counts in the branches of its ternary that are statically horizontal; a branch the
    text does not name (a call, another value) is taken as not horizontal.
    """
    value = _plain(entries.get(LAYOUT_KEY))
    if value is None:
        return None
    if not value.startswith("="):
        return TRUE if value in _spellings()["horizontal"] else None
    expression, text = _binding(value)
    if expression is None:
        return None
    formula = simplify(_layout_branches(expression, text))
    return None if formula == FALSE else formula


def _layout_branches(node, text: str) -> tuple:
    if isinstance(node, P.Ternary) and node.otherwise is not None:
        condition = expression_formula(node.cond, text)
        return ("or",
                ("and", condition, _layout_branches(node.then, text)),
                ("and", ("not", condition), _layout_branches(node.otherwise, text)))
    spellings = _spellings()
    if (isinstance(node, P.Member) and isinstance(node.obj, P.Name)
            and node.obj.name in spellings["layout-type"] and node.name in spellings["horizontal"]):
        return TRUE
    return FALSE


def is_horizontal(entries: dict) -> bool:
    """Whether the layout is the literal horizontal value; a binding does not count here."""
    return _plain(entries.get(LAYOUT_KEY)) in _spellings()["horizontal"]


def is_vertical(entries: dict) -> bool:
    return _plain(entries.get(LAYOUT_KEY)) in _spellings()["vertical"]


def visibility(entries: dict) -> tuple | None:
    """The states in which the node is shown; None when the condition cannot be read."""
    entry = entries.get(_VISIBLE_KEY)
    if entry is None:
        return TRUE
    value = _plain(entry)
    if value is None:
        return None
    if value in _TRUE_VALUES:
        return TRUE
    if value in _FALSE_VALUES:
        return FALSE
    return binding_formula(value) if value.startswith("=") else None


def caption_view(entries: dict) -> dict[str, str]:
    """The keys that decide whether a button shows its caption, as text.

    A structured value (a localized string written out) is a caption too; it is kept as a marker.
    """
    view: dict[str, str] = {}
    for key in (_TITLE_KEY, _TITLE_DISPLAY_KEY, _BUTTON_KIND_KEY):
        entry = entries.get(key)
        if entry is None:
            continue
        text = _plain(entry)
        view[key] = "=struct" if text is None else text
    return view


def shows_caption(view: dict[str, str]) -> bool:
    """Whether a button shows a text caption - the only button a measurement stands behind."""
    title = view.get(_TITLE_KEY)
    if not title:
        return False
    spellings = _spellings()
    for key, forbidden in ((_TITLE_DISPLAY_KEY, "icon-only"), (_BUTTON_KIND_KEY, "action-icon")):
        value = view.get(key)
        if value is None:
            continue
        if value.startswith("=") or value.rsplit(".", 1)[-1] in spellings[forbidden]:
            return False
    return True


def participant(mapping) -> tuple[str, tuple] | None:
    """(kind, shown) of a native button with a caption or a native picture, else None."""
    kind = component_kind(mapping)
    if kind not in (BUTTON, PICTURE):
        return None
    entries = _scalar_entries(mapping)
    if SELF_ALIGN_KEY in entries:
        return None
    if kind == BUTTON and not shows_caption(caption_view(entries)):
        return None
    shown = visibility(entries)
    if shown is None or shown == FALSE:
        return None
    return kind, shown


def label(mapping) -> str:
    """How a finding names a child: its `Name`, or its type when it has none."""
    name = _plain(_scalar_entries(mapping).get("Имя"))
    return name or type_name(mapping) or "?"


def _read_together(first: tuple, second: tuple) -> bool:
    """Whether the file can tell when two children are shown together.

    A child shown unconditionally is there in every state, so the other child's condition alone
    decides. Two conditional children are compared only when they stand on the same conditions:
    two different conditions may exclude each other in the program (a picture, or a button in its
    place), and nothing in the file says so.
    """
    if TRUE in (first, second):
        return True
    return set(atoms(first)) == set(atoms(second))


def conflict(horizontal: tuple, children: list[tuple[str, tuple, str]]) -> tuple[str, str] | None:
    """(button label, picture label) of the first pair shown together in the row, or None.

    `children` holds (kind, shown, label) of the children that take part.
    """
    for first, second in combinations(children, 2):
        if {first[0], second[0]} != {BUTTON, PICTURE}:
            continue
        if not _read_together(first[1], second[1]):
            continue
        if satisfiable(horizontal, first[1], second[1]) is True:
            button, picture = (first, second) if first[0] == BUTTON else (second, first)
            return button[2], picture[2]
    return None


# --- project components -----------------------------------------------------------------------


def literal_value(node) -> tuple:
    """The value an instance gives a property: a constant, or ("expr",) for anything computed."""
    if not isinstance(node, yaml.ScalarNode) or node.style in ("|", ">"):
        return ("expr",)
    value = node.value.strip()
    if value.startswith("="):
        expression, _text_ = _binding(value)
        constant = _literal(expression) if expression is not None else None
        return constant if constant is not None else ("expr",)
    if not value or value.startswith("$"):
        return ("expr",)
    if value in _TRUE_VALUES:
        return ("bool", True)
    if value in _FALSE_VALUES:
        return ("bool", False)
    if value in _UNDEFINED_VALUES:
        return ("undef",)
    return ("plain", value)


def _raw(mapping, keys) -> object:
    for key, value in mapping.value:
        if isinstance(key, yaml.ScalarNode) and key.value in keys:
            return value
    return None


def component_fact(root, name: str) -> dict:
    """What a component description tells the reduce step: its properties and what it draws."""
    properties: dict[str, dict] = {}
    declared = _raw(root, PROPERTIES_KEYS)
    if isinstance(declared, yaml.SequenceNode):
        default_keys = _spellings()["default-value"]
        for item in declared.value:
            if not isinstance(item, yaml.MappingNode):
                continue
            entries = _scalar_entries(item)
            prop = _plain(entries.get("Имя"))
            if not prop:
                continue
            default = _raw(item, default_keys)
            properties[prop] = {
                "type": _plain(entries.get("Тип")) or "",
                "default": literal_value(default) if default is not None else None,
            }
    inherit = _raw(root, INHERIT_KEYS)
    draws = _draws(inherit) if isinstance(inherit, yaml.MappingNode) else None
    return {"name": name, "props": properties, "draws": draws}


def _draws(inherit) -> dict | None:
    kind = component_kind(inherit)
    if kind in (BUTTON, PICTURE):
        entries = _scalar_entries(inherit)
        if SELF_ALIGN_KEY in entries:
            return None
        shown = visibility(entries)
        if shown is None:
            return None
        # The caption of an inherited button may come from the instance: the reduce step merges
        # the instance keys over these before judging it.
        return {"alts": [[kind, shown]], "others": [], "caption": caption_view(entries)}
    if kind == _CUSTOM:
        # The root sits in the row itself: its own alignment and visibility come first.
        entries = _scalar_entries(inherit)
        if SELF_ALIGN_KEY in entries:
            return None
        shown = visibility(entries)
        if shown is None or shown == FALSE:
            return None
        content = component_children(inherit)
        return _under(shown, _carrier(content[0]) if len(content) == 1 else None)
    if kind == _GROUP:
        return _carrier(inherit)
    return None


def _under(shown: tuple, inner: dict | None) -> dict | None:
    """The variants of a single child, drawn only while its parent is shown."""
    if inner is None:
        return None
    return {
        "alts": [[kind, conjunction(shown, formula)] for kind, formula in inner["alts"]],
        "others": [conjunction(shown, formula) for formula in inner["others"]],
    }


def _carrier(node, depth: int = 0) -> dict | None:
    """The variants a node of the component content draws on the baseline, or None."""
    if depth > 8:
        return None
    entries = _scalar_entries(node)
    if SELF_ALIGN_KEY in entries:
        return None
    shown = visibility(entries)
    if shown is None:
        return None
    kind = component_kind(node)
    if kind in (BUTTON, PICTURE):
        if kind == BUTTON and not shows_caption(caption_view(entries)):
            return None
        return {"alts": [[kind, shown]], "others": []}
    if kind != _GROUP or not is_vertical(entries):
        return None
    children = component_children(node)
    if len(children) == 1:
        return _under(shown, _carrier(children[0], depth + 1))
    alts: list[list] = []
    others: list[tuple] = []
    for child in children:
        child_entries = _scalar_entries(child)
        child_shown = visibility(child_entries)
        if child_shown is None:
            return None
        child_kind = component_kind(child)
        if child_kind in (BUTTON, PICTURE):
            if SELF_ALIGN_KEY in child_entries:
                return None
            if child_kind == BUTTON and not shows_caption(caption_view(child_entries)):
                return None
            alts.append([child_kind, conjunction(shown, child_shown)])
        else:
            others.append(conjunction(shown, child_shown))
    return {"alts": alts, "others": others} if alts else None


def module_conditions(module, text: str) -> dict[str, tuple]:
    """{method: formula} of the methods without parameters whose whole body is one return.

    Only formulas made of comparisons, names and calls are kept - anything else could never
    resolve to a constant at an instance.
    """
    out: dict[str, tuple] = {}
    for member in module.members:
        if not isinstance(member, P.Method) or member.params or member.is_static:
            continue
        body = member.body
        if len(body) != 1 or not isinstance(body[0], P.Return) or body[0].value is None:
            continue
        formula = simplify(expression_formula(body[0].value, text))
        if all(atom[0] != "atom" for atom in atoms(formula).values()):
            out[member.name] = formula
    return out


def child_is_component(mapping) -> bool:
    """Whether the child's type is not a platform component - a candidate project component.

    Without the ui schema every type is a candidate; the reduce step then finds no description
    for a platform name and leaves the child out.
    """
    written = type_name(mapping)
    return bool(written) and uischema.canonical_component(written) not in _platform_components()


def child_fact(mapping) -> dict:
    """What the reduce step needs of one child of a row."""
    entries = _scalar_entries(mapping)
    values = {
        key.value: literal_value(value)
        for key, value in mapping.value
        if isinstance(key, yaml.ScalarNode)
    }
    return {
        "label": label(mapping),
        "type": type_name(mapping) or "",
        "native": participant(mapping),
        "component": child_is_component(mapping),
        "aligned": SELF_ALIGN_KEY in entries,
        "shown": visibility(entries),
        "values": values,
        "caption": caption_view(entries),
    }


def _nullable(declared_type: str) -> bool:
    members = [part.strip() for part in declared_type.split("|")]
    return declared_type.strip().endswith("?") or any(m in _UNDEFINED_VALUES for m in members)


def _instance_value(prop: str, definition: dict, values: dict) -> tuple | None:
    if prop in values:
        return values[prop]
    declared = definition["props"][prop]
    if declared["default"] is not None:
        return declared["default"]
    return ("undef",) if _nullable(declared["type"]) else None


def _compare(value: tuple | None, constant: tuple, declared_type: str) -> bool | None:
    """Whether the instance value equals the constant; None when it cannot be told."""
    if value is None or value[0] == "expr":
        return None
    if constant[0] == "enum":
        base = declared_type.strip().rstrip("?").strip().rsplit("::", 1)[-1]
        if base != constant[1]:
            return None  # not the property's own enumeration - a module constant, a union
        if value[0] == "undef":
            return False
        if value[0] == "enum":
            return value[2] == constant[2] if value[1] == constant[1] else None
        if value[0] == "plain":
            return value[1].rsplit(".", 1)[-1] == constant[2]
        return None
    if constant[0] == "undef":
        return value[0] == "undef"
    if value[0] == "undef":
        return False
    if constant[0] == "bool":
        return value[1] == constant[1] if value[0] == "bool" else None
    if value[0] == constant[0] or (constant[0] == "num" and value[0] == "plain"):
        return value[1] == constant[1]
    return None


def _own(atom: tuple, definition: dict, methods: dict) -> bool:
    tag = atom[0]
    if tag == "eq":
        return atom[1] in definition["props"]
    if tag == "name":
        return atom[1] in definition["props"]
    if tag == "call":
        return atom[1] in methods
    return False


def _substitute(formula: tuple, definition: dict, values: dict, methods: dict,
                depth: int = 0) -> tuple | None:
    """The formula with the component's own conditions replaced by their value at the instance.

    None when an own condition cannot be resolved there.
    """
    tag = formula[0]
    if tag in ("T", "F"):
        return formula
    if tag in ("and", "or"):
        left = _substitute(formula[1], definition, values, methods, depth)
        right = _substitute(formula[2], definition, values, methods, depth)
        return None if left is None or right is None else simplify((tag, left, right))
    if tag == "not":
        inner = _substitute(formula[1], definition, values, methods, depth)
        return None if inner is None else simplify(("not", inner))
    if not _own(formula, definition, methods):
        return formula
    if tag == "eq":
        declared = definition["props"][formula[1]]["type"]
        equal = _compare(_instance_value(formula[1], definition, values), formula[2], declared)
        return None if equal is None else (TRUE if equal else FALSE)
    if tag == "name":
        value = _instance_value(formula[1], definition, values)
        if value is None or value[0] != "bool":
            return None
        return TRUE if value[1] else FALSE
    if depth > 4:
        return None
    body = _substitute(methods[formula[1]], definition, values, methods, depth + 1)
    return body if body in (TRUE, FALSE) else None


def _conjuncts(formula: tuple) -> list[tuple]:
    if formula[0] == "and":
        return _conjuncts(formula[1]) + _conjuncts(formula[2])
    return [] if formula == TRUE else [formula]


def instance_draw(child: dict, definition: dict, methods: dict) -> tuple[str, tuple] | None:
    """(kind, shown) of what one instance of a project component draws on the row's baseline."""
    draws = definition["draws"]
    if draws is None or child["aligned"] or child["shown"] in (None, FALSE):
        return None
    values = child["values"]
    variants: list[tuple[str, list, list]] = []
    for kind, formula in draws["alts"]:
        own, gate = [], []
        for part in _conjuncts(formula):
            owned = [_own(atom, definition, methods) for atom in atoms(part).values()]
            if all(owned):
                own.append(part)
            elif not any(owned):
                gate.append(part)
            else:
                return None  # a condition mixing the property with something else
        variants.append((kind, own, gate))
    if len(variants) > 1:
        kinds = {kind for kind, _own_parts, _gate in variants}
        if kinds != {BUTTON, PICTURE} or not all(own for _kind, own, _gate in variants):
            return None
        if len({repr(sorted(map(repr, gate))) for _kind, _own_parts, gate in variants}) != 1:
            return None  # the variants differ in more than the property
    picked = []
    for kind, own, gate in variants:
        resolved = _substitute(conjunction(*own), definition, values, methods)
        if resolved is None:
            return None
        if resolved == TRUE:
            picked.append((kind, gate))
    if len(picked) != 1:
        return None
    kind, gate = picked[0]
    if len(variants) == 1 and gate:
        return None  # a single element shown under a condition is not drawn unconditionally
    shown = conjunction(*gate)
    for other in draws["others"]:
        resolved = _substitute(other, definition, values, methods)
        if resolved is None or satisfiable(shown, resolved) is not False:
            return None
    if "caption" in draws and kind == BUTTON:
        if not shows_caption({**draws["caption"], **child["caption"]}):
            return None
    return kind, conjunction(shown, child["shown"])
