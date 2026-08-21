import pytest

from xbsl.translation.machine.provider import MachineError, select


def test_named_provider_wins():
    assert select("google", {"XBSL_TRANSLATE_GOOGLE_KEY": "k"}).code() == "google"


def test_the_only_configured_one_is_google():
    assert select(None, {"XBSL_TRANSLATE_GOOGLE_KEY": "k"}).code() == "google"


def test_the_only_configured_one_is_yandex():
    assert select(None, {"XBSL_TRANSLATE_YANDEX_KEY": "k", "XBSL_TRANSLATE_YANDEX_FOLDER": "f"}).code() == "yandex"


def test_nothing_configured_is_a_named_refusal():
    with pytest.raises(MachineError) as error:
        select(None, {})
    text = str(error.value)
    assert "XBSL_TRANSLATE_GOOGLE_KEY" in text and "XBSL_TRANSLATE_YANDEX_KEY" in text


def test_two_configured_without_a_choice_refuses_and_names_both():
    with pytest.raises(MachineError) as error:
        select(None, {"XBSL_TRANSLATE_GOOGLE_KEY": "k", "XBSL_TRANSLATE_YANDEX_KEY": "k", "XBSL_TRANSLATE_YANDEX_FOLDER": "f"})
    text = str(error.value)
    assert "yandex" in text and "google" in text


def test_a_named_yandex_without_its_key_refuses_before_any_request():
    """An explicit --provider must not skip the check the autopick does: no key, no request."""
    with pytest.raises(MachineError) as error:
        select("yandex", {})
    text = str(error.value)
    assert "XBSL_TRANSLATE_YANDEX_KEY" in text and "XBSL_TRANSLATE_YANDEX_FOLDER" in text


def test_a_named_google_without_its_key_refuses_before_any_request():
    with pytest.raises(MachineError) as error:
        select("google", {})
    assert "XBSL_TRANSLATE_GOOGLE_KEY" in str(error.value)


def test_a_half_configured_yandex_names_only_what_is_missing():
    """Yandex needs two variables; the refusal must point at the one that is not set."""
    with pytest.raises(MachineError) as error:
        select("yandex", {"XBSL_TRANSLATE_YANDEX_KEY": "k"})
    text = str(error.value)
    assert "XBSL_TRANSLATE_YANDEX_FOLDER" in text
    assert "XBSL_TRANSLATE_YANDEX_KEY" not in text
