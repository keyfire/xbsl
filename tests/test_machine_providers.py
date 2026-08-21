import json

from xbsl.translation.machine.yandex import Yandex
from xbsl.translation.machine.google import Google


def test_yandex_builds_the_request():
    provider = Yandex(env={"XBSL_TRANSLATE_YANDEX_KEY": "k1", "XBSL_TRANSLATE_YANDEX_FOLDER": "f1"})
    request = provider.request(["АдресСайта"], target="en", source="ru", glossary=())
    assert request.url == "https://translate.api.cloud.yandex.net/translate/v2/translate"
    body = json.loads(request.body.decode("utf-8"))
    assert body["folderId"] == "f1"
    assert body["texts"] == ["АдресСайта"]
    assert body["targetLanguageCode"] == "en"


def test_yandex_parses_the_answer_in_order():
    provider = Yandex(env={})
    body = '{"translations": [{"text": "Site address"}, {"text": "Order"}]}'
    assert provider.parse(body) == ["Site address", "Order"]


def test_yandex_needs_both_key_and_folder():
    assert not Yandex(env={"XBSL_TRANSLATE_YANDEX_KEY": "k1"}).configured()
    assert Yandex(env={"XBSL_TRANSLATE_YANDEX_KEY": "k1", "XBSL_TRANSLATE_YANDEX_FOLDER": "f1"}).configured()


def test_yandex_authorizes_with_the_api_key_scheme_not_a_header_of_that_name():
    """`Api-Key` is the AUTHORIZATION SCHEME, not the name of a header.

    Yandex Cloud reads `Authorization: Api-Key <key>`; a header literally called `Api-Key` is
    a name nobody on the other side knows, and the service answers 401 to every batch. The
    first version of this module invented exactly that, and the test that stood here asserted
    the invention instead of the contract.
    """
    provider = Yandex(env={"XBSL_TRANSLATE_YANDEX_KEY": "k1", "XBSL_TRANSLATE_YANDEX_FOLDER": "f1"})
    request = provider.request(["Заказ"], target="en", source="ru", glossary=())
    assert "Api-Key" not in request.headers
    scheme, _, key = request.headers["Authorization"].partition(" ")
    assert scheme == "Api-Key"
    assert key == "k1"
    assert "k1" not in request.url


def test_both_providers_state_the_answer_format_they_expect():
    yandex = Yandex(env={"XBSL_TRANSLATE_YANDEX_KEY": "k1", "XBSL_TRANSLATE_YANDEX_FOLDER": "f1"})
    google = Google(env={"XBSL_TRANSLATE_GOOGLE_KEY": "k2"})
    for provider in (yandex, google):
        request = provider.request(["Заказ"], target="en", source="ru", glossary=())
        assert request.headers["Accept"] == "application/json"


def test_google_puts_the_key_in_a_header_not_in_the_url():
    provider = Google(env={"XBSL_TRANSLATE_GOOGLE_KEY": "k2"})
    request = provider.request(["Заказ"], target="en", source="ru", glossary=())
    assert request.url == "https://translation.googleapis.com/language/translate/v2"
    assert request.headers["X-goog-api-key"] == "k2"
    assert "Authorization" not in request.headers  # google names its own header, no scheme
    assert "k2" not in request.url  # a query parameter would end up in proxy logs


def test_google_parses_the_nested_answer():
    body = '{"data": {"translations": [{"translatedText": "Order"}]}}'
    assert Google(env={}).parse(body) == ["Order"]


def test_google_needs_no_folder_and_has_no_glossary():
    provider = Google(env={"XBSL_TRANSLATE_GOOGLE_KEY": "k2"})
    assert provider.configured()
    assert not provider.supports_glossary()
    assert provider.batch_limit() == 5000


def test_yandex_request_carries_the_glossary_pairs_in_order():
    provider = Yandex(env={"XBSL_TRANSLATE_YANDEX_KEY": "k1", "XBSL_TRANSLATE_YANDEX_FOLDER": "f1"})
    glossary = [("Заказ", "Order"), ("Товар", "Item")]
    request = provider.request(["Текст"], target="en", source="ru", glossary=glossary)
    body = json.loads(request.body.decode("utf-8"))
    pairs = body["glossaryConfig"]["glossaryData"]["glossaryPairs"]
    assert pairs == [
        {"sourceText": "Заказ", "translatedText": "Order"},
        {"sourceText": "Товар", "translatedText": "Item"},
    ]


def test_yandex_request_has_no_glossary_config_when_the_glossary_is_empty():
    provider = Yandex(env={"XBSL_TRANSLATE_YANDEX_KEY": "k1", "XBSL_TRANSLATE_YANDEX_FOLDER": "f1"})
    request = provider.request(["Текст"], target="en", source="ru", glossary=())
    body = json.loads(request.body.decode("utf-8"))
    assert "glossaryConfig" not in body


def test_google_request_ignores_the_glossary_entirely():
    provider = Google(env={"XBSL_TRANSLATE_GOOGLE_KEY": "k2"})
    glossary = [("Заказ", "Order")]
    request = provider.request(["Текст"], target="en", source="ru", glossary=glossary)
    body = json.loads(request.body.decode("utf-8"))
    assert "glossaryConfig" not in body
    assert set(body) == {"q", "target", "source", "format"}
