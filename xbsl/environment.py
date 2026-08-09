"""What exactly answers: the engine, its interpreter, the data version and the plugins.

One snapshot for every surface that names the environment - the LSP start log and the MCP
diagnostic. The reason it exists: two servers with diverged plugin versions (the editor's
LSP from one interpreter, the agent's MCP from another) answer differently on the same
file, and nothing used to say so - the diagnosis went through site-packages of both.
"""

from __future__ import annotations

import sys

from xbsl import __version__, dataset, plugins


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
