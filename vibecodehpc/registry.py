"""Agent registry - manages agent-to-pane mapping and lifecycle state.

File-backed (JSONL) for crash recovery and inter-process visibility.
Replaces the bash-parsed agent_and_pane_id_table.jsonl from VibeCodeHPC-jp.
"""

import json
import fcntl
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from vibecodehpc.adapters.base import CLIType


@dataclass
class AgentEntry:
    """Single agent record in the registry."""

    agent_id: str
    cli_type: str  # CLIType value string
    tmux_session: str
    tmux_window: int
    tmux_pane: int
    working_dir: str
    status: str = "not_started"  # not_started, running, stopped, dead
    session_id: Optional[str] = None
    last_updated: Optional[str] = None
    model: Optional[str] = None
    role: Optional[str] = None
    cli_args: Optional[list] = None  # extra CLI flags (e.g. ["--context-window", "65536"])

    def to_jsonl(self) -> str:
        d = asdict(self)
        if self.last_updated is None:
            d["last_updated"] = datetime.now(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
        return json.dumps(d, ensure_ascii=False)

    @classmethod
    def from_dict(cls, d: dict) -> "AgentEntry":
        # Handle legacy key: claude_session_id → session_id
        if "claude_session_id" in d and "session_id" not in d:
            d = dict(d)
            d["session_id"] = d.pop("claude_session_id")
        known_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in d.items() if k in known_fields}
        # Default cli_type to claude for legacy entries
        if "cli_type" not in filtered:
            filtered["cli_type"] = CLIType.CLAUDE.value
        return cls(**filtered)


class AgentRegistry:
    """
    Manages the agent-to-pane mapping and lifecycle state.

    JSONL-backed for compatibility with VibeCodeHPC-jp and for
    inter-process visibility (hooks, monitors can read the file).
    """

    def __init__(self, registry_path: Path):
        self.path = registry_path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _read_all(self) -> list[AgentEntry]:
        """Read all entries from JSONL file."""
        if not self.path.exists():
            return []
        entries = []
        for line in self.path.read_text(encoding="utf-8").strip().split("\n"):
            line = line.strip()
            if line:
                try:
                    entries.append(AgentEntry.from_dict(json.loads(line)))
                except (json.JSONDecodeError, TypeError):
                    continue
        return entries

    def _write_all(self, entries: list[AgentEntry]) -> None:
        """Write all entries to JSONL file with file locking."""
        with open(self.path, "w", encoding="utf-8") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                for entry in entries:
                    f.write(entry.to_jsonl() + "\n")
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)

    def register(self, entry: AgentEntry) -> None:
        """Add or update an agent entry."""
        entries = self._read_all()
        # Replace if exists, append if new
        found = False
        for i, e in enumerate(entries):
            if e.agent_id == entry.agent_id:
                entries[i] = entry
                found = True
                break
        if not found:
            entries.append(entry)
        self._write_all(entries)

    def get(self, agent_id: str) -> Optional[AgentEntry]:
        """Get an agent entry by ID."""
        for entry in self._read_all():
            if entry.agent_id == agent_id:
                return entry
        return None

    def update_status(self, agent_id: str, status: str) -> None:
        """Update an agent's status."""
        entries = self._read_all()
        for entry in entries:
            if entry.agent_id == agent_id:
                entry.status = status
                entry.last_updated = datetime.now(timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                )
                break
        self._write_all(entries)

    def update_session_id(self, agent_id: str, session_id: str) -> None:
        """Update an agent's CLI session ID."""
        entries = self._read_all()
        for entry in entries:
            if entry.agent_id == agent_id:
                entry.session_id = session_id
                entry.last_updated = datetime.now(timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                )
                break
        self._write_all(entries)

    def update_working_dir(self, agent_id: str, working_dir: str) -> None:
        """Update an agent's working directory."""
        entries = self._read_all()
        for entry in entries:
            if entry.agent_id == agent_id:
                entry.working_dir = working_dir
                entry.last_updated = datetime.now(timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                )
                break
        self._write_all(entries)

    def list_all(self) -> list[AgentEntry]:
        """List all agent entries."""
        return self._read_all()

    def list_by_role(self, role: str) -> list[AgentEntry]:
        """List agents by role (PM, SE, PG, CD, SOLO)."""
        return [e for e in self._read_all() if e.role == role]

    def list_by_status(self, status: str) -> list[AgentEntry]:
        """List agents by status."""
        return [e for e in self._read_all() if e.status == status]

    def list_by_cli(self, cli_type: CLIType) -> list[AgentEntry]:
        """List agents by CLI type."""
        return [e for e in self._read_all() if e.cli_type == cli_type.value]

    def remove(self, agent_id: str) -> bool:
        """Remove an agent entry."""
        entries = self._read_all()
        new_entries = [e for e in entries if e.agent_id != agent_id]
        if len(new_entries) < len(entries):
            self._write_all(new_entries)
            return True
        return False

    def clear(self) -> None:
        """Remove all entries."""
        self._write_all([])

    def get_tmux_target(self, agent_id: str) -> Optional[str]:
        """Get the tmux target string for an agent."""
        entry = self.get(agent_id)
        if entry:
            return f"{entry.tmux_session}:{entry.tmux_window}.{entry.tmux_pane}"
        return None
