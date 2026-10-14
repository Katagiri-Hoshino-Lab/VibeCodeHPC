"""Read every configured quota source, record it, and set the launch gate.

Config: ``Agent-shared/quota_config.json`` (or ``--config``)::

    {
      "sources": [
        {"type": "codex_rollouts", "account": "personal", "codex_home": "~/.codex"},
        {"type": "claude_usage", "account": "personal"},
        {"type": "command", "provider": "other", "command": ["python3", "my_reader.py"]}
      ],
      "thresholds": {"claude": {"5h": 90, "week": 90}, "codex/personal": {"week": 85}},
      "notify": "PM"
    }

Outputs under ``Agent-shared/quota/``:

- ``usage.jsonl``: every reading, one window per line;
- ``quota.log``: one summary line per reading;
- ``state.json``: the latest windows, ``pause_new_seats`` and its reasons,
  valid for three reading intervals (a stopped keeper stops gating).

When the gate opens or closes, PM is told once with ``vibecodehpc send``.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from vibecodehpc.monitor.quota import QUOTA_DIR, STATE_FILE
from vibecodehpc.monitor.quota import readers

CONFIG_FILE = Path("Agent-shared") / "quota_config.json"


def read_sources(sources: list[dict], project_root: Path) -> list[readers.QuotaWindow]:
    rows: list[readers.QuotaWindow] = []
    for source in sources:
        kind = source.get("type")
        account = source.get("account", "default")
        if kind == "codex_rollouts":
            rows += readers.codex_rollouts(source.get("codex_home", "~/.codex"), account,
                                           float(source.get("max_age_s", 6 * 3600)))
        elif kind == "claude_usage":
            rows += readers.claude_usage(account, source.get("config_dir"),
                                         source.get("claude", "claude"), str(project_root))
        elif kind == "command":
            rows += readers.command(source.get("command") or [], source.get("provider", "other"),
                                    account)
        else:
            rows.append(readers.failure(str(kind), account, "config", "unknown source type"))
    return rows


def threshold_for(thresholds: dict, row: readers.QuotaWindow):
    """The most specific threshold: provider/account, then provider."""
    base_account = row.account.split(":", 1)[0]
    for key in (f"{row.provider}/{row.account}", f"{row.provider}/{base_account}", row.provider):
        table = thresholds.get(key)
        if isinstance(table, dict) and row.window in table:
            return table[row.window]
    return None


def decide(rows: list[readers.QuotaWindow], thresholds: dict) -> list[str]:
    """Reasons to pause new agents (empty: keep going)."""
    reasons = []
    for row in rows:
        limit = threshold_for(thresholds, row)
        if row.used_pct is not None and limit is not None and row.used_pct >= float(limit):
            reasons.append(f"{row.provider}/{row.account} {row.window} "
                           f"{row.used_pct:g}% >= {float(limit):g}%")
    return reasons


def summary_line(as_of: str, rows: list[readers.QuotaWindow], reasons: list[str]) -> str:
    groups: dict[str, list[str]] = {}
    for row in rows:
        name = f"{row.provider}/{row.account}"
        if row.error:
            groups.setdefault(name, []).append("na")
        else:
            pct = "na" if row.used_pct is None else f"{row.used_pct:g}%"
            groups.setdefault(name, []).append(f"{row.window} {pct}")
    parts = [f"{name} " + " / ".join(items) for name, items in groups.items()]
    parts.append("pause_new_seats " + ("yes" if reasons else "no"))
    if reasons:
        parts.append("; ".join(reasons))
    return as_of + " " + " | ".join(parts)


def notify(project_root: Path, target: str, text: str) -> bool:
    proc = subprocess.run([sys.executable, "-m", "vibecodehpc", "send", target, text],
                          cwd=project_root, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    return proc.returncode == 0


def run_once(project_root: Path, config: dict, interval_s: float) -> dict:
    """One reading: record it, update the gate, notify on a change."""
    out_dir = project_root / QUOTA_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = read_sources(config.get("sources") or [], project_root)
    reasons = decide(rows, config.get("thresholds") or {})
    now = datetime.now(timezone.utc)
    as_of = now.isoformat(timespec="seconds")

    with (out_dir / "usage.jsonl").open("a", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row.to_dict(), ensure_ascii=False) + "\n")
    with (out_dir / "quota.log").open("a", encoding="utf-8") as fh:
        fh.write(summary_line(as_of, rows, reasons) + "\n")

    state_path = project_root / STATE_FILE
    try:
        was_paused = bool(json.loads(state_path.read_text(encoding="utf-8")).get("pause_new_seats"))
    except (OSError, ValueError):
        was_paused = False
    state = {
        "as_of": as_of,
        "valid_until": (now + timedelta(seconds=3 * interval_s)).isoformat(timespec="seconds"),
        "pause_new_seats": bool(reasons),
        "reasons": reasons,
        "windows": [row.to_dict() for row in rows],
    }
    tmp = state_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(state_path)

    target = config.get("notify")
    if target and bool(reasons) != was_paused:
        text = ("[TK] [Warning] Quota: do not start new agents ("
                + "; ".join(reasons) + "). Finish running work; launch waits for the reset."
                if reasons else
                "[TK] [Report] Quota back under the thresholds; new agents may start again.")
        state["notified"] = notify(project_root, target, text)
    return state


def load_config(path: Path) -> dict:
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SystemExit(f"cannot read quota config {path}: {exc}")
    if not isinstance(config, dict):
        raise SystemExit(f"quota config {path} must be a JSON object")
    return config


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Token Keeper: record quota windows, gate launches.")
    p.add_argument("--project-root", type=Path, default=Path.cwd())
    p.add_argument("--config", type=Path, default=None,
                   help=f"default: <project root>/{CONFIG_FILE}")
    group = p.add_mutually_exclusive_group()
    group.add_argument("--once", action="store_true", help="read once and exit (for cron)")
    group.add_argument("--interval", type=float, default=300, help="seconds between readings")
    args = p.parse_args(argv)
    root = args.project_root.resolve()
    config = load_config(args.config or root / CONFIG_FILE)
    interval = float(config.get("interval_s", args.interval))

    while True:
        state = run_once(root, config, interval)
        print(summary_line(state["as_of"], [readers.QuotaWindow(**w) for w in state["windows"]],
                           state["reasons"]), flush=True)
        if args.once:
            return
        time.sleep(interval)


if __name__ == "__main__":
    main()
