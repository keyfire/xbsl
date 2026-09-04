"""Tier D: a form module reaching a component its own markup does not declare.

`Компоненты.X` is the static map a form gets from its markup, so a name that is not in the
paired yaml does not exist at compile time and the apply refuses the project with
`Unknown property "<Form>.Компоненты.<Name>"`. The compiler is the only thing that sees it
today: nothing in the module itself is wrong, the name simply lost its counterpart when a
field was moved out of one column and not put into another.

Two questions had to be answered before the rule could be trusted, and both were answered
with evidence rather than with the documentation.

**Does a nested name work?** A component sits inside a group, and the group inside the form
template. A probe compiled three forms on a throwaway application, one access each: the name
of a nested component and the name of the group itself both compile, an invented name is
refused. So the whole tree of the markup is reachable through the root, and the rule must
collect names at every depth.

**Does inheritance bring names from outside?** A form inherits `ObjectForm<X>`,
`ListForm<X>`, `StandardCard` and the like, and a component contributed by the base
would be a false positive - the dangerous direction, since a name absent from the markup would
then be reported as a defect. A measurement over a live project settled it: 157 forms with
modules, 360 `Компоненты.X` accesses, and NOT ONE name outside its own markup, whatever the
form inherits. The tree compiles, so every one of those accesses is legal - the measurement is
therefore a direct count of the false positives this rule would produce, and it is zero.

Deliberately lax, so that doubt keeps silence:

- the declared set is every `Name` value of the yaml, not only the ones under `Content`.
  A key that names something other than a component costs at most a missed finding, while a
  stricter reading would cost a false one;
- an access whose root is shadowed in the module (a local named like the root) is skipped;
- only the FIRST name after the root is judged: in `Компоненты.Карточка.Компоненты.Поле` the
  second one belongs to another component's markup, which this file cannot see;
- a yaml that does not parse is left to the checks that judge syntax.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path

from xbsl import dataset, i18n, terms
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, make_source, rule
from xbsl.rules._syntax import code_tokens
from xbsl.rules.yaml_schema import _parsed, object_kind, yaml

MESSAGES = {
    "code/unknown-form-component.title": {
        "ru": "Обращение к компоненту, которого нет в разметке формы",
        "en": "Access to a component the form markup does not declare",
    },
    "code/unknown-form-component.access": {
        "ru": "Компонента '{name}' нет в разметке формы '{form}' – применение отвергает "
              "проект сообщением Unknown property \"{form}.Компоненты.{name}\". Обычно имя "
              "осталось от компонента, который вынесли из разметки и не вернули: верните "
              "компонент либо снимите обращение.",
        "en": "Component '{name}' is not declared in the markup of form '{form}' - the apply "
              "refuses the project with an \"Unknown property\" naming it. Usually the name "
              "outlived a component that was taken out of the markup and never put back: "
              "restore the component, or drop the access.",
    },
}
i18n.register(MESSAGES)


#: Both spellings of the root through which a form reaches its own components. Written out
#: rather than asked of the term dictionary: the root is a language surface, not a metadata
#: name, and the dictionary answers it with the Russian spelling alone.
_COMPONENT_ROOTS = frozenset({"Компоненты", "Components"})


@lru_cache(maxsize=1)
def _name_keys() -> frozenset[str]:
    """Both spellings of the key that names a component."""
    return frozenset(terms.key_forms("Имя"))


dataset.register_reset(_name_keys.cache_clear)

#: A local that shadows the root: a declaration, a parameter or an assignment of that name.
#: The rule reads the module as text, so the cheap textual test is the honest one - a shadowed
#: root means the accesses are not the form's own, and the whole file is skipped.
_SHADOW_RE = re.compile(
    r"(?:^|[^.\w])(?:знч|пер|var|val)\s+(?P<name>[A-Za-zА-Яа-яЁё_][\wА-Яа-яЁё]*)\b"
)


def _declared_names(pair: Path) -> set[str] | None:
    """Every value of a name key in the paired yaml; None when it does not parse."""
    try:
        if not pair.is_file():
            return None
        source = make_source(pair, pair.read_bytes())
    except OSError:
        return None
    data, error = _parsed(source)
    if error is not None or not isinstance(data, dict):
        return None
    if object_kind(data) != "КомпонентИнтерфейса":
        return None
    keys = _name_keys()
    found: set[str] = set()

    def walk(node) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key in keys and isinstance(value, str):
                    found.add(value)
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(data)
    return found


@rule("code/unknown-form-component", "code/unknown-form-component.title", "D",
      severity=Severity.ERROR)
def unknown_form_component(source: SourceFile) -> Iterable[Diagnostic]:
    """`Компоненты.X` where X is not a name of the paired markup."""
    if source.kind != "xbsl" or yaml is None:
        return
    toks = code_tokens(source)
    if not toks:
        return
    roots = _COMPONENT_ROOTS
    accesses = []
    for i, tok in enumerate(toks):
        if tok.kind != "IDENT" or tok.value not in roots:
            continue
        if i > 0 and toks[i - 1].kind == "OP" and toks[i - 1].value == ".":
            continue  # a nested access: the name belongs to another component's markup
        if not (i + 2 < len(toks) and toks[i + 1].kind == "OP" and toks[i + 1].value == "."
                and toks[i + 2].kind == "IDENT"):
            continue
        accesses.append(toks[i + 2])
    if not accesses:
        return
    if any(m.group("name") in roots for m in _SHADOW_RE.finditer(source.text)):
        return
    declared = _declared_names(Path(source.path).with_suffix(".yaml"))
    if declared is None:
        return
    form = Path(source.path).stem
    for token in accesses:
        if token.value in declared:
            continue
        yield Diagnostic(
            source.rel, token.line, token.col, "code/unknown-form-component",
            Severity.ERROR,
            i18n.t("code/unknown-form-component.access", name=token.value, form=form),
        )
