"""Keys of the project's OWN json resources - the other half of a structure field.

A structure reads a resource file by FIELD NAME: the field `Языки` binds to the key "Языки"
of the json. Rename the field and leave the key, and the binding quietly finds nothing - the
reading options tolerate an unknown property and initialize a missing field, so the
translated project compiles, applies, starts, and seeds an empty catalog. The pilot found it
exactly that way: the compiler said nothing and the site came up without a single language.

So a key that names a field of a project structure goes through the same token map as the
field itself. Everything else in the file stays byte for byte: every value is data, and a key
no structure declares belongs to data too (a map keyed by content, an external contract).
The rewrite is by span, so formatting, order and any duplicate keys survive untouched.
"""

from __future__ import annotations

from collections.abc import Iterator

from xbsl.translation.dictionary import Dictionary
from xbsl.translation.reporting import FileReport


def translate_json(
    text: str,
    dictionary: Dictionary,
    fields: frozenset[str],
    report: FileReport | None = None,
) -> str:
    """Rewrite the object keys that name a field of a project structure."""
    pieces: list[str] = []
    cursor = 0
    for start, end, key in _key_spans(text):
        if key not in fields:
            continue
        translated = dictionary.token(key)
        if translated is None:
            if report is not None:
                report.data_keys_missing += 1
            continue
        pieces.append(text[cursor:start])
        pieces.append(translated)
        cursor = end
        if report is not None:
            report.data_keys += 1
    if not pieces:
        return text
    pieces.append(text[cursor:])
    return "".join(pieces)


def _key_spans(text: str) -> Iterator[tuple[int, int, str]]:
    """(start, end, key) of every string a colon follows - a json object key.

    Reading the strings themselves is what makes this safe: a value that spells `"Код":`
    inside itself is walked over as a string, never mistaken for a key. A key written with an
    escape is left alone - the map answers plain names, and rewriting an escaped span would
    have to re-encode it.
    """
    index = 0
    length = len(text)
    while index < length:
        if text[index] != '"':
            index += 1
            continue
        end = _string_end(text, index)
        if end is None:
            return
        raw = text[index + 1 : end]
        after = end + 1
        while after < length and text[after] in " \t\r\n":
            after += 1
        if after < length and text[after] == ":" and "\\" not in raw:
            yield index + 1, end, raw
        index = end + 1


def _string_end(text: str, start: int) -> int | None:
    """Index of the closing quote of the string that opens at `start`, or None if unclosed."""
    index = start + 1
    length = len(text)
    while index < length:
        char = text[index]
        if char == "\\":
            index += 2
            continue
        if char == '"':
            return index
        index += 1
    return None
