"""The provider contract: every translation service speaks these five methods."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol, Sequence


@dataclass(frozen=True)
class Request:
    """One prepared call: the dispatcher performs it, the provider only shapes it."""

    url: str
    headers: dict[str, str]
    body: bytes


class MachineError(Exception):
    """A refusal the user must read: no provider, no key, a service that said no."""


class Provider(Protocol):
    def code(self) -> str: ...
    def configured(self) -> bool: ...
    def missing(self) -> tuple[str, ...]: ...
    def batch_limit(self) -> int: ...
    def texts_limit(self) -> int: ...
    def supports_glossary(self) -> bool: ...
    def request(self, texts: Sequence[str], target: str, source: str,
                glossary: Sequence[tuple[str, str]]) -> Request: ...
    def parse(self, body: str) -> list[str]: ...


def select(name: str | None, env: Mapping[str, str]) -> Provider:
    """The provider to use: the named one, or the only configured one - never a silent guess."""
    from .google import Google
    from .yandex import Yandex

    providers = {"yandex": Yandex(env), "google": Google(env)}
    if name:
        if name not in providers:
            raise MachineError(f"unknown provider {name!r}: expected one of {sorted(providers)}")
        chosen = providers[name]
        # Naming the service does not conjure its key: without this check the run would build a
        # live request with an empty credential and send the whole project to a stranger for a
        # 401 on every batch. The refusal names the variables of THIS service and nothing else.
        if not chosen.configured():
            raise MachineError(f"provider {name!r} is not configured:"
                               f" set {' and '.join(chosen.missing())}")
        return chosen
    ready = [code for code, provider in providers.items() if provider.configured()]
    if not ready:
        raise MachineError(
            "no translation provider is configured: set XBSL_TRANSLATE_GOOGLE_KEY"
            " and/or XBSL_TRANSLATE_YANDEX_KEY with XBSL_TRANSLATE_YANDEX_FOLDER")
    if len(ready) > 1:
        raise MachineError(f"several providers are configured ({', '.join(sorted(ready))}):"
                           " choose one with --provider")
    return providers[ready[0]]
