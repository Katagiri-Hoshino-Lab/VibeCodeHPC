#!/usr/bin/env python3
"""VibeCodeHPC PostToolUse Hook for SSH/SFTP validation (Claude Code).

Validates SSH/SFTP usage and provides session management guidance.
Refactored from VibeCodeHPC-jp/hooks/templates/post_tool_ssh_handler.py.

Key changes:
- Removed Desktop Commander MCP dependency (using Bash SSH directly)
- Simplified to guidance-only (no blocking)
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
        if not command.strip().startswith(("ssh ", "sftp ", "scp ")):
            sys.exit(0)

        # Extract potential PID from response
        tool_response = str(input_data.get("tool_response", ""))
        pid_match = re.search(r"PID (\d+)", tool_response)
        pid_info = f"PID: {pid_match.group(1)}" if pid_match else ""

        has_sessions = check_sessions_file()

        message = f"""SSH/SFTP command detected: {command[:80]}
{pid_info}

Session management:
- Please manage sessions via ssh_sftp_sessions.json
{"- Existing session file detected" if has_sessions else "- Session file not yet created"}
- Refer to Agent-shared/ssh_sftp_guide.md

Continue your work.
"""
        print(message, file=sys.stderr)
        sys.exit(0)  # Advisory only, don't block

    except Exception:
        sys.exit(0)


if __name__ == "__main__":
    main()
