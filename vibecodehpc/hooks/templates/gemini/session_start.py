#!/usr/bin/env python3
"""VibeCodeHPC SessionStart Hook for Gemini CLI.

Registers agent in registry and injects role-specific context.
Mirrors the Claude Code session_start.py hook, adapted for Gemini's
hooks.json protocol (stdin JSON → stdout JSON, exit 0).

Gemini stdin payload (expected):
  {"event": "SessionStart", "session_id": "...", ...}

Gemini stdout payload:
  {"additionalContext": "..."}
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def find_project_root(start_path: Path) -> Path | None:
    """Find project root (multi-CLI aware).

    Uses a 2-of-3 heuristic: the directory containing at least two of
    ``CLAUDE.md``, ``Agent-shared/``, and ``instructions/`` is the root.
    Note: vibecodehpc/ alone is NOT sufficient -- it is the Python package,
    not the project root.
    """
    _landmarks = ("CLAUDE.md", "Agent-shared", "instructions")
    current = start_path.resolve()
    while current != current.parent:
        hits = sum(1 for lm in _landmarks if (current / lm).exists())
        if hits >= 2:
            return current
        current = current.parent
    return None


def get_agent_id() -> str | None:
    """Read agent_id from hooks directory."""
    candidates = [
        Path.cwd() / ".gemini" / "hooks" / "agent_id.txt",
        Path.cwd() / ".claude" / "hooks" / "agent_id.txt",
        Path.cwd() / ".codex" / "hooks" / "agent_id.txt",
        Path.cwd() / ".agents" / "hooks" / "agent_id.txt",
        Path.cwd() / "agent_id.txt",
    ]
    for path in candidates:
        if path.exists():
            return path.read_text(encoding="utf-8").strip()
    return None


def get_role(agent_id: str) -> str:
    """Extract role prefix from agent_id (e.g. PG1.1 -> PG)."""
    if not agent_id:
        return ""
    if agent_id in ("PM", "SOLO"):
        return agent_id
    for prefix in ("CD", "SE", "PG"):
        if agent_id.startswith(prefix):
            return prefix
    return agent_id


ROLE_FILES = {
    "PM": [
        "instructions/PM.md",
        "Agent-shared/skills/hpc-strategies/references/typical_hpc_structure.md",
        "Agent-shared/skills/hpc-strategies/references/evolutionary_flat_dir.md",
    ],
    "SE": [
        "instructions/SE.md",
        "Agent-shared/skills/changelog-format/references/changelog_api.md",
    ],
    "PG": [
        "instructions/PG.md",
        "Agent-shared/skills/changelog-format/SKILL.md",
    ],
    "CD": ["instructions/CD.md"],
    "SOLO": ["instructions/SOLO.md"],
}

COMMON_FILES = ["GEMINI.md", "Agent-shared/directory_pane_map.txt"]


def update_registry(project_root: Path, agent_id: str, session_id: str):
    """Update agent registry with session info."""
    table_file = project_root / "Agent-shared" / "agent_and_pane_id_table.jsonl"
    if not table_file.exists():
        return

    lines = table_file.read_text(encoding="utf-8").strip().split("\n")
    updated = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            updated.append(line)
            continue

        if entry.get("agent_id") == agent_id:
            entry["session_id"] = session_id
            entry["status"] = "running"
            entry["cli"] = "gemini"
            entry["last_updated"] = datetime.now(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )

        updated.append(json.dumps(entry, ensure_ascii=False))

    table_file.write_text("\n".join(updated) + "\n", encoding="utf-8")


def generate_context(agent_id: str | None, role: str) -> str:
    """Generate session start context string."""
    parts = [
        "## Session Start",
        "",
        "Started as a VibeCodeHPC agent (Gemini CLI).",
        "Please read the following files:",
        "",
        "### Required Files",
    ]

    files = COMMON_FILES.copy()
    if role in ROLE_FILES:
        files.extend(ROLE_FILES[role])

    for f in files:
        parts.append(f"- {f}")

    parts.extend([
        "",
        "### Checklist",
        "- Confirm current location with `pwd`",
        "- Confirm your placement in `directory_pane_map.md`",
        "",
        "### Polling Agent",
        "Do not enter an idle state — periodically check for tasks.",
    ])

    return "\n".join(parts)


def main():
    try:
        input_data = json.load(sys.stdin)
        session_id = input_data.get("session_id", "")

        agent_id = get_agent_id()
        role = get_role(agent_id) if agent_id else ""

        project_root = find_project_root(Path.cwd())
        if project_root and agent_id:
            update_registry(project_root, agent_id, session_id)

        context = generate_context(agent_id, role)
        output = {"additionalContext": context}
        print(json.dumps(output, ensure_ascii=False))

        sys.exit(0)

    except Exception:
        sys.exit(0)


if __name__ == "__main__":
    main()
