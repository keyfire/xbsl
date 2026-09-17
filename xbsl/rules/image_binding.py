"""Tier D: computed UI properties that reach server endpoints.

Both rules share method, environment and cache facts. The image rule keeps its
historical property scope and metadata-only inputs; the opt-in general check groups
proven client-available calls by form and endpoint. Neither predicts call frequency.
"""

from __future__ import annotations

from collections.abc import Iterable

from xbsl import i18n
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import rule
from xbsl.rules._server_calls import (
    SERVER_KINDS as _SERVER_KINDS,
    ServerCallGraph,
    binding_calls as _binding_calls,
    server_call_mapper,
)

MESSAGES = {
    "code/image-binding-server-call.title": {
        "ru": "Картинка отдельным серверным вызовом",
        "en": "An image by a separate server call",
    },
    "code/image-binding-server-call.direct": {
        "ru": "Свойство '{prop}' вычисляется выражением с серверным вызовом '{call}'. "
              "Рассмотрите передачу изображения вместе с данными или получение "
              "из уже загруженных клиентских данных (ресурс, готовый Url).",
        "en": "Property '{prop}' is computed by an expression with the server call "
              "'{call}'. Consider passing the image with the data or obtaining it "
              "from client data already loaded (a resource, a ready Url).",
    },
    "code/image-binding-server-call.chain": {
        "ru": "Свойство '{prop}' вычисляется выражением с вызовом '{call}', транзитивно "
              "доходящим до серверного метода '{endpoint}'. Рассмотрите передачу "
              "изображения вместе с данными или получение из уже загруженных "
              "клиентских данных (ресурс, готовый Url).",
        "en": "Property '{prop}' is computed by an expression whose call '{call}' "
              "transitively reaches the server method '{endpoint}'. Consider passing "
              "the image with the data or obtaining it from client data already loaded "
              "(a resource, a ready Url).",
    },
}
i18n.register(MESSAGES)

_image_binding_mapper = server_call_mapper


@rule(
    "code/image-binding-server-call", "code/image-binding-server-call.title", "D",
    scope="project", severity=Severity.INFO, mapper=server_call_mapper,
)
def image_binding_server_call(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    graph = ServerCallGraph(facts)
    for rel, form in sorted(graph.forms):
        for binding in form["bindings"]:
            # Historically only a platform component's own Image was covered here.
            if (binding["component"] in graph.components
                    or graph.property_kind(binding["component"], binding["property"]) != "image"):
                continue
            for call in binding["calls"]:
                paths = graph.paths(form["stem"], call, legacy_image=True)
                if not paths:
                    continue
                _stem, _method, chain = paths[0]
                spelled, endpoint = call[2], chain[-1]
                key = "direct" if len(chain) == 1 else "chain"
                message = i18n.t(f"code/image-binding-server-call.{key}",
                                 prop=binding["property"], call=spelled, endpoint=endpoint)
                yield Diagnostic(rel, binding["line"], binding["col"],
                                 "code/image-binding-server-call", Severity.INFO, message)
                break


MESSAGES_COMPUTED = {
    "code/computed-property-server-call.title": {
        "ru": "Серверный вызов из вычисляемого свойства",
        "en": "Server call from a computed property",
    },
    "code/computed-property-server-call.found": {
        "ru": "Вычисляемые свойства ({sites}) обращаются к серверному методу '{endpoint}' "
              "без штатного кеша результата. Доказанные цепочки: {chains}. Рассмотрите "
              "предварительную загрузку нужных данных и передачу их свойствам.",
        "en": "Computed properties ({sites}) reach the server method '{endpoint}' "
              "without the standard result cache. Proven call paths: {chains}. Consider "
              "loading the required data in advance and passing it to the properties.",
    },
    "code/computed-property-server-call.off": {
        "ru": "серверный вызов из вычисляемого свойства может быть осознанным решением, а "
              "частоту пересчета свойства по коду не определить. Включайте, когда ищете "
              "данные, которые форма может загрузить заранее",
        "en": "a server call from a computed property may be intentional, and the code does "
              "not show how often the platform recalculates the property. Enable it when "
              "looking for data the form could load in advance",
    },
}
i18n.register(MESSAGES_COMPUTED)


@rule(
    "code/computed-property-server-call", "code/computed-property-server-call.title", "D",
    scope="project", severity=Severity.INFO, enabled_by_default=False,
    off_reason="code/computed-property-server-call.off", mapper=server_call_mapper,
)
def computed_property_server_call(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    """One finding per form and endpoint, excluding sites owned by the image rule."""
    graph = ServerCallGraph(facts)
    for rel, form in sorted(graph.forms):
        groups: dict[tuple[str, str], list[tuple[dict, list[str]]]] = {}
        for binding in form["bindings"]:
            kind = graph.property_kind(binding["component"], binding["property"])
            if kind not in ("property", "image"):
                continue
            if kind == "image" and binding["component"] not in graph.components:
                continue
            for call in binding["calls"]:
                for stem, method, chain in graph.paths(form["stem"], call):
                    groups.setdefault((stem, method), []).append((binding, chain))
        for (stem, method), sites in sorted(groups.items()):
            binding = min((s[0] for s in sites), key=lambda b: (b["line"], b["col"]))
            properties = dict.fromkeys(f"{b['property']}:{b['line']}" for b, _ in sites)
            chains = dict.fromkeys(" -> ".join(chain) for _, chain in sites)
            name = graph.metadata[stem].get("name")
            endpoint = f"{name}.{method}" if name else method
            yield Diagnostic(rel, binding["line"], binding["col"],
                             "code/computed-property-server-call", Severity.INFO,
                             i18n.t("code/computed-property-server-call.found",
                                    sites=", ".join(properties), endpoint=endpoint,
                                    chains="; ".join(chains)))
