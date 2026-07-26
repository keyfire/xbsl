"""Tier B: secrets hardcoded into the sources.

A key pasted into a constant ships with the code: it lands in the repository, in every clone
and in the build - and rotating it means a new release. The platform has a place for such
values (`Параметры` / the settings of the deployed application), and the working sources use
it - `Параметры.ПолучитьПараметр(ИмяПараметраСерверногоКлюча)`, with the literal only as a
fallback default. This rule is about that fallback being a live key.

Telling a secret from an ordinary string is the whole difficulty: one file may hold both

    конст СерверныйКлючКапчи = "ysc2_<48 random characters>"        <- a live key
    конст ИмяПараметраСерверногоКлюча = "СмартКапча.СерверныйКлюч"  <- the name of a setting

and name both of them "ключ". So the name alone never fires; a finding needs the VALUE to
look like a secret too - or to carry a vendor prefix, which is proof by itself:

  * a name that speaks of a secret (ключ/секрет/пароль/токен/key/secret/password/token/...)
    AND a value shaped like one: long, ASCII, mixing case and digits;
  * or a value with a known vendor prefix (ysc2_, sk_live_, AKIA..., ghp_, xox*-), whatever
    the name is.

Deliberately NOT reported, to keep the rule free of false positives: a value with any
Cyrillic, a URL, a dotted name, an all-lowercase or all-uppercase string, anything shorter
than 16 characters, and a placeholder like "xxx" / "changeme".
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from xbsl import i18n
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, rule
from xbsl.lexer import tokens

MESSAGES = {
    "security/hardcoded-secret.title": {
        "ru": "Секрет в исходном коде",
        "en": "A secret in the sources",
    },
    "security/hardcoded-secret.found": {
        "ru": "Похоже на секрет в литерале ('{name}'). Ключи и пароли хранятся в параметрах "
              "приложения (Параметры.ПолучитьПараметр), а не в коде: литерал уезжает в "
              "репозиторий и в сборку, а смена ключа требует релиза.",
        "en": "This literal looks like a secret ('{name}'). Keys and passwords belong in the "
              "application settings ({n[Параметры.ПолучитьПараметр]}), not in the code: a literal "
              "ships with the repository and the build, and rotating it needs a release.",
    },
    "security/hardcoded-secret.vendor": {
        "ru": "Секрет в литерале: префикс '{prefix}' – это ключ {vendor}. Хранить в параметрах "
              "приложения (Параметры.ПолучитьПараметр); если ключ уже в репозитории, его "
              "недостаточно убрать из кода – он скомпрометирован и подлежит отзыву.",
        "en": "A secret literal: the '{prefix}' prefix is a {vendor} key. Keep it in the "
              "application settings ({n[Параметры.ПолучитьПараметр]}); a key already committed is "
              "compromised - removing it from the code is not enough, it has to be revoked.",
    },
}
i18n.register(MESSAGES)

# A name that promises a secret. The name is split into its CamelCase parts and each part is
# weighed on its own - "СерверныйКлючКапчи" holds the word "Ключ", while "КлючеваяСтавка"
# merely starts with the same letters and is not about keys at all.
_SECRET_WORDS = (
    "ключ", "секрет", "пароль", "токен",
    "key", "secret", "password", "passwd", "token", "apikey", "credential",
)
_NAME_PARTS = re.compile(r"[A-ZА-ЯЁ]?[a-zа-яё0-9]+|[A-ZА-ЯЁ]+(?![a-zа-яё])")
# A Russian part may carry an inflection ("Ключа", "Токеном"); a couple of trailing letters
# still means the same word, four of them ("Ключевая") mean another one.
_MAX_INFLECTION = 2


def _is_secret_word(part: str) -> bool:
    word = part.lower()
    return any(
        word == w or (word.startswith(w) and len(word) - len(w) <= _MAX_INFLECTION)
        for w in _SECRET_WORDS
    )


def _name_promises_secret(name: str) -> bool:
    return any(_is_secret_word(p) for p in _NAME_PARTS.findall(name))

# Vendor prefixes are proof on their own - the format is documented and unique to the issuer.
_VENDORS = (
    ("ysc1_", "Яндекс SmartCaptcha (клиентский)"),
    ("ysc2_", "Яндекс SmartCaptcha (серверный)"),
    ("sk_live_", "Stripe"),
    ("sk_test_", "Stripe"),
    ("rk_live_", "Stripe"),
    ("AKIA", "AWS"),
    ("ASIA", "AWS"),
    ("ghp_", "GitHub"),
    ("gho_", "GitHub"),
    ("ghs_", "GitHub"),
    ("github_pat_", "GitHub"),
    ("glpat-", "GitLab"),
    ("xoxb-", "Slack"),
    ("xoxp-", "Slack"),
    ("xoxa-", "Slack"),
    ("AIza", "Google"),
    ("ya29.", "Google OAuth"),
    ("SG.", "SendGrid"),
    ("y0_", "Яндекс OAuth"),
)

_MIN_LENGTH = 16
# The alphabet secrets are written in. Cyrillic in a value means prose or a setting name,
# never a key.
_SECRET_ALPHABET = re.compile(r"^[A-Za-z0-9_+/=.\-]+$")
# Obvious non-secrets that fit the shape: a stand-in the author left on purpose.
_PLACEHOLDERS = re.compile(
    r"^(?:x+|X+|\.+|-+|_+|0+|changeme|placeholder|your[_-]?\w*|todo|none|null|empty)$",
    re.IGNORECASE,
)


def _vendor_of(value: str) -> tuple[str, str] | None:
    for prefix, vendor in _VENDORS:
        # A prefix alone is not a key - there has to be a body after it.
        if value.startswith(prefix) and len(value) >= len(prefix) + 8:
            return prefix, vendor
    return None


def _looks_like_secret(value: str) -> bool:
    """A random-looking string: long, ASCII, and mixing character classes.

    The three signals together are what separates a key from the strings that surround it in
    real code - a header name, a content type, a url, a dotted setting name, a UUID.
    """
    if len(value) < _MIN_LENGTH or _PLACEHOLDERS.match(value):
        return False
    if not _SECRET_ALPHABET.match(value):
        return False
    if "://" in value or value.count(".") >= 2 or value.count("/") >= 2:
        return False  # a url or a path
    classes = (
        bool(re.search(r"[a-z]", value))
        + bool(re.search(r"[A-Z]", value))
        + bool(re.search(r"[0-9]", value))
    )
    return classes >= 3


def _string_value(raw: str) -> str | None:
    """The text of a STRING token, or None if it is not a plain literal.

    An interpolated string ("secret=%{Секрет}") is a template, not a value - and it is how the
    secret is USED, which is exactly right and must not be reported.
    """
    if len(raw) < 2 or not raw.startswith('"') or not raw.endswith('"'):
        return None
    body = raw[1:-1]
    if "%{" in body or "${" in body or "%" in body or "$" in body:
        return None
    return body


@rule("security/hardcoded-secret", "security/hardcoded-secret.title", "B", severity=Severity.ERROR)
def hardcoded_secret(source: SourceFile) -> Iterable[Diagnostic]:
    if source.kind != "xbsl":
        return
    # `конст|знч|пер ИМЯ = "..."` and a bare `ИМЯ = "..."`: keep the last identifier seen
    # before an `=`, then look at the string that follows it.
    name = ""
    after_assign = False
    for token in tokens(source):
        if token.kind == "IDENT":
            name, after_assign = token.value, False
            continue
        if token.kind == "OP" and token.value == "=":
            after_assign = bool(name)
            continue
        if token.kind == "STRING" and after_assign:
            after_assign = False
            value = _string_value(token.value)
            if value is None:
                continue
            vendor = _vendor_of(value)
            if vendor:
                yield Diagnostic(
                    source.rel, token.line, token.col, "security/hardcoded-secret", Severity.ERROR,
                    i18n.t("security/hardcoded-secret.vendor", prefix=vendor[0], vendor=vendor[1]),
                )
            elif _name_promises_secret(name) and _looks_like_secret(value):
                yield Diagnostic(
                    source.rel, token.line, token.col, "security/hardcoded-secret", Severity.ERROR,
                    i18n.t("security/hardcoded-secret.found", name=name),
                )
            continue
        if token.kind != "COMMENT":
            after_assign = False
