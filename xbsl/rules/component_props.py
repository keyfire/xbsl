"""Tier A: a markup key that belongs to ANOTHER interface component.

The yaml/unknown-component-property rule. A node of the markup names its component in `Type`,
and every other key of that node is a property of that component. A key the component does
not have costs a deploy cycle: applying the build answers `Неизвестное свойство "X"` -
measured on a probe for `Checkbox` + `PlaceholderText` and for `HtmlEditor` +
`DataValidationResult` / `MessageWarning`. All three are properties of `Edit` copied over to a
neighbouring component, which is what the rule is named after: the key exists in the platform,
just not here.

Judged is exactly that class - a key the ui schema declares as a TYPED property of at least
one other component. The reason is that the documentation does not describe a component's
yaml keys in full, and the gaps are not guessable:

- the reference page of a constructible component lists its properties in the constructor,
  and a property outside it (`ListForm.TableComponent`) is only in the prose section;
- the keys of an instance description are the business of the guide topics
  (`IncludeInAutoInterface`, `TrackDataModification`, the title of a list form's create
  command), and only about half the components have such a topic;
- a legal property may be missing from the reference entirely and appear only in the guide
  (`FilesChoice.Title`) - or in neither, as `StandardTableColumn.BadgeBackgroundColor` and the
  events of `SchedulesComponent`, which the documentation writes in its own examples while
  describing them nowhere.

So "not in the schema" alone is not a violation, and the extractor now folds what the prose
and the guides state into `yaml_props` (see xbsl/extract/uischema.py). What remains judged is
the copy-over: a name the platform does type - for another component. A key nothing declares
(a typo, an undocumented property) is silence, deliberately: on real projects such keys are
legal far more often than not.

Zero-false-positive guards beyond that:

- only nodes UNDER `Inherits` are walked - the markup of a component instance. Elsewhere a
  `Type` names a type, not a component: an item of `Properties` declaring `Type: Picture`
  carries `DefaultValue`, which is no component property at all;
- a node is judged only when its `Type` names a component of the schema (the generic head is
  taken: `Edit<String>` -> `Edit`), so a project component - whose own properties the schema
  cannot know - is never judged;
- `Type` and `Name` are the structural keys of a node, always allowed;
- a Latin key that the platform dictionaries cannot map to a schema name is skipped: the data
  does not spell every component property in English (the property dictionary is built from
  the sources that do, and a handful of properties have no English spelling anywhere), so
  judging an ASCII key would report legal English sources. A missed finding rather than a
  false one.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from functools import lru_cache

from xbsl import dataset, i18n, terms, uischema
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, rule
from xbsl.rules.yaml_schema import (
    _HAVE_YAML,
    _composed,
    _is_object,
    _parsed,
    _scalar_entries,
    object_kind,
    yaml,
)

MESSAGES = {
    "yaml/unknown-component-property.title": {
        "ru": "Неизвестное свойство компонента",
        "en": "Unknown component property",
    },
    "yaml/unknown-component-property.foreign": {
        "ru": "Свойства '{prop}' у компонента '{component}' нет – оно объявлено у {owners}. "
              "Применение сборки отвергнет узел разметки ('Неизвестное свойство').",
        "en": "Component '{component}' has no property '{prop}' – it is declared by {owners}. "
              "Applying the build rejects the markup node ('Неизвестное свойство').",
    },
    "yaml/ref-input-auto-commands.title": {
        "ru": "У ссылочного поля ввода команды по умолчанию",
        "en": "A reference input with the default commands",
    },
    "yaml/ref-input-auto-commands.auto": {
        "ru": "Поле ввода со ссылочным типом '{type}' не задаёт Команды: платформа добавит рядом "
              "свою кнопку открытия значения в отдельном окне (у ссылочного поля Авто "
              "разворачивается во фрагмент командного интерфейса). Кнопка не нужна – задайте "
              "пустой фрагмент: 'Команды:' с 'Тип: ФрагментКомандногоИнтерфейса' без элементов.",
        "en": "An input of the reference type '{type}' declares no {n[Команды]}: the platform adds "
              "its own button that opens the value in a separate window (for a reference input "
              "{n[Авто]} unfolds into a command-interface fragment). To do without the button, "
              "declare an empty fragment.",
    },
    "yaml/ref-input-auto-commands.off": {
        "ru": "информационное: кнопка открытия чаще всего и нужна, отличить намерение нельзя",
        "en": "informational: the open button is usually wanted, and the intent is not tellable",
    },
    "yaml/toggle-command-pair.title": {
        "ru": "Пара команд с зеркальной видимостью",
        "en": "A pair of commands with mirrored visibility",
    },
    "yaml/inline-command-name.title": {
        "ru": "Имя у команды в разметке",
        "en": "A name on an inline command",
    },
    "yaml/inline-command-name.found": {
        "ru": "Команда '{name}' объявлена прямо в разметке (инлайновый "
              "{n[ФрагментКомандногоИнтерфейса]}) и несёт {n[Имя]} – применение сборки "
              "отвергнет узел (\"Имя команды разрешено задавать только в элементах проекта "
              "типа фрагмент командного интерфейса\") и стенд откатится на прежнюю сборку. "
              "Обращайтесь к команде через параметр обработчика (Команда.Активна, "
              "Команда.Видимость) – либо, если имя необходимо, вынесите фрагмент отдельным "
              "элементом проекта.",
        "en": "Command '{name}' is declared inline in the markup (an inline "
              "{n[ФрагментКомандногоИнтерфейса]}) and carries {n[Имя]} – the apply rejects "
              "the node (\"a command name is allowed only in command-interface-fragment "
              "project elements\") and the stand rolls back to the previous build. Reach "
              "the command through the handler parameter (Command.{n[Активна]}, "
              "Command.{n[Видимость]}) – or, when the name is needed, move the fragment "
              "into a project element of its own.",
    },
    "yaml/toggle-command-pair.pair": {
        "ru": "Две соседние {n[ОбычнаяКоманда]} с зеркальной {n[Видимость]} ('{first}' и "
              "'{second}') изображают одну команду с двумя состояниями. У платформы она есть: "
              "{n[ПереключаемаяКоманда]} несёт представления и изображения обоих состояний, "
              "начальное {n[Активна]} задаётся литералом (состоянием владеет платформа, биндинг "
              "запрещён), а обработчик читает состояние из свойства команды.",
        "en": "Two adjacent {n[ОбычнаяКоманда]} commands with mirrored {n[Видимость]} "
              "('{first}' and '{second}') emulate one command with two states. The platform "
              "has the real thing: a {n[ПереключаемаяКоманда]} carries the representations and "
              "images of both states, the initial {n[Активна]} is a literal (the platform owns "
              "the state, a binding is forbidden), and the handler reads the state off the "
              "command.",
    },
}
i18n.register(MESSAGES)

#: The key whose subtree is the markup of the component instance, either spelling.
_MARKUP_KEYS = ("Наследует", "Inherits")
#: Keys of a markup node that name the node itself rather than a property of the component.
_STRUCTURAL = frozenset({"Тип", "Имя"})


@lru_cache(maxsize=1)
def _tables() -> tuple[dict[str, frozenset[str]], dict[str, tuple[str, ...]]]:
    """({component: the keys it accepts}, {property: the components that declare it}).

    Built once: resolving the dataset walks the installed data plugins, and both tables are
    the same for every file. The accepted keys are the typed properties plus `yaml_props` -
    the names the prose and the guide topics state (see the module docstring); the owner
    table holds TYPED properties only, so an undocumented or instance-only key is never
    judged for anyone.

    A schema generated before `yaml_props` existed knows the constructor parameters alone,
    and judging against it reports legal code all over a real project. Such a schema switches
    the rule off entirely - the same degradation as having no data at all.
    """
    schema = dataset.load_ui_schema()
    if not schema:
        return {}, {}
    records = (schema.get("components") or {}).values()
    if not any(record.get("yaml_props") for record in records):
        return {}, {}  # data older than the rule - see the docstring
    accepted: dict[str, frozenset[str]] = {}
    owners: dict[str, list[str]] = {}
    for component, record in (schema.get("components") or {}).items():
        props = record.get("props") or {}
        accepted[component] = frozenset(props) | frozenset(record.get("yaml_props") or ())
        for prop in props:
            owners.setdefault(prop, []).append(component)
    return accepted, {prop: tuple(sorted(names)) for prop, names in owners.items()}


dataset.register_reset(_tables.cache_clear)


def _markup_nodes(root):
    """Every mapping under an `Inherits` key of the document - the markup of an instance."""
    stack = [(root, False)]
    seen: set[int] = set()
    while stack:
        node, inside = stack.pop()
        if id(node) in seen:  # an anchor may alias the same node twice
            continue
        seen.add(id(node))
        if isinstance(node, yaml.MappingNode):
            if inside:
                yield node
            for key_node, value_node in node.value:
                is_markup = isinstance(key_node, yaml.ScalarNode) and key_node.value in _MARKUP_KEYS
                stack.append((value_node, inside or is_markup))
        elif isinstance(node, yaml.SequenceNode):
            stack.extend((item, inside) for item in node.value)


def _type_value(mapping):
    """The scalar value node of the `Type` key of a mapping, either spelling, or None."""
    for key_node, value_node in mapping.value:
        if (
            isinstance(key_node, yaml.ScalarNode) and key_node.value in ("Тип", "Type")
            and isinstance(value_node, yaml.ScalarNode)
        ):
            return value_node
    return None


@rule(
    "yaml/unknown-component-property", "yaml/unknown-component-property.title", "A",
    severity=Severity.ERROR,
)
def unknown_component_property(source: SourceFile) -> Iterable[Diagnostic]:
    """A markup key the component does not declare while another component does."""
    if source.kind != "yaml" or not _HAVE_YAML:
        return
    accepted, owners = _tables()
    if not accepted or not any(key in source.text for key in _MARKUP_KEYS):
        return  # no ui schema, or no component markup in this file
    data, err = _parsed(source)
    if err is not None or not _is_object(data):
        return
    root = _composed(source)
    if root is None:  # pragma: no cover - _parsed has already vetted the syntax
        return
    for mapping in _markup_nodes(root):
        type_node = _type_value(mapping)
        if type_node is None:
            continue
        component = uischema.canonical_component(type_node.value.split("<", 1)[0].strip())
        allowed = accepted.get(component)
        if allowed is None:
            continue  # a project component, a data type, a command - not a palette component
        # The keys are canonicalized only for a node that is worth judging: building the
        # dictionary for every mapping of every file would be the bulk of the rule's cost.
        for key, (key_node, _value) in _scalar_entries(mapping).items():
            if key in _STRUCTURAL or key in allowed or key_node.value in allowed:
                continue
            declared = owners.get(key)
            if not declared:
                continue  # no component types this name - see the module docstring
            yield Diagnostic(
                source.rel,
                key_node.start_mark.line + 1, key_node.start_mark.column + 1,
                "yaml/unknown-component-property", Severity.ERROR,
                i18n.t(
                    "yaml/unknown-component-property.foreign",
                    prop=key_node.value, component=component,
                    owners=", ".join(declared[:3]),
                ),
            )


# The reference input whose commands are left to the platform: the type argument names a
# reference facet, and the node declares no commands of its own.
_COMMANDS_KEYS = frozenset({"Команды", "Commands"})
_REFERENCE_FACET = "Ссылка"


@lru_cache(maxsize=1)
def _reference_facets() -> tuple[str, ...]:
    """Both spellings of the reference facet, from the platform dictionary.

    The English spelling used to be written by hand as a word the serializer never writes -
    on a translated tree the rule saw no reference inputs at all.
    """
    return tuple(dict.fromkeys(
        name for name in (_REFERENCE_FACET, terms.facet_suffix_english(_REFERENCE_FACET))
        if name
    ))


dataset.register_reset(_reference_facets.cache_clear)
_INPUT_COMPONENTS = frozenset({"ПолеВвода", "Edit"})


def _reference_argument(type_value: str) -> str | None:
    """The type argument of an input when it names a reference facet, else None."""
    start = type_value.find("<")
    if start < 0 or not type_value.endswith(">"):
        return None
    argument = type_value[start + 1:-1].strip()
    for member in argument.split("|"):
        member = member.strip().rstrip("?").strip()
        if any(member.endswith(f".{facet}") for facet in _reference_facets()):
            return argument
    return None


@rule(
    "yaml/ref-input-auto-commands", "yaml/ref-input-auto-commands.title", "D",
    severity=Severity.INFO, enabled_by_default=False,
    off_reason="yaml/ref-input-auto-commands.off",
)
def ref_input_auto_commands(source: SourceFile) -> Iterable[Diagnostic]:
    """A reference input that leaves its commands to the platform.

    With no commands of its own the field gets the platform's own "open the value in a separate
    window" button next to it: the documentation of the type states that for a reference input
    the `Auto` value turns into a command-interface fragment. That is often what the author
    wants, which is why the rule is off by default - it answers the question "where did this
    button come from" rather than reports a mistake. An empty fragment silences the button.
    """
    if source.kind != "yaml" or not _HAVE_YAML:
        return
    if not any(key in source.text for key in _MARKUP_KEYS):
        return
    data, err = _parsed(source)
    if err is not None or not _is_object(data):
        return
    root = _composed(source)
    if root is None:  # pragma: no cover - _parsed has already vetted the syntax
        return
    for mapping in _markup_nodes(root):
        type_node = _type_value(mapping)
        if type_node is None:
            continue
        value = type_node.value.strip()
        component = uischema.canonical_component(value.split("<", 1)[0].strip())
        if component not in _INPUT_COMPONENTS:
            continue
        argument = _reference_argument(value)
        if argument is None:
            continue
        if any(key in _COMMANDS_KEYS for key in _scalar_entries(mapping)):
            continue
        if any(isinstance(k, yaml.ScalarNode) and k.value in _COMMANDS_KEYS
               for k, _v in mapping.value):
            continue  # the commands are a nested fragment, not a scalar entry
        yield Diagnostic(
            source.rel,
            type_node.start_mark.line + 1, type_node.start_mark.column + 1,
            "yaml/ref-input-auto-commands", Severity.INFO,
            i18n.t("yaml/ref-input-auto-commands.auto", type=argument),
        )


# The handmade toggle: two adjacent usual commands whose visibility bindings negate each
# other - one is shown exactly when the other is hidden.
_USUAL_COMMAND = "ОбычнаяКоманда"
_VISIBILITY = "Видимость"

#: The negation head of a binding: the keyword, not an identifier that merely starts with it.
_NEGATION_RE = re.compile(r"^(?:не|not)(?=[\s(])\s*(.+)$", re.DOTALL)


@lru_cache(maxsize=1)
def _toggle_names() -> tuple[frozenset[str], frozenset[str]]:
    """Both spellings of the usual-command kind and of the visibility key, from the data.

    The kind comes from the serializer's own vocabulary (`terms.kinds_table`) - the type
    dictionary spells the KIND of an English project differently from the stdlib type. With
    no data only the Russian spelling matches, which is the usual degradation.
    """
    spelled_kind = terms.kinds_table().get(_USUAL_COMMAND)
    kinds = frozenset(name for name in (_USUAL_COMMAND, spelled_kind) if name)
    visibility = frozenset(
        name for name in (
            _VISIBILITY,
            *(en for en, ru in uischema.property_aliases().items() if ru == _VISIBILITY),
        ) if name
    )
    return kinds, visibility


dataset.register_reset(_toggle_names.cache_clear)


def _whole_parens_stripped(expression: str) -> str:
    """The expression without a parenthesis pair that wraps the whole of it, repeatedly."""
    expression = expression.strip()
    while expression.startswith("(") and expression.endswith(")"):
        depth = 0
        for position, char in enumerate(expression):
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0 and position < len(expression) - 1:
                    return expression  # the pair closes before the end - not a wrapper
        expression = expression[1:-1].strip()
    return expression


def _mirrored(first: str, second: str) -> bool:
    """Whether one visibility binding negates the other (`=X` against `=не X`)."""
    if not (first.startswith("=") and second.startswith("=")):
        return False
    left = _whole_parens_stripped(first[1:])
    right = _whole_parens_stripped(second[1:])
    for negated, plain in ((left, right), (right, left)):
        match = _NEGATION_RE.match(negated)
        if match is None:
            continue
        stripped = _whole_parens_stripped(match.group(1))
        if re.sub(r"\s+", "", stripped) == re.sub(r"\s+", "", plain):
            return True
    return False


def _visibility_binding(mapping, names: frozenset[str]):
    """The scalar (key, value) nodes of the visibility property, either spelling."""
    for key_node, value_node in mapping.value:
        if not (
            isinstance(key_node, yaml.ScalarNode) and isinstance(value_node, yaml.ScalarNode)
        ):
            continue
        if key_node.value in names:
            return key_node, value_node
    return None


@rule(
    "yaml/toggle-command-pair", "yaml/toggle-command-pair.title", "D",
    severity=Severity.WARNING,
)
def toggle_command_pair(source: SourceFile) -> Iterable[Diagnostic]:
    """A pair of usual commands whose visibilities negate each other - a handmade toggle.

    One command is shown exactly when the other is hidden: together they emulate a command
    with two states, and the platform declares that command itself (`SwitchableCommand` -
    the representations and images of both states, the `Active` flag the platform owns).
    A shared handler strengthens the case but is not required: the pair with two handlers
    is the same toggle written apart.

    Adjacency is judged among the mapping items of one sequence: a scalar reference between
    them (`- =Обновить`) does not break the pair, another command node does.
    """
    if source.kind != "yaml" or not _HAVE_YAML:
        return
    if not any(key in source.text for key in _MARKUP_KEYS):
        return
    kinds, visibility_names = _toggle_names()
    if not any(name in source.text for name in visibility_names):
        return
    data, err = _parsed(source)
    if err is not None or not _is_object(data):
        return
    root = _composed(source)
    if root is None:  # pragma: no cover - _parsed has already vetted the syntax
        return
    for mapping in _markup_nodes(root):
        for _key, value in mapping.value:
            if not isinstance(value, yaml.SequenceNode):
                continue
            items = [item for item in value.value if isinstance(item, yaml.MappingNode)]
            for first, second in zip(items, items[1:]):
                first_type = _type_value(first)
                second_type = _type_value(second)
                if first_type is None or first_type.value.strip() not in kinds:
                    continue
                if second_type is None or second_type.value.strip() not in kinds:
                    continue
                first_vis = _visibility_binding(first, visibility_names)
                second_vis = _visibility_binding(second, visibility_names)
                if first_vis is None or second_vis is None:
                    continue
                if not _mirrored(first_vis[1].value, second_vis[1].value):
                    continue
                key_node = first_vis[0]
                yield Diagnostic(
                    source.rel,
                    key_node.start_mark.line + 1, key_node.start_mark.column + 1,
                    "yaml/toggle-command-pair", Severity.WARNING,
                    i18n.t(
                        "yaml/toggle-command-pair.pair",
                        first=first_vis[1].value, second=second_vis[1].value,
                    ),
                )


# --- yaml/inline-command-name ---------------------------------------------------------

#: Command components a markup node may declare inline, in the Russian spelling.
_COMMAND_KINDS = ("ОбычнаяКоманда", "ПереключаемаяКоманда", "КомандаСПараметром")
_FRAGMENT_KIND = "ФрагментКомандногоИнтерфейса"
#: The structural key the platform refuses on an inline command, either spelling.
_NAME_KEYS = ("Имя", "Name")


def _kind_spellings(names: tuple[str, ...]) -> frozenset[str]:
    """Every spelling of the given kinds: the serializer's vocabulary plus the type
    dictionary - the two sources cover different names (`CommandWithParameter` has no
    serializer entry, `LocalizedStrings` no type entry), and a hand-written English
    spelling is exactly what the data exists to replace. With no data only the Russian
    spellings match - the usual degradation."""
    kinds = terms.kinds_table()
    out = set(names)
    for name in names:
        out.update({kinds.get(name), terms.english(name, "types")})
    return frozenset(out - {None})


@lru_cache(maxsize=1)
def _command_names() -> frozenset[str]:
    return _kind_spellings(_COMMAND_KINDS)


@lru_cache(maxsize=1)
def _fragment_names() -> frozenset[str]:
    return _kind_spellings((_FRAGMENT_KIND,))


dataset.register_reset(_command_names.cache_clear)
dataset.register_reset(_fragment_names.cache_clear)


@rule(
    "yaml/inline-command-name", "yaml/inline-command-name.title", "A",
    severity=Severity.ERROR,
)
def inline_command_name(source: SourceFile) -> Iterable[Diagnostic]:
    """An inline command of the markup carrying a `Name` - the apply refuses the node.

    A command declared straight in the markup (an inline command-interface fragment, or a
    single-command property such as `MainCommand`) must not carry a name: the platform
    answers "a command name is allowed only in command-interface-fragment project
    elements" at apply time, so the defect costs a deploy cycle and a
    rollback. In a fragment PROJECT ELEMENT the same key is legal - that is the cure when
    the name is actually needed - so a file whose root kind is the fragment is skipped
    whole. Only nodes under `Inherits` are judged: elsewhere a command spelling next to a
    `Name` is a declaration, not markup.
    """
    if source.kind != "yaml" or not _HAVE_YAML:
        return
    commands = _command_names()
    if not any(name in source.text for name in commands):
        return
    data, err = _parsed(source)
    if err is not None or not _is_object(data):
        return
    if object_kind(data) in _fragment_names():
        return  # a fragment project element - its commands own their names
    root = _composed(source)
    if root is None:  # pragma: no cover - _parsed has already vetted the syntax
        return
    for mapping in _markup_nodes(root):
        type_node = _type_value(mapping)
        if type_node is None:
            continue
        if type_node.value.split("<", 1)[0].strip() not in commands:
            continue
        for key_node, value_node in mapping.value:
            if not (isinstance(key_node, yaml.ScalarNode) and key_node.value in _NAME_KEYS):
                continue
            shown = value_node.value if isinstance(value_node, yaml.ScalarNode) else ""
            yield Diagnostic(
                source.rel,
                key_node.start_mark.line + 1, key_node.start_mark.column + 1,
                "yaml/inline-command-name", Severity.ERROR,
                i18n.t("yaml/inline-command-name.found", name=shown),
            )
