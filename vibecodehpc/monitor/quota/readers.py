"""Quota readers. None of them opens a credential file.

- ``codex_rollouts``: the ``rate_limits`` that Codex CLI writes into its own
  session logs (``$CODEX_HOME/sessions/**/rollout-*.jsonl``). The values are
  the last snapshot Codex saw, so they are as fresh as the last Codex turn.
- ``claude_usage``: opens Claude Code in a private tmux session, shows
  ``/usage`` and reads the screen. The CLI uses its own login; no model
  request is made. Opt-in, POSIX with tmux only.
- ``command``: runs a command you supply that prints a JSON list of
  windows. Use it for any other provider.

Every reader returns ``QuotaWindow`` rows and raises nothing: a failure is
one row with ``error`` set.
"""

from __future__ import annotations

import glob
import json
import os
import re
import shlex
import subprocess
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_LABEL = re.compile(r"[^\w .,:/()+-]")
_PCT_USED = re.compile(r"(\d+(?:\.\d+)?)%\s*used")
_RESETS = re.compile(r"Resets\s+([^\n(]+?)(?:\s*\(|\s{2,}|$)")


@dataclass
class QuotaWindow:
    """One usage window of one account. Only non-secret fields."""

    provider: str
    account: str
    window: str = ""
    used_pct: Optional[float] = None
    resets_at: Optional[str] = None
    source: str = ""
    observed_at: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


def _label(value, limit: int = 40) -> str:
    return _LABEL.sub("", str(value or ""))[:limit]


def _pct(value) -> Optional[float]:
    if isinstance(value, bool):
        return None
    try:
        pct = float(value)
    except (TypeError, ValueError):
        return None
    return pct if 0.0 <= pct <= 100.0 else None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _iso_from_epoch(value) -> Optional[str]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        return datetime.fromtimestamp(value, timezone.utc).isoformat(timespec="seconds")
    except (OverflowError, OSError, ValueError):
        return None


def _window_name(minutes) -> str:
    try:
        minutes = int(minutes)
    except (TypeError, ValueError):
        return "unknown"
    return {300: "5h", 10080: "week"}.get(minutes, f"{minutes}m")


def failure(provider: str, account: str, source: str, error: str) -> QuotaWindow:
    return QuotaWindow(provider=_label(provider), account=_label(account), source=source,
                       observed_at=_now_iso(), error=_label(error, 120))


# ── Codex CLI: rate_limits in rollout logs ────────────────────────────────

def _find_rate_limits(obj) -> Optional[dict]:
    if isinstance(obj, dict):
        if isinstance(obj.get("rate_limits"), dict):
            return obj["rate_limits"]
        for value in obj.values():
            found = _find_rate_limits(value)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for value in obj:
            found = _find_rate_limits(value)
            if found is not None:
                return found
    return None


def codex_rollouts(codex_home: str = "~/.codex", account: str = "default",
                   max_age_s: float = 6 * 3600, max_files: int = 20) -> list[QuotaWindow]:
    """Newest rate_limits per plan type from recent Codex session logs."""
    home = Path(os.path.expanduser(codex_home))
    files = glob.glob(str(home / "sessions" / "**" / "rollout-*.jsonl"), recursive=True)
    now = time.time()
    files = [f for f in files if now - os.path.getmtime(f) <= max_age_s]
    files = sorted(files, key=os.path.getmtime, reverse=True)[:max_files]
    if not files:
        return [failure("codex", account, "codex_rollouts", "no recent session log")]

    newest: dict[str, tuple[str, dict]] = {}
    for path in files:
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    if '"rate_limits"' not in line:
                        continue
                    try:
                        record = json.loads(line)
                    except ValueError:
                        continue
                    limits = _find_rate_limits(record)
                    if not limits:
                        continue
                    stamp = str(record.get("timestamp") or "")
                    plan = _label(limits.get("plan_type") or "unknown")
                    if plan not in newest or stamp > newest[plan][0]:
                        newest[plan] = (stamp, limits)
        except OSError:
            continue
    if not newest:
        return [failure("codex", account, "codex_rollouts", "no rate_limits in recent logs")]

    rows = []
    for plan, (stamp, limits) in sorted(newest.items()):
        for key in ("primary", "secondary"):
            window = limits.get(key)
            if not isinstance(window, dict):
                continue
            rows.append(QuotaWindow(
                provider="codex", account=_label(f"{account}:{plan}"),
                window=_window_name(window.get("window_minutes")),
                used_pct=_pct(window.get("used_percent")),
                resets_at=_iso_from_epoch(window.get("resets_at")),
                source="codex_rollouts", observed_at=stamp[:32] or _now_iso()))
    return rows or [failure("codex", account, "codex_rollouts", "rate_limits without windows")]


# ── Claude Code: the /usage screen ────────────────────────────────────────

def parse_usage_screen(text: str, account: str) -> list[QuotaWindow]:
    """Windows shown by Claude Code's /usage (each heading, then '<n>% used')."""
    lines = text.splitlines()
    rows = []
    for i, line in enumerate(lines):
        if "Current session" in line:
            window = "5h"
        elif "Current week (all models)" in line:
            window = "week"
        elif "Current week (" in line:
            window = "week:" + _label(line.split("Current week (", 1)[1].split(")")[0], 30)
        else:
            continue
        block = " ".join(lines[i:i + 4])
        used = _PCT_USED.search(block)
        resets = _RESETS.search(block)
        rows.append(QuotaWindow(
            provider="claude", account=_label(account), window=window,
            used_pct=_pct(used.group(1)) if used else None,
            resets_at=_label(resets.group(1).strip(), 40) if resets else None,
            source="claude_usage", observed_at=_now_iso()))
    return rows


def _tmux(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["tmux", *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def claude_usage(account: str = "default", config_dir: Optional[str] = None,
                 claude: str = "claude", workdir: Optional[str] = None,
                 wait_s: float = 60) -> list[QuotaWindow]:
    """Start Claude Code in a private tmux session, read /usage, then exit."""
    session = "vchpc_usage_" + re.sub(r"\W", "_", account)
    if _tmux("has-session", "-t", session).returncode == 0:
        return [failure("claude", account, "claude_usage", "previous reading still running")]
    env = (f"CLAUDE_CONFIG_DIR={shlex.quote(os.path.expanduser(config_dir))} "
           if config_dir else "")
    cwd = shlex.quote(workdir or os.getcwd())
    started = _tmux("new-session", "-d", "-s", session, "-x", "200", "-y", "60",
                    f"cd {cwd} && {env}{shlex.quote(claude)}; sleep 30")
    if started.returncode != 0:
        return [failure("claude", account, "claude_usage", "tmux new-session failed")]
    try:
        deadline = time.time() + wait_s
        while time.time() < deadline:
            time.sleep(2)
            if "❯" in _tmux("capture-pane", "-p", "-t", session).stdout:
                break
        _tmux("send-keys", "-t", session, "-l", "/usage")
        time.sleep(1)
        _tmux("send-keys", "-t", session, "Enter")
        time.sleep(10)
        screen = _tmux("capture-pane", "-p", "-S", "-150", "-t", session).stdout
    finally:
        _tmux("send-keys", "-t", session, "Escape")
        time.sleep(1)
        _tmux("send-keys", "-t", session, "-l", "/exit")
        time.sleep(1)
        _tmux("send-keys", "-t", session, "Enter")
    rows = parse_usage_screen(screen, account)
    return rows or [failure("claude", account, "claude_usage", "usage screen not recognised")]


# ── Any provider: a command that prints JSON ──────────────────────────────

def command(cmd: list, provider: str = "other", account: str = "default",
            timeout_s: float = 60) -> list[QuotaWindow]:
    """Run ``cmd``; stdout must be a JSON list of objects with ``window``,
    ``used_pct`` and optionally ``resets_at``, ``provider``, ``account``.
    Other fields are dropped."""
    try:
        proc = subprocess.run([str(c) for c in cmd], capture_output=True, text=True,
                              encoding="utf-8", errors="replace",
                              timeout=timeout_s)
        items = json.loads(proc.stdout)
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        return [failure(provider, account, "command", type(exc).__name__)]
    if not isinstance(items, list):
        return [failure(provider, account, "command", "output is not a JSON list")]
    rows = []
    for item in items:
        if not isinstance(item, dict):
            continue
        rows.append(QuotaWindow(
            provider=_label(item.get("provider") or provider),
            account=_label(item.get("account") or account),
            window=_label(item.get("window")), used_pct=_pct(item.get("used_pct")),
            resets_at=_label(item.get("resets_at"), 40) or None,
            source="command", observed_at=_now_iso()))
    return rows or [failure(provider, account, "command", "no windows in output")]
