"""Common interface of the IPC backends (send / receive / health / launch)."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

REGISTRY = Path("Agent-shared") / "agent_and_pane_id_table.jsonl"
SEND_LOG = Path("Agent-shared") / "logs" / "send_log.txt"


class IPCBackend(ABC):
    """How the framework reaches agents. Mirrors CLIAdapter: one class per transport."""

    name = "abstract"

    def __init__(self, project_root: Path):
        self.project_root = Path(project_root)

    @abstractmethod
    def send(self, agent_id: str, message: str, sender: str = "framework") -> bool:
        """Deliver one message to an agent. True if handed over."""

    def receive(self, agent_id: str) -> list[dict]:
        """Take the agent's pending messages (backends without an inbox: none)."""
        return []

    @abstractmethod
    def health(self, agent_id: str) -> Optional[bool]:
        """True if the agent's session is alive, False if not, None if unknown."""

    @abstractmethod
    def launch(self, agent_id: str, command: list[str], workdir: Path,
               first_message: str = "") -> str:
        """Start the agent's CLI with ``command`` in ``workdir``; return a handle."""

    # ── helpers shared by backends (stdlib only: also runs on native Windows) ──

    def registry_rows(self) -> dict[str, dict]:
        """Registry rows by agent_id, read without the fcntl-based AgentRegistry."""
        rows: dict[str, dict] = {}
        try:
            text = (self.project_root / REGISTRY).read_text(encoding="utf-8")
        except OSError:
            return rows
        for line in text.splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict) and row.get("agent_id"):
                rows[row["agent_id"]] = row
        return rows

    def log_send(self, agent_id: str, message: str) -> None:
        """Same line format as AgentManager._log_send."""
        path = self.project_root / SEND_LOG
        path.parent.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with path.open("a", encoding="utf-8") as fh:
            fh.write(f'[{stamp}] {agent_id}: "{message}"\n')
