#!/usr/bin/env python3
"""VibeCodeHPC Stop Hook for Polling Agents (Claude Code).

Prevents agent idle by blocking Stop events (exit code 2) and
re-injecting context with probabilistic file embedding.

Refactored from VibeCodeHPC-jp/hooks/templates/stop_polling_v3.py.
Key changes:
- Removed hardcoded paths, uses config-driven file provision
- Simplified probabilistic embedding logic
- Structured as importable module (not just __main__)
- CLI-agnostic file provision logic in separate functions
"""

import json
import sys
from pathlib import Path
from datetime import datetime, timezone


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


_HOOKS_DIRS = [".claude", ".codex", ".gemini", ".agents"]


def _find_hooks_dir() -> Path:
    """Find the first existing hooks dir for any CLI."""
    cwd = Path.cwd()
    for d in _HOOKS_DIRS:
        hooks_dir = cwd / d / "hooks"
        if hooks_dir.is_dir():
            return hooks_dir
    return cwd / ".claude" / "hooks"  # fallback


def get_agent_id() -> str:
    """Read agent_id from hooks dir (multi-CLI aware)."""
    for d in _HOOKS_DIRS:
        path = Path.cwd() / d / "hooks" / "agent_id.txt"
        if path.exists():
            return path.read_text(encoding="utf-8").strip()
    return "unknown"


def load_stop_config() -> dict:
    """Load adapter-provided stop-hook config when available."""
    path = _find_hooks_dir() / "stop_config.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def get_stop_count() -> int:
    """Read current stop count."""
    path = _find_hooks_dir() / "stop_count.txt"
    if path.exists():
        try:
            return int(path.read_text(encoding="utf-8").strip())
        except (ValueError, OSError):
            pass
    return 0


def increment_stop_count() -> int:
    """Increment and return new stop count."""
    hooks_dir = _find_hooks_dir()
    hooks_dir.mkdir(parents=True, exist_ok=True)
    count = get_stop_count() + 1
    (hooks_dir / "stop_count.txt").write_text(str(count), encoding="utf-8")
    return count


# Default thresholds per role
DEFAULT_THRESHOLDS = {
    "PM": 50,
    "SOLO": 100,
    "CD": 40,
    "SE": 30,
    "PG": 20,
}


def get_stop_threshold(agent_id: str, project_root: Path | None = None) -> int:
    """Get stop threshold for agent."""
    stop_config = load_stop_config()
    max_stop_count = stop_config.get("max_stop_count")
    if isinstance(max_stop_count, int) and max_stop_count > 0:
        return max_stop_count

    # Try config file first
    if project_root:
        config_file = project_root / "Agent-shared" / "stop_thresholds.json"
        if config_file.exists():
            try:
                config = json.loads(config_file.read_text(encoding="utf-8"))
                thresholds = config.get("thresholds", {})
                if agent_id in thresholds:
                    return thresholds[agent_id]
                for prefix, val in thresholds.items():
                    if agent_id.startswith(prefix):
                        return val
            except (json.JSONDecodeError, OSError):
                pass

    # Fallback defaults
    for prefix, val in DEFAULT_THRESHOLDS.items():
        if agent_id.startswith(prefix) or agent_id == prefix:
            return val
    return 30


def load_file_provision_config(project_root: Path) -> dict:
    """Load file provision config."""
    config_file = (
        project_root
        / "Agent-shared"
        / "strategies"
        / "auto_tuning"
        / "auto_tuning_config.json"
    )
    if config_file.exists():
        try:
            return json.loads(config_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass

    return {
        "file_provision": {
            "always_full": [
                "requirement_definition.md",
                "Agent-shared/directory_pane_map.md",
                "CLAUDE.md",
            ],
            "periodic_full": {},
            "path_only": [],
        }
    }


def should_provide(file_path: str, probability: float, stop_count: int) -> bool:
    """Deterministic probabilistic file provision."""
    numerator = int(probability * 100)
    offset = hash(file_path) % 100
    return ((stop_count + offset) % 100) < numerator


def read_file_safe(path: Path, max_bytes: int = 10000) -> str | None:
    """Read file with size limit."""
    if not path.exists():
        return None
    try:
        content = path.read_text(encoding="utf-8")
        if len(content) > max_bytes:
            return content[:max_bytes] + "\n\n...[truncated]"
        return content
    except OSError:
        return None


def get_role(agent_id: str) -> str:
    """Extract role from agent_id."""
    if agent_id in ("PM", "SOLO"):
        return agent_id
    for prefix in ("CD", "SE", "PG"):
        if agent_id.startswith(prefix):
            return prefix
    return agent_id


def generate_embedded_content(
    stop_count: int, agent_id: str, project_root: Path
) -> str:
    """Generate context re-injection content."""
    config = load_file_provision_config(project_root)
    role = get_role(agent_id)
    parts = []

    # Always-provide files
    always = config.get("file_provision", {}).get("always_full", [])
    if always:
        parts.append("## Required File Contents\n")
        for fp in always:
            fp_resolved = fp.replace("{role}", role)
            content = read_file_safe(project_root / fp_resolved)
            if content:
                parts.append(f"### {fp_resolved}")
                parts.append(f"```\n{content}\n```\n")

    # Periodic files (probabilistic)
    periodic = config.get("file_provision", {}).get("periodic_full", {})
    ref_only = []
    for fp, fc in periodic.items():
        probs = fc.get("probabilities", {})
        prob = probs.get(role, 0)
        if prob <= 0:
            continue

        fp_resolved = fp.replace("{role}", role)
        if should_provide(fp, prob, stop_count):
            content = read_file_safe(project_root / fp_resolved)
            if content:
                parts.append(f"### {fp_resolved}")
                parts.append(f"```\n{content}\n```\n")
        else:
            ref_only.append(fp_resolved)

    if ref_only:
        parts.append("\n## Recommended Reference Files\n")
        for p in ref_only:
            parts.append(f"- {p}")

    return "\n".join(parts)


def get_elapsed_time(project_root: Path | None) -> str | None:
    """Get elapsed time since project start (for SOLO agent)."""
    if not project_root:
        return None
    start_file = project_root / "Agent-shared" / "project_start_time.txt"
    if not start_file.exists():
        return None
    try:
        start_str = start_file.read_text(encoding="utf-8").strip()
        start = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
        elapsed = datetime.now(start.tzinfo) - start
        total_sec = int(elapsed.total_seconds())
        hours, minutes = total_sec // 3600, (total_sec % 3600) // 60
        return f"{hours}h{minutes}m" if hours > 0 else f"{minutes}m"
    except (ValueError, OSError):
        return None


# Role-specific task hints for stop-block messages
_ROLE_TASKS = {
    "PM": [
        "Check progress of all agents — read their ChangeLog.md for new entries",
        "Verify directory_pane_map.md is up to date",
        "Budget check (pjstat / budget_tracker.py)",
        "Intervene with stalled agents (no update > 5 min → send message)",
        "Use: bash(sleep 180 &) then repeat this cycle",
    ],
    "SE": [
        "Monitor ChangeLog.md update status of each PG",
        "Generate SOTA update history graphs",
        "Check for pending job results (squeue / ls slurm-*.out)",
        "Use: bash(sleep 120 &) then repeat this cycle",
    ],
    "PG": [
        "Update ChangeLog.md and manage SOTA",
        "Check job queue status (squeue etc.)",
        "Analyze and fix compilation warnings",
        "Implement new optimization techniques",
    ],
    "CD": [
        "Check SOTA-achieving code from each PG",
        "Anonymization and git commit/push",
        "Verify .gitignore is up to date",
    ],
    "SOLO": [
        "Check latest ChangeLog.md entry",
        "Implement next version optimization",
        "Check job results and tune parameters",
        "SOTA determination and sota_local.txt update",
        "Check budget consumption status",
    ],
}


def generate_block_reason(stop_count: int, agent_id: str) -> str:
    """Generate the stop-block message."""
    project_root = find_project_root(Path.cwd())
    threshold = get_stop_threshold(agent_id, project_root)
    role = get_role(agent_id)

    # Elapsed time (useful for SOLO and PM)
    elapsed_str = get_elapsed_time(project_root)
    elapsed_info = f" [Elapsed: {elapsed_str}]" if elapsed_str else ""

    # Threshold reached — graceful shutdown
    if stop_count >= threshold:
        shutdown_msg = (
            f"STOP count has reached the limit ({threshold}). {elapsed_info}\n\n"
        )
        if role == "SOLO":
            shutdown_msg += (
                "Execute the following pre-shutdown tasks as a SOLO agent:\n"
                "1. Verify all items in requirement_definition.md\n"
                "2. Final update of ChangeLog.md\n"
                "3. Verify and organize SOTA-achieving code\n"
                "4. Create final report (as far as possible)\n"
            )
        else:
            shutdown_msg += (
                f"Report to PM and wait for instructions.\n"
                f'agent_send.sh PM "[{agent_id}] STOP limit reached. Awaiting instructions"'
            )
        return shutdown_msg

    header = (
        f"Polling agent ({agent_id}) must not idle.\n"
        f"[STOP: {stop_count}/{threshold}]{elapsed_info}\n\n"
    )

    content = ""
    if project_root:
        content = generate_embedded_content(stop_count, agent_id, project_root)

    # Role-specific task hints
    tasks = _ROLE_TASKS.get(role, [])
    task_section = ""
    if tasks:
        task_lines = "\n".join(f"{i}. {t}" for i, t in enumerate(tasks, 1))
        task_section = f"\n## {role} Ongoing Tasks\n{task_lines}\n"

    actions = f"""
## Next Actions
1. Review the file contents above
2. Execute priority tasks from the list above
3. Report progress: python3 -m vibecodehpc send <recipient> "message"
4. Wait with: bash(sleep 180 &)
5. Repeat 1-4 — do NOT stop

[Communication] python3 -m vibecodehpc send [recipient] "[{agent_id}] message"
(Remaining STOP: {threshold - stop_count})
"""

    return header + content + task_section + actions


def main():
    try:
        json.load(sys.stdin)  # consume input

        agent_id = get_agent_id()
        stop_count = increment_stop_count()
        reason = generate_block_reason(stop_count, agent_id)

        print(reason, file=sys.stderr)
        sys.exit(2)  # Block stop

    except Exception:
        sys.exit(0)


if __name__ == "__main__":
    main()
