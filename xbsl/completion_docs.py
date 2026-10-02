"""Lazy Markdown documentation for a selected standard-library method completion."""

from __future__ import annotations

import re
from html import escape

from xbsl import dataset, docs, terms
from xbsl.extract.stdlib import _without_mark

_HEADING_RE = re.compile(r"<h3\b[^>]*>.*?</h3>", re.I | re.S)
_CODE_RE = re.compile(r"<pre\b[^>]*>(.*?)</pre>", re.I | re.S)
_DETAIL_RE = re.compile(r"<h[1-6]\b|<hr\b|<p\b[^>]*>\s*<(?:strong|b)\b", re.I)
_PARAM_CAPTION_RE = re.compile(
    r"<(?:strong|b)\b[^>]*>\s*(?:Параметры|Parameters)\s*</(?:strong|b)>", re.I,
)
_DEFINITION_RE = re.compile(r"<dt\b[^>]*>(.*?)</dt>\s*<dd\b[^>]*>(.*?)</dd>", re.I | re.S)
_SIGNATURE_TOKEN_RE = re.compile(r'"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'|[A-Za-zА-Яа-яЁё_][\wА-Яа-яЁё]*')


def resolve(data: object) -> str:
    """The selected standard method's signature, brief description and parameters.

    Completion carries the receiver and the catalogue's member spelling, so an unrelated
    method of the same name never supplies the description. Missing data stays optional.
    """
    if not isinstance(data, dict):
        return ""
    context = data.get("xbsl_stdlib")
    if not isinstance(context, dict):
        return ""
    owner, member = context.get("owner"), context.get("member")
    if not isinstance(owner, str) or not isinstance(member, str) or not owner.strip() or not member.strip():
        return ""
    owner = owner.split("<", 1)[0].strip().rstrip("?")
    language = "en" if context.get("language") == "en" else "ru"
    seen_pages: set[str] = set()
    for group in _owner_groups(owner):
        matches: list[tuple[str, str]] = []
        for candidate in group:
            forms = _owner_forms(candidate)
            for spelling in forms:
                page_id = docs.for_symbol(spelling)
                if not page_id or page_id in seen_pages:
                    continue
                seen_pages.add(page_id)
                page = docs.page(page_id)
                if not page or page.get("kind") != "type":
                    continue
                if str(page.get("title") or "").casefold() not in {name.casefold() for name in forms}:
                    continue
                found = _method_block(page.get("html") or "", member, owner)
                if found:
                    matches.append(found)
        if matches:
            # Equally near unrelated bases must not supply an arbitrary description.
            return _markdown(matches[0][1], matches[0][0], language, owner) if len(matches) == 1 else ""
    return ""


def _owner_forms(owner: str) -> tuple[str, ...]:
    """Exact bilingual spellings of one receiver, with the page's Russian form first."""
    russian = terms.russian(owner, "types") or terms.russian(owner, "facets") or terms.common_russian(owner)
    forms = [russian, owner]
    for role in ("types", "facets"):
        forms.extend((terms.russian(owner, role), terms.english(owner, role)))
    forms.extend((terms.common_russian(owner), terms.common_english(owner)))
    return tuple(dict.fromkeys(name for name in forms if name))


def _owner_groups(owner: str) -> list[list[str]]:
    """The receiver, then antichain layers of its known ancestors, nearest first."""
    catalog = dataset.load_optional("stdlib.json") or {}
    bases = catalog.get("bases") or {}

    def ancestors_of(name: str) -> list[str]:
        return list(dict.fromkeys(_owner_forms(base)[0]
                                  for form in _owner_forms(name) for base in bases.get(form) or ()
                                  if isinstance(base, str) and base))

    remaining = ancestors_of(owner)
    ancestry = {name: set(ancestors_of(name)) for name in remaining}
    groups = [[owner]]
    while remaining:
        nearest = [name for name in remaining
                   if not any(name in ancestry[other] for other in remaining if other != name)]
        if not nearest:
            break  # Cyclic metadata cannot establish a declaring ancestor safely.
        groups.append(nearest)
        taken = set(nearest)
        remaining = [name for name in remaining if name not in taken]
    return groups


def _method_block(html: str, member: str, owner: str) -> tuple[str, str] | None:
    """Only the named method's own section on this exact reference page."""
    direct = docs.member_block(html, member, section="Методы")
    if direct:
        return direct
    # Completion normally carries the catalogue's Russian name. An English name is
    # resolved against only this page's headings using the receiver-specific vocabulary.
    for heading in _HEADING_RE.finditer(html):
        name = _plain(heading.group()).removesuffix("()")
        english = terms.member_english_of(owner, name) or terms.common_english(name)
        if english == member:
            return docs.member_block(html, name, section="Методы")
    return None


def _markdown(block: str, member: str, language: str, owner: str = "") -> str:
    """Render every documented overload without examples or unrelated detail sections."""
    headings = list(_HEADING_RE.finditer(block))
    chunks = [block[heading.end():headings[index + 1].start() if index + 1 < len(headings) else len(block)]
              for index, heading in enumerate(headings)]
    rendered: list[str] = []
    for chunk in chunks:
        signature_block = next((match for match in _CODE_RE.finditer(chunk)
                                if _signature_name(_without_mark(_plain(match.group(1)))) == member.removesuffix("()")), None)
        if signature_block is None:
            continue
        signature = _without_mark(_plain(signature_block.group(1)))
        tail = chunk[signature_block.end():]
        description = _inline(_DETAIL_RE.split(tail, maxsplit=1)[0])
        if len(description) > 300:
            description = description[:300].rsplit(" ", 1)[0].rstrip(" ,;:") + "..."
        parts = [f"```xbsl\n{_spelling(signature, language, owner)}\n```"]
        if description:
            parts.append(description)
        descriptions = _parameter_descriptions(tail)
        params = _parameters(signature)
        if params:
            caption = "Parameters" if language == "en" else "Параметры"
            lines = []
            for parameter in params:
                name = parameter.partition(":")[0].strip()
                detail = descriptions.get(name, "")
                lines.append(f"- `{_spelling(parameter, language)}`" + (f" – {detail}" if detail else ""))
            parts.append(f"**{caption}**\n\n" + "\n".join(lines))
        rendered.append("\n\n".join(parts))
    return "\n\n".join(dict.fromkeys(rendered))


def _plain(fragment: str) -> str:
    return " ".join(docs.plain_text(fragment).split())


def _inline(fragment: str) -> str:
    """The small prose fragment as Markdown, preserving inline code and emphasis."""
    fragment = re.sub(r"<code\b[^>]*>(.*?)</code>", lambda match: "`" + escape(_plain(match.group(1))) + "`",
                      fragment, flags=re.I | re.S)
    for tag, mark in (("strong|b", "**"), ("em|i", "*")):
        fragment = re.sub(rf"<(?:{tag})\b[^>]*>(.*?)</(?:{tag})>",
                          lambda match: mark + _plain(match.group(1)) + mark,
                          fragment, flags=re.I | re.S)
    return _plain(fragment)


def _signature_name(signature: str) -> str:
    return signature.partition("(")[0].split("<", 1)[0].strip()


def _spelling(text: str, language: str, owner: str = "") -> str:
    if language != "en":
        return text
    # Only the declaration's first name is a member of the receiver. Parameters and
    # result types use their own vocabulary, even when they repeat the method's name.
    method_spelling = terms.member_english_of(owner, _signature_name(text)) if owner else None

    def translate(match: re.Match) -> str:
        word = match.group()
        if word.startswith(('"', "'")):
            return word
        if match.start() == 0 and method_spelling:
            return method_spelling
        return terms.common_english(word) or terms.english(word, "types") or word

    return _SIGNATURE_TOKEN_RE.sub(translate, text)


def _parameters(signature: str) -> list[str]:
    """Split top-level arguments, preserving generic commas and quoted defaults."""
    start = signature.find("(")
    if start < 0:
        return []
    depth = 0
    quote = ""
    parameters: list[str] = []
    left = start + 1
    for index in range(left, len(signature)):
        char = signature[index]
        if quote:
            if char == quote and (index == 0 or signature[index - 1] != "\\"):
                quote = ""
        elif char in "\"'":
            quote = char
        elif char in "(<[{":
            depth += 1
        elif char == ")" and depth == 0:
            if signature[left:index].strip():
                parameters.append(signature[left:index].strip())
            return parameters
        elif char in ")>]}":
            depth -= 1
        elif char == "," and depth == 0:
            parameters.append(signature[left:index].strip())
            left = index + 1
    return []


def _parameter_descriptions(tail: str) -> dict[str, str]:
    caption = _PARAM_CAPTION_RE.search(tail)
    if caption is None:
        return {}
    body = re.split(r"<h[1-6]\b|<hr\b", tail[caption.end():], maxsplit=1, flags=re.I)[0]
    return {_plain(term).partition(":")[0].strip(): _inline(description)
            for term, description in _DEFINITION_RE.findall(body)}
