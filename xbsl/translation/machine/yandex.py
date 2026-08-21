"""Yandex Cloud Translate v2. The key is a service account API key - it does not expire.

`Api-Key` is the AUTHORIZATION SCHEME the service expects in the `Authorization` header, not
the name of a header of its own: the value reads `Api-Key <key>`. A header literally named
`Api-Key` is a name nobody on the other side knows, and every batch comes back 401.
"""

from __future__ import annotations

import json
from typing import Mapping, Sequence

from .provider import Request

URL = "https://translate.api.cloud.yandex.net/translate/v2/translate"


class Yandex:
    def __init__(self, env: Mapping[str, str]) -> None:
        self._key = env.get("XBSL_TRANSLATE_YANDEX_KEY", "")
        self._folder = env.get("XBSL_TRANSLATE_YANDEX_FOLDER", "")

    def code(self) -> str:
        return "yandex"

    def missing(self) -> tuple[str, ...]:
        """The variables this service still needs: it authorizes with a key AND a folder id."""
        absent = []
        if not self._key:
            absent.append("XBSL_TRANSLATE_YANDEX_KEY")
        if not self._folder:
            absent.append("XBSL_TRANSLATE_YANDEX_FOLDER")
        return tuple(absent)

    def configured(self) -> bool:
        return not self.missing()

    def batch_limit(self) -> int:
        return 10000

    def texts_limit(self) -> int:
        """How many texts one request may carry. Deliberately below any published figure:
        a batch that is refused whole costs the same money as one that is accepted."""
        return 100

    def supports_glossary(self) -> bool:
        return True

    def request(self, texts: Sequence[str], target: str, source: str,
                glossary: Sequence[tuple[str, str]] = ()) -> Request:
        body: dict = {
            "folderId": self._folder,
            "texts": list(texts),
            "targetLanguageCode": target,
            "sourceLanguageCode": source,
            "format": "PLAIN_TEXT",
        }
        if glossary:
            body["glossaryConfig"] = {"glossaryData": {"glossaryPairs": [
                {"sourceText": src_text, "translatedText": dst_text} for src_text, dst_text in glossary]}}
        return Request(
            url=URL,
            headers={"Authorization": f"Api-Key {self._key}",
                     "Content-Type": "application/json", "Accept": "application/json"},
            body=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        )

    def parse(self, body: str) -> list[str]:
        data = json.loads(body)
        return [item["text"] for item in data.get("translations", [])]
