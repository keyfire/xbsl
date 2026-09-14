"""Tier B: the prose of a comment - what a pass of the sources through a style edit kept
finding by eye, turned into checks.

A comment of a module, of an element description or of a resource file is read by the
next developer, and a project that publishes its sources shows every one of them to the
reader. Three habits kept coming back through a whole-project edit of the
comments, each caught on one line and then chased through the tree by hand:

- `comment/subjunctive` - the particle "бы": a comment in the subjunctive describes what
  the code would do, not what it does. The trap is in the repair: dropping the particle
  turns a hypothesis into a statement about the code ("отвязывали бы прайс" becomes
  "отвязывают прайс" - an action the code never takes), so the message asks for a word of
  condition - "если", "иначе", "без" - in the indicative, and there is no automatic fix.
  The turns that are not the subjunctive are left alone: the fixed "хотя бы", "будто бы",
  "вроде бы", "лишь бы", "только бы"; an interrogative word with "ни" a few words after
  the particle ("что бы ни", "каким бы путём ни", "как бы то ни было",
  "сколько бы их ни было"); and "что бы" without "ни" - the conjunction "чтобы" misspelled.
- `comment/first-person` - the author speaking as "мы" (we): a pronoun ("мы", "нас",
  "нам", "нами", "наш" in every form) or a verb of the first person plural ("делаем",
  "проверяем", "берём", "обращаемся", the slang "тащим" and "валим"). A comment is
  impersonal by convention: "проверяется", "код берёт", "модуль держит". "свой" is
  legitimate and is not judged. The pronouns are exact; the verbs are a calibrated
  heuristic - see `_verb_hit` for what the endings can and cannot tell.
- `comment/emphasis-caps` - a function word shouted in capitals for emphasis ("НЕ",
  "ТОЛЬКО", "ОДИН"). Only the listed function words and intensifiers are judged; an
  abbreviation, a name from the code, `JSON` or `SQL` are not. The fix lowercases the
  word, or capitalizes its first letter at the start of a sentence; a word inside a phrase
  in capitals ("ПОД ПРАВАМИ ПОЛЬЗОВАТЕЛЯ") gets no fix, because the phrase is rewritten
  as a whole.

The three read the same comment lines (`_comments.lines`), skip what stands inside quotes
or backticks (a quoted label or a cited identifier is data, not the author's voice), and
are OFF by default: on a code base that never adopted the convention they fire in bulk,
and a project that did turns the group on with `--enable comment` in its CI.

A translated comment has an English half, and `comment/first-person` reads it too. A project
that translates its sources keeps the English line of every comment as a `phrases` value of
its `xbsl-translation` dictionary, and the translated tree takes its comments from there: "we
build it from the name" is the same author speaking as "we" that the Russian check reports.
Only that section is read - a `literals` value is a string of the code, often a text the user
reads ("I accept the terms"), and `tokens` and `terms` hold names.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from xbsl import i18n
from xbsl.diagnostics import Diagnostic, Severity, TextEdit
from xbsl.engine import SourceFile, rule
from xbsl.rules import _comments
from xbsl.rules.translation_values import _entries, _is_dictionary_file, _position
from xbsl.rules.yaml_schema import _composed

MESSAGES = {
    "comment/subjunctive.title": {
        "ru": "Частица \"бы\" в комментарии",
        "en": "Subjunctive particle in a comment",
    },
    "comment/subjunctive.found": {
        "ru": "Частица \"бы\" в комментарии: сослагательное наклонение описывает не то, что "
              "код делает. Перефразируйте словом условия в изъявительном наклонении – "
              "\"если ...\", \"иначе ...\", \"без ...\"; просто снять частицу нельзя: "
              "\"делал бы\" превращается в \"делает\", а такого действия в коде нет.",
        "en": "The subjunctive particle (would) in a comment: the subjunctive describes what "
              "the code would do, not what it does. Rephrase with a word of condition in the "
              "indicative - \"если\" (if), \"иначе\" (otherwise), or \"without\"; dropping the "
              "particle alone is wrong: \"would do\" turns into \"does\", an action the code "
              "never takes.",
    },
    "comment/subjunctive.off": {
        "ru": "соглашение ПРОЕКТА о слоге комментариев, а не платформы: на чужом коде "
              "срабатывает массово. Проект включает группу `comment` в своём CI (--enable comment)",
        "en": "a PROJECT convention about the wording of comments rather than a platform one: "
              "on foreign code it fires in bulk. A project turns the `comment` group on in "
              "its CI (--enable comment)",
    },
    "comment/first-person.title": {
        "ru": "Первое лицо в комментарии",
        "en": "First person in a comment",
    },
    "comment/first-person.pronoun": {
        "ru": "Местоимение первого лица \"{word}\" в комментарии – комментарий безличен: "
              "действующее лицо не автор, а код, модуль или объект (\"свой\" законно).",
        "en": "The first-person pronoun \"{word}\" (we, our) in a comment - a comment is "
              "impersonal: the actor is the code, the module or the object, not the author "
              "(the word for one's own is fine).",
    },
    "comment/first-person.verb": {
        "ru": "Глагол первого лица \"{word}\" в комментарии – комментарий безличен: "
              "\"проверяется\" или \"код проверяет\", а не \"проверяем\".",
        "en": "The first-person plural verb \"{word}\" (we do) in a comment - a comment is "
              "impersonal: write that something is checked, or that the code checks it, not "
              "that we check it.",
    },
    "comment/first-person.english": {
        "ru": "Первое лицо \"{word}\" в английской строке комментария (значение словаря "
              "перевода) – комментарий безличен на любом языке: действует код, модуль или "
              "объект, а не автор.",
        "en": "The first person \"{word}\" in the English line of a comment (a value of the "
              "translation dictionary) - a comment is impersonal in any language: the code, the "
              "module or the object acts, not the author.",
    },
    "comment/first-person.off": {
        "ru": "соглашение ПРОЕКТА о слоге комментариев, а не платформы: на чужом коде "
              "срабатывает массово. Проект включает группу `comment` в своём CI (--enable comment)",
        "en": "a PROJECT convention about the wording of comments rather than a platform one: "
              "on foreign code it fires in bulk. A project turns the `comment` group on in "
              "its CI (--enable comment)",
    },
    "comment/emphasis-caps.title": {
        "ru": "Капс смыслового ударения в комментарии",
        "en": "Emphasis in capitals in a comment",
    },
    "comment/emphasis-caps.found": {
        "ru": "Слово \"{word}\" прописными ради ударения – ударение в комментарии несёт "
              "порядок слов, а не регистр; пишется \"{suggestion}\".",
        "en": "The word \"{word}\" in capitals for emphasis - in a comment the emphasis is "
              "carried by the word order, not by the case; write \"{suggestion}\".",
    },
    "comment/emphasis-caps.off": {
        "ru": "соглашение ПРОЕКТА о слоге комментариев, а не платформы: на чужом коде "
              "срабатывает массово. Проект включает группу `comment` в своём CI (--enable comment)",
        "en": "a PROJECT convention about the wording of comments rather than a platform one: "
              "on foreign code it fires in bulk. A project turns the `comment` group on in "
              "its CI (--enable comment)",
    },
}
i18n.register(MESSAGES)

#: What stands inside quotes or backticks is data - a label the user reads, a cited name -
#: and none of the three rules judges it. Replaced with spaces so the offsets hold.
_QUOTED = re.compile(r'"[^"\n]*"|\u00ab[^\u00bb\n]*\u00bb|`[^`\n]*`')

#: A word of Russian prose: one word, no inner capital (an identifier), no digits, no
#: underscore, no Latin letter - such a token is a name from the code, not prose.
_WORD = re.compile(r"(?<![\w-])([А-ЯЁа-яё][а-яё]+)(?![\w-])")


def _prose(text: str) -> str:
    return _QUOTED.sub(lambda m: " " * len(m.group(0)), text)


def _cyrillic_words(text: str) -> list[str]:
    return [w.lower() for w in re.findall(r"[А-ЯЁа-яё]+", text)]


def _neighbours(lines: list[_comments.CommentLine], index: int) -> tuple[str, str]:
    """The prose of the comment lines just above and just below line `index`.

    A sentence of a comment runs over several lines, so a turn may start on one line and end
    on the next ("каким бы путём" / "ни пришла запись"). A line counts as a neighbour only
    when it is the adjacent line of the file; otherwise the text is empty.
    """
    current = lines[index]
    above = below = ""
    if index > 0 and lines[index - 1].line == current.line - 1:
        text = lines[index - 1].text
        above = _prose(text[_comments.lead(text):])
    if index + 1 < len(lines) and lines[index + 1].line == current.line + 1:
        text = lines[index + 1].text
        below = _prose(text[_comments.lead(text):])
    return above, below


# --- comment/subjunctive -------------------------------------------------------------------

_BY = re.compile(r"(?<![\w-])бы(?![\w-])", re.IGNORECASE)

#: An interrogative word before the particle with "ни" a few words after it makes the
#: concessive turn ("что бы ни", "каким бы путём ни пришла", "сколько бы их ни было").
_INTERROGATIVES = frozenset((
    "что", "как", "где", "кто", "куда", "когда", "откуда", "докуда", "сколько", "насколько",
    "почему", "зачем", "отчего", "чей", "чья", "чьё", "чье", "чьи", "чьим", "чьих", "чьей",
    "какой", "какая", "какое", "какие", "каким", "какими", "какого", "какому", "какую",
    "каком", "каких", "кому", "кем", "кого", "чего", "чему", "чем", "каков", "какова",
    "каково", "каковы", "который", "которая", "которое", "которые", "которым", "которых",
    "котором", "которой", "которого", "которому", "которую",
))
#: How many words after the particle the "ни" may stand: "каким бы путём ни",
#: "сколько бы их ни было", "как бы то ни было".
_NI_WINDOW = 3

#: Fixed turns where the particle is not the subjunctive: "хотя бы" (at least), "будто бы"
#: and "вроде бы" (seemingly), "лишь бы" and "только бы" (if only).
_FIXED_BEFORE = frozenset(("хотя", "будто", "вроде", "лишь", "только"))


def _not_subjunctive(before: str, after: str) -> bool:
    """Whether the particle at this spot belongs to a turn that is not the subjunctive.

    Three such turns: a fixed one ("хотя бы"), a concessive one (an interrogative word
    before the particle and "ни" a few words after it), and "что бы" without that "ни" -
    the conjunction "чтобы" written in two words ("для того, что бы избавиться"). The last
    is a spelling mistake, and a message about the mood would send its reader the wrong way.
    """
    previous = _cyrillic_words(before)
    if not previous:
        return False
    last = previous[-1]
    if last in _FIXED_BEFORE:
        return True
    if last in _INTERROGATIVES:
        following = _cyrillic_words(after)[:_NI_WINDOW]
        return "ни" in following or last == "что"
    return False


@rule(
    "comment/subjunctive", "comment/subjunctive.title", "B",
    severity=Severity.WARNING, enabled_by_default=False, off_reason="comment/subjunctive.off",
)
def subjunctive(source: SourceFile) -> Iterable[Diagnostic]:
    """The particle `бы` in a comment, outside the fixed and concessive turns.

    No fix: the repair is a rephrase with a word of condition, which is a human decision -
    a mechanical removal of the particle is exactly the mistake the message warns about.
    """
    if "бы" not in source.text and "Бы" not in source.text and "БЫ" not in source.text:
        return
    lines = _comments.lines(source)
    for index, cl in enumerate(lines):
        text = _prose(cl.text)
        matches = list(_BY.finditer(text))
        if not matches:
            continue
        above, below = _neighbours(lines, index)
        for m in matches:
            before = f"{above} {text[:m.start()]}"
            after = f"{text[m.end():]} {below}"
            if _not_subjunctive(before, after):
                continue
            yield Diagnostic(
                source.rel, cl.line, cl.column + m.start(), "comment/subjunctive",
                Severity.WARNING, i18n.t("comment/subjunctive.found"),
            )


# --- comment/first-person ------------------------------------------------------------------

_PRONOUNS = frozenset((
    "мы", "нас", "нам", "нами",
    "наш", "наша", "наше", "наши", "нашего", "нашей", "нашему", "нашим", "нашими", "наших",
    "нашу",
))

# The verb of the first person plural is told by its ending, and the endings are shared
# with other parts of speech - the calibration over three corpora (a cleaned project, a
# vendor library, a pre-edit snapshot with 24k comment lines) settled which can be judged
# by the ending alone and which need a list:
#
# - the reflexive `-емся`, `-ёмся`, `-имся` belongs to a verb - or to a reflexive participle
#   in the prepositional or the instrumental case ("в раскрывающемся списке",
#   "в открывшемся окне", "с завершившимся заданием"), which the suffix before the ending
#   gives away: `-ущ-`, `-ющ-`, `-ащ-`, `-ящ-`, `-вш-` (`_PARTICIPLE_STEMS`);
# - `-аем`, `-яем`, `-уем`, `-юем` (with `-ываем`, `-иваем`, `-оваем` inside) is the open
#   productive class of the first conjugation, and the only other words with those endings
#   are the instrumental of a handful of nouns in `-ай`, `-яй`, `-уй` - "краем", "случаем",
#   "чаем" - listed in `_OPEN_CLASS_NOUNS`, and the short passive adjective, which has the
#   form of the verb: a negated one is written in one word ("нечитаем", "неуправляем") and
#   is skipped by the prefix, a few frequent ones without negation ("предсказуем",
#   "узнаваем") are listed in `_SHORT_ADJECTIVES`;
# - `-ем` after a consonant is the instrumental of every soft-stem noun ("полем",
#   "значением", "пользователем", "путём", "объём"), a pronoun ("тем", "чем", "всем",
#   "своём") and an adverb ("затем", "вдвоём"); `-им` is the instrumental of every adjective
#   and pronoun in the plural ("одним", "своим", "внешним", "ним"), a noun ("режим",
#   "аноним") and a short adjective ("необходим", "видим", "применим", "допустим");
#   `-жем`, `-чем`, `-шем`, `-щем` is "чем", "прочем", "будущем", "хранилищем". Those three
#   groups are judged only for the verbs of `_LISTED_VERBS` - the common ones, spelled with
#   and without the letter "ё" - and the short adjectives that coincide with a verb form
#   ("видим", "применим", "выполним", "сравним", "допустим") are deliberately not there.

#: Instrumental nouns that end like a verb of the open class.
_OPEN_CLASS_NOUNS = frozenset((
    "краем", "случаем", "чаем", "сараем", "трамваем", "урожаем", "обычаем", "лишаем",
    "попугаем", "негодяем", "лентяем", "разгильдяем", "шалопаем", "слюнтяем", "буем",
    "паем", "маем", "раем", "лаем", "дунаем", "алтаем", "николаем",
))

#: Short passive adjectives in the form of an open-class verb, written without "не".
_SHORT_ADJECTIVES = frozenset((
    "предсказуем", "узнаваем", "досягаем", "осязаем", "обозреваем", "исчисляем",
))

_OPEN_CLASS_ENDINGS = ("аем", "яем", "уем", "юем")
_REFLEXIVE_ENDINGS = ("емся", "ёмся", "имся")
#: The suffix of an active participle right before a reflexive ending.
_PARTICIPLE_STEMS = ("ущ", "ющ", "ащ", "ящ", "вш")

#: First-person plural verbs whose ending is shared with nouns, pronouns and adjectives:
#: the stressed `-ём` and the `-ем` after a consonant, the second conjugation `-им`, the
#: hissing stems. Spelled with "ё"; the spelling with "е" is derived below.
_LISTED_VERBS_SOURCE = """
берём ведём идём ждём живём найдём начнём поймём вернём зовём несём везём кладём растём
прочтём учтём сочтём зайдём пройдём перейдём обойдём войдём уйдём придём пойдём дойдём
выйдём сойдём отойдём наберём соберём уберём приберём переберём разберём отберём подберём
возьмём займём наймём даём создаём передаём отдаём узнаём признаём встаём сдаём задаём
продаём выдаём раздаём придаём подаём бережём стережём печём испечём влечём привлечём
извлечём отвлечём сечём отсечём
будем забудем выберем примем снимем поднимем отнимем тянем станем встанем достанем
перестанем сядем
имеем умеем успеем сумеем владеем смеем посмеем жалеем одолеем преодолеем греем сеем
можем сможем поможем скажем подскажем покажем расскажем докажем откажем укажем
ищем пишем запишем перепишем допишем опишем спишем подпишем распишем впишем режем отрежем
обрежем срежем нарежем подрежем вырежем вяжем свяжем привяжем отвяжем перевяжем подвяжем
мажем прячем спрячем шепчем машем ляжем лижем гложем
приведём проведём переведём выведем заведём введём сведём отведём доведём подведём наведём
разведём перестаём вызовем позовём откроем закроем скроем раскроем перекроем
ставим поставим выставим оставим представим вставим доставим предоставим составим переставим
расставим отставим подставим сопоставим правим поправим подправим направим отправим переправим
храним сохраним строим построим выстроим настроим перестроим достроим отстроим смотрим
посмотрим рассмотрим просмотрим досмотрим ловим выловим чистим очистим почистим тащим вытащим
затащим притащим протащим валим завалим свалим отвалим держим удержим придержим задержим
поддержим сдержим выдержим продержим хотим захотим сидим лежим стоим говорим поговорим
получим решим проверим заполним удалим определим установим обновим добавим изменим заменим
отменим включим выключим отключим подключим переключим назначим обозначим ценим оценим чиним
починим гоним ходим приходим находим уходим выходим заходим проходим обходим переходим
подходим входим отходим доходим сходим приводим выводим заводим вводим переводим проводим
сводим наводим разводим отводим доводим подводим производим возим носим приносим выносим
заносим переносим уносим относим вносим просим спросим запросим попросим бросим сбросим
отбросим набросим тратим потратим платим оплатим заплатим летим пустим запустим выпустим
отпустим пропустим впустим кормим крепим закрепим прикрепим открепим купим красим окрасим
учим научим изучим молчим кричим разместим поместим переместим растим вырастим освоим
присвоим успокоим заметим отметим пометим разметим наметим помним запомним напомним вспомним
лечим вылечим дарим варим жарим парим творим сотворим ускорим повторим доверим поверим сверим
измерим замерим отмерим примерим верим расширим сузим грузим загрузим выгрузим перегрузим
подгрузим догрузим отгрузим разгрузим погрузим тормозим хвалим молим чтим гасим погасим
тушим потушим глушим заглушим душим уводим готовим приготовим подготовим судим будим
копим накопим создадим передадим отдадим зададим селектим
"""


def _with_both_spellings(words: Iterable[str]) -> frozenset[str]:
    out: set[str] = set()
    for word in words:
        out.add(word)
        out.add(word.replace("ё", "е"))
    return frozenset(out)


_LISTED_VERBS = _with_both_spellings(_LISTED_VERBS_SOURCE.split())


def _verb_hit(word: str) -> bool:
    """Whether a lower-case word of prose is a verb of the first person plural."""
    if word in _LISTED_VERBS:
        return True
    if word.endswith(_REFLEXIVE_ENDINGS):
        stem = word[:-4]
        return len(stem) > 1 and not stem.endswith(_PARTICIPLE_STEMS)
    if word.endswith(_OPEN_CLASS_ENDINGS):
        return (
            word not in _OPEN_CLASS_NOUNS
            and word not in _SHORT_ADJECTIVES
            and not word.startswith("не")
        )
    return False


@rule(
    "comment/first-person", "comment/first-person.title", "B",
    severity=Severity.WARNING, enabled_by_default=False, off_reason="comment/first-person.off",
)
def first_person(source: SourceFile) -> Iterable[Diagnostic]:
    """The author speaking as "we" in a comment: a pronoun or a first-person plural verb.

    In a translation dictionary the English lines of the comments are read as well
    (`_english_first_person`).
    """
    for cl in _comments.lines(source):
        text = _prose(cl.text)
        for m in _WORD.finditer(text):
            word = m.group(1).lower()
            if word in _PRONOUNS:
                key = "comment/first-person.pronoun"
            elif _verb_hit(word):
                key = "comment/first-person.verb"
            else:
                continue
            yield Diagnostic(
                source.rel, cl.line, cl.column + m.start(), "comment/first-person",
                Severity.WARNING, i18n.t(key, word=m.group(1)),
            )
    yield from _english_first_person(source)


# --- comment/first-person: the English line of a translated comment ------------------------

#: The English first person, both numbers: a pronoun, a possessive, a reflexive and the
#: imperative "let's". A verb needs no list - an English verb carries its pronoun. A word glued
#: to a slash, a dot, a hyphen or a backslash is a path, a file or a code (`en-us`, `I/O`).
_ENGLISH_PERSON = re.compile(
    r"(?<![\w'./\\-])(we|us|our|ours|ourselves|i|me|my|mine|myself|let's)(?![\w/\\-])",
    re.IGNORECASE,
)

#: A word right before a capital "I" that makes the letter a name or a numeral: "the letter I",
#: "part I", "type I".
_I_AS_NAME_AFTER = frozenset("""
    a an the letter letters part phase type stage level class grade chapter section volume tier
""".split())

#: The box-drawing characters of a separator line: a heading drawn with them names a section
#: rather than opening a sentence ("── My details ──" repeats the caption of a panel).
_RULE_CHARS = frozenset("─━═")

_LATIN_LETTER = re.compile(r"[A-Za-z]")
_LATIN_WORDS = re.compile(r"[A-Za-z]+")


def _opens_english_sentence(text: str, at: int, key: str) -> bool:
    """Whether a capitalized word at `at` of an English comment line opens a sentence.

    A capital that does not open one marks a name - a caption of the interface cited without
    quotes ("on the right - My data"), a page title ("Contact Us"). At the start of the value
    the Russian key decides: a line that goes on from the line above starts with a small
    letter there, and so does its translation.
    """
    head = text[:at]
    cut = max(head.rfind("."), head.rfind("!"), head.rfind("?"))
    if _LATIN_LETTER.search(head[cut + 1:]):
        return False
    if cut >= 0:
        return True
    if any(ch in _RULE_CHARS for ch in head):
        return False
    first = next((ch for ch in key if ch.isalpha()), "")
    return not first or first.isupper()


def _english_person_hit(text: str, m: re.Match, key: str) -> bool:
    """Whether a match of `_ENGLISH_PERSON` is the author speaking in the first person."""
    word = m.group(1)
    if word.lower() == "i":
        if word != "I":
            return False  # a loop variable or an index
        before = _LATIN_WORDS.findall(text[:m.start()])
        if before and before[-1].lower() in _I_AS_NAME_AFTER:
            return False
        return text[m.end():m.end() + 1] not in (".", ")")
    if len(word) > 1 and word.isupper():
        return word != "US"  # the country; a pronoun in capitals is still the first person
    if word[0].isupper():
        return _opens_english_sentence(text, m.start(), key)
    return True


def _english_first_person(source: SourceFile) -> Iterable[Diagnostic]:
    """The first person in the `phrases` values of a translation dictionary file."""
    if source.kind != "yaml" or "phrases:" not in source.text:
        return
    if not _is_dictionary_file(source.path):
        return
    root = _composed(source)
    if root is None:
        return
    for section, key_node, value_node in _entries(root):
        if section != "phrases" or not value_node.value:
            continue
        text = _prose(value_node.value)
        for m in _ENGLISH_PERSON.finditer(text):
            if not _english_person_hit(text, m, key_node.value):
                continue
            word = m.group(1)
            line, column = _position(source, value_node, word, m.start(), True)
            yield Diagnostic(
                source.rel, line, column, "comment/first-person", Severity.WARNING,
                i18n.t("comment/first-person.english", word=word),
            )


# --- comment/emphasis-caps -----------------------------------------------------------------

#: The function words and intensifiers a comment shouts for emphasis, read off three corpora
#: (the snapshot of one project before its comments were edited held 366 of them, "НЕ" the
#: most frequent). A content word in capitals is not judged ("ЦЕЛИКОМ" is an intensifier and
#: is listed), nor is an abbreviation ("ТЧ", "СУБД") or a name from the code. "ИЛИ" is not
#: listed on purpose: in a comment it names the logical operation
#: ("значения складываются по ИЛИ, между группами - И"), and on the corpora it never once
#: carried emphasis.
_EMPHASIS = frozenset("""
НЕ НИ ТОЛЬКО ЛИШЬ ИМЕННО РОВНО ТОЖЕ ЖЕ ЕЩЁ ЕЩЕ УЖЕ ПОКА СРАЗУ ВОВСЕ СОВСЕМ ЦЕЛИКОМ
ОДИН ОДНА ОДНО ОДНИ ОДНОГО ОДНОЙ ОДНОМУ ОДНИМ ОДНОМ ОДНУ ОДНИХ ОДНИМИ
ДВА ДВЕ ТРИ РАЗ
ВСЕ ВСЁ ВСЕХ ВСЕМ ВСЕМИ ВСЕМУ ВСЕГО ВСЕЙ ВСЮ ВЕСЬ ВСЯ ВСЕГДА
НИКОГДА НИКТО НИЧТО НИЧЕГО НИКАК НИГДЕ НИКАКОЙ НИКАКАЯ НИКАКОЕ НИКАКИЕ
ДО ПОСЛЕ ПЕРЕД БЕЗ ПОД НАД ВНУТРИ
НЕЛЬЗЯ МОЖНО НУЖНО НАДО ОБЯЗАТЕЛЬНО ОБЯЗАН ОБЯЗАНА ОБЯЗАНО ОБЯЗАНЫ ДОЛЖЕН ДОЛЖНА ДОЛЖНО ДОЛЖНЫ
ЛЮБОЙ ЛЮБАЯ ЛЮБОЕ ЛЮБЫЕ ЛЮБОГО ЛЮБОМ ЛЮБУЮ ЛЮБЫХ ЛЮБЫМ
КАЖДЫЙ КАЖДАЯ КАЖДОЕ КАЖДЫЕ КАЖДОГО КАЖДОЙ КАЖДОМ КАЖДУЮ КАЖДЫХ КАЖДЫМ
САМ САМА САМО САМИ САМОГО САМОЙ САМОМ САМИМ САМОМУ САМУ САМИХ
СВОЙ СВОЯ СВОЁ СВОЕ СВОИ СВОЕГО СВОЕЙ СВОЕМУ СВОИМ СВОЁМ СВОЕМ СВОЮ СВОИХ СВОИМИ
ТОТ ТА ТО ТЕ ТОГО ТОЙ ТОМУ ТЕМ ТОМ ТУ ТЕХ ТЕМИ
ЛИБО НЕТ ЕСТЬ ДА СНАЧАЛА ПОТОМ ЗАТЕМ ТАК ТАМ ЗДЕСЬ ЧТО ИХ
""".split())

#: A capital word of the query language on the same line means the comment cites a query
#: ("ГДЕ НЕ Удалён", "ОБЪЕДИНИТЬ ВСЕ", "ЕСТЬ NULL"), and the capitals there are syntax.
_QUERY_MARKERS = frozenset((
    "ВЫБРАТЬ", "ИЗ", "ГДЕ", "ПОМЕСТИТЬ", "СОЕДИНЕНИЕ", "ОБЪЕДИНИТЬ", "УПОРЯДОЧИТЬ",
    "СГРУППИРОВАТЬ", "ПЕРВЫЕ", "РАЗЛИЧНЫЕ", "СУЩЕСТВУЕТ", "ЕСТЬNULL", "NULL", "ВЫРАЗИТЬ",
    "ПОДОБНО", "ИМЕЮЩИЕ", "ИЕРАРХИИ",
    "SELECT", "FROM", "WHERE", "JOIN", "UNION", "EXISTS", "ISNULL", "DISTINCT", "HAVING",
))

_CAPS_WORD = re.compile(r"(?<![\w-])([А-ЯЁ]{2,})(?![\w-])")
#: What may stand between two words of one phrase in capitals: spaces and a dash.
_PHRASE_GAP = re.compile(r"[ \t\-\u2013\u2014]*")
_ANY_CAPS_WORD = re.compile(r"(?<![\w-])([A-ZА-ЯЁ]{2,})(?![\w-])")


def _cites_query(text: str) -> bool:
    return any(w in _QUERY_MARKERS for w in _ANY_CAPS_WORD.findall(text))


def _sentence_start(prose: str, index: int, previous: str | None) -> bool:
    """Whether the word at `index` of the comment line opens a sentence.

    A spot after a full stop, an exclamation or a question mark opens one. So does the start
    of the line's prose (after the marker and a bullet) - unless the comment goes on from
    the line above (`previous`, its prose) and that line did not end its sentence: then the
    word continues the sentence and keeps a lower-case letter.
    """
    head = prose[_comments.lead(prose):index].rstrip()
    if head:
        return head[-1] in ".!?"
    if previous is None:
        return True
    tail = previous[_comments.lead(previous):].rstrip()
    return not tail or tail[-1] in ".!?"


def _in_caps_phrase(text: str, words: list[re.Match], position: int) -> bool:
    """Whether the word stands in a run of capitals that holds a word the rule does not judge.

    The stress often falls on a phrase ("ПОД ПРАВАМИ ПОЛЬЗОВАТЕЛЯ", "ДЛЯ КАЖДОГО ОБЪЕКТА").
    Lowering the listed word alone would leave the rest of the phrase shouting, so such a
    finding carries no fix and the phrase is rewritten by hand. A run of listed words only
    ("ТЕ ЖЕ", "ЕЩЁ РАЗ") is fixed word by word.
    """
    first = last = position
    while first > 0 and _PHRASE_GAP.fullmatch(text, words[first - 1].end(), words[first].start()):
        first -= 1
    while last + 1 < len(words) and _PHRASE_GAP.fullmatch(
        text, words[last].end(), words[last + 1].start(),
    ):
        last += 1
    return any(words[i].group(1) not in _EMPHASIS for i in range(first, last + 1))


@rule(
    "comment/emphasis-caps", "comment/emphasis-caps.title", "B",
    severity=Severity.WARNING, enabled_by_default=False, off_reason="comment/emphasis-caps.off",
)
def emphasis_caps(source: SourceFile) -> Iterable[Diagnostic]:
    """A listed function word in capitals; the fix restores the case of ordinary prose."""
    before: _comments.CommentLine | None = None
    for cl in _comments.lines(source):
        previous = before.text if before is not None and before.line == cl.line - 1 else None
        before = cl
        text = _prose(cl.text)
        if _cites_query(cl.text) or not re.search(r"[а-яё]", text[_comments.lead(text):]):
            # A cited query, or a line written in capitals from end to end: a heading or a
            # shout of the whole line, where no single word is stressed.
            continue
        words = list(_CAPS_WORD.finditer(text))
        for position, m in enumerate(words):
            word = m.group(1)
            if word not in _EMPHASIS:
                continue
            lowered = word.lower()
            opens = _sentence_start(text, m.start(), previous)
            suggestion = lowered.capitalize() if opens else lowered
            offset = cl.offset + m.start()
            fix = None if _in_caps_phrase(text, words, position) else TextEdit(
                offset, offset + len(word), suggestion,
            )
            yield Diagnostic(
                source.rel, cl.line, cl.column + m.start(), "comment/emphasis-caps",
                Severity.WARNING,
                i18n.t("comment/emphasis-caps.found", word=word, suggestion=suggestion),
                fix=fix,
            )
