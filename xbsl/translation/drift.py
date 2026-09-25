"""Comment lines of the dictionary that name a name differently from the name's own pair.

A phrase entry translates a comment line whole, and the names the line mentions are written
inside the translation by hand. The tokens section says how the name is spelled in the
translated tree; when the two disagree - the token was renamed after the phrase was written,
or the phrase was translated as prose and got its own idea of the name - the English comment
names something the English tree does not have. Nothing else notices: the pass translates both
entries faithfully, the tree builds, and the only trace is a finding of `comment/unknown-name`
on the English tree, which points at the English comment and not at the entry to fix.

The check reads the dictionary alone, the way `--check-duplicates` does. A name of the key is
a candidate when it is written like an identifier (a capital, then a lower letter followed by a
capital somewhere) in Cyrillic, and it is judged when it has a pair: the token entry of the
project (a scoped entry `<Dictionary>.<Key>` counts as a spelling too) or an English spelling
of the platform data. The phrase drifts when its translation carries none of those spellings
AND names something instead - a Latin name written the same way that is neither a token value
of the dictionary nor a word of the platform data. A translation that paraphrases the name in
plain words names nothing and is left alone: the English comment then reads as prose, and
there is nothing to rename.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from xbsl import dataset, terms, uischema
from xbsl.rules import comment_names

#: A word of a comment line: letters of either alphabet, digits and the underscore after them.
_WORD = re.compile(r"[A-Za-zА-Яа-яЁё][A-Za-z0-9А-Яа-яЁё_]*")


@dataclass(frozen=True)
class NameDrift:
    """One name of one phrase whose translation spells it otherwise."""

    #: The name as the key writes it.
    name: str
    #: The spellings the translation could carry: the token pair first, then the platform's.
    expected: tuple[str, ...]
    #: The Latin names of the translation that answer to nothing - what it says instead.
    found: tuple[str, ...]
    #: The comment line (the key of the phrase) and its translation.
    key: str
    value: str

    def as_dict(self) -> dict:
        return {
            "name": self.name, "expected": list(self.expected), "found": list(self.found),
            "key": self.key, "value": self.value,
        }


def _is_name(word: str) -> bool:
    """A word written like an identifier (see comment_names): no plain word of the prose."""
    return comment_names._is_candidate(word)


@lru_cache(maxsize=None)
def _platform_spellings(name: str) -> tuple[str, ...]:
    """The English spellings the platform data gives a Russian name, in every role."""
    out: list[str] = []
    for spelling in (
        terms.common_english(name),
        *(terms.english(name, section) for section in terms.SECTIONS),
        *terms.member_spellings(name),
        uischema.english_property(name),
    ):
        if spelling and spelling != name and spelling not in out:
            out.append(spelling)
    return tuple(out)


dataset.register_reset(_platform_spellings.cache_clear)


def _scoped(dictionary) -> dict[str, list[str]]:
    """{name: [the values of its scoped entries `<Owner>.<Name>`]} of the tokens section."""
    out: dict[str, list[str]] = {}
    for key, value in dictionary.tokens.items():
        if "." in key:
            out.setdefault(key.rsplit(".", 1)[1], []).append(value)
    return out


def _spellings(dictionary, name: str, scoped: dict[str, list[str]]) -> tuple[str, ...]:
    """The token pair of the name (the plain entry, then the scoped ones), then the platform's."""
    out: list[str] = []
    plain = dictionary.tokens.get(name)
    for spelling in (plain, *scoped.get(name, ()), *_platform_spellings(name)):
        if spelling and spelling not in out:
            out.append(spelling)
    return tuple(out)


def phrase_drift(dictionary) -> list[NameDrift]:
    """Every name of every phrase whose translation spells it otherwise (see the module note)."""
    token_values = set(dictionary.tokens.values())
    scoped = _scoped(dictionary)
    platform = comment_names._platform_names()
    out: list[NameDrift] = []
    for key, value in dictionary.phrases.items():
        said = set(_WORD.findall(value))
        unknown = None
        for name in dict.fromkeys(_WORD.findall(key)):
            if not _is_name(name) or comment_names._script(name) != "cyrillic":
                continue
            expected = _spellings(dictionary, name, scoped)
            if not expected or name in said or said.intersection(expected):
                continue
            if unknown is None:
                unknown = tuple(
                    word for word in dict.fromkeys(_WORD.findall(value))
                    if _is_name(word) and comment_names._script(word) == "latin"
                    and word not in token_values and word not in platform
                )
            if unknown:
                out.append(NameDrift(name, expected, unknown, key, value))
    return out
