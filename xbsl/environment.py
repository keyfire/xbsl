"""What exactly answers: the engine, its interpreter, the data version and the plugins.

One snapshot for every surface that names the environment - the LSP start log and the MCP
diagnostic. The reason it exists: two servers with diverged plugin versions (the editor's
LSP from one interpreter, the agent's MCP from another) answer differently on the same
file, and nothing used to say so - the diagnosis went through site-packages of both.
"""

from __future__ import annotations

import sys

from xbsl import __version__, dataset, i18n, plugins


def snapshot() -> dict:
    """The environment as data: engine, interpreter, Element data versions, plugins."""
    try:
        data = {
            "default": dataset.default_version(),
            "available": dataset.available_versions(),
            # WHERE the data is read from, not just which version it claims to be: a server
            # started from an installed copy answers from that copy's data files, and a
            # regenerated checkout does not reach it. Without the path the divergence looks
            # like the platform not knowing a kind at all.
            "root": str(dataset.data_root()),
            "root_source": dataset.data_root_source(),
        }
    except dataset.DatasetError:
        data = None
    return {
        "engine": __version__,
        "python": sys.executable,
        "data": data,
        "plugins": plugins.installed(),
    }


def rule_set(active: list) -> dict:
    """The rule set a run judged by: {active, total, plugin}.

    `active` is what the run carried (engine.active_rules); `total` every rule this
    installation knows, plugins included; `plugin` the active rules that came from plugins.
    Two servers disagreeing about one tree differ here first.
    """
    from xbsl.engine import RULES  # lazy: the engine is heavy and not needed by snapshot()

    return {
        "active": len(active),
        "total": len(RULES),
        "plugin": sum(1 for r in active if not r.func.__module__.startswith("xbsl.")),
    }


def provenance(active: list) -> dict:
    """What judged a report: the engine version, the plugins and the rule set.

    Goes into the summary of every check (the CLI json, the MCP answer), so that two
    environments answering differently about one tree show the difference in the answer
    itself rather than after a second round of `--version` on both sides.
    """
    return {"engine": __version__, "plugins": plugins.installed(), "rules": rule_set(active)}


def provenance_note(info: dict) -> str:
    """The same as one line of the text summary."""
    listed = ", ".join(f"{p['name']} {p['version']}" for p in info["plugins"])
    return i18n.t(
        "cli.run-set", engine=info["engine"], plugins=listed or i18n.t("cli.plugins-none"),
        **info["rules"],
    )


def note() -> str:
    """The same snapshot as one log line."""
    info = snapshot()
    data = info["data"]
    listed = ", ".join(f"{p['name']} {p['version']}" for p in info["plugins"]) or "нет"
    return (
        f"python {info['python']}; "
        f"данные Элемента: {data['default'] if data else 'нет'}"
        + (f" из {data['root']}" if data else "")
        + f"; надстройки: {listed}"
    )
