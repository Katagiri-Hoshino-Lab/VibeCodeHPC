"""cross_session backend: Claude Code agents without tmux (native Windows or Linux).

- launch: ``claude --bg`` in the agent's directory (or a visible Windows
  Terminal tab with ``launcher="wt"``), with the first message as the
  initial prompt. The inbox hook is installed in the agent's
  ``.claude/settings.local.json`` first.
- send (framework to agent): append to ``Agent-shared/ipc/inbox/<id>.jsonl``;
  ``inbox_inject.py`` hands it to the session at its next event.
- agent to agent: Claude Code's own cross-session messaging
  (``ListAgents`` / ``SendMessage``) between sessions on the same machine.
- health: ``claude agents --json`` (background and interactive sessions).

Limits: an idle session with an empty turn queue is not woken by the
inbox; a SendMessage from another session, or the next turn, wakes it.
Sessions in WSL and native Windows cannot message each other.
Standard library only; does not import the fcntl-based registry.
"""

from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from vibecodehpc.ipc.base import IPCBackend

HOOK_TEMPLATE = (Path(__file__).resolve().parent.parent
                 / "hooks" / "templates" / "claude" / "inbox_inject.py")
HOOK_EVENTS = ("UserPromptSubmit", "PostToolUse", "Stop")
IPC_DIR = Path("Agent-shared") / "ipc"
_BG_ID = re.compile(r"\b((?=[0-9a-z]*\d)[0-9a-z]{8})\b")
_ENDED = {"done", "exited", "stopped", "failed"}


def install_inbox_hooks(workdir: Path, agent_id: str, inbox: Path) -> Path:
    """Copy the inbox hook into ``workdir/.claude/hooks`` and register it."""
    hooks_dir = workdir / ".claude" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    hook = hooks_dir / HOOK_TEMPLATE.name
    shutil.copy2(HOOK_TEMPLATE, hook)
    (hooks_dir / "inbox_path.txt").write_text(str(inbox), encoding="utf-8")
    (hooks_dir / "agent_id.txt").write_text(agent_id, encoding="utf-8")

    command = f'"{Path(sys.executable).as_posix()}" "{hook.as_posix()}"'
    settings_path = workdir / ".claude" / "settings.local.json"
    try:
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        settings = {}
    hooks = settings.setdefault("hooks", {})
    for event in HOOK_EVENTS:
        entries = hooks.setdefault(event, [])
        if not any(h.get("command") == command for e in entries for h in e.get("hooks", [])):
            entries.append({"hooks": [{"type": "command", "command": command}]})
    settings_path.write_text(json.dumps(settings, indent=2, ensure_ascii=False),
                             encoding="utf-8")
    return hook


class CrossSessionBackend(IPCBackend):
    name = "cross_session"

    def __init__(self, project_root: Path, claude: str = "claude", launcher: str = "bg"):
        super().__init__(project_root)
        self.claude = claude
        self.launcher = launcher
        self.ipc_dir = self.project_root / IPC_DIR
        self.sessions_path = self.ipc_dir / "sessions.json"

    # ── bookkeeping ──

    def inbox(self, agent_id: str) -> Path:
        return self.ipc_dir / "inbox" / f"{agent_id}.jsonl"

    def sessions(self) -> dict:
        try:
            return json.loads(self.sessions_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save_session(self, agent_id: str, record: dict) -> None:
        data = self.sessions()
        data[agent_id] = record
        self.ipc_dir.mkdir(parents=True, exist_ok=True)
        self.sessions_path.write_text(json.dumps(data, indent=1), encoding="utf-8")

    def _agents(self) -> Optional[list]:
        """``claude agents --json``: active interactive and background sessions."""
        try:
            proc = subprocess.run([self.claude, "agents", "--json"], capture_output=True,
                                  text=True, encoding="utf-8", errors="replace", timeout=60)
            entries = json.loads(proc.stdout or "null")
        except (OSError, ValueError, subprocess.TimeoutExpired):
            return None
        return entries if isinstance(entries, list) else None

    def _background_id(self, workdir: Path) -> str:
        """Id of the newest background session started in ``workdir``."""
        matches = [e for e in self._agents() or []
                   if e.get("kind") == "background" and e.get("id")
                   and Path(str(e.get("cwd", ""))).resolve() == workdir]
        matches.sort(key=lambda e: str(e.get("startedAt", "")))
        return str(matches[-1]["id"]) if matches else ""

    # ── interface ──

    def send(self, agent_id: str, message: str, sender: str = "framework") -> bool:
        path = self.inbox(agent_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        item = {"time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "from": sender, "text": message}
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(item, ensure_ascii=False) + "\n")
        self.log_send(agent_id, message)
        return True

    def receive(self, agent_id: str) -> list[dict]:
        """Take pending messages the same way the hook does (for tools and tests)."""
        spec = importlib.util.spec_from_file_location("vchpc_inbox_inject", HOOK_TEMPLATE)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.drain(self.inbox(agent_id))

    def health(self, agent_id: str) -> Optional[bool]:
        record = self.sessions().get(agent_id)
        if not record:
            return None
        entries = self._agents()
        if entries is None:
            return None
        for entry in entries:
            same_id = record.get("bg_id") and entry.get("id") == record["bg_id"]
            same_dir = (not record.get("bg_id")
                        and Path(str(entry.get("cwd", ""))) == Path(record["workdir"]))
            if same_id or same_dir:
                return str(entry.get("state", "")).lower() not in _ENDED
        return False

    def launch(self, agent_id: str, command: list[str], workdir: Path,
               first_message: str = "") -> str:
        workdir = Path(workdir).resolve()
        install_inbox_hooks(workdir, agent_id, self.inbox(agent_id).resolve())
        args = [self.claude if command[0] == "claude" else command[0], *command[1:]]
        if first_message:
            args.append(first_message)
        if self.launcher == "wt":
            # A visible Windows Terminal tab instead of a background session.
            subprocess.Popen(["wt.exe", "-w", "vibecodehpc", "new-tab", "--title", agent_id,
                              "-d", str(workdir), *args])
            handle = f"wt:{agent_id}"
        else:
            proc = subprocess.run([args[0], "--bg", *args[1:]], cwd=workdir, timeout=180,
                                  capture_output=True, text=True,
                                  encoding="utf-8", errors="replace")
            if proc.returncode != 0:
                raise RuntimeError(f"claude --bg failed: {(proc.stderr or proc.stdout)[-300:]}")
            match = _BG_ID.search(proc.stdout)
            handle = self._background_id(workdir) or (match.group(1) if match else "")
        self._save_session(agent_id, {
            "bg_id": handle if self.launcher != "wt" else "",
            "launcher": self.launcher, "workdir": str(workdir),
            "started": datetime.now(timezone.utc).isoformat(timespec="seconds")})
        return handle
