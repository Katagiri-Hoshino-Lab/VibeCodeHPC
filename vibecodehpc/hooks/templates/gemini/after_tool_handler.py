#!/usr/bin/env python3
"""VibeCodeHPC AfterTool Hook for SSH/SFTP validation (Gemini CLI).

Validates SSH/SFTP usage and provides session management guidance.
Mirrors the Claude Code post_tool_handler.py, adapted for Gemini's
AfterTool hook event.

Gemini stdin: {"event": "AfterTool", "tool_name": "...", "tool_input": {...}, ...}
Exit 0 → advisory only.
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

        # Gemini tool names may differ — accept shell/execute_command/Bash
        if tool_name not in ("shell", "execute_command", "Bash"):
            sys.exit(0)

        tool_input = input_data.get("tool_input", {})
        command = tool_input.get("command", "")
        if not command.strip().startswith(("ssh ", "sftp ", "scp ")):
            sys.exit(0)

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
        sys.exit(0)  # Advisory only

    except Exception:
        sys.exit(0)


if __name__ == "__main__":
    main()
