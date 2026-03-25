#!/usr/bin/env python3
"""VibeCodeHPC PreToolUse Hook for SSH/SFTP validation (Claude Code).

Warns before direct Bash SSH/SFTP usage and suggests session management.
Ported from VibeCodeHPC-jp/hooks/templates/pre_tool_ssh_validator.py.

Key changes:
- Removed Desktop Commander MCP references (using Bash SSH directly)
- Advisory only (exit 0), does not block
"""

import json
import re
import sys
from pathlib import Path


def check_sessions_file() -> bool:
    """Check if ssh_sftp_sessions.json exists and has entries."""
    path = Path.cwd() / "ssh_sftp_sessions.json"
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return len(data.get("sessions", [])) > 0
        except (json.JSONDecodeError, OSError):
            pass
    return False


def main():
    try:
        input_data = json.load(sys.stdin)
        tool_name = input_data.get("tool_name", "")
        tool_input = input_data.get("tool_input", {})

        if tool_name != "Bash":
            sys.exit(0)

        command = tool_input.get("command", "")
        if not re.match(r"^\s*(ssh|sftp|scp)\s+", command):
            sys.exit(0)

        has_sessions = check_sessions_file()

        warning = f"""SSH/SFTP command detected:
- Refer to Agent-shared/ssh_sftp_guide.md
- Session management via ssh_sftp_sessions.json is required
{"- Existing session file detected" if has_sessions else "- Session file not yet created"}

Note: Be mindful of context consumption from large output."""

        print(warning, file=sys.stderr)
        sys.exit(0)  # Advisory only, don't block

    except Exception:
        sys.exit(0)


if __name__ == "__main__":
    main()
