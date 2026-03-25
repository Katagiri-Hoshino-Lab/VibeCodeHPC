#!/usr/bin/env python3
"""Generate hooks.json configuration for Gemini CLI.

Gemini CLI reads hooks from ``.gemini/hooks.json`` at the project level
or ``~/.gemini/hooks.json`` globally.  Each hook specifies an event type
(``BeforeTool``, ``AfterTool``, ``SessionStart``) and a shell command to
execute.  Exit code 2 blocks the event (same semantics as Claude Code).

This module generates the hooks.json content that wires Gemini CLI into
the VibeCodeHPC hook scripts (session_start, stop_polling, after_tool).
"""

import json
from pathlib import Path
from typing import Optional


def generate_hooks_json(
    hooks_dir: Optional[str] = None,
    enable_session_start: bool = True,
    enable_stop_polling: bool = True,
    enable_after_tool: bool = True,
) -> dict:
    """Generate hooks.json config dict for Gemini CLI.

    Args:
        hooks_dir: Directory containing the hook scripts.
            Defaults to ``vibecodehpc/hooks/templates/gemini``.
        enable_session_start: Enable the SessionStart hook.
        enable_stop_polling: Enable the Stop-blocking hook (BeforeTool on idle).
        enable_after_tool: Enable the AfterTool SSH/SFTP validation hook.

    Returns:
        A dict suitable for writing as hooks.json.
    """
    if hooks_dir is None:
        hooks_dir = "vibecodehpc/hooks/templates/gemini"

    hooks = []

    if enable_session_start:
        hooks.append({
            "event": "SessionStart",
            "command": f"python3 {hooks_dir}/session_start.py",
            "description": "VibeCodeHPC agent registration and context injection",
        })

    if enable_stop_polling:
        hooks.append({
            "event": "Stop",
            "command": f"python3 {hooks_dir}/stop_polling.py",
            "description": "Anti-idle: block Stop and re-inject context (exit 2)",
        })

    if enable_after_tool:
        hooks.append({
            "event": "AfterTool",
            "command": f"python3 {hooks_dir}/after_tool_handler.py",
            "matcher": "shell|execute_command",
            "description": "SSH/SFTP session tracking (advisory, exit 0)",
        })

    return {"hooks": hooks}


def write_hooks_json(
    target_dir: Path,
    hooks_dir: Optional[str] = None,
    **kwargs,
) -> Path:
    """Write hooks.json to a .gemini/ directory.

    Args:
        target_dir: Project root (hooks.json will be written to
            ``target_dir/.gemini/hooks.json``).
        hooks_dir: Override script directory path.
        **kwargs: Forwarded to :func:`generate_hooks_json`.

    Returns:
        Path to the written hooks.json.
    """
    gemini_dir = target_dir / ".gemini"
    gemini_dir.mkdir(parents=True, exist_ok=True)
    out_path = gemini_dir / "hooks.json"

    config = generate_hooks_json(hooks_dir=hooks_dir, **kwargs)
    out_path.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return out_path
