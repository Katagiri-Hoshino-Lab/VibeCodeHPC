"""Token Keeper: subscription quota windows as input for starting agents.

Flat-rate CLI subscriptions have usage windows (for example 5 hours and
one week). The keeper reads how much of each window is used, records it
every few minutes, and closes a gate when a window passes its threshold.
While the gate is closed, ``vibecodehpc launch`` does not start new
agents (``--ignore-quota`` overrides), and PM is told once.

Readers never open credential files: they read the CLIs' own session
logs, the CLI's own usage screen, or the output of a command you supply.
Only percentages, window names and reset times are stored.

Run: ``python3 -m vibecodehpc.monitor.quota --once`` (from cron or the
Task Scheduler) or ``--interval 300``. See docs/token_keeper.md.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

QUOTA_DIR = Path("Agent-shared") / "quota"
STATE_FILE = QUOTA_DIR / "state.json"


def read_gate(project_root: Path) -> tuple[bool, list[str]]:
    """Return (paused, reasons) from the keeper's state file.

    A missing, unreadable or expired state never pauses anything, so a
    stopped keeper cannot block launches.
    """
    path = Path(project_root) / STATE_FILE
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        valid_until = datetime.fromisoformat(state["valid_until"])
    except (OSError, ValueError, KeyError, TypeError):
        return False, []
    if valid_until.tzinfo is None:
        valid_until = valid_until.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) > valid_until:
        return False, []
    if not state.get("pause_new_seats"):
        return False, []
    return True, [str(r) for r in state.get("reasons") or []]
