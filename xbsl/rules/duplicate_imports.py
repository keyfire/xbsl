"""A namespace imported a second time (code/duplicate-import, yaml/duplicate-import).

`импорт Справочное` written twice brings nothing the first line has not brought. The platform
IDE warns about every repeat after the first in a module, and code/duplicate-import repeats what
the IDE judges, checked on probe projects variant by variant:

- the short and the full name are one namespace: `импорт Справочное` and
  `импорт Поставщик::Проект::Справочное` of the same project repeat each other, and so do the two
  spellings of a package (`Справочное::Пакет`);
- the names compare by their letters exactly: `импорт справочное` is not the same namespace (the
  IDE refuses it as unknown);
- an import that is repeated and unused at once is reported by both rules - the IDE does the same.

The `Import` section of an element yaml gets no warning from the IDE, repeats included; yet the
repeated entry adds nothing there either, so yaml/duplicate-import reports it by the same
reading. The two halves are separate rules on purpose: the module half is the IDE's warning, the
yaml half is not.

Telling the short name from the full one needs the identity of the project (the vendor and the
name of its descriptor), so both rules are project rules. Without a descriptor in the run only
the equal texts repeat each other. The removal of the line is mechanical, so the finding carries
a fix when the line holds nothing but the import (the module) or nothing but the entry (a block
list of the yaml).
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from xbsl import i18n
from xbsl.diagnostics import Diagnostic, Severity, TextEdit
from xbsl.engine import SourceFile, is_query_file, rule
from xbsl.lexer import Token
from xbsl.rules._syntax import code_tokens
from xbsl.rules.yaml_imports import _layout_fact, _layout_from
from xbsl.rules.yaml_schema import _HAVE_YAML, _composed, yaml
from xbsl.rules.yaml_types import _key_spellings

CODE_RULE = "code/duplicate-import"
YAML_RULE = "yaml/duplicate-import"

MESSAGES = {
    "code/duplicate-import.title": {
        "ru": "Повторный импорт пространства имён",
        "en": "A namespace imported again",
    },
    "code/duplicate-import.repeated": {
        "ru": "Пространство имён '{name}' уже импортировано в строке {line} – повторную строку можно снять.",
        "en": "Namespace '{name}' is already imported on line {line} – the repeated line can go.",
    },
    "yaml/duplicate-import.title": {
        "ru": "Повторный элемент секции Импорт",
        "en": "A repeated entry of the {n[Импорт]} section",
    },
    "yaml/duplicate-import.repeated": {
        "ru": "Пространство имён '{name}' уже есть в секции Импорт (строка {line}) – повторный "
              "элемент можно снять.",
        "en": "Namespace '{name}' is already in the {n[Импорт]} section (line {line}) – the repeated "
              "entry can go.",
    },
}
i18n.register(MESSAGES)


def _line_span(text: str, start: int, end: int) -> tuple[int, int] | None:
    """The whole line of [start, end) with its line break, when the line holds nothing else."""
    head = max(text.rfind("\n", 0, start), text.rfind("\r", 0, start)) + 1
    tail = end
    while tail < len(text) and text[tail] not in "\r\n":
        tail += 1
    if text[head:start].strip() or text[end:tail].strip():
        return None
    if text.startswith("\r\n", tail):
        tail += 2
    elif tail < len(text):
        tail += 1
    return head, tail


def _module_imports(source: SourceFile) -> list[tuple[str, int, int, tuple[int, int] | None]]:
    """(the namespace as written, line, column, the span of its line) of every `импорт`."""
    toks: list[Token] = code_tokens(source)
    out: list[tuple[str, int, int, tuple[int, int] | None]] = []
    for i, tok in enumerate(toks):
        if tok.kind != "KEYWORD" or tok.canonical != "IMPORT":
            continue
        parts: list[str] = []
        last = tok
        j = i + 1
        while j < len(toks) and toks[j].kind == "IDENT":
            parts.append(toks[j].value)
            last = toks[j]
            if j + 2 < len(toks) and toks[j + 1].kind == "OP" and toks[j + 1].value == "::":
                j += 2
                continue
            break
        if parts:
            out.append(("::".join(parts), tok.line, tok.col, _line_span(source.text, tok.start, last.end)))
    return out


def _yaml_imports(source: SourceFile) -> list[tuple[str, int, int, tuple[int, int] | None]]:
    """(the namespace, line, column, the span of its line) of every entry of the `Import` section."""
    root = _composed(source)
    if not isinstance(root, yaml.MappingNode):
        return []
    keys = _key_spellings("Импорт")
    out: list[tuple[str, int, int, tuple[int, int] | None]] = []
    for key_node, value in root.value:
        if not (isinstance(key_node, yaml.ScalarNode) and key_node.value in keys):
            continue
        if not isinstance(value, yaml.SequenceNode):
            continue
        block = not value.flow_style
        for item in value.value:
            if not isinstance(item, yaml.ScalarNode) or not isinstance(item.value, str):
                continue
            span = None
            if block and item.style in (None, ""):
                dash = source.text.rfind("-", 0, item.start_mark.index)
                span = _line_span(source.text, dash, item.end_mark.index) if dash >= 0 else None
            out.append((item.value.strip(), item.start_mark.line + 1, item.start_mark.column + 1, span))
    return out


def _mapper(source: SourceFile) -> dict | None:
    """The map phase: a descriptor gives its place in the layout, a module or an element yaml the
    namespaces it imports - only when there are two of them at least."""
    if source.kind == "xbsl" and not is_query_file(source.path):
        if "импорт" not in source.text and "import" not in source.text \
                and "Импорт" not in source.text and "Import" not in source.text:
            return None
        imports = _module_imports(source)
        return {"k": "mod", "path": str(source.path), "imports": imports} if len(imports) > 1 else None
    if source.kind != "yaml" or not _HAVE_YAML:
        return None
    if (fact := _layout_fact(source)) is not None:
        return fact
    imports = _yaml_imports(source)
    return {"k": "yml", "path": str(source.path), "imports": imports} if len(imports) > 1 else None


def _repeats(facts: dict[str, dict], kind: str, rule_id: str) -> Iterable[Diagnostic]:
    layout = _layout_from(facts)
    for rel, fact in facts.items():
        if fact["k"] != kind:
            continue
        project_dir = layout.project_dir_of(Path(fact["path"]))
        first_line: dict[str, int] = {}
        for written, line, col, span in fact["imports"]:
            key = layout.local_name(written, project_dir)
            if key not in first_line:
                first_line[key] = line
                continue
            yield Diagnostic(
                rel, line, col, rule_id, Severity.WARNING,
                i18n.t(f"{rule_id}.repeated", name=written, line=first_line[key]),
                fix=TextEdit(span[0], span[1], "") if span else None,
            )


@rule(CODE_RULE, "code/duplicate-import.title", "C", scope="project", severity=Severity.WARNING,
      mapper=_mapper)
def duplicate_code_import(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    """A namespace a module imports again - see the module docstring."""
    yield from _repeats(facts, "mod", CODE_RULE)


@rule(YAML_RULE, "yaml/duplicate-import.title", "A", scope="project", severity=Severity.WARNING,
      mapper=_mapper)
def duplicate_yaml_import(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    """A namespace the `Import` section of an element lists again - see the module docstring."""
    yield from _repeats(facts, "yml", YAML_RULE)
