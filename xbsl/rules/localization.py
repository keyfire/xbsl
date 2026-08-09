"""Tier D: what the localization mechanism silently lets through.

Four checks over the dictionary of localized strings and its use.

--- yaml/placeholder-key-in-strings ---

The two sections of a localized-strings dictionary are not interchangeable.

A `ЛокализованныеСтроки` element holds `Строки` and `Шаблоны`, and the platform compiles them
differently: an entry of `Строки` becomes a method WITHOUT parameters, an entry of `Шаблоны` a
method that takes the substitutions its text names (`$0`, `$1`, ...).

So a text carrying a placeholder is only useful in `Шаблоны`. Left in `Строки` it still
compiles - the placeholder is just text there - and the failure surfaces at the call site
instead: `Словарь.Ключ("значение")` finds no method of that arity and the apply answers
`Неизвестный метод`, naming the key but never the section, so the message points away from
the cause.

The check is file-local (both the section and its entries are in one yaml) and reads the
section names in either spelling, from the metamodel record of the kind.

--- code/compare-with-localized ---

A localized value is whatever the reader's language turns it into, so comparing it against a
fixed string decides on one language and silently misses on every other: the branch simply
never runs. Two shapes are read as localized - a call of a dictionary of the project
(`<Словарь>.<Ключ>(...)`) and the platform's own `Представление()` - and the comparison is
reported when the other side is a string literal or a second localized value.

The cure is to branch on the VALUE behind the presentation (an enumeration element, a code, a
reference) rather than on its text.

A comparison against a plain VARIABLE is skipped on purpose, even though the localized side
still varies by language there: what the variable holds is not visible to a token-level check,
and a rule that guessed would fire on every dispatch that legitimately compares two values.
The narrow form is the one the defect was actually met in.

The check is project-wide because the dictionaries are project elements: which names are
localized cannot be told from one module. The `Представление()` shape is kept in the same rule
rather than split into a file one - it is the same defect and the same message, and on the
corpus it is the smaller half by an order of magnitude.

--- conventions/untranslated-visible-literal ---

Visible text left as a literal where the project already localizes it. The rule is
self-tuning: only the keys the project itself references into a dictionary somewhere are
judged - a fixed list of "visible" properties would go stale with the first new component,
while the reference count states the project's intent directly.

The intent is counted PER ELEMENT KIND: same-named properties of different kinds are
different properties. A localized `Описание` of a component card does not make the
`Описание` of an event-log element judgeable - that one is operator documentation, and the
project never stated an intent to localize it.

The language-count gate is mandatory: a single-language project has nothing to localize,
and without the gate the rule would be noise on every such project. Everything the check
relies on is platform mechanics - the localization languages of the descriptor, the
dictionaries, the `$Dictionary.Key` references - which is what makes it an engine rule.

--- conventions/untranslated-code-literal ---

The same defect one layer down: visible text written as a literal in a MODULE, where no
yaml property carries it and the check above cannot see it.

What is judged is not the literal but the SINK it reaches. A Cyrillic phrase is a finding
when it lands in something the platform shows to a person:

* an argument of the platform's `Message` call - a message box;
* a property of an event-log event constructor - the event's `ШаблонПредставления` prints
  those properties, and unlike the template itself a property value is never localized;
* ONE-STEP FORWARDING of either: a parameter that goes whole into one of the sinks above
  makes every call of that method with a literal a finding too.

Forwarding is not a refinement but the point of the rule. On the corpus that prompted it,
seven of the nine findings reached the journal through a wrapper method, and a rule without
forwarding would have found none of them.

Everything else is deliberately NOT judged, and reconnaissance is why:

* a single-language project is skipped by the same language gate as above (without it one
  corpus answered 35 findings, all of them noise);
* a phrase with no sink is skipped - most of them are seeding data, layout constants and
  interpolation templates;
* markup, styles and pure interpolation are skipped by shape;
* a literal that merely REPEATS a dictionary value is not a finding on its own. Seeding
  code passes a Russian text next to its English twin into a catalog, which no dictionary
  call replaces; the match only enriches the message of a sink finding with the key whose
  translation already exists.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable
from functools import lru_cache

import yaml as _yaml

from xbsl import dataset, i18n, metamodel, terms
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, rule
from xbsl.rules._syntax import code_tokens, in_query, signatures
from xbsl.rules.yaml_schema import _composed, _HAVE_YAML, _mapping_nodes, _parsed, object_kind

MESSAGES = {
    "yaml/placeholder-key-in-strings.title": {
        "ru": "Подстановка в секции Строки, а не Шаблоны",
        "en": "A placeholder in the Strings section instead of Templates",
    },
    "code/compare-with-localized.title": {
        "ru": "Сравнение с локализованным значением",
        "en": "A comparison against a localized value",
    },
    "code/compare-with-localized.literal": {
        "ru": "Сравнение локализованного значения ({what}) с литералом {literal}: на другом "
              "языке ветка молча не сработает. Ветвитесь по значению – элементу перечисления, "
              "коду, ссылке, – а не по его тексту.",
        "en": "A localized value ({what}) is compared against the literal {literal}: in another "
              "language the branch simply never runs. Branch on the VALUE – an enumeration "
              "element, a code, a reference – rather than on its text.",
    },
    "code/compare-with-localized.both": {
        "ru": "Сравнение двух локализованных значений ({what}): совпадение зависит от языка "
              "читателя. Сравнивайте значения, стоящие за представлениями.",
        "en": "Two localized values are compared ({what}): whether they match depends on the "
              "reader's language. Compare the values behind the presentations.",
    },
    "yaml/placeholder-key-in-strings.found": {
        "ru": "Ключ '{key}' несёт подстановку {placeholder}, но лежит в секции Строки – она "
              "компилируется в метод БЕЗ параметров, и вызов с аргументом упадёт на применении "
              "\"Неизвестный метод\". Перенесите ключ в секцию Шаблоны.",
        "en": "Key '{key}' carries the placeholder {placeholder} but sits in the {n[Строки]} "
              "section, which compiles to a method WITHOUT parameters – a call with an argument "
              "fails the apply with \"Неизвестный метод\". Move the key to {n[Шаблоны]}.",
    },
    "conventions/untranslated-visible-literal.title": {
        "ru": "Непереведённый видимый литерал",
        "en": "An untranslated visible literal",
    },
    "conventions/untranslated-code-literal.title": {
        "ru": "Непереведённый литерал в коде",
        "en": "An untranslated literal in code",
    },
    "conventions/untranslated-code-literal.off": {
        "ru": "видимый текст отличается от технической строки СТОКОМ, куда он попадает, а "
              "проект вправе собирать прозу в коде – начальные данные, константы макета. "
              "Включайте там, где всякая читаемая человеком строка обязана приходить из "
              "словаря",
        "en": "visible text is told from a technical string by the SINK it reaches, and a "
              "project may legitimately build prose in code - seeding data, layout "
              "constants. Enable it where every string a person reads must come from a "
              "dictionary",
    },
    "conventions/untranslated-code-literal.found": {
        "ru": "Кириллический текст \"{value}\" попадает в {sink} – это видит человек, а "
              "литерал не переводится. Языков локализации больше одного, значит на "
              "остальных текст останется русским. Вынесите его в словарь и зовите "
              "Словарь.Ключ().",
        "en": "The Cyrillic text \"{value}\" reaches {sink}, where a person reads it, and a "
              "literal is never translated. The project has more than one localization "
              "language, so the text stays Russian in the others. Move it to a dictionary "
              "and call Dictionary.Key().",
    },
    "conventions/untranslated-code-literal.known": {
        "ru": "Кириллический текст \"{value}\" попадает в {sink} – это видит человек, а "
              "литерал не переводится. Перевод для него уже написан: зовите {key}().",
        "en": "The Cyrillic text \"{value}\" reaches {sink}, where a person reads it, and a "
              "literal is never translated. Its translation is already written: call "
              "{key}().",
    },
    "conventions/untranslated-code-literal.message-sink": {
        "ru": "сообщение пользователю ({call})",
        "en": "a message box ({call})",
    },
    "conventions/untranslated-code-literal.event-sink": {
        "ru": "свойство {property} события журнала {event}",
        "en": "property {property} of the event-log event {event}",
    },
    "conventions/untranslated-code-literal.forwarded-sink": {
        "ru": "{sink} через {method}()",
        "en": "{sink} through {method}()",
    },
    "conventions/untranslated-visible-literal.found": {
        "ru": "Свойство '{key}' здесь – кириллический литерал \"{value}\", а в других "
              "местах проекта то же свойство вынесено ссылкой на словарь. Языков локализации "
              "больше одного, значит на остальных текст останется русским. Замените литерал "
              "на $Словарь.Ключ.",
        "en": "Property '{key}' is the Cyrillic literal \"{value}\" here, while elsewhere in "
              "the project the same property is a dictionary reference. The project has more "
              "than one localization language, so the text stays Russian in the others. "
              "Replace the literal with $Dictionary.Key.",
    },
}
i18n.register(MESSAGES)

_KIND = "ЛокализованныеСтроки"
_STRINGS = "Строки"
_TEMPLATES = "Шаблоны"

#: `$0`, `$1`, ... - the substitution a template names in its text.
_PLACEHOLDER = re.compile(r"\$\d")


@lru_cache(maxsize=1)
def _section_names() -> frozenset[str]:
    """Both spellings of the `Строки` section, from the metamodel record of the kind."""
    record = metamodel.properties(_KIND).get(_STRINGS) or {}
    return frozenset({_STRINGS, record.get("en")} - {None})


dataset.register_reset(_section_names.cache_clear)


@rule(
    "yaml/placeholder-key-in-strings",
    "yaml/placeholder-key-in-strings.title", "D",
    severity=Severity.ERROR,
)
def placeholder_key_in_strings(source: SourceFile) -> Iterable[Diagnostic]:
    """A dictionary entry with a substitution left outside the templates section."""
    if not _HAVE_YAML or source.kind != "yaml":
        return
    if not _PLACEHOLDER.search(source.text):
        return  # the cheap gate - no substitution anywhere in the file
    data, error = _parsed(source)
    if error is not None or not isinstance(data, dict) or object_kind(data) != _KIND:
        return
    sections = _section_names()
    root = _composed(source)
    if root is None or not isinstance(root, _yaml.MappingNode):
        return
    for key_node, value_node in root.value:
        if not (isinstance(key_node, _yaml.ScalarNode) and key_node.value in sections):
            continue
        if not isinstance(value_node, _yaml.MappingNode):
            continue
        for entry_key, entry_value in value_node.value:
            if not (isinstance(entry_key, _yaml.ScalarNode)
                    and isinstance(entry_value, _yaml.ScalarNode)):
                continue
            found = _PLACEHOLDER.search(entry_value.value or "")
            if found is None:
                continue
            yield Diagnostic(
                source.rel, entry_key.start_mark.line + 1, entry_key.start_mark.column + 1,
                "yaml/placeholder-key-in-strings", Severity.ERROR,
                i18n.t("yaml/placeholder-key-in-strings.found",
                       key=entry_key.value, placeholder=found.group(0)),
            )


# --- code/compare-with-localized -------------------------------------------------------

_COMPARISONS = frozenset({"==", "!="})
_PRESENTATION = "Представление"


@lru_cache(maxsize=1)
def _presentation_names() -> frozenset[str]:
    """Both spellings of the platform's presentation method."""
    english = terms.common_english(_PRESENTATION)
    return frozenset({_PRESENTATION, english} - {None})


dataset.register_reset(_presentation_names.cache_clear)


def _call_end(toks: list, name_at: int) -> int | None:
    """Index just past a `Имя(...)` call whose name token is at `name_at`, else None."""
    n = len(toks)
    if not (name_at + 1 < n and toks[name_at + 1].kind == "OP"
            and toks[name_at + 1].value == "("):
        return None
    depth, j = 1, name_at + 2
    while j < n and depth:
        if toks[j].kind == "OP" and toks[j].value == "(":
            depth += 1
        elif toks[j].kind == "OP" and toks[j].value == ")":
            depth -= 1
        j += 1
    return j if not depth else None


def _comparison_candidates(toks: list) -> list[dict]:
    """Localized calls that STAND NEXT TO a comparison, with everything the reduce needs.

    The map phase cannot judge on its own - which names are dictionaries is known only
    after every yaml has been read - but it can do all the token work here and ship a
    handful of records instead of the source: the reduce then only filters by name. The
    candidates are narrowed by the comparison itself, so a module full of ordinary calls
    contributes nothing at all.
    """
    presentation = _presentation_names()
    spans: list[tuple[int, int, str, str]] = []  # start, end, what, base ("" - Представление)
    n = len(toks)
    for i, t in enumerate(toks):
        if t.kind != "IDENT":
            continue
        if (i + 2 < n and toks[i + 1].kind == "OP" and toks[i + 1].value == "."
                and toks[i + 2].kind == "IDENT"):
            end = _call_end(toks, i + 2)
            if end is not None:
                spans.append((i, end, f"{t.value}.{toks[i + 2].value}", t.value))
        elif (t.value in presentation and i
              and toks[i - 1].kind == "OP" and toks[i - 1].value == "."):
            end = _call_end(toks, i)
            if end is not None:
                spans.append((i - 1, end, f".{t.value}()", ""))
    starts = {start: number for number, (start, _e, _w, _b) in enumerate(spans)}
    ends = {end: number for number, (_s, end, _w, _b) in enumerate(spans)}

    found: list[dict] = []
    for start, end, what, base in spans:
        sides = []
        for op_at, other_at, peer in (
            (start - 1, start - 2, ends.get(start - 1)),
            (end, end + 1, starts.get(end + 1)),
        ):
            if not (0 <= op_at < n and 0 <= other_at < n):
                continue
            op = toks[op_at]
            if not (op.kind == "OP" and op.value in _COMPARISONS):
                continue
            other = toks[other_at]
            sides.append({
                "op_at": op_at, "peer": peer,
                "kind": other.kind, "value": other.value,
            })
        if sides:
            anchor = toks[start]
            found.append({
                "base": base, "what": what,
                "line": anchor.line, "col": anchor.col, "sides": sides,
            })
    return found


def _compare_mapper(source: SourceFile) -> dict | None:
    """The map phase: a yaml names a dictionary of the project, a module contributes the
    candidates found in its own tokens - the reduce needs the dictionary names to judge."""
    if not _HAVE_YAML:
        return None
    if source.kind == "yaml":
        data, error = _parsed(source)
        if error is not None or not isinstance(data, dict) or object_kind(data) != _KIND:
            return None
        name = data.get("Имя") or data.get("Name")
        if not isinstance(name, str):
            return None
        return {"k": "y", "name": name}
    if source.kind != "xbsl":
        return None
    candidates = _comparison_candidates(code_tokens(source))
    return {"k": "x", "spans": candidates} if candidates else None


@rule(
    "code/compare-with-localized", "code/compare-with-localized.title", "D",
    scope="project", severity=Severity.WARNING, mapper=_compare_mapper,
)
def compare_with_localized(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    """The reduce phase: keep the candidates whose base is a dictionary of THIS project."""
    dictionaries = frozenset(f["name"] for f in facts.values() if f["k"] == "y")
    for rel, fact in facts.items():
        if fact["k"] != "x":
            continue
        spans = fact["spans"]
        # A candidate is localized when its base is a project dictionary; `Представление`
        # is localized by the platform itself and carries no base.
        live = {
            number for number, span in enumerate(spans)
            if not span["base"] or span["base"] in dictionaries
        }
        seen: set[int] = set()
        for number in sorted(live):
            span = spans[number]
            for side in span["sides"]:
                op_at = side["op_at"]
                if op_at in seen:
                    continue
                if side["peer"] in live:
                    key, args = "code/compare-with-localized.both", {"what": span["what"]}
                elif side["kind"] == "STRING":
                    key = "code/compare-with-localized.literal"
                    args = {"what": span["what"], "literal": side["value"]}
                else:
                    continue  # comparing against a value, not against text
                seen.add(op_at)
                yield Diagnostic(
                    rel, span["line"], span["col"],
                    "code/compare-with-localized", Severity.WARNING,
                    i18n.t(key, **args),
                )


# --- conventions/untranslated-visible-literal ---------------------------------------------

#: A localization-dictionary reference: $Dictionary.Key or $Key.
_REFERENCE_RE = re.compile(r"^\$[A-Za-zА-Яа-яЁё_][\w.]*$")
_CYRILLIC_RE = re.compile(r"[А-Яа-яЁё]")

#: Identifier-like keys: their value is never shown to a user.
_TECHNICAL_KEYS = frozenset({
    "Имя", "Name", "Ид", "Id", "Тип", "Type", "ВидЭлемента", "ElementKind",
    "Обработчик", "Handler", "Значение", "Value", "Выражение", "Expression",
})
_PRESENTATION_KEYS = frozenset({"Представление", "Presentation"})
_LANGUAGES_KEYS = ("ЯзыкиЛокализации", "LocalizationLanguages")


def _scalar_entries(root):
    """(key, value, value node, whether the mapping is the file root) over every mapping."""
    for mapping in _mapping_nodes(root):
        top = mapping is root
        for key_node, value_node in mapping.value:
            if (isinstance(key_node, _yaml.ScalarNode)
                    and isinstance(value_node, _yaml.ScalarNode)
                    and isinstance(value_node.value, str)):
                yield key_node.value, value_node.value, value_node, top


def _untranslated_mapper(source: SourceFile) -> dict | None:
    """Map phase: the descriptor answers the localization languages, an object its
    references and literals.

    The narrowings without which the reconnaissance lied fourfold: a localized-strings
    dictionary is not judged (its key IS the text), a value starting with "=" is an
    expression rather than text (it may call the dictionary itself), and a top-level
    `Представление` of an object is a FIELD NAME, not a caption - that one belongs to
    yaml/presentation-field.
    """
    if not _HAVE_YAML or source.kind != "yaml":
        return None
    data, error = _parsed(source)
    if error is not None or not isinstance(data, dict):
        return None
    for key in _LANGUAGES_KEYS:
        languages = data.get(key)
        if isinstance(languages, list):
            return {"k": "languages", "languages": [str(x) for x in languages]}
    kind = object_kind(data)
    if not kind or kind == _KIND:
        return None
    root = _composed(source)
    if root is None or not isinstance(root, _yaml.MappingNode):
        return None
    refs: list[str] = []
    literals: list[tuple[str, str, int, int]] = []
    for key, value, node, top in _scalar_entries(root):
        if key in _TECHNICAL_KEYS or value.startswith("="):
            continue
        if top and key in _PRESENTATION_KEYS:
            continue
        if _REFERENCE_RE.match(value):
            refs.append(key)
        elif _CYRILLIC_RE.search(value):
            literals.append((key, value, node.start_mark.line + 1, node.start_mark.column + 1))
    if not refs and not literals:
        return None
    return {"k": "object", "kind": kind, "refs": refs, "literals": literals}


@rule(
    "conventions/untranslated-visible-literal",
    "conventions/untranslated-visible-literal.title", "D",
    scope="project", severity=Severity.WARNING, mapper=_untranslated_mapper,
)
def untranslated_visible_literal(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    """Visible text left as a literal where the project already localizes that property.

    Self-tuning: only the keys the project itself references into a dictionary somewhere
    are judged, and the intent is counted per element kind - see the module docstring.
    """
    languages: list[str] = []
    for fact in facts.values():
        if fact["k"] == "languages":
            languages = fact["languages"]
            break
    if len(languages) < 2:
        return
    reference_keys: Counter = Counter()
    for fact in facts.values():
        if fact["k"] == "object":
            reference_keys.update((fact["kind"], key) for key in fact["refs"])
    if not reference_keys:
        return
    for rel, fact in facts.items():
        if fact["k"] != "object":
            continue
        for key, value, line, col in fact["literals"]:
            if (fact["kind"], key) not in reference_keys:
                continue
            yield Diagnostic(
                rel, line, col,
                "conventions/untranslated-visible-literal", Severity.WARNING,
                i18n.t("conventions/untranslated-visible-literal.found",
                       key=key, value=value),
            )


# --- conventions/untranslated-code-literal -------------------------------------------------

_EVENT_KIND = "СобытиеЖурналаСобытий"
_MESSAGE_CALL = "Сообщить"
_PROPERTY_KEYS = ("Свойства", "Properties")
_NAME_KEYS = ("Имя", "Name")

#: How far back a call opener is looked for from an argument: a call longer than this is
#: neither a message nor an event constructor.
_CALL_SPAN = 120


@lru_cache(maxsize=1)
def _message_names() -> frozenset[str]:
    """Both spellings of the platform's message call."""
    return frozenset({_MESSAGE_CALL, terms.common_english(_MESSAGE_CALL)} - {None})


dataset.register_reset(_message_names.cache_clear)


def _has_cyrillic(text: str) -> bool:
    return bool(_CYRILLIC_RE.search(text))


def _literal_text(value: str) -> str:
    """The text of a STRING token without its quotes."""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def _is_technical(text: str) -> bool:
    """Shapes that carry no prose: markup, styles, pure interpolation, a single word.

    A single Cyrillic word is not judged on purpose: those are field names, codes and keys,
    and reconnaissance found them to outnumber real phrases.
    """
    stripped = text.strip()
    if not stripped or "<" in stripped:
        return True
    if "{" in stripped and "}" in stripped and ";" in stripped:
        return True
    without_holes = stripped
    for opener in ("%{", "${"):
        while opener in without_holes:
            start = without_holes.index(opener)
            end = without_holes.find("}", start)
            if end < 0:
                break
            without_holes = f"{without_holes[:start]} {without_holes[end + 1:]}"
    words = [w for w in without_holes.replace(",", " ").split() if _has_cyrillic(w)]
    return len(words) < 2


def _enclosing_call(toks: list, at: int) -> int | None:
    """Index of the '(' whose argument list holds the token at `at`, else None."""
    depth = 0
    for back in range(at - 1, max(-1, at - _CALL_SPAN), -1):
        token = toks[back]
        if token.kind != "OP":
            continue
        if token.value in ")]}":
            depth += 1
        elif token.value in "([{":
            if depth == 0:
                return back if token.value == "(" else None
            depth -= 1
    return None


def _argument_position(toks: list, opener: int, at: int) -> int | None:
    """Zero-based position of the argument that holds the token at `at`."""
    position, depth = 0, 0
    for j in range(opener + 1, len(toks)):
        if j == at:
            return position
        token = toks[j]
        if token.kind != "OP":
            continue
        if token.value in "([{":
            depth += 1
        elif token.value in ")]}":
            if depth == 0:
                return None
            depth -= 1
        elif token.value == "," and depth == 0:
            position += 1
    return None


def _sink_at(toks: list, at: int) -> dict | None:
    """The sink an expression at index `at` lands in, as far as one module can tell.

    An event sink is reported as a CANDIDATE: whether the holder is an event-log event is
    known only after every yaml of the project is read, so the reduce decides.
    """
    opener = _enclosing_call(toks, at)
    if not opener:
        return None
    callee = toks[opener - 1]
    if callee.kind != "IDENT":
        return None
    if callee.value in _message_names():
        return {"kind": "message", "call": callee.value}
    if (at >= 2 and toks[at - 1].kind == "OP" and toks[at - 1].value == "="
            and toks[at - 2].kind == "IDENT"):
        return {"kind": "event", "holder": callee.value, "property": toks[at - 2].value}
    position = _argument_position(toks, opener, at)
    if position is None:
        return None
    qualifier = None
    if (opener >= 3 and toks[opener - 2].kind == "OP" and toks[opener - 2].value == "."
            and toks[opener - 3].kind == "IDENT"):
        qualifier = toks[opener - 3].value
    return {"kind": "call", "callee": callee.value, "qualifier": qualifier,
            "position": position}


def _forwarded_parameters(toks: list) -> list[dict]:
    """Methods whose parameter goes WHOLE into a sink: one record per (method, position)."""
    out: list[dict] = []
    sigs = signatures(toks)
    seen: set[tuple[str, int]] = set()
    for number, sig in enumerate(sigs):
        end = sigs[number + 1].name.line if number + 1 < len(sigs) else 1 << 30
        names = [p.name.value for p in sig.params]
        if not names:
            continue
        for i, token in enumerate(toks):
            if token.kind != "IDENT" or token.value not in names:
                continue
            if not sig.name.line <= token.line < end:
                continue
            sink = _sink_at(toks, i)
            if sink is None or sink["kind"] == "call":
                continue
            key = (sig.name.value, names.index(token.value))
            if key in seen:
                continue
            seen.add(key)
            out.append({"method": key[0], "position": key[1], "sink": sink})
    return out


def _code_literal_mapper(source: SourceFile) -> dict | None:
    """Map phase: a yaml answers languages, events and dictionary values; a module its
    literals with the sink each one reaches and the parameters it forwards."""
    if not _HAVE_YAML:
        return None
    if source.kind == "yaml":
        data, error = _parsed(source)
        if error is not None or not isinstance(data, dict):
            return None
        for key in _LANGUAGES_KEYS:
            languages = data.get(key)
            if isinstance(languages, list):
                return {"k": "languages", "languages": [str(x) for x in languages]}
        kind = object_kind(data)
        name = next((data[k] for k in _NAME_KEYS if isinstance(data.get(k), str)), None)
        if kind == _EVENT_KIND and name:
            properties: list[str] = []
            for section in _PROPERTY_KEYS:
                for item in data.get(section) or []:
                    if isinstance(item, dict):
                        properties += [
                            item[k] for k in _NAME_KEYS if isinstance(item.get(k), str)
                        ]
            return {"k": "event", "name": name, "properties": properties}
        if kind == _KIND and name:
            values: dict[str, str] = {}
            for section in (*_section_names(), _TEMPLATES):
                entries = data.get(section)
                if not isinstance(entries, dict):
                    continue
                for key, value in entries.items():
                    if (isinstance(value, str) and _has_cyrillic(value)
                            and len(value.split()) > 1):
                        values.setdefault(value.strip(), f"{name}.{key}")
            return {"k": "dictionary", "values": values} if values else None
        return None
    if source.kind != "xbsl":
        return None
    toks = code_tokens(source)
    literals = []
    for i, token in enumerate(toks):
        if token.kind != "STRING" or in_query(source, token.start):
            continue
        text = _literal_text(token.value)
        if not _has_cyrillic(text) or _is_technical(text):
            continue
        sink = _sink_at(toks, i)
        if sink is not None:
            literals.append(
                {"line": token.line, "col": token.col, "text": text, "sink": sink}
            )
    forwards = _forwarded_parameters(toks)
    if not literals and not forwards:
        return None
    stem = source.rel.replace("\\", "/").rsplit("/", 1)[-1]
    return {"k": "module", "module": stem.split(".")[0],
            "literals": literals, "forwards": forwards}


def _sink_phrase(sink: dict, events: dict[str, frozenset[str]]) -> str | None:
    """The human half of the message: which sink the literal reaches, None if none does."""
    if sink["kind"] == "message":
        return i18n.t("conventions/untranslated-code-literal.message-sink", call=sink["call"])
    if sink["kind"] == "event":
        holder, prop = sink["holder"], sink["property"]
        if prop in events.get(holder, frozenset()):
            return i18n.t("conventions/untranslated-code-literal.event-sink",
                          event=holder, property=prop)
    return None


@rule(
    "conventions/untranslated-code-literal",
    "conventions/untranslated-code-literal.title", "D",
    scope="project", severity=Severity.WARNING, mapper=_code_literal_mapper,
    enabled_by_default=False, off_reason="conventions/untranslated-code-literal.off",
)
def untranslated_code_literal(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    """Visible text left as a literal in a module - see the module docstring."""
    languages: list[str] = []
    events: dict[str, frozenset[str]] = {}
    dictionary: dict[str, str] = {}
    for fact in facts.values():
        if fact["k"] == "languages":
            languages = fact["languages"]
        elif fact["k"] == "event":
            events[fact["name"]] = frozenset(fact["properties"])
        elif fact["k"] == "dictionary":
            dictionary.update(fact["values"])
    if len(languages) < 2:
        return
    # A method is a conduit when the sink its parameter reaches is a real one. The owning
    # module is part of the key, so a namesake in another module does not answer for it.
    conduits: dict[tuple[str, str], dict[int, str]] = {}
    for fact in facts.values():
        if fact["k"] != "module":
            continue
        for forward in fact["forwards"]:
            phrase = _sink_phrase(forward["sink"], events)
            if phrase is None:
                continue
            key = (fact["module"], forward["method"])
            conduits.setdefault(key, {})[forward["position"]] = phrase
    for rel, fact in facts.items():
        if fact["k"] != "module":
            continue
        for literal in fact["literals"]:
            sink = literal["sink"]
            phrase = _sink_phrase(sink, events)
            if phrase is None and sink["kind"] == "call":
                owner = sink["qualifier"] or fact["module"]
                forwarded = conduits.get((owner, sink["callee"]), {}).get(sink["position"])
                if forwarded is not None:
                    phrase = i18n.t("conventions/untranslated-code-literal.forwarded-sink",
                                    sink=forwarded, method=sink["callee"])
            if phrase is None:
                continue
            known = dictionary.get(literal["text"].strip())
            message_key = ("conventions/untranslated-code-literal.known" if known
                           else "conventions/untranslated-code-literal.found")
            arguments = {"value": literal["text"][:60], "sink": phrase}
            if known:
                arguments["key"] = known
            yield Diagnostic(
                rel, literal["line"], literal["col"],
                "conventions/untranslated-code-literal", Severity.WARNING,
                i18n.t(message_key, **arguments),
            )
