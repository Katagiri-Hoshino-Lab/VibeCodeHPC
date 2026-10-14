"""The existing tmux transport behind the IPCBackend interface.

Uses tmux_utils unchanged. ``vibecodehpc launch`` remains the full launch
path (hooks, skills, settings); ``launch`` here only types the command.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from vibecodehpc.ipc.base import IPCBackend
from vibecodehpc.tmux_utils import send_keys, session_exists


class TmuxBackend(IPCBackend):
    name = "tmux"

    def _target(self, agent_id: str) -> Optional[str]:
        row = self.registry_rows().get(agent_id) or {}
        if not row.get("tmux_session") or row.get("tmux_pane") is None:
            return None
        return f"{row['tmux_session']}:{row.get('tmux_window', 0)}.{row['tmux_pane']}"

    def send(self, agent_id: str, message: str, sender: str = "framework") -> bool:
        target = self._target(agent_id)
        if not target or not send_keys(target, message):
            return False
        self.log_send(agent_id, message)
        return True

    def health(self, agent_id: str) -> Optional[bool]:
        row = self.registry_rows().get(agent_id)
        if not row or not row.get("tmux_session"):
            return None
        return session_exists(row["tmux_session"])

    def launch(self, agent_id: str, command: list[str], workdir: Path,
               first_message: str = "") -> str:
        target = self._target(agent_id)
        if not target:
            raise ValueError(f"{agent_id} has no tmux pane in the registry")
        send_keys(target, f"cd {workdir}")
        send_keys(target, " ".join(command))
        if first_message:
            send_keys(target, first_message)
        return target
