#!/usr/bin/env python3
"""Send each worker its first instruction once, from the job script.

In VibeCodeHPC the PM sends the first instruction after ``launch --all``.
With a slow model the PM may take many minutes to do so, or may send the
same instruction repeatedly. This script waits until the registry lists
workers as running and sends each of them one message with v2's own
``python3 -m vibecodehpc send``. Workers already served are recorded in
``Agent-shared/.init_sent[_TAG]``, so a restart does not send twice.

Two kinds of message:

- first: for a worker started with a new conversation (first job, or an
  agent that joined in a later job);
- resume: with ``--tag``, for a worker started with ``--resume`` in its
  registry ``cli_args`` (see resume_sessions.py). Sent once per tag,
  typically the job id.

Usage (cwd and PYTHONPATH = project root):
    python3 init_send.py [--project-root DIR] [--wait-min 30]
        [--tag JOB_ID --end-time HH:MM] [--assignments FILE]
        [--first-template FILE] [--resume-template FILE]

``--assignments`` is a JSON object {"AGENT_ID": "text", ...} inserted as
``{assignment}``. Templates may use {agent_id}, {role}, {assignment} and
{end_time}.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

FIRST_TEMPLATE = (
    "[job] [Request] You are {agent_id} ({role}). Read CLAUDE.md, "
    "instructions/{role}.md, directory_pane_map.md and "
    "requirement_definition.md. {assignment} Start now and report to your "
    "SE/PM with python3 -m vibecodehpc send."
)
RESUME_TEMPLATE = (
    "[job] [Request] New batch job: you were resumed with your conversation. "
    "Stop new work at {end_time}. Re-read requirement_definition.md first; "
    "it may have changed. {assignment} Report to your SE/PM with "
    "python3 -m vibecodehpc send."
)
DEFAULT_ASSIGNMENT = "Your area is given in requirement_definition.md."


class _Keep(dict):
    """format_map helper that leaves unknown placeholders as they are."""

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def read_ids(path: Path) -> set[str]:
    return set(path.read_text().split()) if path.exists() else set()


def write_ids(path: Path, ids: set[str]) -> None:
    path.write_text("\n".join(sorted(ids)) + "\n")


def read_registry(path: Path) -> list[dict]:
    rows = []
    if path.exists():
        for line in path.read_text(errors="replace").splitlines():
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    return rows


def role_of(row: dict) -> str:
    aid = row["agent_id"]
    return row.get("role") or ("SE" if aid.startswith("SE") else "PG")


def send(root: Path, agent_id: str, message: str) -> bool:
    proc = subprocess.run(
        [sys.executable, "-m", "vibecodehpc", "send", agent_id, message],
        cwd=root, capture_output=True, text=True)
    print(time.strftime("%H:%M:%S"), "send", agent_id, "rc", proc.returncode,
          (proc.stderr or "")[-200:].strip(), flush=True)
    return proc.returncode == 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--project-root", type=Path, default=Path.cwd())
    p.add_argument("--wait-min", type=float, default=30,
                   help="give up after this many minutes")
    p.add_argument("--tag", default="",
                   help="resume mode: send the resume message once per tag")
    p.add_argument("--end-time", default="?", help="HH:MM to stop new work")
    p.add_argument("--assignments", type=Path, default=None)
    p.add_argument("--first-template", type=Path, default=None)
    p.add_argument("--resume-template", type=Path, default=None)
    p.add_argument("--interval", type=float, default=20,
                   help="seconds between registry checks")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    root = args.project_root.resolve()
    shared = root / "Agent-shared"
    registry = shared / "agent_and_pane_id_table.jsonl"
    sent_path = shared / (".init_sent_" + args.tag if args.tag else ".init_sent")

    assignments = {}
    if args.assignments:
        assignments = json.loads(args.assignments.read_text(encoding="utf-8"))
    first = (args.first_template.read_text(encoding="utf-8").strip()
             if args.first_template else FIRST_TEMPLATE)
    resume = (args.resume_template.read_text(encoding="utf-8").strip()
              if args.resume_template else RESUME_TEMPLATE)

    sent = read_ids(sent_path)
    deadline = time.time() + args.wait_min * 60
    while time.time() < deadline:
        rows = [r for r in read_registry(registry)
                if r.get("agent_id") and r["agent_id"] != "PM"]
        running = [r for r in rows if r.get("status") == "running"]
        for row in running:
            aid = row["agent_id"]
            if aid in sent:
                continue
            resumed = "--resume" in (row.get("cli_args") or [])
            template = resume if args.tag and resumed else first
            message = template.format_map(_Keep(
                agent_id=aid, role=role_of(row), end_time=args.end_time,
                assignment=assignments.get(aid, DEFAULT_ASSIGNMENT)))
            if send(root, aid, message):
                sent.add(aid)
                write_ids(sent_path, sent)
            time.sleep(3)
        if rows and len(running) == len(rows) and all(
                r["agent_id"] in sent for r in running):
            break
        time.sleep(args.interval)
    print("init_send done", sorted(sent), flush=True)


if __name__ == "__main__":
    main()
