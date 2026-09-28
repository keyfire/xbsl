"""Documentation comments in the editor: the hover, the signature help and the completion.

The environment builds its hover, its signature help and its completion from the `///` block
of a declaration (`xbsl/doctags.py` reads it). The language server answers the same three
questions from the same block, so a method documented for the environment reads alike in the
editor:

- the hover of a project method renders the block with a section per kind of tag -
  "Параметры", "Возвращает", "Выбрасывает", "Смотреть также" - the way the environment's own
  card does (`doc_markdown`);
- the signature help of a call of a project method shows the parameter under the cursor with
  the text of its `@параметр` tag (`signature_help`);
- inside a `///` line the completion offers the tag words, after `@параметр` the parameters
  of the method below that the block has not described yet, and on an empty line above a
  declaration the block the environment's template writes (`doc_completions`).

The functions take plain text and the project index; the server wires them in `lsp.py`.
"""

from __future__ import annotations

import dataclasses
import re
from typing import Optional

from xbsl import doctags, engine, lexer
from xbsl.parser import Enum, EnumItem, Method, ObjectField, Structure, parse
from xbsl.rules.comment_doc_tags import _no_result_forms

#: The template of a block, by language: the placeholders the environment's own template
#: writes (a description, a parameter, a result).
_TEMPLATE_WORDS = {
    "ru": {"description": "Документирующий комментарий", "param": "Параметр",
           "returns": "Результат"},
    "en": {"description": "Doc comment", "param": "Parameter", "returns": "Result"},
}
_DETAILS = {
    "param": "параметр метода", "returns": "возвращаемое значение",
    "throws": "выбрасываемое исключение", "see": "дополнительная информация",
}
#: How far back a call is looked for: a call spread over more lines than this is rare, and
#: the prefix of a long module is tokenized on every keystroke of the signature help.
_CALL_LOOKBACK_LINES = 400

_DOC_LINE_RE = re.compile(r"^(\s*)///")
_TAG_WORD_RE = re.compile(r"(\s*)@(\w*)")
_PARAM_NAME_RE = re.compile(r"\s*@(?:" + "|".join(doctags.TAGS["param"]) + r")\s+(\w*)")
_ANNOTATION_RE = re.compile(r"\s*(?:@\w+(?:\([^)]*\))?\s*)*")


def doc_markdown(doc: str, lang: str = "ru") -> str:
    """The Markdown of a documentation comment: the description and a section per kind of tag."""
    return doctags.render_markdown(doctags.environment_model(doc), lang)


# --- the signature help ------------------------------------------------------------------------

def split_params(params: str) -> list[tuple[int, int]]:
    """(start, end) of every parameter inside a parenthesized list `(А: Число, Б: Строка = "")`.

    A comma inside brackets, angle brackets or a string belongs to the parameter; `->` of a
    function type is no closing bracket.
    """
    if len(params) < 2 or params[0] != "(" or params[-1] != ")":
        return []
    spans: list[tuple[int, int]] = []
    depth, start, quoted = 0, 1, False
    for index in range(1, len(params) - 1):
        char = params[index]
        if char == '"':
            quoted = not quoted
        if quoted:
            continue
        if char in "(<[{":
            depth += 1
        elif char in ")]}" or (char == ">" and params[index - 1] != "-"):
            depth -= 1
        elif char == "," and depth == 0:
            spans.append((start, index))
            start = index + 1
    spans.append((start, len(params) - 1))
    out = []
    for first, last in spans:
        piece = params[first:last]
        if not piece.strip():
            continue
        first += len(piece) - len(piece.lstrip())
        last -= len(piece) - len(piece.rstrip())
        out.append((first, last))
    return out


def param_name(piece: str) -> str:
    """The name of a parameter as the signature writes it, its annotations taken off."""
    rest = piece[_ANNOTATION_RE.match(piece).end():]
    found = re.match(r"\w+", rest)
    return found.group(0) if found else ""


def call_at(prefix: str) -> Optional[tuple[list[str], int]]:
    """(the chain of names the call is made on, the index of the argument the cursor is in).

    `prefix` is the text of the document up to the cursor. The innermost bracket still open
    decides: a round one after a name is a call, anything else is not. A constructor
    (`новый Тип(`) is not a call of a method.
    """
    lines = prefix.split("\n")
    text = "\n".join(lines[-_CALL_LOOKBACK_LINES:])
    try:
        toks = [tok for tok in lexer.tokenize(text) if tok.kind != "COMMENT"]
    except Exception:  # noqa: BLE001 - a buffer the lexer cannot take has no call to show
        return None
    depth = commas = 0
    opening = -1
    for index in range(len(toks) - 1, -1, -1):
        tok = toks[index]
        if tok.kind != "OP":
            continue
        if tok.value in (")", "]", "}"):
            depth += 1
        elif tok.value in ("(", "[", "{"):
            if depth == 0:
                opening = index if tok.value == "(" else -1
                break
            depth -= 1
        elif tok.value == "," and depth == 0:
            commas += 1
    if opening < 1 or toks[opening - 1].kind != "IDENT":
        return None
    chain = [toks[opening - 1].value]
    index = opening - 2
    while index >= 1 and toks[index].kind == "OP" and toks[index].value == "." \
            and toks[index - 1].kind in ("IDENT", "KEYWORD"):
        chain.insert(0, toks[index - 1].value)
        index -= 2
    if index >= 0 and toks[index].kind == "KEYWORD" and toks[index].canonical == "NEW":
        return None
    return chain, commas


def resolve_method(lookup, chain: list[str], file_stem: str,
                   file_path: Optional[str]) -> Optional[dict]:
    """The project method a call names: one of this module, of another module, of a component."""
    name = chain[-1]
    if len(chain) == 1:
        return (lookup.method_in_file(file_path, name) if file_path else None) or \
            lookup.method(file_stem, name)
    return lookup.method(chain[-2], name)


def signature_help(lookup, prefix: str, file_stem: str,
                   file_path: Optional[str] = None) -> Optional[dict]:
    """The signature of the project method whose call the cursor stands in, or None.

    {label, documentation, parameters: [{label: [start, end], documentation}], active}: the
    documentation of a parameter is the text of its `@параметр` tag, that of the method its
    description and the sections of the result and the exceptions.
    """
    found = call_at(prefix)
    if found is None:
        return None
    chain, active = found
    method = resolve_method(lookup, chain, file_stem, file_path)
    if method is None:
        return None
    name = method.get("name", chain[-1])
    params = method.get("params") or "()"
    label = f"{name}{params}"
    if method.get("returns"):
        label += f": {method['returns']}"
    model = doctags.environment_model(str(method.get("doc") or ""))
    parameters = []
    for first, last in split_params(params):
        text = model.param(param_name(params[first:last]))
        parameters.append({
            "label": [len(name) + first, len(name) + last],
            "documentation": (text or "").strip(),
        })
    return {
        "label": label,
        "documentation": doctags.render_markdown(dataclasses.replace(model, params=())),
        "parameters": parameters,
        "active": min(active, len(parameters) - 1) if parameters else 0,
    }


# --- the completion ---------------------------------------------------------------------------

def _language(source) -> str:
    """`en` for a module written with English keywords, `ru` otherwise."""
    latin = cyrillic = 0
    for tok in lexer.tokens(source):
        if tok.kind == "KEYWORD" and tok.value[:1].isalpha():
            if tok.value[:1].isascii():
                latin += 1
            else:
                cyrillic += 1
    return "en" if latin > cyrillic else "ru"


def _declarations(module):
    for member in module.members:
        yield member
        if isinstance(member, Structure):
            yield from member.members
        elif isinstance(member, Enum):
            yield from member.items
            yield from member.methods


def _declaration_below(text: str, name: str, first: int):
    """(the declaration whose first line - annotations included - is line `first`, 0-based, the
    language of the module), or (None, language)."""
    source = engine.load_text(name, text)
    language = _language(source)
    module, _errors = parse(source)
    if module is None:
        return None, language
    lm = lexer.linemap(source)
    for decl in _declarations(module):
        if isinstance(decl, (Method, ObjectField, Structure, Enum, EnumItem)) \
                and lm.linecol(decl.start)[0] == first + 1:
            return decl, language
    return None, language


def _is_doc_line(line: str) -> bool:
    return _DOC_LINE_RE.match(line) is not None


def _item(label: str, kind: str, detail: str, new_text: str, start: int, end: int,
          snippet: bool = False, sort: str = "") -> dict:
    return {"label": label, "kind": kind, "detail": detail, "new_text": new_text,
            "range": (start, end), "snippet": snippet, "sort": sort or label}


def _template(decl, language: str, indent: str) -> str:
    """The block the environment's template writes above a declaration, as a snippet."""
    words = _TEMPLATE_WORDS[language]
    lines = [f"{indent}/// ${{1:{words['description']}}}"]
    number = 2
    if isinstance(decl, Method):
        if decl.params:
            lines.append(f"{indent}///")
            for param in decl.params:
                lines.append(f"{indent}/// @{doctags.keyword('param', language)} {param.name}"
                             f" - ${{{number}:{words['param']}}}")
                number += 1
        if decl.return_type is not None and decl.return_type.text not in _no_result_forms():
            lines.append(f"{indent}///")
            lines.append(f"{indent}/// @{doctags.keyword('returns', language)}"
                         f" ${{{number}:{words['returns']}}}")
    return "\n".join(lines)


def doc_completions(text: str, name: str, line: int, character: int
                    ) -> tuple[list[dict], bool]:
    """(the completion items of a documentation comment, whether they are the whole answer).

    Inside a `///` line they are: the tag words, the parameters after `@параметр`, or the
    template on a line that is the only one of its block. On an empty line above a
    declaration the template joins the items of the code. Anywhere else there is nothing.
    """
    lines = text.split("\n")
    if line >= len(lines):
        return [], False
    current = lines[line].rstrip("\r")
    prefix = current[:character]
    marker = _DOC_LINE_RE.match(prefix)
    if marker is None:
        if current.strip():
            return [], False
        block_top = line
        doc_block = False
    else:
        block_top = line
        while block_top > 0 and _is_doc_line(lines[block_top - 1]):
            block_top -= 1
        doc_block = True
    below = line + 1
    while below < len(lines) and _is_doc_line(lines[below]):
        below += 1
    decl, language = _declaration_below(text, name, below)
    if not doc_block:
        if decl is None or (line > 0 and _is_doc_line(lines[line - 1])):
            return [], False
        return [_template_item(decl, language, current, character)], False
    body = prefix[marker.end():]
    tag = _TAG_WORD_RE.fullmatch(body)
    if tag:
        start = marker.end() + len(tag.group(1))
        items = []
        for order, kind in enumerate(doctags.ORDER):
            if kind != "see" and decl is not None and not isinstance(decl, Method):
                continue
            word = "@" + doctags.keyword(kind, language)
            items.append(_item(word, "keyword", _DETAILS[kind], word + " ", start, character,
                               sort=str(order)))
        return items, True
    named = _PARAM_NAME_RE.fullmatch(body)
    if named:
        if not isinstance(decl, Method):
            return [], True
        described = set()
        for number in range(block_top, below):
            written = _PARAM_NAME_RE.match(lines[number][len(_DOC_LINE_RE.match(lines[number])
                                                             .group(0)):])
            if written and number != line:
                described.add(written.group(1))
        start = character - len(named.group(1))
        items = [
            _item(param.name, "field", param.type.text if param.type else "",
                  param.name + " - ", start, character, sort=f"{order:03}")
            for order, param in enumerate(decl.params) if param.name not in described
        ]
        return items, True
    alone = block_top == line and below == line + 1
    if not body.strip() and alone and decl is not None and character >= len(current.rstrip()):
        return [_template_item(decl, language, current, character)], True
    return [], True


def _template_item(decl, language: str, current: str, character: int) -> dict:
    """The template of a block; it replaces the whole line and is filtered by what the line
    holds before the cursor (`///`, or nothing on an empty line)."""
    indent = current[:len(current) - len(current.lstrip())]
    label = _TEMPLATE_WORDS[language]["description"]
    item = _item(label, "snippet", "///", _template(decl, language, indent), 0,
                 max(character, len(current)), snippet=True, sort="!")
    item["filter"] = current[:character] + label
    return item
