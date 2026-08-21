"""Google Cloud Translation v2. The key goes in a header: a query parameter lands in proxy logs.

The v2 request carries only texts, languages and format - there is no glossary in it, so the
project terminology is enforced afterwards, when the prose is shaped into an identifier.
"""

from __future__ import annotations

import json
from typing import Mapping, Sequence

from .provider import Request

URL = "https://translation.googleapis.com/language/translate/v2"


class Google:
    def __init__(self, env: Mapping[str, str]) -> None:
        self._key = env.get("XBSL_TRANSLATE_GOOGLE_KEY", "")

    def code(self) -> str:
        return "google"

    def missing(self) -> tuple[str, ...]:
        """The variables this service still needs: one key, no folder id of any kind."""
        return () if self._key else ("XBSL_TRANSLATE_GOOGLE_KEY",)

    def configured(self) -> bool:
        return not self.missing()

    def batch_limit(self) -> int:
        return 5000

    def texts_limit(self) -> int:
        """How many texts one request may carry - a deliberately conservative figure, see
        the same method on the Yandex provider."""
        return 100

    def supports_glossary(self) -> bool:
        return False

    def request(self, texts: Sequence[str], target: str, source: str,
                glossary: Sequence[tuple[str, str]] = ()) -> Request:
        body = {"q": list(texts), "target": target, "source": source, "format": "text"}
        return Request(
            url=URL,
            headers={"X-goog-api-key": self._key,
                     "Content-Type": "application/json", "Accept": "application/json"},
            body=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        )

    def parse(self, body: str) -> list[str]:
        data = json.loads(body)
        return [item["translatedText"] for item in data.get("data", {}).get("translations", [])]
