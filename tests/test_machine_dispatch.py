import json
from pathlib import Path
from typing import Sequence

from xbsl.translation.entries import Gap
from xbsl.translation.machine.cache import Cache
from xbsl.translation.machine.dispatch import suggest
from xbsl.translation.machine.provider import Request
from xbsl.translation.machine.yandex import Yandex

YANDEX = Yandex(env={"XBSL_TRANSLATE_YANDEX_KEY": "k", "XBSL_TRANSLATE_YANDEX_FOLDER": "f"})


def scripted_transport(answers: list[list[str]]):
    """A transport that answers from a script and records what it was asked."""
    calls: list[list[str]] = []

    def transport(request):
        body = json.loads(request.body.decode("utf-8"))
        calls.append(body["texts"])
        return json.dumps({"translations": [{"text": text} for text in answers.pop(0)]})

    transport.calls = calls
    return transport


class FakeProvider:
    """A minimal provider stub for testing the DISPATCHER's own logic in isolation.

    It answers "Ok <length>" for whatever it is asked, and records the glossary and the
    batches it was given - so a test can assert what the dispatcher decided to pass along,
    independently of what any real provider (which may ignore or always accept a glossary)
    would do on its own. The stand-in answer is Latin on purpose: an answer that kept the
    Cyrillic is exactly what the dispatcher now refuses, so a Cyrillic stub would test the
    refusal instead of the path it was written for.
    """

    def __init__(self, supports_glossary: bool = True, batch_limit: int = 10000,
                 texts_limit: int = 100):
        self._supports_glossary = supports_glossary
        self._batch_limit = batch_limit
        self._texts_limit = texts_limit
        self.seen_glossary: Sequence[tuple[str, str]] | None = None
        self.batches: list[list[str]] = []

    def code(self) -> str:
        return "fake"

    def configured(self) -> bool:
        return True

    def batch_limit(self) -> int:
        return self._batch_limit

    def texts_limit(self) -> int:
        return self._texts_limit

    def supports_glossary(self) -> bool:
        return self._supports_glossary

    def request(self, texts, target, source, glossary):
        self.seen_glossary = glossary
        self.batches.append(list(texts))
        return Request(url="fake://", headers={},
                        body=json.dumps({"texts": list(texts)}, ensure_ascii=False).encode("utf-8"))

    def parse(self, body: str) -> list[str]:
        data = json.loads(body)
        return ["Ok " + str(len(text)) for text in data["texts"]]


def echo_transport(request):
    """Return the request body verbatim, so FakeProvider.parse sees exactly what was sent."""
    return request.body.decode("utf-8")


# --- the five scenarios from the brief -------------------------------------------------

def test_same_text_is_asked_once(tmp_path: Path):
    gaps = [Gap(key="Заказ", kind="token"), Gap(key="Заказ", kind="phrase")]
    transport = scripted_transport([["Order"]])
    result = suggest(gaps, YANDEX, Cache(tmp_path / "c.json"), (), transport, set())
    assert transport.calls == [["Заказ"]]
    assert result.requested == 1


def test_second_run_takes_everything_from_the_cache(tmp_path: Path):
    path = tmp_path / "c.json"
    cache = Cache(path)
    suggest([Gap(key="Заказ", kind="token")], YANDEX, cache, (), scripted_transport([["Order"]]), set())
    cache.save()

    transport = scripted_transport([])
    result = suggest([Gap(key="Заказ", kind="token")], YANDEX, Cache(path), (), transport, set())
    assert transport.calls == []
    assert result.cached == 1 and result.requested == 0
    assert result.values[("token", "Заказ")] == "Order"


def test_a_rejected_suggestion_still_costs_nothing_next_time(tmp_path: Path):
    path = tmp_path / "c.json"
    cache = Cache(path)
    suggest([Gap(key="Заказ", kind="token")], YANDEX, cache, (), scripted_transport([["Order"]]), set())
    cache.save()  # nobody accepted anything - the cache is kept anyway
    transport = scripted_transport([])
    suggest([Gap(key="Заказ", kind="token")], YANDEX, Cache(path), (), transport, set())
    assert transport.calls == []


def test_a_refusal_is_not_cached(tmp_path: Path):
    path = tmp_path / "c.json"
    cache = Cache(path)

    def failing_transport(request):
        raise RuntimeError("503")

    result = suggest([Gap(key="Заказ", kind="token")], YANDEX, cache, (), failing_transport, set())
    cache.save()  # the file is written on purpose: an unsaved cache could not prove anything

    assert result.values == {}
    assert result.refused
    assert path.exists()
    assert json.loads(path.read_text(encoding="utf-8")) == {}
    assert Cache(path).get("yandex", "ru", "en", "", "Заказ") is None


def test_a_token_becomes_an_identifier_and_a_phrase_stays_prose(tmp_path: Path):
    gaps = [Gap(key="АдресСайта", kind="token"), Gap(key="Адрес сайта.", kind="phrase")]
    transport = scripted_transport([["Site address", "Site address."]])
    result = suggest(gaps, YANDEX, Cache(tmp_path / "c.json"), (), transport, set())
    assert result.values[("token", "АдресСайта")] == "SiteAddress"
    assert result.values[("phrase", "Адрес сайта.")] == "Site address."


# --- review round 1: four fixes ---------------------------------------------------------

def test_same_text_as_token_and_phrase_each_get_their_own_suggestion(tmp_path: Path):
    """A name and a one-word comment sharing the same source text must not overwrite each other."""
    gaps = [Gap(key="Заказ", kind="token"), Gap(key="Заказ", kind="phrase")]
    transport = scripted_transport([["Order"]])
    result = suggest(gaps, YANDEX, Cache(tmp_path / "c.json"), (), transport, set())
    assert result.values[("token", "Заказ")] == "Order"
    assert result.values[("phrase", "Заказ")] == "Order"


def test_a_short_answer_refuses_the_whole_batch_and_caches_nothing(tmp_path: Path):
    """The service answering fewer translations than asked must not be split silently by zip."""
    provider = FakeProvider()
    gaps = [Gap(key="Заказ", kind="token"), Gap(key="Товар", kind="token")]
    path = tmp_path / "c.json"
    cache = Cache(path)

    def dropping_transport(request):
        body = json.loads(request.body.decode("utf-8"))
        body["texts"] = body["texts"][:-1]  # the service answers one short
        return json.dumps(body)

    result = suggest(gaps, provider, cache, (), dropping_transport, set())
    cache.save()

    assert result.values == {}
    assert set(result.refused) == {("token", "Заказ"), ("token", "Товар")}
    for reason in result.refused.values():
        assert "2" in reason and "1" in reason  # 2 texts sent, 1 translation returned

    reloaded = Cache(path)
    assert reloaded.get("fake", "ru", "en", "", "Заказ") is None
    assert reloaded.get("fake", "ru", "en", "", "Товар") is None


def test_empty_gap_list_touches_nothing(tmp_path: Path):
    provider = FakeProvider()
    result = suggest([], provider, Cache(tmp_path / "c.json"), (), echo_transport, set())
    assert result.values == {} and result.refused == {}
    assert result.cached == 0 and result.requested == 0
    assert provider.batches == []


def test_text_exactly_at_the_limit_is_sent_whole(tmp_path: Path):
    provider = FakeProvider(batch_limit=len("Заказ"))
    gaps = [Gap(key="Заказ", kind="phrase")]
    result = suggest(gaps, provider, Cache(tmp_path / "c.json"), (), echo_transport, set())
    assert provider.batches == [["Заказ"]]
    assert result.refused == {}
    assert result.values[("phrase", "Заказ")] == "Ok 5"


def test_text_longer_than_the_limit_is_refused_without_being_sent(tmp_path: Path):
    provider = FakeProvider(batch_limit=len("Заказ") - 1)
    gaps = [Gap(key="Заказ", kind="token")]
    result = suggest(gaps, provider, Cache(tmp_path / "c.json"), (), echo_transport, set())
    assert provider.batches == []  # never sent - it could not possibly fit
    assert result.values == {}
    reason = result.refused[("token", "Заказ")]
    assert str(len("Заказ")) in reason
    assert str(len("Заказ") - 1) in reason


def test_glossary_reaches_the_provider_only_when_the_dispatcher_lets_it_through(tmp_path: Path):
    """A fake provider proves the DISPATCHER's own gate, not a real provider's own behavior."""
    glossary = [("Заказ", "Order")]
    gaps = [Gap(key="Заказ", kind="token")]

    supporting = FakeProvider(supports_glossary=True)
    suggest(gaps, supporting, Cache(tmp_path / "a.json"), glossary, echo_transport, set())
    assert supporting.seen_glossary == glossary

    not_supporting = FakeProvider(supports_glossary=False)
    suggest(gaps, not_supporting, Cache(tmp_path / "b.json"), glossary, echo_transport, set())
    assert not_supporting.seen_glossary == ()


# --- review round 2: an answer is not trusted just because it arrived ---------------------

def mirror_transport(request):
    """A service that hands every text back unchanged - what a machine translator does with
    a string it did not understand. The answer looks well formed and is worthless."""
    body = json.loads(request.body.decode("utf-8"))
    return json.dumps({"translations": [{"text": text} for text in body["texts"]]})


def test_an_echoed_answer_is_refused_and_never_reaches_the_cache(tmp_path: Path):
    """A phrase has no identifier builder to save it: the echo would be written as a translation."""
    path = tmp_path / "c.json"
    cache = Cache(path)
    text = "Задача помечается выполненной."
    result = suggest([Gap(key=text, kind="phrase")], YANDEX, cache, (), mirror_transport, set())
    cache.save()

    assert result.values == {}
    assert text in result.refused[("phrase", text)]  # the reason quotes what came back
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert not [key for key in stored if text in key]
    assert Cache(path).get("yandex", "ru", "en", "", text) is None


def test_an_answer_that_kept_cyrillic_is_refused_for_a_name_too(tmp_path: Path):
    """The cache is keyed by TEXT, not by kind: a poisoned answer would come back on a phrase."""
    path = tmp_path / "c.json"
    cache = Cache(path)
    transport = scripted_transport([["Order Заказа"]])
    result = suggest([Gap(key="Заказ", kind="token")], YANDEX, cache, (), transport, set())
    cache.save()

    assert result.values == {}
    assert result.refused[("token", "Заказ")]
    assert Cache(path).get("yandex", "ru", "en", "", "Заказ") is None


def test_an_empty_answer_is_refused_so_the_dictionary_keeps_its_row(tmp_path: Path):
    """An empty value is not a weak translation - written to the dictionary it DELETES the row."""
    from xbsl.translation.entries import plan_entries

    plan = tmp_path / "xbsl-translation"
    plan.mkdir()
    stub = plan / "080-machine.yaml"
    stub.write_text("version: 1\nlanguage: en\n\ntokens:\n    Заказ: \n", encoding="utf-8")
    # What an unchecked empty answer would do once it reached the dictionary writer.
    damage = plan_entries(plan, [{"key": "Заказ", "value": "", "kind": "token"}])
    assert damage["removed"] == 1
    assert "Заказ" not in damage["files"][str(stub)]

    path = tmp_path / "c.json"
    cache = Cache(path)
    result = suggest([Gap(key="Заказ", kind="token")], YANDEX, cache, (),
                     scripted_transport([[""]]), set())
    cache.save()

    assert result.values == {}
    assert result.refused[("token", "Заказ")]
    assert Cache(path).get("yandex", "ru", "en", "", "Заказ") is None
    edits = [{"key": key, "value": value, "kind": kind}
             for (kind, key), value in result.values.items()]
    kept = plan_entries(plan, edits)
    assert kept["removed"] == 0 and kept["changed"] == 0
    assert stub.read_text(encoding="utf-8").count("Заказ") == 1


def test_an_answer_of_spaces_alone_is_refused_and_not_cached(tmp_path: Path):
    path = tmp_path / "c.json"
    cache = Cache(path)
    result = suggest([Gap(key="Заказ", kind="phrase")], YANDEX, cache, (),
                     scripted_transport([["   "]]), set())
    cache.save()
    assert result.values == {}
    assert result.refused[("phrase", "Заказ")]
    assert Cache(path).get("yandex", "ru", "en", "", "Заказ") is None


def test_an_answer_that_is_not_a_string_is_refused_not_a_crash(tmp_path: Path):
    """A `null` in the answer array reaches the dispatcher as None - it must be a named refusal."""
    path = tmp_path / "c.json"
    cache = Cache(path)
    result = suggest([Gap(key="Заказ", kind="phrase")], YANDEX, cache, (),
                     scripted_transport([[None]]), set())
    cache.save()
    assert result.values == {}
    assert result.refused[("phrase", "Заказ")]
    assert Cache(path).get("yandex", "ru", "en", "", "Заказ") is None


# --- review round 2: a batch is bounded by BOTH limits ------------------------------------

def test_a_batch_is_cut_by_the_number_of_texts(tmp_path: Path):
    """Short texts never reach the character limit - only a count keeps the batch sane."""
    provider = FakeProvider(batch_limit=10000, texts_limit=2)
    gaps = [Gap(key=key, kind="phrase") for key in ("аа", "бб", "вв", "гг", "дд")]
    suggest(gaps, provider, Cache(tmp_path / "c.json"), (), echo_transport, set())
    assert provider.batches == [["аа", "бб"], ["вв", "гг"], ["дд"]]


def test_a_batch_is_cut_by_the_sum_of_lengths(tmp_path: Path):
    """The character limit still cuts on its own when the count is nowhere near its own."""
    provider = FakeProvider(batch_limit=8, texts_limit=100)
    gaps = [Gap(key=key, kind="phrase") for key in ("ааааа", "ббббб", "вв")]
    suggest(gaps, provider, Cache(tmp_path / "c.json"), (), echo_transport, set())
    assert provider.batches == [["ааааа"], ["ббббб", "вв"]]


def test_both_limits_cut_the_same_run(tmp_path: Path):
    """One run, both reasons: the first batch closes on the count with room to spare in
    characters, the second on the characters with room to spare in the count."""
    long_text = "г" * 19
    provider = FakeProvider(batch_limit=20, texts_limit=2)
    gaps = [Gap(key=key, kind="phrase") for key in ("аа", "бб", "вв", long_text, "дд")]
    suggest(gaps, provider, Cache(tmp_path / "c.json"), (), echo_transport, set())
    assert provider.batches == [["аа", "бб"], ["вв"], [long_text], ["дд"]]


def test_both_real_providers_declare_a_text_count_limit():
    """The contract is not the dispatcher's private affair - a real provider answers it too."""
    from xbsl.translation.machine.google import Google

    assert YANDEX.texts_limit() > 0
    assert Google(env={"XBSL_TRANSLATE_GOOGLE_KEY": "k"}).texts_limit() > 0


def test_a_failing_batch_does_not_take_the_next_one_down(tmp_path: Path):
    """The isolation the dispatcher claims in prose: one dead batch, the rest still answered."""
    provider = FakeProvider(batch_limit=10000, texts_limit=2)
    gaps = [Gap(key=key, kind="phrase") for key in ("аа", "бб", "вв", "гг")]

    def transport(request):
        body = json.loads(request.body.decode("utf-8"))
        if "аа" in body["texts"]:  # only the FIRST batch is refused by the service
            raise RuntimeError("503 from the service")
        return json.dumps(body)

    path = tmp_path / "c.json"
    cache = Cache(path)
    result = suggest(gaps, provider, cache, (), transport, set())
    cache.save()

    assert provider.batches == [["аа", "бб"], ["вв", "гг"]]
    assert sorted(result.refused) == [("phrase", "аа"), ("phrase", "бб")]
    for reason in result.refused.values():
        assert "503" in reason
    assert result.values == {("phrase", "вв"): "Ok 2", ("phrase", "гг"): "Ok 2"}
    assert result.requested == 2  # the surviving batch alone, not the whole run

    reloaded = Cache(path)
    assert reloaded.get("fake", "ru", "en", "", "аа") is None
    assert reloaded.get("fake", "ru", "en", "", "вв") == "Ok 2"
