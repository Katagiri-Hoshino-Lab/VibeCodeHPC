#!/usr/bin/env python3
"""VibeCodeHPC hook: deliver queued messages into a Claude Code session.

Used by the optional ``cross_session`` IPC backend, where there is no tmux
pane to type into. The framework appends messages to a JSONL inbox; this
hook takes them at the next event of the session:

- UserPromptSubmit / PostToolUse: added to the context
  (``hookSpecificOutput.additionalContext``);
- Stop: the stop is blocked with the messages as the reason, so the agent
  continues and reads them.

The inbox path is in ``inbox_path.txt`` next to this script. Standard
library only (runs on native Windows). Any error: exit 0, deliver nothing.
"""

import json
import os
import sys
from pathlib import Path


def drain(inbox: Path) -> list:
    """Take all queued messages. A message appended meanwhile waits for the next event."""
    taken = inbox.with_name(f"{inbox.name}.{os.getpid()}.taking")
    try:
        os.replace(inbox, taken)
    except OSError:
        return []
    messages = []
    try:
        for line in taken.read_text(encoding="utf-8").splitlines():
            try:
                item = json.loads(line)
            except ValueError:
                continue
            if isinstance(item, dict) and item.get("text"):
                messages.append(item)
    finally:
        try:
            taken.unlink()
        except OSError:
            pass
    return messages


def main() -> None:
    try:
        event = json.load(sys.stdin).get("hook_event_name", "")
    except (ValueError, AttributeError):
        event = ""
    try:
        inbox = Path((Path(__file__).resolve().parent / "inbox_path.txt")
                     .read_text(encoding="utf-8").strip())
    except OSError:
        sys.exit(0)
    messages = drain(inbox)
    if not messages:
        sys.exit(0)

    text = "Messages for you (VibeCodeHPC):\n" + "\n".join(
        f"[{m.get('from', 'framework')}] {m['text']}" for m in messages)
    if event == "Stop":
        print(json.dumps({"decision": "block", "reason": text}))
    else:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": event or "PostToolUse", "additionalContext": text}}))
    sys.exit(0)


if __name__ == "__main__":
    main()
