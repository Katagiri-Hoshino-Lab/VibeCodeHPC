"""Optional, experimental IPC backends.

VibeCodeHPC's default IPC is tmux (``vibecodehpc send`` types into panes).
Nothing in that default path imports this package. A backend is loaded
only when chosen with ``VIBECODEHPC_IPC_BACKEND`` or ``ipc_backend:`` in
config.yaml, and only through ``python -m vibecodehpc.ipc``.

Backends:

- ``tmux``: the existing tmux path, behind the common interface.
- ``cross_session``: Claude Code background sessions, a file inbox
  delivered by hooks, and Claude Code's own cross-session messaging
  between agents. Works on native Windows (no tmux) and on Linux/WSL.

See docs/windows_native.md.
"""

from __future__ import annotations

import importlib
import os
import re
from pathlib import Path
from typing import Optional

DEFAULT_BACKEND = "tmux"
BACKENDS = {
    "tmux": "vibecodehpc.ipc.tmux_backend:TmuxBackend",
    "cross_session": "vibecodehpc.ipc.cross_session:CrossSessionBackend",
}
_CONFIG_KEY = re.compile(r"""(?m)^ipc_backend\s*:\s*["']?([A-Za-z_]+)""")


def selected_backend(project_root: Optional[Path] = None) -> str:
    """Backend name from the environment, then config.yaml, else tmux."""
    name = os.environ.get("VIBECODEHPC_IPC_BACKEND", "").strip()
    if name:
        return name
    config = Path(project_root or Path.cwd()) / "config.yaml"
    try:
        match = _CONFIG_KEY.search(config.read_text(encoding="utf-8"))
    except OSError:
        match = None
    return match.group(1) if match else DEFAULT_BACKEND


def get_backend(name: Optional[str] = None, project_root: Optional[Path] = None):
    """Import and construct a backend (imported only when asked for)."""
    root = Path(project_root or Path.cwd()).resolve()
    name = name or selected_backend(root)
    if name not in BACKENDS:
        raise ValueError(f"unknown IPC backend {name!r}; choose from {', '.join(BACKENDS)}")
    module_name, class_name = BACKENDS[name].split(":")
    return getattr(importlib.import_module(module_name), class_name)(root)
