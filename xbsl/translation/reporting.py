"""What one translated file tells about itself: counters, gaps, warnings.

The counters split three ways on purpose. The project's own names and comments are the
DICTIONARY's coverage - that is the number a team fills towards 100%. A platform token the
dataset cannot spell is a DATA gap - nothing a dictionary entry should paper over. And a
Cyrillic scalar left alone as data (a label, a description) is neither: it is listed so a
reviewer can confirm it really is data, but it does not count against anything.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FileReport:
    """The outcome of translating one source file."""

    path: str
    #: Occurrences of the project's own tokens: translated by the dictionary / left as is.
    user_done: int = 0
    user_missing: int = 0
    #: Comment lines with Cyrillic text: translated by the dictionary / left as is.
    phrases_done: int = 0
    phrases_missing: int = 0
    #: Platform tokens the dataset knows no English spelling for (a data gap, not the dictionary's).
    platform_missing: int = 0
    #: OCCURRENCES of string literals the literals plane named: replaced whole / left as written.
    literals_done: int = 0
    literals_missing: int = 0
    #: {literal text: how many times it was replaced}. The summary counts distinct TEXTS, the
    #: same unit as the gaps, so both halves of one sentence measure one thing.
    named_literals: dict[str, int] = field(default_factory=dict)
    #: {token: [(line, col), ...]} of the dictionary gaps.
    missing_tokens: dict[str, list[tuple[int, int]]] = field(default_factory=dict)
    #: {trimmed comment text: [(line, col), ...]} of the phrase gaps.
    missing_phrases: dict[str, list[tuple[int, int]]] = field(default_factory=dict)
    #: {token: [(line, col), ...]} of the dataset gaps.
    missing_platform: dict[str, list[tuple[int, int]]] = field(default_factory=dict)
    #: {literal text without the quotes: [(line, col), ...]} the literals plane does not name.
    missing_literals: dict[str, list[tuple[int, int]]] = field(default_factory=dict)
    #: Cyrillic scalars left untouched as data - for a reviewer's eye, not for the coverage.
    texts_kept: list[tuple[str, int, int]] = field(default_factory=list)
    #: Suspicions worth a human look: (kind, line, col, what) - e.g. a string literal that
    #: equals a renamed token (a method called by name in a string breaks silently).
    warnings: list[tuple[str, int, int, str]] = field(default_factory=list)
    #: {name: [(line, col), ...]} of the names the platform tables answered.
    platform_tokens: dict[str, list[tuple[int, int]]] = field(default_factory=dict)
    #: Missing tokens that name resource FILES - the stub annotates them for the filler.
    resource_tokens: set[str] = field(default_factory=set)
    #: Keys of a json resource that name a field of a project structure: renamed with the
    #: field / left as written because the dictionary has no entry for the field yet.
    data_keys: int = 0
    data_keys_missing: int = 0
    #: Names that COLLIDED: {namespace: {translation: [the source names]}}. Two different
    #: names of one namespace translated into one word is a build-breaking defect of the
    #: dictionary (the platform refuses a repeated name), and only the translator can see it.
    collisions: dict[str, dict[str, list[str]]] = field(default_factory=dict)

    def note_name(self, namespace: str, source: str, translated: str) -> None:
        """Register a translated name inside a namespace and detect a collision."""
        seen = self.collisions.setdefault(namespace, {}).setdefault(translated, [])
        if source not in seen:
            seen.append(source)

    def collided(self) -> list[tuple[str, str, list[str]]]:
        """[(namespace, translation, the source names)] where more than one name collided."""
        return [
            (namespace, translated, sources)
            for namespace, table in sorted(self.collisions.items())
            for translated, sources in sorted(table.items())
            if len(sources) > 1
        ]

    def note_platform_answer(self, name: str, line: int, col: int) -> None:
        """Remember a name the PLATFORM tables answered.

        The project-names gate turns such an answer into a gap when the project declares the
        same word (see names.py). A per-file pass cannot know the whole project's
        declarations, so it records the answers and lets the project-wide reduce decide.
        """
        self.platform_tokens.setdefault(name, []).append((line, col))

    def note_token(self, name: str, line: int, col: int, *, resource: bool = False) -> None:
        self.user_missing += 1
        self.missing_tokens.setdefault(name, []).append((line, col))
        if resource:
            self.resource_tokens.add(name)

    def note_missing(self, name: str, line: int, col: int, plane: str, *,
                     resource: bool = False) -> None:
        """A name nothing spelled in English - written down as WHOSE gap it is.

        The dictionary answers for the project's own names; a member the platform declares
        but the data does not spell belongs to the platform's own list, where no dictionary
        entry is expected to appear.
        """
        if plane == "platform-gap":
            self.note_platform(name, line, col)
        else:
            self.note_token(name, line, col, resource=resource)

    def note_phrase(self, text: str, line: int, col: int) -> None:
        self.phrases_missing += 1
        self.missing_phrases.setdefault(text, []).append((line, col))

    def note_literal_named(self, text: str) -> None:
        """A string literal the literals plane named and the pass replaced whole."""
        self.literals_done += 1
        self.named_literals[text] = self.named_literals.get(text, 0) + 1

    def note_literal(self, text: str, line: int, col: int) -> None:
        """A Cyrillic string literal the literals plane leaves as written."""
        self.literals_missing += 1
        self.missing_literals.setdefault(text, []).append((line, col))

    def note_text_kept(self, text: str, line: int, col: int) -> None:
        """A Cyrillic scalar left untouched as data - listed for a reviewer, counted nowhere.

        The preview is capped: a report is read by a person, and a paragraph pasted into one
        row hides the rows around it.
        """
        self.texts_kept.append((text if len(text) <= 60 else text[:57] + "...", line, col))

    def note_platform(self, name: str, line: int, col: int) -> None:
        self.platform_missing += 1
        self.missing_platform.setdefault(name, []).append((line, col))

    @property
    def covered(self) -> bool:
        return not self.user_missing and not self.phrases_missing

    def coverage(self) -> float:
        """The dictionary's share of this file's own surfaces, 1.0 for a file with none."""
        total = self.user_done + self.user_missing + self.phrases_done + self.phrases_missing
        if total == 0:
            return 1.0
        return (self.user_done + self.phrases_done) / total
