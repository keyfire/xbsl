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
- `comment/emphasis-caps` - a word shouted in capitals for emphasis: a function word
  ("НЕ", "ТОЛЬКО", "ОДИН"), any other word the file shows to be an ordinary one
  ("берётся ТЕКУЩИЙ"), a one-letter word inside a sentence ("в порядке, В котором"), a
  negation glued on ("НЕзаполненным"), and in a translation dictionary the English line of
  a comment ("is NOT a filter"). An abbreviation, a mask of a date, a name carried from the
  code or from the key, and a cited query are not judged. The fix lowercases the word, or
  capitalizes its first letter at the start of a sentence - the sweep of a project over
  two hundred lines did exactly that.

The three read the same comment lines (`_comments.lines`), skip what stands inside quotes
or backticks (a quoted label or a cited identifier is data, not the author's voice), and
are OFF by default: on a code base that never adopted the convention they fire in bulk,
and a project that did turns the group on with `--enable comment` in its CI.
"""

from __future__ import annotations

import re
from bisect import bisect_left
from collections.abc import Iterable

from xbsl import i18n
from xbsl.diagnostics import Diagnostic, Severity, TextEdit
from xbsl.engine import SourceFile, rule
from xbsl.rules.translation_values import (
    _ABBREVIATIONS, _caps_findings, _entries, _is_dictionary_file, _key_words, _occurrences,
    _opens_sentence, _position,
)
from xbsl.rules.yaml_schema import _composed
from xbsl.rules import _comments

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
    "comment/emphasis-caps.letter": {
        "ru": "Однобуквенное слово \"{word}\" прописной буквой посреди фразы – так выделяют "
              "ударение, а в комментарии его несёт порядок слов; пишется \"{suggestion}\".",
        "en": "The one-letter word \"{word}\" in a capital inside a sentence - a stress marked by "
              "the case, while in a comment the word order carries it; write \"{suggestion}\".",
    },
    "comment/emphasis-caps.prefix": {
        "ru": "Отрицание прописными в слове \"{word}\" – так выделяют ударение, а в комментарии "
              "его несёт порядок слов; пишется \"{suggestion}\".",
        "en": "The negation in capitals in the word \"{word}\" - a stress marked by the case, "
              "while in a comment the word order carries it; write \"{suggestion}\".",
    },
    "comment/emphasis-caps.english": {
        "ru": "Слово \"{word}\" прописными ради ударения в английской строке комментария "
              "(значение словаря перевода) – ударение несёт порядок слов, а не регистр; "
              "пишется \"{suggestion}\".",
        "en": "The word \"{word}\" in capitals for emphasis in the English line of a comment (a "
              "value of the translation dictionary) - the emphasis is carried by the word order, "
              "not by the case; write \"{suggestion}\".",
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
    """The author speaking as "we" in a comment: a pronoun or a first-person plural verb."""
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


# --- comment/emphasis-caps -----------------------------------------------------------------
#
# A word in capitals stresses what the sentence would stress with its word order. Four shapes of
# that habit came back through a sweep of one project's comments, and the rule reads all four:
#
# - a word of two capitals or more. A function word or an intensifier of `_EMPHASIS` is judged
#   whatever the file holds; any other word only on the evidence of the file (`_shouted_word`),
#   because an abbreviation has the same shape;
# - one capital letter standing for a preposition or a conjunction inside a sentence
#   ("в порядке, В котором", "значок И текст") - `_stressed_letter`;
# - a negation glued on in capitals ("НЕзаполненным");
# - in a translation dictionary, the English line of a comment ("is NOT a filter",
#   "ONE BY ONE", "UNfilled") - `_english_emphasis`.

#: The function words and intensifiers a comment shouts for emphasis, read off three corpora
#: (the snapshot of one project before its comments were edited held 366 of them, "НЕ" the
#: most frequent). "ИЛИ" and "И" name a logical operation too ("значения складываются по ИЛИ"),
#: and the first version of the rule left them alone for that; the sweep that followed wrote
#: them in small letters all the same, so they are judged like the rest.
_EMPHASIS = frozenset("""
НЕ НИ ТОЛЬКО ЛИШЬ ИМЕННО РОВНО ТОЖЕ ЖЕ ЕЩЁ ЕЩЕ УЖЕ ПОКА СРАЗУ ВОВСЕ СОВСЕМ ЦЕЛИКОМ
ОДИН ОДНА ОДНО ОДНИ ОДНОГО ОДНОЙ ОДНОМУ ОДНИМ ОДНОМ ОДНУ ОДНИХ ОДНИМИ
ДВА ДВЕ ТРИ РАЗ
ВСЕ ВСЁ ВСЕХ ВСЕМ ВСЕМИ ВСЕМУ ВСЕГО ВСЕЙ ВСЮ ВЕСЬ ВСЯ ВСЕГДА
НИКОГДА НИКТО НИЧТО НИЧЕГО НИКАК НИГДЕ НИКАКОЙ НИКАКАЯ НИКАКОЕ НИКАКИЕ
ДО ПОСЛЕ ПЕРЕД БЕЗ ПОД НАД ВНУТРИ ПО НА ЗА ОТ ИЗ ДЛЯ ПРИ СО ВО ВНЕ ЧЕРЕЗ
НЕЛЬЗЯ МОЖНО НУЖНО НАДО ОБЯЗАТЕЛЬНО ОБЯЗАН ОБЯЗАНА ОБЯЗАНО ОБЯЗАНЫ ДОЛЖЕН ДОЛЖНА ДОЛЖНО ДОЛЖНЫ
ЛЮБОЙ ЛЮБАЯ ЛЮБОЕ ЛЮБЫЕ ЛЮБОГО ЛЮБОМ ЛЮБУЮ ЛЮБЫХ ЛЮБЫМ
КАЖДЫЙ КАЖДАЯ КАЖДОЕ КАЖДЫЕ КАЖДОГО КАЖДОЙ КАЖДОМ КАЖДУЮ КАЖДЫХ КАЖДЫМ
САМ САМА САМО САМИ САМОГО САМОЙ САМОМ САМИМ САМОМУ САМУ САМИХ
СВОЙ СВОЯ СВОЁ СВОЕ СВОИ СВОЕГО СВОЕЙ СВОЕМУ СВОИМ СВОЁМ СВОЕМ СВОЮ СВОИХ СВОИМИ
ТОТ ТА ТО ТЕ ТОГО ТОЙ ТОМУ ТЕМ ТОМ ТУ ТЕХ ТЕМИ
ЛИБО НЕТ ЕСТЬ ДА СНАЧАЛА ПОТОМ ЗАТЕМ ТАК ТАМ ЗДЕСЬ ЧТО ИХ ГДЕ КАК ИЛИ НЕМ НЁМ ОБА ОБЕ
ЭТО ЭТОТ ЭТА ЭТИ ЭТОМ ЭТИМ ЭТОЙ ЭТОГО ЭТУ
""".split())

#: Words of the query language that never stress a sentence: a comment line holding one in
#: capitals cites a query ("ОБЪЕДИНИТЬ ВСЕ", "ЕСТЬ NULL"), and every capital of the line is
#: syntax. The keywords that are ordinary words as well are `_QUERY_WORDS`.
_QUERY_MARKERS = frozenset((
    "ВЫБРАТЬ", "ПОМЕСТИТЬ", "СОЕДИНЕНИЕ", "ОБЪЕДИНИТЬ", "УПОРЯДОЧИТЬ", "СГРУППИРОВАТЬ",
    "РАЗЛИЧНЫЕ", "СУЩЕСТВУЕТ", "ЕСТЬNULL", "NULL", "ВЫРАЗИТЬ", "ПОДОБНО", "ИМЕЮЩИЕ", "ИЕРАРХИИ",
    "SELECT", "FROM", "WHERE", "JOIN", "UNION", "EXISTS", "ISNULL", "DISTINCT", "HAVING",
))

#: The aggregate functions of the query language: written in capitals exactly like this, the
#: word names the function ("по МИНИМУМ и МАКСИМУМ", "КОЛИЧЕСТВО(*)"). A stressed word is
#: declined with the sentence ("остаток задан МИНИМУМОМ") and stays judged.
_QUERY_FUNCTIONS = frozenset(("МИНИМУМ", "МАКСИМУМ", "КОЛИЧЕСТВО", "СУММА", "СРЕДНЕЕ"))

#: Query keywords that are ordinary words as well. In capitals such a word is syntax only when
#: code follows it (`_code_around`): "Т.Поле В (&Список)", "Склады КАК Склады",
#: "ГДЕ НЕ Удалён". Otherwise it is judged like any other word.
_QUERY_WORDS = frozenset((
    "В", "И", "ИЛИ", "НЕ", "КАК", "ПО", "ИЗ", "ГДЕ", "ЕСТЬ", "ВСЕ", "МЕЖДУ", "КОГДА", "ТОГДА",
    "ИНАЧЕ", "КОНЕЦ", "ПЕРВЫЕ",
    "IN", "AND", "OR", "NOT", "AS", "ON", "IS", "BY", "ALL", "BETWEEN", "WHEN", "THEN", "ELSE",
    "END", "LIKE",
))

#: A word that names a part of a query right before its keyword: "операнд условия В" cites
#: the operator.
_QUERY_NOUNS = frozenset("""
условие условия условию условием условии оператор оператора оператору оператором операторе
операция операции операцию операцией секция секции секцию секцией предложение предложения
предложению предложением предложении
""".split())
#: The same in English, right after the keyword: "an IN condition", "the AND operator".
_QUERY_NOUNS_ENGLISH = frozenset("""
condition conditions operator operators clause clauses keyword keywords operation operations
section statement expression
""".split())
#: A clause keyword after a preposition names the clause: "отбор в коде, а не в ГДЕ".
_CLAUSE_WORDS = frozenset(("ГДЕ", "ИЗ", "ИМЕЮЩИЕ"))
_CLAUSE_PREPOSITIONS = frozenset(("в", "во", "из", "до", "после", "перед"))

#: What follows a keyword of a query and not a word of prose: a parameter, a dotted name with
#: a capital, an underscored name, a bracket that opens a list or a subquery, an operator.
_CODE_AFTER = re.compile(
    r"^[&%]\w|[A-ZА-ЯЁ]\w*\.\w|\w\.[A-ZА-ЯЁ]|\w_\w|^\((?:[&%]|[A-ZА-ЯЁ]{2,}|\w+\.\w|\)|$)"
    r"|^(?:=|==|<>|!=|<|>|<=|>=)$"
)
#: An identifier with a capital inside: `КодСклада`, `authorizationCode`.
_CAMEL = re.compile(r"[a-zа-яё][A-ZА-ЯЁ]")
_TITLE_WORD = re.compile(r"^[A-ZА-ЯЁ][a-zа-яё]+[,.;:]?$")

_CAPS_WORD = re.compile(r"(?<![\w-])([А-ЯЁ]{2,})(?![\w-])")
#: What may stand between two words of one phrase in capitals: spaces and a dash.
_PHRASE_GAP = re.compile(r"[ \t\-\u2013\u2014]*")
_ANY_CAPS_WORD = re.compile(r"(?<![\w-])([A-ZА-ЯЁ]{2,})(?![\w-])")

#: The one-letter words of Russian: a preposition, a conjunction, a particle, a pronoun.
_LETTER_WORDS = "ВКСОУИАЯ"
_LETTER = re.compile(rf"(?<![\w-])([{_LETTER_WORDS}])(?![\w-])")
#: A negation written in capitals and glued to the word: `НЕзаполненным`, `НИкак`.
_NEGATION_PREFIX = re.compile(r"(?<![\w-])(НЕ|НИ)([а-яё]{3,})(?![\w-])")

#: A numbered point after the comment marker ("3.5 ", "1) ", "а) "): what follows opens a
#: sentence of its own.
_NUMBERING = re.compile(r"(?:\d+(?:\.\d+)*[.)]?|[а-яa-z]\))\s+")

#: What a comment cites rather than says: a quoted caption, a name in backticks, a placeholder
#: of a markup template.
_CITED = re.compile(r'"[^"\n]*"|\u00ab[^\u00bb\n]*\u00bb|`[^`\n]*`|\{\{[^}\n]*\}\}')

_VOWELS = frozenset("АЕЁИОУЫЭЮЯ")
_LOWER_WORD = re.compile(r"(?<![А-ЯЁа-яё])[а-яё]+(?![А-ЯЁа-яё])")
_CAMEL_NAME = re.compile(r"[А-ЯЁа-яё]*[а-яё][А-ЯЁ][А-ЯЁа-яё]*")
_TITLE_PART = re.compile(r"[А-ЯЁ][а-яё]+")


def _cited_blank(text: str, open_quote: bool) -> tuple[str, bool]:
    """The line with its citations blanked, and whether a double quote is left open.

    A quote may open on one comment line and close on the next, so the state of the double
    quote goes from line to line: a line that starts inside a quote is blank up to its closing
    mark, and a mark left without a pair blanks the rest of the line - a caption cited over a
    line break is not read for a capital. Blanks keep the offsets.
    """
    head = ""
    rest = text
    if open_quote:
        close = text.find('"')
        if close < 0:
            return " " * len(text), True
        head, rest = " " * (close + 1), text[close + 1:]
    rest = _CITED.sub(lambda m: " " * len(m.group(0)), rest)
    loose = rest.find('"')
    if loose >= 0:
        return head + rest[:loose] + " " * (len(rest) - loose), True
    return head + rest, False


def _body_start(prose: str) -> int:
    """Where the words of a comment line start: after the marker, a bullet and a number."""
    start = _comments.lead(prose)
    numbered = _NUMBERING.match(prose, start)
    return numbered.end() if numbered else start


def _cites_query(text: str) -> bool:
    return any(w in _QUERY_MARKERS for w in _ANY_CAPS_WORD.findall(text))


def _sentence_start(prose: str, index: int, previous: str | None) -> bool:
    """Whether the word at `index` of the comment line opens a sentence.

    A spot after a full stop, an exclamation or a question mark opens one. So does the start
    of the line's prose (after the marker, a bullet and a number) - unless the comment goes on
    from the line above (`previous`, its prose) and that line did not end its sentence: then
    the word continues the sentence and keeps a lower-case letter.
    """
    head = prose[_body_start(prose):index].rstrip()
    if head:
        return head[-1] in ".!?"
    if previous is None:
        return True
    tail = previous[_comments.lead(previous):].rstrip()
    return not tail or tail[-1] in ".!?"


def _file_words(source: SourceFile) -> tuple[list[str], frozenset[str]]:
    """(the words of the file in small letters, sorted; the parts of its camel-case names)."""
    key = "emphasis_caps_words"
    if key not in source.cache:
        text = source.text
        lower = sorted(set(_LOWER_WORD.findall(text)))
        parts = frozenset(
            part for name in _CAMEL_NAME.findall(text) for part in _TITLE_PART.findall(name)
        )
        source.cache[key] = (lower, parts)
    return source.cache[key]


def _written_small(word: str, lower: list[str]) -> bool:
    """Whether the file writes `word` (small letters) in some case form of its own.

    The stem drops the letters a case ending may take (none from a short word, one or two
    from a longer one), and a found word may add up to three letters of an ending to it.
    """
    size = len(word)
    stem = word if size <= 4 else word[:size - 1] if size <= 6 else word[:size - 2]
    ending = 0 if size <= 2 else 2 if size == 3 else 3
    index = bisect_left(lower, stem)
    while index < len(lower) and lower[index].startswith(stem):
        if len(lower[index]) - len(stem) <= ending:
            return True
        index += 1
    return False


def _shouted_word(word: str, source: SourceFile) -> bool:
    """Whether a word in capitals outside `_EMPHASIS` is an ordinary word written loudly.

    An abbreviation has the shape of a stressed word, and the file is what tells them apart,
    measured on seven corpora (the snapshot of one project before its sweep, two vendor
    libraries, a foreign project and three more): a word the file also writes in small
    letters ("ТЕКУЩИЙ" next to "текущий") is stressed; a word without a vowel (`ТЧ`, `ГГГГ`) is
    an abbreviation; a word of two vowels or more is stressed unless a camel-case name of the
    file carries it as a part - that is how the naming standard writes an abbreviation
    (`ОКПО` next to `КодОкпоСклада`), and a misspelled abbreviation keeps the letters of
    the part (`ОПКО` in the same file). Short words with one vowel (`ИТС`, `УНФ`, `ПРОФ`)
    count as stressed only when the file writes them in small letters.
    """
    vowels = sum(ch in _VOWELS for ch in word)
    if not vowels:
        return False
    lower, parts = _file_words(source)
    if _written_small(word.lower(), lower):
        return True
    if vowels < 2 or len(word) < 4:
        return False
    letters = sorted(word)
    return not any(sorted(part.upper()) == letters for part in parts if len(part) == len(word))


def _token_after(text: str, end: int) -> str:
    """The token right after `end`; words in capitals of the query language are looked past
    ("ГДЕ НЕ Удалён" looks at `Удалён`)."""
    after = text[end:].split()
    while after and after[0].strip(",.;:") in _QUERY_WORDS and after[0].isupper():
        after = after[1:]
    return after[0] if after else ""


def _code_around(text: str, end: int, opens: bool) -> bool:
    """Whether a query keyword is followed by code, which makes the keyword syntax.

    What stands after the keyword decides, not what stands before it: prose puts a word of its
    own after a stressed "НЕ" even when a name of the code stands before it
    ("ПересчётОстатков НЕ меняет"), and a query puts a name, a parameter or a bracket there
    ("Т.Поле В (&Список)", "Склады КАК Склады", "ГДЕ НЕ Удалён"). A name in title case counts
    as a field only where the keyword does not open a sentence; an annotation is not code of a
    query ("намеренно НЕ @ДоступноСКлиенту").
    """
    after = _token_after(text, end)
    if not after or after.startswith("@"):
        return False
    if _CODE_AFTER.search(after) or _CAMEL.search(after):
        return True
    before = text[:end].split()
    alias = after.strip(",.;:")
    if len(before) > 1 and alias and before[-2].split(".")[-1] == alias:
        return True  # an alias of the field before it: "Т.Код КАК Код"
    return _TITLE_WORD.match(after) is not None and not opens


def _query_syntax(word: str, text: str, start: int, end: int, opens: bool) -> bool:
    """Whether a keyword of the query language in capitals is cited rather than stressed.

    A word in capitals right before an opening bracket is a call of the language
    ("КОЛИЧЕСТВО(*)", "COUNT(*)") whatever the word is.
    """
    if word in _QUERY_FUNCTIONS or text[end:end + 1] == "(":
        return True
    if word not in _QUERY_WORDS:
        return False
    words_before = re.findall(r"[А-ЯЁа-яёA-Za-z]+", text[:start])
    previous = words_before[-1] if words_before else ""
    if previous.lower() in _QUERY_NOUNS:
        return True
    if word in _CLAUSE_WORDS and previous in _CLAUSE_PREPOSITIONS:
        return True
    following = re.match(r"\s*([A-Za-z]+)", text[end:])
    if following and following.group(1).lower() in _QUERY_NOUNS_ENGLISH:
        return True
    return _code_around(text, end, opens)


def _in_caps_phrase(text: str, words: list[re.Match], position: int, judged: list[bool]) -> bool:
    """Whether the word stands in a run of capitals holding a word the rule could not judge.

    The stress often falls on a phrase ("ПОД ПРАВАМИ ПОЛЬЗОВАТЕЛЯ"). A word of the run that
    looks like a word (two vowels, four letters) and still was not judged may be stressed as
    well, and lowering its neighbours alone would leave it shouting: such a finding carries
    no fix, and the phrase is rewritten by hand. An abbreviation in the run (`ИТС`) does not
    stop the fix - it stays in capitals by right.
    """
    first = last = position
    while first > 0 and _PHRASE_GAP.fullmatch(text, words[first - 1].end(), words[first].start()):
        first -= 1
    while last + 1 < len(words) and _PHRASE_GAP.fullmatch(
        text, words[last].end(), words[last + 1].start(),
    ):
        last += 1
    for index in range(first, last + 1):
        other = words[index].group(1)
        if judged[index]:
            continue
        if sum(ch in _VOWELS for ch in other) >= 2 and len(other) >= 4:
            return True
    return False


def _stressed_letter(text: str, match: re.Match, body: int, previous: str | None) -> bool:
    """Whether a one-letter word in capitals is stressed.

    Judged inside a sentence: after a word, a comma or a dash. Not judged where a capital is
    in its right: at the start of a sentence (after a full stop, a question or an exclamation
    mark, and at the start of a line whose line above ended its sentence), after a colon, a
    semicolon, a bracket or a quote; a letter with a full stop and a letter after it (`Т.к.`);
    an item of a list of names in title case ("Склады, Партии, О складе"); the operator of a
    cited query. At the start of a line that goes on from the line above only the conjunctions
    `И` and `А` are judged: a line of a list or of a parameter description starts with a
    preposition in capitals by right ("В остальных случаях ...").
    """
    letter, start, end = match.group(1), match.start(), match.end()
    head = text[body:start].rstrip()
    if not head:
        if previous is None or letter not in "ИА":
            return False
        tail = previous[_comments.lead(previous):].rstrip()
        if not tail or not (tail[-1].islower() or tail[-1] == ","):
            return False
    elif head[-1] in ".!?:;([\"'\u00ab":
        return False
    if re.match(r"\.\w|[:/\\]", text[end:end + 2]):
        return False  # `Т.к.`, a drive or a path
    if head.endswith(","):
        items = re.findall(r"[А-ЯЁа-яё]+", head)
        if items and _TITLE_WORD.match(items[-1]):
            item_start = body + head.rfind(items[-1])
            if not _sentence_start(text, item_start, None):
                return False
    return not _query_syntax(letter, text, start, end, opens=False)


def _emphasis_fix(offset: int, word: str, suggestion: str) -> TextEdit:
    return TextEdit(offset, offset + len(word), suggestion)


@rule(
    "comment/emphasis-caps", "comment/emphasis-caps.title", "B",
    severity=Severity.WARNING, enabled_by_default=False, off_reason="comment/emphasis-caps.off",
)
def emphasis_caps(source: SourceFile) -> Iterable[Diagnostic]:
    """A word, a letter or a prefix in capitals for emphasis; the fix restores the case."""
    before: _comments.CommentLine | None = None
    open_quote = False
    for cl in _comments.lines(source):
        adjacent = before is not None and before.line == cl.line - 1
        previous = before.text if adjacent else None
        before = cl
        text, open_quote = _cited_blank(cl.text, open_quote and adjacent)
        body = _body_start(text)
        if _cites_query(text) or not re.search(r"[а-яё]", text[body:]):
            # A cited query, or a line written in capitals from end to end: a heading or a
            # shout of the whole line, where no single word is stressed.
            continue
        yield from _caps_words(source, cl, text, previous)
        for m in _LETTER.finditer(text):
            if m.start() < body or not _stressed_letter(text, m, body, previous):
                continue
            lowered = m.group(1).lower()
            offset = cl.offset + m.start()
            yield Diagnostic(
                source.rel, cl.line, cl.column + m.start(), "comment/emphasis-caps",
                Severity.WARNING,
                i18n.t("comment/emphasis-caps.letter", word=m.group(1), suggestion=lowered),
                fix=_emphasis_fix(offset, m.group(1), lowered),
            )
        for m in _NEGATION_PREFIX.finditer(text):
            if m.start() < body:
                continue
            prefix = m.group(1)
            opens = _sentence_start(text, m.start(), previous)
            suggestion = (prefix.capitalize() if opens else prefix.lower()) + m.group(2)
            offset = cl.offset + m.start()
            yield Diagnostic(
                source.rel, cl.line, cl.column + m.start(), "comment/emphasis-caps",
                Severity.WARNING,
                i18n.t("comment/emphasis-caps.prefix", word=m.group(0), suggestion=suggestion),
                fix=_emphasis_fix(offset, m.group(0), suggestion),
            )
    yield from _english_emphasis(source)


def _caps_words(
    source: SourceFile, cl: _comments.CommentLine, text: str, previous: str | None,
) -> Iterable[Diagnostic]:
    """The words of two capitals or more on one comment line."""
    body = _body_start(text)
    words = [m for m in _CAPS_WORD.finditer(text) if m.start() >= body]
    judged: list[bool] = []
    opening: list[bool] = []
    for m in words:
        word = m.group(1)
        opens = _sentence_start(text, m.start(), previous)
        opening.append(opens)
        if _query_syntax(word, text, m.start(), m.end(), opens):
            judged.append(False)
            continue
        judged.append(word in _EMPHASIS or _shouted_word(word, source))
    for position, m in enumerate(words):
        if not judged[position]:
            continue
        word = m.group(1)
        lowered = word.lower()
        suggestion = lowered.capitalize() if opening[position] else lowered
        offset = cl.offset + m.start()
        fix = None if _in_caps_phrase(text, words, position, judged) else _emphasis_fix(
            offset, word, suggestion,
        )
        yield Diagnostic(
            source.rel, cl.line, cl.column + m.start(), "comment/emphasis-caps",
            Severity.WARNING,
            i18n.t("comment/emphasis-caps.found", word=word, suggestion=suggestion),
            fix=fix,
        )


# --- comment/emphasis-caps: the English line of a translated comment ------------------------
#
# A project that translates its sources keeps the English line of every comment as a `phrases`
# value of its `xbsl-translation` dictionary. A stressed Russian line is translated with its
# capitals ("ONE BY ONE" for "ПО ОДНОЙ"), and a translation may add capitals of its own.
# `translation/english-shape`, on by default, reports the capitals a key without stress does
# not have; this rule reports the rest - the capitals that came from a stressed key, the
# capital prefix and the article of a phrase in capitals - so a word is reported once.

#: English words that stress a turn rather than name a thing: those a translation shouted
#: after its key ("NOT", "ONE BY ONE", "IT IS", "AT the moment OF adding") and their kin. A
#: word that is also an abbreviation of the list of `translation/english-shape` (`ITS` stands
#: for a product there) is judged only inside a phrase in capitals ("of ITS OWN warehouse").
_ENGLISH_EMPHASIS = frozenset("""
NOT NO NON NONE NEVER ONLY ONE ONCE TWICE TWO BOTH EACH EVERY ALL ANY EITHER NEITHER
IS ARE WAS WERE BE BEEN DO DOES DID MUST SHOULD CAN CANNOT WILL WOULD
IN ON AT BY OF TO FROM INTO ONTO WITH WITHOUT WITHIN INSIDE OUTSIDE BEFORE AFTER ABOVE BELOW
UNDER OVER BETWEEN THROUGH UP DOWN OFF OUT PER VIA AS
AND OR BUT NOR IF THEN ELSE WHEN WHERE WHY HOW WHAT WHO WHICH
THE AN IT ITS THIS THAT THESE THOSE SAME OTHER OWN
ALREADY ALWAYS STILL YET EVEN JUST VERY ALSO TOO AGAIN HERE THERE NOW FIRST LAST
""".split())

#: A word of capitals in an English line. A hyphen may follow ("NON-stretched").
_ENGLISH_CAPS = re.compile(r"(?<![A-Za-z0-9_-])[A-Z]{2,}(?![A-Za-z0-9_])")
#: A query cited in an English line: these keywords are never a stressed word of prose.
_ENGLISH_QUERY_MARKERS = frozenset((
    "SELECT", "JOIN", "UNION", "EXISTS", "ISNULL", "DISTINCT", "HAVING", "NULL",
))
#: A word in capitals of the key; a hyphen or a colon may touch it ("1С:ИТС", "ИТС-подписка").
_KEY_CAPS = re.compile(r"(?<![А-ЯЁа-яё])[А-ЯЁ]{2,}(?![А-ЯЁа-яё])")
#: The article of a phrase in capitals: "AS A value", "NOT A single".
_ENGLISH_ARTICLE = re.compile(r"(?<![A-Za-z0-9_-])A(?![A-Za-z0-9_-])")
#: A prefix written in capitals and glued to the word: "UNfilled", "NONempty".
_ENGLISH_PREFIX = re.compile(
    r"(?<![A-Za-z0-9_-])(UN|NON|DIS|MIS|RE|PRE|IN|IM|IL|IR|OVER|UNDER|ANTI|SEMI|SUB|SUPER)"
    r"([a-z]{3,})(?![A-Za-z0-9_])"
)
#: A mask of a date or a time (`YYYY`, `HH:MM` - the letters only) and a color in hex.
_MASK = re.compile(r"(?:YYYY|YY|MM|DD|HH|SS|MMMM)+|[A-F]{6}|[A-F]{8}")
_LATIN_VOWELS = frozenset("AEIOU")

#: How a Cyrillic letter of an abbreviation is spelled in Latin, for a name the translation
#: carries over (`ПРОФ` - `PROF`, `КОРП` - `CORP`, `ИТС` - `ITS`).
_TRANSLIT = {
    "А": "A", "Б": "B", "В": "V", "Г": "G", "Д": "D", "Е": "E", "Ё": "(?:E|YO)", "Ж": "(?:ZH|J)",
    "З": "Z", "И": "I", "Й": "(?:Y|I|J)", "К": "(?:K|C)", "Л": "L", "М": "M", "Н": "N", "О": "O",
    "П": "P", "Р": "R", "С": "S", "Т": "T", "У": "U", "Ф": "F", "Х": "(?:KH|H|X)",
    "Ц": "(?:TS|C|TZ)", "Ч": "CH", "Ш": "SH", "Щ": "(?:SHCH|SCH)", "Ъ": "", "Ы": "(?:Y|I)",
    "Ь": "", "Э": "E", "Ю": "(?:YU|IU|JU|U)", "Я": "(?:YA|IA|JA)",
}


def _transliterates(cyrillic: str, latin: str) -> bool:
    pattern = "".join(_TRANSLIT.get(ch, re.escape(ch)) for ch in cyrillic)
    return re.fullmatch(pattern, latin) is not None


def _english_word_shaped(word: str) -> bool:
    """Two vowels in four letters or more: `PARENT`, `TABLE` - not `SM`, `DBMS`, `LLC`."""
    vowels = sum(ch in _LATIN_VOWELS or (ch == "Y" and index > 0) for index, ch in enumerate(word))
    return vowels >= 2 and len(word) >= 4


def _russian_name_shaped(word: str) -> bool:
    """A Cyrillic word in capitals of the key that looks like an abbreviation rather than a
    stressed word: no two vowels in four letters, and not a function word."""
    if word in _EMPHASIS:
        return False
    return not (sum(ch in _VOWELS for ch in word) >= 2 and len(word) >= 4)


def _english_suggestion(value: str, start: int, word: str, key: str) -> str:
    """The word in small letters, or with a capital where it opens a sentence of the line.

    At the start of the value the key tells whether the line opens a sentence: a key that
    starts with a small letter goes on from the line above, and so does a key that starts
    with the conjunction `И` or `А` in capitals ("И фон строки" continues "красит рамку") -
    a preposition there opens a sentence as often as not.
    """
    lowered = word.lower()
    if not _opens_sentence(value, start):
        return lowered
    if re.search(r"[.!?]", value[:start]):
        return lowered.capitalize()
    first = re.search(r"[А-ЯЁа-яёA-Za-z]+", key)
    if first is None:
        return lowered.capitalize()
    head = first.group(0)
    if head[0].islower() or head in ("И", "А"):
        return lowered
    return lowered.capitalize()


def _value_offset(source: SourceFile, node, needle: str, start: int) -> int | None:
    """File offset of the occurrence of `needle` at `start` of a scalar's value, or None when
    the raw scalar does not hold the same occurrences (a value folded over lines)."""
    in_value = _occurrences(node.value, needle, True)
    raw = source.text[node.start_mark.index:node.end_mark.index]
    in_raw = _occurrences(raw, needle, True)
    if len(in_raw) != len(in_value) or start not in in_value:
        return None
    return node.start_mark.index + in_raw[in_value.index(start)]


def _english_emphasis(source: SourceFile) -> Iterable[Diagnostic]:
    """Capitals of emphasis in the `phrases` values of a translation dictionary file."""
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
        key, value = key_node.value, value_node.value
        for word, start, suggestion in _english_findings(key, value):
            line, column = _position(source, value_node, word, start, True)
            offset = _value_offset(source, value_node, word, start)
            fix = None if offset is None else TextEdit(offset, offset + len(word), suggestion)
            yield Diagnostic(
                source.rel, line, column, "comment/emphasis-caps", Severity.WARNING,
                i18n.t("comment/emphasis-caps.english", word=word, suggestion=suggestion),
                fix=fix,
            )


def _key_cites_query(key: str) -> bool:
    """Whether the Russian line cites a query keyword - then its translation cites it too."""
    text = _CITED.sub(lambda m: " " * len(m.group(0)), key)
    if _cites_query(text):
        return True
    for m in _ANY_CAPS_WORD.finditer(text):
        if _query_syntax(m.group(1), text, m.start(), m.end(), opens=False):
            return True
    return any(
        _query_syntax(m.group(1), text, m.start(), m.end(), opens=False)
        for m in _LETTER.finditer(text)
    )


def _english_findings(key: str, value: str) -> list[tuple[str, int, str]]:
    """(the word as written, its offset in the value, the suggestion) for one pair."""
    text = _CITED.sub(lambda m: " " * len(m.group(0)), value)
    if not re.search(r"[a-z]", text):
        return []  # a heading in capitals from end to end: no single word is stressed
    if any(word in _ENGLISH_QUERY_MARKERS for word in _ENGLISH_CAPS.findall(text)):
        return []
    owned = {start for _word, start in _caps_findings("phrases", key, value)}
    key_latin = _key_words(key)
    key_caps = _KEY_CAPS.findall(key)
    key_names = [word for word in key_caps if _russian_name_shaped(word)]
    key_query = _key_cites_query(key)
    candidates: list[tuple[re.Match, bool]] = []
    stressed: list[tuple[int, int]] = []
    for m in _ENGLISH_CAPS.finditer(text):
        word, start = m.group(0), m.start()
        if start in owned:
            stressed.append((start, m.end()))  # reported by translation/english-shape
            continue
        if word.lower() in key_latin or _MASK.fullmatch(word) or text[start - 1:start] == "#":
            continue
        if any(_transliterates(name, word) for name in key_caps):
            continue
        following = re.match(r"\s*([A-Za-z]+)", text[m.end():])
        if text[m.end():m.end() + 1] == "(" or (word in _QUERY_WORDS and (
            key_query or (following and following.group(1).lower() in _QUERY_NOUNS_ENGLISH)
        )):
            continue
        if word not in _ENGLISH_EMPHASIS:
            if word in _ABBREVIATIONS:
                continue
            if key_names and not _english_word_shaped(word):
                continue  # the translation of an abbreviation of the key: `FRC` for `ЦФО`
        # A pronoun that is also a product abbreviation counts only inside a phrase of capitals;
        # alone it is the product ("the contract number, ITS").
        candidates.append((m, word in _ABBREVIATIONS))
        stressed.append((start, m.end()))

    def next_to_stress(begin: int, end: int) -> bool:
        return any(
            (other_end < begin and _PHRASE_GAP.fullmatch(text, other_end, begin))
            or (other_begin > end and _PHRASE_GAP.fullmatch(text, end, other_begin))
            for other_begin, other_end in stressed
        )

    found: list[tuple[str, int, str]] = []
    for m, in_phrase_only in candidates:
        if in_phrase_only and not next_to_stress(m.start(), m.end()):
            continue
        word, start = m.group(0), m.start()
        found.append((word, start, _english_suggestion(value, start, word, key)))
    for m in _ENGLISH_ARTICLE.finditer(text):
        if next_to_stress(m.start(), m.end()):
            found.append(("A", m.start(), _english_suggestion(value, m.start(), "A", key)))
    for m in _ENGLISH_PREFIX.finditer(text):
        suggestion = _english_suggestion(value, m.start(), m.group(1), key) + m.group(2)
        found.append((m.group(0), m.start(), suggestion))
    return sorted(found, key=lambda item: item[1])
