"""A rule that is off by default has to say WHY, right where the reader looks.

The guard exists because a bare `off` in `--list-rules` tells the reader nothing: the reason
used to live in three unrelated places – the rule's docstring, a column in `docs/RULES.md` and
somebody's backlog – and none of them is the listing. The user of the toolkit hit exactly this:
"part of the rules is disabled and I do not understand why".
"""

from __future__ import annotations

import pytest

from xbsl import engine, i18n


def _own():
    """Правила САМОГО движка.

    В реестре могут лежать и правила надстроек – их автор отвечает за свои тексты сам,
    и падение здесь означало бы, что набор движка зависит от установленных плагинов.
    Свои узнаём по модулю, в котором объявлена функция правила.
    """
    return [r for r in engine.RULES if getattr(r.func, "__module__", "").startswith("xbsl.")]


def _disabled():
    return [r for r in _own() if not r.enabled_by_default]


def test_there_are_disabled_rules():
    """Without this the rest of the file would pass on an empty set."""
    assert _disabled(), "ни одно правило не выключено – проверьте загрузку реестра"


@pytest.mark.parametrize("lang", ("ru", "en"))
def test_every_disabled_rule_explains_itself(lang):
    i18n.set_lang(lang)
    try:
        silent = [r.id for r in _disabled() if not r.off_reason_text.strip()]
        assert not silent, (
            "выключенные правила без причины: %s. Добавьте off_reason= в регистрацию и текст "
            "в каталог – иначе читатель видит 'off' и не понимает, сломано правило, шумит "
            "или просто не про него" % silent
        )
    finally:
        i18n.set_lang("ru")


def test_reason_is_translated_not_a_bare_key():
    """A missing catalog entry comes back as the key itself – that must not pass for a reason."""
    for r in _disabled():
        assert r.off_reason_text != r.off_reason, (
            "у правила %s причина не переведена: в каталоге нет записи '%s'" % (r.id, r.off_reason)
        )


def test_enabled_rule_reports_no_reason():
    """The reason is about being off; an enabled rule must not carry one."""
    for r in _own():
        if r.enabled_by_default:
            assert r.off_reason_text == "", (
                "правило %s включено, но объясняет, почему выключено" % r.id
            )


def test_reason_reaches_the_machine_readable_listing():
    """MCP and the editor read as_dict(), so the reason has to travel there too."""
    for r in _disabled():
        assert r.as_dict()["off_reason"] == r.off_reason_text
    for r in _own():
        if r.enabled_by_default:
            assert r.as_dict()["off_reason"] == ""
