#!/usr/bin/env python3
"""Restart a VibeCodeHPC organisation in a new batch job with the same conversations.

A batch job ends at its walltime; the next job starts on a fresh node with
no tmux server. ``vibecodehpc setup`` would start a new PM conversation and
has no way to continue the previous one. This script rebuilds the
organisation from v2's own pieces and resumes every Claude Code
conversation:

1. recreate the tmux sessions ``NAME_PM`` and ``NAME_Workers<k>`` with
   ``tmux_utils.setup_multi_agent_sessions``;
2. start PM in ``NAME_PM:0.0`` with the adapter's launch command plus
   ``--resume <PM session id>`` (the job script acts for the user here);
3. put ``["--resume", <session id>]`` into each worker's ``cli_args`` and
   status ``not_started`` in the registry, then run
   ``python3 -m vibecodehpc launch --all`` (v2 appends ``cli_args`` to the
   launch command, so the adapter is unchanged);
4. tell PM that this is a new job and when to stop new work.

Session ids come from a copy of the registry saved at the end of the
previous job (v2's SessionStart hook writes ``session_id`` into it). A
registry id is used only if its conversation file exists; otherwise the
newest conversation started in the agent's working directory is used.
Conversations are keyed by directory path, so the project root must have
the same path in every job.

Agents listed in ``--new-agents`` join with a new conversation in the next
free worker pane. Each row needs agent_id, working_dir, cli_type, role and
optionally model, as PM would register it.

``--pm-only`` relaunches only PM, resumed, in a recreated ``NAME_PM``
session; workers are left as they are. ``setup --resume`` cannot do this:
without the PM session it falls through to a full new setup.

Usage (cwd and PYTHONPATH = project root, HOME restored from the previous job):
    python3 resume_sessions.py --name NAME [--model MODEL]
        [--sessions state/sessions_latest.jsonl] [--new-agents FILE]
        [--workers N] [--end-time HH:MM] [--pm-note TEXT] [--pm-only]
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from vibecodehpc.adapters.base import AgentConfig, CLIType
from vibecodehpc.adapters.factory import create_adapter
from vibecodehpc.config import VibeCodeConfig
from vibecodehpc.registry import AgentEntry, AgentRegistry
from vibecodehpc.tmux_utils import (create_session, run_tmux, send_keys,
                                    setup_multi_agent_sessions)

REGISTRY = Path("Agent-shared") / "agent_and_pane_id_table.jsonl"


def read_jsonl(path: Path | None) -> list[dict]:
    rows = []
    if path and path.exists():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    return rows


class Conversations:
    """Claude Code conversation files: ``<config dir>/projects/<dir>/<id>.jsonl``."""

    def __init__(self) -> None:
        config_dir = Path(os.environ.get("CLAUDE_CONFIG_DIR")
                          or Path.home() / ".claude")
        newest: dict[str, tuple[float, str]] = {}
        self.known: set[str] = set()
        for path in (config_dir / "projects").glob("*/*.jsonl"):
            self.known.add(path.stem)
            cwd = self._first_cwd(path)
            if not cwd:
                continue
            mtime = path.stat().st_mtime
            key = os.path.normpath(cwd)
            if key not in newest or mtime > newest[key][0]:
                newest[key] = (mtime, path.stem)
        self.by_dir = {cwd: sid for cwd, (_, sid) in newest.items()}

    @staticmethod
    def _first_cwd(path: Path) -> str | None:
        with path.open(errors="replace") as fh:
            for _, line in zip(range(50), fh):
                try:
                    cwd = json.loads(line).get("cwd")
                except ValueError:
                    continue
                if cwd:
                    return cwd
        return None

    def session_for(self, root: Path, row: dict) -> str | None:
        """The registry's session id if its file exists, else the newest in the agent's dir."""
        sid = row.get("session_id")
        if sid in self.known:
            return sid
        found = self.by_dir.get(os.path.normpath(root / (row.get("working_dir") or ".")))
        print(f"session {row.get('agent_id')}: registry {sid} -> by dir {found}")
        return found


def worker_slots(name: str, count: int, per_session: int) -> list[tuple[str, int]]:
    """(session, pane) of each worker pane in the layout setup creates."""
    return [(f"{name}_Workers{i // per_session + 1}", i % per_session)
            for i in range(count)]


def slot_index(session: str | None, pane: int | None, name: str,
               per_session: int) -> int:
    """Position of a (session, pane) in worker_slots order; -1 if foreign."""
    prefix = f"{name}_Workers"
    if not session or not session.startswith(prefix) or not isinstance(pane, int):
        return -1
    try:
        k = int(session[len(prefix):])
    except ValueError:
        return -1
    return (k - 1) * per_session + pane


def top_up_panes(slots: list[tuple[str, int]]) -> None:
    """Split and re-tile until every session has the panes the layout needs."""
    need: dict[str, int] = {}
    for session, pane in slots:
        need[session] = max(need.get(session, 0), pane + 1)
    for session, count in need.items():
        window = f"{session}:0"
        have = 0
        for _ in range(count + 1):
            out = run_tmux("list-panes", "-t", window, check=False).stdout
            have = len([line for line in out.splitlines() if line.strip()])
            if have == 0 or have >= count:
                break
            run_tmux("split-window", "-t", f"{window}.{have - 1}", check=False)
            run_tmux("select-layout", "-t", window, "tiled", check=False)
        print(f"{session}: {have} of {count} panes")


def launch_pm(root: Path, name: str, cli: str, model: str | None,
              session_id: str | None) -> str:
    """Start PM in NAME_PM:0.0, resumed if a session id is known. Returns the target."""
    target = f"{name}_PM:0.0"
    send_keys(target, f"cd {root}")
    send_keys(target, f"export PYTHONPATH={root}:${{PYTHONPATH:-}}")
    adapter = create_adapter(AgentConfig(
        agent_id="PM", workdir=root, project_root=root, cli_type=CLIType(cli),
        tmux_target=target, role="PM", model_override=model))
    command = adapter.build_launch_command()
    if session_id:
        command += ["--resume", session_id]
    send_keys(target, " ".join(command))
    print("PM:", " ".join(command))
    time.sleep(3)
    send_keys(target, "C-m", enter=False, literal=False)   # trust prompt
    return target


def v2(root: Path, *args: str) -> subprocess.CompletedProcess:
    """Run ``python3 -m vibecodehpc ARGS`` in the project root."""
    return subprocess.run([sys.executable, "-m", "vibecodehpc", *args],
                          cwd=root, capture_output=True, text=True)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--name", required=True, help="project name used at setup")
    p.add_argument("--project-root", type=Path, default=Path.cwd())
    p.add_argument("--model", default=None, help="PM model (as for setup)")
    p.add_argument("--cli", default="claude",
                   help="PM CLI; session discovery supports claude only")
    p.add_argument("--sessions", type=Path, default=None,
                   help="registry copy to resume from [state/sessions_latest.jsonl; "
                        "the live registry with --pm-only]")
    p.add_argument("--new-agents", type=Path, default=None,
                   help="JSONL of registry rows for agents joining now")
    p.add_argument("--workers", type=int, default=0,
                   help="minimum number of worker panes")
    p.add_argument("--end-time", default="?", help="HH:MM to stop new work")
    p.add_argument("--pm-note", default="", help="extra text for PM's notice")
    p.add_argument("--notice-delay", type=float, default=20,
                   help="seconds to wait before notifying PM")
    p.add_argument("--pm-only", action="store_true",
                   help="relaunch only PM in a recreated NAME_PM session")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    root = args.project_root.resolve()
    per_session = VibeCodeConfig.load(root).max_panes_per_session
    default = root / (REGISTRY if args.pm_only else Path("state/sessions_latest.jsonl"))

    rows: dict[str, dict] = {}
    for row in read_jsonl(args.sessions or default):    # the last row of an agent wins
        if row.get("agent_id"):
            rows[row["agent_id"]] = row
    conversations = Conversations()
    pm_row = rows.get("PM", {"agent_id": "PM", "working_dir": "."})
    pm_sid = conversations.session_for(root, pm_row)

    if args.pm_only:
        create_session(f"{args.name}_PM")
        launch_pm(root, args.name, args.cli, args.model, pm_sid)
        return

    # Panes: keep every saved agent's pane, put joining agents in free ones.
    workers = [r for r in rows.values() if r["agent_id"] != "PM"]
    joining = [r for r in read_jsonl(args.new_agents)
               if r.get("agent_id") and r["agent_id"] not in rows]
    used = {(r.get("tmux_session"), r.get("tmux_pane")) for r in workers}
    last_used = max((slot_index(s, p, args.name, per_session) for s, p in used),
                    default=-1)
    n_workers = max(args.workers, len(workers) + len(joining), last_used + 1)
    slots = worker_slots(args.name, n_workers, per_session)
    free = [s for s in slots if s not in used]
    for row, (session, pane) in zip(joining, free):
        row.update(tmux_session=session, tmux_window=0, tmux_pane=pane,
                   status="not_started", session_id=None, cli_args=[])
        (root / row["working_dir"]).mkdir(parents=True, exist_ok=True)
        rows[row["agent_id"]] = row
    joined = [r["agent_id"] for r in joining]
    print("joined", joined)

    # 1. tmux sessions
    setup_multi_agent_sessions(args.name, n_workers, per_session)
    top_up_panes(slots)

    # 2. PM, resumed
    if pm_sid and "PM" in rows:
        rows["PM"]["session_id"] = pm_sid
    target = launch_pm(root, args.name, args.cli, args.model, pm_sid)

    # 3. workers, resumed through v2's launch
    for row in workers:
        old = row.get("cli_args") or []
        cli_args = [a for i, a in enumerate(old)
                    if a != "--resume" and not (i > 0 and old[i - 1] == "--resume")]
        sid = conversations.session_for(root, row)
        if sid:
            cli_args += ["--resume", sid]
            row["session_id"] = sid
        row["cli_args"] = cli_args
        row["status"] = "not_started"
    registry = AgentRegistry(root / REGISTRY)
    registry.clear()
    for row in rows.values():
        registry.register(AgentEntry.from_dict(row))
    proc = v2(root, "launch", "--all")
    print("launch --all rc", proc.returncode, proc.stdout[-1500:], proc.stderr[-800:])

    # 4. tell PM
    time.sleep(args.notice_delay)
    notice = ("[job] This is a new batch job. You and all workers were resumed "
              f"with the same conversations. Stop new work at {args.end_time}. "
              "Re-read requirement_definition.md first; it may have changed.")
    if joined:
        notice += (f" Joined in this job: {', '.join(joined)} (new conversations);"
                   " add them to directory_pane_map.md.")
    if args.pm_note:
        notice += " " + args.pm_note
    notice += " Then continue."
    if v2(root, "send", "PM", notice).returncode != 0:
        send_keys(target, notice)
    print("resume done")


if __name__ == "__main__":
    main()
