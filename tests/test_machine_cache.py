from pathlib import Path

from xbsl.translation.machine.cache import Cache, fingerprint


def test_fingerprint_ignores_order_and_case():
    first = fingerprint([("Программа", "Program"), ("Абонент", "Subscriber")])
    second = fingerprint([("абонент", "Subscriber"), ("Программа", "Program")])
    assert first == second
    assert first != fingerprint([("Программа", "Software")])


def test_empty_glossary_has_an_empty_fingerprint():
    assert fingerprint(()) == ""


def test_put_then_get_survives_a_reload(tmp_path: Path):
    path = tmp_path / "machine-cache.json"
    cache = Cache(path)
    assert cache.get("yandex", "ru", "en", "", "АдресСайта") is None
    cache.put("yandex", "ru", "en", "", "АдресСайта", "Site address")
    cache.save()

    second = Cache(path)
    assert second.get("yandex", "ru", "en", "", "АдресСайта") == "Site address"
    assert second.get("google", "ru", "en", "", "АдресСайта") is None  # the provider is in the key


def test_counts_hits_and_misses(tmp_path: Path):
    cache = Cache(tmp_path / "c.json")
    cache.put("yandex", "ru", "en", "", "Заказ", "Order")
    cache.get("yandex", "ru", "en", "", "Заказ")
    cache.get("yandex", "ru", "en", "", "Товар")
    assert (cache.hits, cache.misses) == (1, 1)


def test_cache_survives_truncated_json(tmp_path: Path):
    """Cache starts empty when the file is corrupted (truncated JSON)."""
    path = tmp_path / "truncated.json"
    cache = Cache(path)
    cache.put("yandex", "ru", "en", "", "Первое", "First")
    cache.save()

    # Truncate the file in the middle.
    path.write_text('{"key": "val')

    # Should load as empty cache, not raise JSONDecodeError.
    reloaded = Cache(path)
    assert reloaded.get("yandex", "ru", "en", "", "Первое") is None
    # Should work normally after that.
    reloaded.put("google", "ru", "en", "", "Второе", "Second")
    reloaded.save()
    assert reloaded.get("google", "ru", "en", "", "Второе") == "Second"


def test_cache_survives_json_array_instead_of_object(tmp_path: Path):
    """Cache starts empty when JSON is valid but not an object."""
    path = tmp_path / "array.json"
    path.write_text('["item1", "item2"]')

    # Should load as empty cache, not fail or use the array.
    cache = Cache(path)
    assert cache.get("yandex", "ru", "en", "", "Что-то") is None
    cache.put("yandex", "ru", "en", "", "Что-то", "Something")
    assert cache.get("yandex", "ru", "en", "", "Что-то") == "Something"


def test_cache_survives_empty_file(tmp_path: Path):
    """Cache starts empty when the file is empty."""
    path = tmp_path / "empty.json"
    path.write_text("")

    # Should load as empty cache.
    cache = Cache(path)
    assert cache.get("yandex", "ru", "en", "", "Пусто") is None
    cache.put("yandex", "ru", "en", "", "Пусто", "Empty")
    cache.save()
    assert Cache(path).get("yandex", "ru", "en", "", "Пусто") == "Empty"


def test_save_uses_temporary_file_atomically(tmp_path, monkeypatch):
    """The original file survives if os.replace fails; atomicity is the property being tested."""
    import os

    path = tmp_path / "atomic.json"
    cache = Cache(path)
    cache.put("yandex", "ru", "en", "", "Первая", "First")
    cache.save()

    # Verify the file exists with the first entry.
    assert path.exists()
    first_cache = Cache(path)
    assert first_cache.get("yandex", "ru", "en", "", "Первая") == "First"

    # Now add a second entry and make os.replace fail.
    cache.put("yandex", "ru", "en", "", "Вторая", "Second")

    def failing_replace(src, dst):
        raise OSError("Simulated replace failure")

    monkeypatch.setattr(os, "replace", failing_replace)

    # Attempt save should fail.
    try:
        cache.save()
        assert False, "save() should have raised an exception"
    except OSError as e:
        assert "replace failure" in str(e)

    # But the original file on disk should be intact and readable.
    second_cache = Cache(path)
    assert second_cache.get("yandex", "ru", "en", "", "Первая") == "First"
    assert second_cache.get("yandex", "ru", "en", "", "Вторая") is None


def test_temporary_file_cleaned_up_on_save_failure(tmp_path, monkeypatch):
    """Temporary file is deleted if write or os.replace fails."""
    import os

    path = tmp_path / "cleanup.json"
    cache = Cache(path)
    cache.put("yandex", "ru", "en", "", "Данные", "Data")

    def failing_replace(src, dst):
        raise OSError("Replace failed")

    monkeypatch.setattr(os, "replace", failing_replace)

    try:
        cache.save()
    except OSError:
        pass

    # No temporary files should be left behind.
    tmp_files = list(tmp_path.glob("cleanup.json*.tmp"))
    assert tmp_files == [], f"Temporary files not cleaned up: {tmp_files}"
