#!/usr/bin/env python3
"""Prepare a HOME so that Claude Code starts unattended in tmux panes.

``vibecodehpc setup`` and ``launch`` press Enter once, 3 s after starting
the CLI. That clears the folder-trust prompt but not the first-run
onboarding or the bypass-permissions warning, whose default choice exits.
On a batch node nobody is there to answer them. This script writes the
answers in advance:

- ``~/.claude.json``: onboarding done, the project root (and
  ``Agent-workdir/``) trusted, bypass-permissions warning accepted,
  auto-update off.
- ``~/.claude/settings.json``: no auto-update or telemetry traffic,
  optional effort level and output cap, and with ``--text-only`` a
  PreToolUse hook that refuses Read on images, PDFs and videos.
- ``~/.tmux.conf``: a large default size, because v2 creates its sessions
  detached (80x24) and splitting many panes in a small window can fail.

Existing files are merged, not replaced, so a HOME restored from an
earlier job keeps its conversations and settings. Running it twice gives
the same result.

Usage:
    python3 vibecodehpc/scripts/seed_claude_home.py HOME PROJECT_ROOT
        [--text-only] [--effort LEVEL] [--max-output-tokens N]
        [--trust DIR ...] [--tmux-size WxH] [--plain-shell]

Intended for a dedicated HOME (for example a node-local directory set as
HOME inside a batch job), not for a personal HOME.
"""

from __future__ import annotations

import argparse
import json
import shlex
import shutil
import sys
from pathlib import Path

HOOK_TEMPLATE = (
    Path(__file__).resolve().parent.parent
    / "hooks" / "templates" / "claude" / "deny_media_read.py"
)

QUIET_ENV = {
    "DISABLE_AUTOUPDATER": "1",
    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
    "DISABLE_TELEMETRY": "1",
    "DISABLE_ERROR_REPORTING": "1",
}


def load_json(path: Path) -> dict:
    """Read a JSON object, returning {} if the file is missing or broken."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def merge(base: dict, patch: dict) -> dict:
    """Recursively merge *patch* into *base* (dicts merge, other values replace)."""
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            merge(base[key], value)
        else:
            base[key] = value
    return base


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")


def seed_claude_json(home: Path, trusted: list[Path]) -> None:
    """Mark onboarding as done and the given directories as trusted."""
    project = {
        "hasTrustDialogAccepted": True,
        "hasCompletedProjectOnboarding": True,
    }
    patch = {
        "hasCompletedOnboarding": True,
        "bypassPermissionsModeAccepted": True,
        "autoUpdates": False,
        "projects": {str(d): dict(project) for d in trusted},
    }
    path = home / ".claude.json"
    data = load_json(path)
    data.setdefault("theme", "dark")
    write_json(path, merge(data, patch))


def add_read_hook(settings: dict, command: str) -> None:
    """Add a PreToolUse(Read) hook entry unless the same command is present."""
    entries = settings.setdefault("hooks", {}).setdefault("PreToolUse", [])
    for entry in entries:
        for hook in entry.get("hooks", []):
            if hook.get("command") == command:
                return
    entries.append({
        "matcher": "Read",
        "hooks": [{"type": "command", "command": command}],
    })


def seed_settings(home: Path, text_only: bool, effort: str | None,
                  max_output_tokens: int | None) -> None:
    """Write user-level settings shared by every agent that uses this HOME."""
    path = home / ".claude" / "settings.json"
    settings = load_json(path)
    env = dict(QUIET_ENV)
    patch: dict = {"skipDangerousModePermissionPrompt": True}
    if effort:
        patch["effortLevel"] = effort
        env["CLAUDE_CODE_EFFORT_LEVEL"] = effort
        # Send the effort level also for model names Claude Code does not know.
        env["CLAUDE_CODE_ALWAYS_ENABLE_EFFORT"] = "1"
    if max_output_tokens:
        env["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] = str(max_output_tokens)
    patch["env"] = env
    merge(settings, patch)

    if text_only:
        hook_dir = home / ".claude" / "hooks"
        hook_dir.mkdir(parents=True, exist_ok=True)
        hook = hook_dir / HOOK_TEMPLATE.name
        shutil.copy2(HOOK_TEMPLATE, hook)
        hook.chmod(0o755)
        command = f"{shlex.quote(sys.executable)} {shlex.quote(str(hook))}"
        add_read_hook(settings, command)

    write_json(path, settings)


def seed_tmux_conf(home: Path, size: str, plain_shell: bool) -> None:
    """Set tmux options in ~/.tmux.conf, keeping unrelated lines."""
    options = {"history-limit": "20000"}
    if size:
        options["default-size"] = size
    if plain_shell:
        # A login shell would re-read /etc/profile and may reset the
        # environment the job script exported (PATH, ANTHROPIC_*).
        options["default-command"] = '"exec bash --noprofile --norc"'

    path = home / ".tmux.conf"
    kept = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            words = line.split()
            if len(words) >= 3 and words[0] == "set" and words[2] in options:
                continue
            kept.append(line)
    kept += [f"set -g {name} {value}" for name, value in options.items()]
    path.write_text("\n".join(kept) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Pre-answer Claude Code first-run prompts in a HOME.")
    parser.add_argument("home", type=Path, help="HOME directory to prepare")
    parser.add_argument("project_root", type=Path,
                        help="VibeCodeHPC project root to trust")
    parser.add_argument("--trust", type=Path, action="append", default=[],
                        help="additional directory to trust (repeatable)")
    parser.add_argument("--text-only", action="store_true",
                        help="install the hook that refuses Read on media files")
    parser.add_argument("--effort", default=None,
                        help="effort level for every agent (e.g. high, xhigh)")
    parser.add_argument("--max-output-tokens", type=int, default=None,
                        help="CLAUDE_CODE_MAX_OUTPUT_TOKENS; keep prompt + "
                             "output below the server's max model length")
    parser.add_argument("--tmux-size", default="280x80",
                        help="tmux default-size; an empty string leaves it unset")
    parser.add_argument("--plain-shell", action="store_true",
                        help="start tmux panes with bash --noprofile --norc")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    home = args.home.resolve()
    root = args.project_root.resolve()
    (home / ".claude").mkdir(parents=True, exist_ok=True)

    trusted = [root, root / "Agent-workdir"] + [d.resolve() for d in args.trust]
    seed_claude_json(home, trusted)
    seed_settings(home, args.text_only, args.effort, args.max_output_tokens)
    seed_tmux_conf(home, args.tmux_size, args.plain_shell)
    print(f"seeded {home} for {root}")


if __name__ == "__main__":
    main()
