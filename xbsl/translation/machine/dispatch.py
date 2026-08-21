"""Deduplicate, resolve from the cache, cut the rest into batches, ask, shape, report.

The transport is a parameter so the tests never touch the network; the default one is urllib.
"""

from __future__ import annotations

import urllib.request
from dataclasses import dataclass, field
from typing import Callable, Mapping, Sequence

from xbsl.translation.code import has_cyrillic

from .cache import Cache, fingerprint
from .provider import Request
from .shape import identifier

SOURCE_LANGUAGE = "ru"
TARGET_LANGUAGE = "en"


@dataclass
class Result:
    """What one dispatch produced: names/phrases ready to write, refusals, and the tally.

    Both dictionaries are keyed by (kind, key), not by key alone: the same source text can be
    both a token and a phrase at once (a name and a one-word comment share the wording), and
    keying by text alone would let one suggestion silently overwrite the other.
    """

    values: dict[tuple[str, str], str] = field(default_factory=dict)
    refused: dict[tuple[str, str], str] = field(default_factory=dict)
    cached: int = 0
    requested: int = 0


def http_transport(request: Request) -> str:
    """The default transport: perform one prepared call over the network with urllib."""
    prepared = urllib.request.Request(request.url, data=request.body, headers=request.headers)
    with urllib.request.urlopen(prepared, timeout=30) as response:
        return response.read().decode("utf-8")


def _batches(texts: list[str], limit: int, count_limit: int) -> list[list[str]]:
    """Cut texts into batches that stay under BOTH of the provider's limits.

    A service bounds a request twice over: by the characters it carries and by the number of
    texts in it. The character sum alone lets six hundred one-word names ride in a single
    request - well inside the character limit and well outside what the service accepts.

    Every text arriving here already fits the character limit on its own - the caller filters
    out anything oversized first - so the first text of a fresh batch is always safe to add
    unconditionally.
    """
    batches: list[list[str]] = []
    current: list[str] = []
    size = 0
    for text in texts:
        if current and (size + len(text) > limit or len(current) >= count_limit):
            batches.append(current)
            current, size = [], 0
        current.append(text)
        size += len(text)
    if current:
        batches.append(current)
    return batches


def _unusable(text: str, answer) -> str:
    """Why this answer must not be used - an empty string when it is fit to keep.

    The check stands here, before the cache, and not next to the value it protects: the cache
    is keyed by TEXT alone, so an answer stored for a name would be handed back later for the
    same wording as a comment line. It also outlives the run, and nothing rereads it - a bad
    entry would be repeated on every run until somebody deletes the file by hand.

    A machine translator answers a string it did not understand with the string itself. A name
    survives that by accident (the identifier builder drops the Cyrillic and keeps whatever
    Latin came with it), a comment line does not: the Russian would be written down as its own
    translation and the line would count as covered.

    An empty answer is the worst of them: an empty value written to the dictionary does not
    leave the record half filled, it REMOVES the record - the row a person had already put
    there disappears, and the cache repeats the loss on every run after.
    """
    if not isinstance(answer, str):
        return f"the service answered with {type(answer).__name__}, not a string"
    if not answer.strip():
        return "the service answered with an empty string"
    if has_cyrillic(answer):
        return f"the service answered in Russian: {answer!r}"
    if answer == text:
        return "the service returned the source text unchanged"
    return ""


def suggest(gaps: Sequence, provider, cache: Cache,
            glossary: Sequence[tuple[str, str]] = (),
            transport: Callable[[Request], str] = http_transport,
            taken: set[str] | None = None,
            terms: Mapping[str, str] | None = None) -> Result:
    """Turn token/phrase gaps into suggested values: dedupe, cache, batch, ask, shape.

    Only "token" and "phrase" gaps go through the service; a token is shaped into an
    identifier afterwards, a phrase is kept as prose. A text longer than the provider's own
    batch limit is refused outright, without ever being sent - alone it could never fit, so
    sending it would be a request doomed from the start. A batch whose answer count does not
    match what was sent is refused as a whole, with a reason naming both counts, and nothing
    from it is cached: a silent `zip` truncation would drop the tail of a batch without a
    trace - not in the values, not in the cache, not in the counters - and a quiet loss is
    worse than an honest refusal. Every single answer is weighed by `_unusable` before it is
    written down or cached: an answer is not a translation just because it arrived.
    """
    result = Result()
    reserved = set(taken or ())
    term_lookup = {source.casefold(): target for source, target in (terms or {}).items()}
    fp = fingerprint(glossary) if provider.supports_glossary() else ""
    limit = provider.batch_limit()

    wanted = [gap for gap in gaps if gap.kind in ("token", "phrase")]
    unique_texts: list[str] = []
    for gap in wanted:
        if gap.key not in unique_texts:
            unique_texts.append(gap.key)

    translations: dict[str, str] = {}
    text_refusals: dict[str, str] = {}
    to_ask: list[str] = []
    for text in unique_texts:
        known = cache.get(provider.code(), SOURCE_LANGUAGE, TARGET_LANGUAGE, fp, text)
        if known is None:
            to_ask.append(text)
        else:
            translations[text] = known
            result.cached += 1

    batchable: list[str] = []
    for text in to_ask:
        if len(text) > limit:
            text_refusals[text] = (
                f"text is {len(text)} characters long, over the provider's "
                f"{limit} character batch limit"
            )
        else:
            batchable.append(text)

    for batch in _batches(batchable, limit, provider.texts_limit()):
        request = provider.request(batch, TARGET_LANGUAGE, SOURCE_LANGUAGE,
                                    glossary if provider.supports_glossary() else ())
        try:
            answers = provider.parse(transport(request))
        except Exception as error:  # a batch that failed must not take the others down
            for text in batch:
                text_refusals[text] = str(error)
            continue
        if len(answers) != len(batch):
            reason = (
                f"the service returned {len(answers)} translations for a batch of "
                f"{len(batch)} texts"
            )
            for text in batch:
                text_refusals[text] = reason
            continue
        for text, translation in zip(batch, answers):
            unusable = _unusable(text, translation)
            if unusable:
                text_refusals[text] = unusable
                continue
            translations[text] = translation
            cache.put(provider.code(), SOURCE_LANGUAGE, TARGET_LANGUAGE, fp, text, translation)
            result.requested += 1

    for gap in wanted:
        key = (gap.kind, gap.key)
        reason = text_refusals.get(gap.key)
        if reason is not None:
            result.refused[key] = reason
            continue
        prose = translations.get(gap.key)
        if prose is None:
            continue
        if gap.kind == "phrase":
            result.values[key] = prose
            continue
        name, name_reason = identifier(prose, term_lookup, reserved)
        if name:
            reserved.add(name)
            result.values[key] = name
        else:
            result.refused[key] = name_reason
    return result
