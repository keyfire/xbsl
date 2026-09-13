"""Tier B: translation/english-shape - traces of a mechanical replacement in the English values.

A translation dictionary (see xbsl/translation/) pairs a Russian key with an English value, and
`xbsl translate --strict` judges the COVERAGE of that dictionary, never its text: a value that
reads "a second icon onlies clutter the row" passes, because its key is covered. Such a value is
what a mechanical edit leaves behind - the third-person ending moved from the verb onto the
adverb before it, the Russian word order kept around an English passive, the capitals of an
emphasis that the Russian line no longer has - and nobody reads the translated tree closely
enough to catch it by eye. This rule reads the values.

Three shapes, each with its own message, judged on the values of the `tokens`, `phrases`,
`literals` and `terms` sections of a dictionary file (a file inside the discovered
`xbsl-translation` directory, or the single dictionary file next to a project):

- a word that takes no ending with an ending glued on: an adverb, an irregular past participle
  or a finite auxiliary spelled as a third-person verb or a plural (`onlies`, `otherwises`,
  `gones`, `writtens`, `hases`), and a regular participle in the plural (`loadeds`);
- a passive followed straight by a noun phrase without `by` - "is shadowed the parameter" -
  where the subject and the object kept the places of the Russian sentence;
- a word in capitals where the key has none: "does NOT narrow" for a key that says
  `не задаётся` adds an emphasis the original does not carry.

The lists are bounded by a live dictionary of ten thousand names and twenty thousand comment
lines, where every shape was measured against what ordinary English writes: `applies`, `replies`
and `bounds` are verbs and nouns, "is assigned the role" keeps its object legitimately, "until
the counter is raised the call does not happen" is a clause with its comma left out, and `MB`,
`URL` or `RUB` are simply what those abbreviations look like. A word the lists do not know is
left alone: a rule about someone else's prose must not argue with correct English.

No fix. Which word was meant, or how the sentence turns around, is the author's call - the
message names the word and the suspicion, and the position points at the word in the file.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path

from xbsl import i18n
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, rule
from xbsl.rules.translation_gaps import _dictionary_at, _inside
from xbsl.rules.yaml_schema import _composed, _HAVE_YAML

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

MESSAGES = {
    "translation/english-shape.title": {
        "ru": "След механической замены в английском значении словаря перевода",
        "en": "A trace of mechanical replacement in an English value of the translation dictionary",
    },
    "translation/english-shape.inflected": {
        "ru": "Слово '{word}' в переводе '{key}': к '{base}' приклеено окончание, которого у "
              "этого слова не бывает, – так выглядит след механической замены. Перепишите фразу.",
        "en": "The word '{word}' in the translation of '{key}': '{base}' carries an ending this "
              "word never takes - the mark of a mechanical replacement. Rewrite the phrase.",
    },
    "translation/english-shape.passive": {
        "ru": "Оборот '{phrase}' в переводе '{key}': страдательный залог, а сразу за ним именная "
              "группа без 'by' – подлежащее и дополнение остались на местах русской фразы (как "
              "'is shadowed the parameter' вместо 'shadows the parameter'). Перестройте "
              "предложение.",
        "en": "The turn '{phrase}' in the translation of '{key}': a passive followed straight by a "
              "noun phrase without 'by' - the subject and the object kept the places of the "
              "Russian sentence ('is shadowed the parameter' for 'shadows the parameter'). "
              "Rebuild the sentence.",
    },
    "translation/english-shape.caps": {
        "ru": "Слово '{word}' в переводе '{key}' написано прописными, а ключ ничего не выделяет: "
              "перевод добавляет выделение, которого в оригинале нет. Напишите '{lower}' либо "
              "выделите слово и в ключе.",
        "en": "The word '{word}' in the translation of '{key}' is in capitals while the key "
              "stresses nothing: the translation adds a stress the original does not have. "
              "Write '{lower}', or stress the word in the key as well.",
    },
}
i18n.register(MESSAGES)

RULE_ID = "translation/english-shape"

#: The sections whose values are English text; `terms` is not a plane of the translation, but
#: its values are English words a person wrote, and they feed the name builder.
_SECTIONS = ("tokens", "phrases", "literals", "terms")
_SECTION_RE = re.compile(r"^(?:tokens|phrases|literals|terms):", re.MULTILINE)

_WORD_RE = re.compile(r"[A-Za-z]+")
#: A word standing on its own: not a part of a hyphenated compound, which makes nouns with
#: plurals of their own (`has-beens`, `also-rans`), and not a part of a code name.
_STANDALONE_WORD_RE = re.compile(r"(?<![\w-])[A-Za-z]+(?![\w-])")
#: The parts of a CamelCase identifier: `COMConnection` -> `COM`, `Connection`.
_CAMEL_RE = re.compile(r"[A-Z]+(?![a-z])|[A-Z][a-z]+|[a-z]+")

# --- shape 1: a word that takes no ending, with an ending glued on --------------------------

#: Words that never take `-s`: none of them is a base form of a verb or a noun, so an inflected
#: spelling is not English. The trace this catches moves the third-person ending of a verb onto
#: the adverb before it - "only clutters" becomes "onlies clutter".
#:
#: Only the words that are nothing but an adverb. `apply`, `reply`, `supply`, `multiply`, `rely`
#: are verbs (the live dictionary writes `applies` 29 times and `replies` 18), `family` and
#: `assembly` are nouns, `daily` and `weekly` name periodicals, and `still`, `even`, `first`,
#: `later`, `anyway` and `anywhere` have an `-s` form of their own (`stills`, `evens`, `firsts`,
#: `laters`, `anyways`, `anywheres`).
_ADVERBS = frozenset("""
    only just already always often never again also very quite rather almost soon seldom then
    now sometimes somewhat somehow perhaps indeed thus hence therefore otherwise likewise
    instead moreover furthermore nevertheless nonetheless meanwhile twice namely
    silently quietly directly explicitly implicitly currently previously initially finally
    usually normally rarely mostly partly lately likely really simply safely exactly roughly
    strictly nearly merely purely barely entirely separately immediately actually literally
    manually automatically dynamically statically locally globally internally externally
    physically logically technically typically temporarily permanently formerly freshly newly
    badly wrongly correctly incorrectly properly fully partially slightly greatly largely deeply
    briefly shortly quickly slowly rapidly gradually instantly repeatedly frequently
    occasionally eventually ultimately essentially basically generally specifically precisely
    particularly especially notably mainly primarily firstly secondly thirdly lastly
    additionally similarly differently equally evenly randomly sequentially concurrently
    simultaneously independently jointly respectively accordingly consequently subsequently
    effectively efficiently reliably consistently visibly invisibly loudly softly openly
    publicly privately secretly closely loosely tightly firmly weakly strongly poorly highly
    widely narrowly broadly hardly wholly solely truly duly fairly freely easily readily
    apparently obviously clearly plainly surely certainly definitely possibly probably
    presumably supposedly allegedly reportedly admittedly undoubtedly necessarily
    unnecessarily optionally deliberately intentionally accidentally inadvertently mistakenly
    falsely noisily honestly mutually exclusively alternatively relatively absolutely
    completely totally utterly thoroughly carefully cautiously accurately approximately
    remotely virtually practically theoretically ideally preferably hopefully unfortunately
    fortunately naturally artificially forcibly voluntarily willingly reluctantly knowingly
    unknowingly seemingly increasingly surprisingly importantly significantly marginally
    substantially considerably noticeably dramatically drastically radically fundamentally
    inherently intrinsically tacitly verbally numerically alphabetically chronologically
    historically legally illegally financially commercially personally individually
    collectively universally nationally internationally centrally horizontally vertically
    diagonally
""".split())

#: Past participles that differ from the base form of their verb: `gone` never takes `-s`,
#: while `go` and `goes` do. A base form that doubles as a participle (`set`, `put`, `read`,
#: `cut`, `run`, `come`) is absent - `sets` and `reads` are verbs, and the live dictionary
#: writes them hundreds of times. So is a participle whose `-s` form is a noun of its own:
#: `givens`, `knowns`, `bounds`, `grounds`, `wounds`, `frozens`, and the past forms that make
#: nouns (`also-rans`, `choses`, `shooks`, `cames`).
_PARTICIPLES = frozenset("""
    been gone done written taken seen shown thrown drawn grown hidden chosen broken forgotten
    gotten driven risen fallen eaten stolen spoken woken beaten bitten ridden understood
    withdrawn overridden undertaken mistaken proven sworn torn worn built sent kept held told
    sold lost brought bought caught taught fought sought made said laid paid begun sung hung
    stuck struck swung stood spent meant dealt fled bled sewn sown mown hewn strewn shaken
    awoken arisen flown blown shone slid burnt learnt spilt spoilt dreamt
""".split())

#: The finite auxiliaries: `is` and `has` are already inflected, and a second ending makes
#: `ises` and `hases`. The modals are absent - `the shoulds`, `the oughts` and `cans` are nouns.
_AUXILIARIES = frozenset("is are was were has had does did".split())


def _inflect(word: str) -> str:
    """The spelling a mechanical `-s` produces from `word`: `only` -> `onlies`, `has` -> `hases`."""
    if word.endswith("y") and word[-2] not in "aeiou":
        return word[:-1] + "ies"
    if word.endswith(("s", "x", "z", "sh", "ch")):
        return word + "es"
    return word + "s"


#: {inflected spelling: the word it was made from} - the table shape 1 judges by.
_INFLECTED: dict[str, str] = {
    _inflect(word): word for word in (*_ADVERBS, *_PARTICIPLES, *_AUXILIARIES)
}

#: Nouns that end in `-eds` and are not a participle in the plural. With the two shape tests
#: below - a doubled `e` (`needs`, `seeds`, `feeds`, `exceeds`), a bed or a shed (`embeds`,
#: `watersheds`), a stem shorter than three letters (`reds`, `weds`) - this covers every `-eds`
#: word of the live dictionary, where `needs` alone stands 131 times.
_NOUNS_IN_EDS = frozenset("""
    hundreds kindreds shreds thoroughbreds purebreds crossbreds inbreds halfbreds mopeds bipeds
    quadrupeds coeds newlyweds
""".split())


def _plural_participle(word: str) -> bool:
    """Is `word` a regular past participle with a plural ending - `loadeds`, `storeds`?"""
    if not word.endswith("eds") or word.endswith(("eeds", "beds", "sheds", "sleds")):
        return False
    return len(word) - 3 >= 3 and word not in _NOUNS_IN_EDS


def _inflected_findings(section: str, value: str) -> Iterable[tuple[str, int, str]]:
    """(the word as written, its offset in the value, the word it was made from)."""
    if section == "tokens":
        words = [(m.group(0), m.start()) for m in _CAMEL_RE.finditer(value)]
    else:
        words = [(m.group(0), m.start()) for m in _STANDALONE_WORD_RE.finditer(value)]
    for word, start in words:
        lower = word.lower()
        base = _INFLECTED.get(lower)
        if base is None:
            if not _plural_participle(lower):
                continue
            base = lower[:-1]
        # Two capitals make an abbreviation or a code name, and its plural is written with a
        # small `s`: `DIDs` is not `did` with an ending.
        if sum(ch.isupper() for ch in word) >= 2:
            continue
        yield word, start, base


# --- shape 2: a passive followed straight by a noun phrase ----------------------------------

#: Irregular participles whose passive takes neither an object nor a complement. A base form
#: that doubles as a participle (`set`, `put`, `read`) is absent - "is set the" is as often a
#: present tense - and so are `made`, `given`, `shown`, `sold`, `found`, `left`, which keep an
#: object ("was sold the rights").
_PASSIVE_IRREGULAR = (
    "written taken hidden chosen broken forgotten overridden drawn thrown built done gone seen "
    "lost caught held begun struck stuck spent shaken flown blown torn worn sworn sung hung"
)
#: The words that open a noun phrase. `that` is absent (a passive of saying opens a clause with
#: it), and so are `every`, `all`, `no`: "is read every time", "are highlighted all at once",
#: "is called no more than once" are adverbials.
_DETERMINERS = "the|a|an|this|these|those|its|their|our|my|your|his|her"
_PASSIVE_RE = re.compile(
    rf"\b(?:is|are|was|were)\s+"
    rf"(?P<participle>[A-Za-z]{{3,}}ed|{_PASSIVE_IRREGULAR.replace(' ', '|')})\s+"
    rf"(?:{_DETERMINERS})\b"
    r"(?:\s+(?P<w1>[A-Za-z']+))?(?:\s+(?P<w2>[A-Za-z']+))?"
    r"(?:\s+(?P<w3>[A-Za-z']+))?(?:\s+(?P<w4>[A-Za-z']+))?",
    re.IGNORECASE,
)

#: Regular participles whose passive legitimately keeps a direct object or a complement - "is
#: assigned the role", "is named the same as", "are called a draft" - and the verbs of saying
#: and thinking, whose passive opens a clause with `that` left out ("it is assumed the list is
#: sorted"). The live dictionary writes `assigned`, `named`, `called`, `considered` and
#: `promised` this way; the rest are their kin.
_OBJECT_KEEPING = frozenset("""
    called named considered deemed declared elected appointed assigned offered handed passed
    granted denied allowed owed promised awarded charged asked labelled labeled termed dubbed
    voted rated ranked judged guaranteed assured issued served refused spared saved crowned
    proclaimed pronounced nominated designated christened nicknamed entitled styled titled
    rendered reckoned refunded reimbursed credited debited billed invoiced fined quoted advised
    informed notified believed supposed expected assumed hoped reported agreed ensured noted
    decided determined established proved specified indicated recommended suggested requested
    required stated mentioned estimated verified confirmed concluded accepted acknowledged
    announced argued claimed doubted feared implied observed predicted presumed remembered
    revealed warned intended planned
""".split())

#: Words in `-ed` that are not a participle: "is indeed the", "was hundred".
_NOT_A_PARTICIPLE = frozenset("""
    indeed hundred sacred naked wicked rugged wretched crooked jagged ragged dogged hatred
""".split())

#: A noun of time or manner right after the determiner makes the phrase an adverbial, not an
#: object: "is built the same way", "is done the other way round", "is refreshed the next day".
#: Judged on the first two words after the determiner.
_ADVERBIAL = frozenset("""
    same way ways time times moment moments day days week weeks month months year years hour
    hours minute minutes second seconds instant round morning evening night
""".split())

#: A word that opens a subordinate clause: "until the counter is raised the call does not
#: happen" is a sentence with its comma left out, and the noun phrase after the
#: participle is the subject of the main clause. `time`, `moment`, `soon` and `case` stand for
#: "by the time", "the moment", "as soon as" and "in case". Looked for inside the clause of the
#: passive only - a `which` two commas back opens a different one.
_SUBORDINATORS = frozenset("""
    when whenever until till if once after before while unless since because although though
    where wherever whether which what whatever whichever who whom whose how that provided
    whereas lest case time moment soon
""".split())

#: Where a clause ends for the search above: a sentence or bracket mark, a comma, a spaced dash
#: (a hyphen, an en dash or an em dash).
_CLAUSE_BREAK_RE = re.compile(r"[.;:!?()\[\],]|\s[-\u2013\u2014]\s")

#: A finite verb among the words after the noun phrase says the phrase is a subject of its own
#: clause ("is switched the widget is rebuilt"), whatever opened that clause.
_FINITE_MARKERS = frozenset("""
    is are was were has have had does do did can could will would should may might must shall
""".split())

#: A relative pronoun or a conjunction ends the noun phrase: in "is shadowed the parameter that
#: is passed" the finite verb belongs to the relative clause and says nothing about the phrase.
_PHRASE_ENDS = frozenset("that which who whom whose where when and or but".split())


def _passive_findings(value: str) -> Iterable[tuple[str, int]]:
    """(the passive turn as written, its offset in the value) for shape 2."""
    for match in _PASSIVE_RE.finditer(value):
        participle = match.group("participle").lower()
        if participle in _OBJECT_KEEPING or participle in _NOT_A_PARTICIPLE:
            continue
        if participle.endswith("eed"):  # `agreed`, `freed`, `guaranteed` and their kin
            continue
        head = value[:match.start()]
        # A line of a wrapped comment may start with the passive itself: the subject, and
        # whatever opened the clause, then sit on the previous line, out of reach.
        if not _WORD_RE.search(head):
            continue
        clause = _CLAUSE_BREAK_RE.split(head)[-1]
        if _SUBORDINATORS.intersection(w.lower() for w in _WORD_RE.findall(clause)):
            continue
        after = [(match.group(name) or "").lower().strip("'") for name in ("w1", "w2", "w3", "w4")]
        ends = [index for index, word in enumerate(after) if word in _PHRASE_ENDS]
        if ends:
            after = after[:ends[0]]
        if _ADVERBIAL.intersection(after[:2]) or _FINITE_MARKERS.intersection(after):
            continue
        end = match.end("participle")
        determiner = re.match(r"\s+[A-Za-z]+", value[end:])
        yield value[match.start():end + (determiner.end() if determiner else 0)], match.start()


# --- shape 3: capitals the key does not have ----------------------------------------------

#: A word of two or more capital Latin letters and nothing else. A digit (`UTF8`, `B1`) or an
#: underscore (`CACHE_TTL_SECONDS` is a constant) next to it takes it out; so does a letter -
#: an identifier of a `tokens` value is judged by its CamelCase parts instead.
_CAPS_WORD_RE = re.compile(r"(?<![A-Za-z0-9_])[A-Z]{2,}(?![A-Za-z0-9_])")

#: Two Cyrillic capitals in a row anywhere in the key: a word of its own (`ОДНИМ запросом`) or
#: a prefix glued to a word (`НЕизменяемые`). Latin capitals are not a stress of the Russian
#: line - they are a code name or an abbreviation (`ExtAPI`, `JSON`), and they justify only
#: the same word in the value.
_KEY_RUN_RE = re.compile(r"[А-ЯЁ]{2,}")
#: A one-letter Russian word inside an identifier makes two capitals in a row that stress
#: nothing: `ОбъектКПроверке`, `ТоварСОстатком`, `ДатаВРеестре`.
_ONE_LETTER_WORDS = frozenset("ВКСОУИАЯ")
#: A capital letter standing alone. A Russian line stresses a one-letter word that way
#: (`строка И столбец`), and a translation answering with `AND` follows its original - unless
#: the letter merely opens a sentence, which is judged separately.
_KEY_LETTER_RE = re.compile(r"(?<![^\W\d_])[А-ЯЁ](?![^\W\d_])")

#: Abbreviations and code words written in capitals whatever the key does: units, file
#: formats, protocols, currencies, identifiers of standards, HTTP methods, query literals. The
#: live dictionary writes `MB`, `KB`, `GB`, `URL`, `RUB`, `API`, `SVG`, `TTL`, `HR`, `CTA` and
#: `ITS` for lowercase keys; the rest are their kin. A word that is also an ordinary English
#: word in capitals (`LESS`, `IN`, `ON`, `NO`) is not here - that is exactly the emphasis.
_ABBREVIATIONS = frozenset("""
    MB KB GB TB PB KIB MIB GIB MS NS HZ KHZ MHZ GHZ PX PT EM REM DPI PPI FPS BPS KBPS MBPS
    GBPS SVG PNG JPG JPEG GIF WEBP BMP ICO TIFF PDF DOC DOCX XLS XLSX PPT PPTX CSV TSV TXT
    HTML XHTML XML JSON YAML YML CSS JS TS SCSS MD ZIP RAR GZ TAR WAV OGG WEBM AVI MOV EXE DLL
    ISO HTTP HTTPS FTP SFTP SSH SSL TLS TCP UDP IP DNS URL URI URN API REST SOAP WSDL XSD RPC
    JWT OIDC OAUTH SSO SAML LDAP AD SMTP IMAP CDN DB SQL DDL DML ORM CRUD ACL RLS RBAC IAM CI
    CD CLI GUI UI UX IDE SDK JDK JRE JVM OS RAM CPU GPU SSD HDD USB VPN VM VPS LAN WAN WIFI NFC
    QR BIOS UEFI MIME UTF ASCII ANSI UUID GUID ID IDS SKU EAN ISBN IEEE RFC ETL BI KPI OKR SLA
    SLO FAQ SEO SEM SMM CRM ERP CMS LMS HRM HR PR MR TODO FIXME NB PS AM PM UTC GMT MSK CET
    EST VAT TIN INN KPP OGRN BIC IBAN SWIFT USD EUR RUB KZT BYN UAH GBP JPY CNY CHF ATM POS CEO
    CTO CFO COO CIO OK ASAP FYI TBD TBA ETA CTA CTR CPC CPM ROI TTL DOM CORS CSP CSRF XSS AJAX
    SPA PWA SSR SSG AI ML LLM NLP OCR GPS GSM SMS MMS SIM LTE EDT BSL XBSL ITS GET POST PUT
    PATCH DELETE HEAD OPTIONS HMAC RSA AES SHA CRC TRUE FALSE NULL NAN INF II III IV VI VII
    VIII IX XI XII
""".split())


def _opens_sentence(text: str, at: int) -> bool:
    """Is the letter at `at` the first letter of its sentence (or of the whole text)?"""
    head = text[:at]
    cut = max(head.rfind("."), head.rfind("!"), head.rfind("?"))
    return not any(ch.isalpha() for ch in head[cut + 1:])


def _key_stress(key: str) -> tuple[bool, bool]:
    """(the key stresses a word, the key has a lone capital that may only open a sentence)."""
    for match in _KEY_RUN_RE.finditer(key):
        run, after = match.group(0), key[match.end():match.end() + 1]
        if len(run) == 2 and run[0] in _ONE_LETTER_WORDS and after.islower():
            continue
        return True, False
    opening = False
    for match in _KEY_LETTER_RE.finditer(key):
        if not _opens_sentence(key, match.start()):
            return True, False
        opening = True
    return False, opening


def _key_words(key: str) -> set[str]:
    """The Latin words of a key, lowercased and split by CamelCase: `ExtAPI` -> {`ext`, `api`}."""
    return {part.lower() for run in _WORD_RE.findall(key) for part in _CAMEL_RE.findall(run)}


def _caps_findings(section: str, key: str, value: str) -> Iterable[tuple[str, int]]:
    """(the capitalized word as written, its offset in the value) for shape 3."""
    if section == "tokens":
        candidates = [
            (m.group(0), m.start()) for m in _CAMEL_RE.finditer(value)
            if len(m.group(0)) >= 2 and m.group(0).isupper()
        ]
    else:
        candidates = [(m.group(0), m.start()) for m in _CAPS_WORD_RE.finditer(value)]
    if not candidates:
        return
    stressed, opening = _key_stress(key)
    if stressed:
        return
    known = _key_words(key)
    for word, start in candidates:
        if word in _ABBREVIATIONS or word.lower() in known:
            continue
        # "И строка ..." may be a sentence or a stressed word carried over from the line above;
        # the word that opens the translation answers that letter either way.
        if opening and _opens_sentence(value, start):
            continue
        yield word, start


# --- the rule ---------------------------------------------------------------------------------


def _is_dictionary_file(path: Path) -> bool:
    """Does the file belong to the discovered translation dictionary?"""
    resolved = path.resolve()
    found = _dictionary_at(str(resolved.parent))
    return found is not None and _inside(resolved, found)


def _occurrences(text: str, needle: str, bounded: bool) -> list[int]:
    """Offsets of `needle` in `text`; `bounded` - only where no Latin letter touches it."""
    if bounded:
        pattern = re.compile(rf"(?<![A-Za-z]){re.escape(needle)}(?![A-Za-z])")
        return [m.start() for m in pattern.finditer(text)]
    found, at = [], text.find(needle)
    while at >= 0:
        found.append(at)
        at = text.find(needle, at + 1)
    return found


def _position(source: SourceFile, node, needle: str, start: int, bounded: bool) -> tuple[int, int]:
    """Line and column of the finding: the same occurrence of `needle` in the RAW value.

    The raw slice of the file carries the quotes and escapes of the scalar, the parsed value
    does not, so the offset cannot be carried over; the ordinal of the occurrence can - the
    needle is letters and blanks, which no escaping touches. A value folded over lines may lose
    the needle as one run, and the start of the value is the answer then.
    """
    ordinal = sum(1 for at in _occurrences(node.value, needle, bounded) if at < start)
    raw = source.text[node.start_mark.index:node.end_mark.index]
    found = _occurrences(raw, needle, bounded)
    if not found:
        return node.start_mark.line + 1, node.start_mark.column + 1
    index = found[min(ordinal, len(found) - 1)]
    prefix = raw[:index]
    if "\n" in prefix:
        return node.start_mark.line + 1 + prefix.count("\n"), index - prefix.rfind("\n")
    return node.start_mark.line + 1, node.start_mark.column + 1 + index


def _preview(key: str) -> str:
    return key if len(key) <= 60 else key[:57] + "..."


def _entries(root) -> Iterable[tuple[str, object, object]]:
    """(section, key node, value node) for every scalar pair of the dictionary sections."""
    if not isinstance(root, yaml.MappingNode):
        return
    for section_node, mapping in root.value:
        if not isinstance(section_node, yaml.ScalarNode) or section_node.value not in _SECTIONS:
            continue
        if not isinstance(mapping, yaml.MappingNode):
            continue
        for key_node, value_node in mapping.value:
            if isinstance(key_node, yaml.ScalarNode) and isinstance(value_node, yaml.ScalarNode):
                yield section_node.value, key_node, value_node


@rule(RULE_ID, "translation/english-shape.title", "B", severity=Severity.WARNING)
def english_shape(source: SourceFile) -> Iterable[Diagnostic]:
    """The three shapes over every English value of a dictionary file."""
    if source.kind != "yaml" or not _HAVE_YAML or not _SECTION_RE.search(source.text):
        return
    if not _is_dictionary_file(source.path):
        return
    root = _composed(source)
    if root is None:
        return
    for section, key_node, value_node in _entries(root):
        key, value = key_node.value, value_node.value
        if not value:
            continue
        preview = _preview(key)
        bounded = section != "tokens"
        for word, start, base in _inflected_findings(section, value):
            line, column = _position(source, value_node, word, start, bounded)
            yield Diagnostic(
                source.rel, line, column, RULE_ID, Severity.WARNING,
                i18n.t("translation/english-shape.inflected", word=word, base=base, key=preview),
            )
        if section != "tokens":
            for phrase, start in _passive_findings(value):
                line, column = _position(source, value_node, phrase, start, True)
                yield Diagnostic(
                    source.rel, line, column, RULE_ID, Severity.WARNING,
                    i18n.t("translation/english-shape.passive", phrase=phrase, key=preview),
                )
        for word, start in _caps_findings(section, key, value):
            line, column = _position(source, value_node, word, start, bounded)
            yield Diagnostic(
                source.rel, line, column, RULE_ID, Severity.WARNING,
                i18n.t(
                    "translation/english-shape.caps", word=word, lower=word.lower(), key=preview,
                ),
            )
