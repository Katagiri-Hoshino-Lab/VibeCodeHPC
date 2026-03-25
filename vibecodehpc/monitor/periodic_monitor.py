"""Periodic monitor — background process for context/budget monitoring and milestone snapshots.

Python port of VibeCodeHPC-jp/telemetry/periodic_monitor.sh.
Launched from PM/SOLO session_start hook.
"""

import json
import logging
import os
import re
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Ensure vibecodehpc package is importable when run as a standalone script
# (e.g. python3 vibecodehpc/monitor/periodic_monitor.py) without PYTHONPATH.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from vibecodehpc.registry import AgentRegistry
from vibecodehpc.tmux_utils import session_exists

logger = logging.getLogger(__name__)


@dataclass
class MonitorConfig:
    """Configuration for periodic monitor intervals."""

    update_interval_sec: int = 30
    milestone_interval_min: int = 30
    max_runtime_min: int = 120  # 2 hours default
    budget_interval_min: int = 3
    milestones: list[int] = field(default_factory=lambda: [30, 60, 90, 120, 180])

    @classmethod
    def from_file(cls, path: Path) -> "MonitorConfig":
        """Load config overrides from a JSON file."""
        config = cls()
        if not path.exists():
            return config
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            for key in (
                "update_interval_sec",
                "milestone_interval_min",
                "max_runtime_min",
                "budget_interval_min",
            ):
                if key in data:
                    setattr(config, key, int(data[key]))
            if "milestones" in data:
                config.milestones = [int(m) for m in data["milestones"]]
        except (json.JSONDecodeError, ValueError, TypeError):
            pass
        return config


def _find_python() -> str:
    """Find available python command."""
    for cmd in ("python3", "python"):
        try:
            subprocess.run(
                [cmd, "--version"], capture_output=True, check=True
            )
            return cmd
        except (subprocess.CalledProcessError, FileNotFoundError):
            continue
    return "python3"


def _run_script(python_cmd: str, script_path: Path, args: list[str],
                timeout: int = 120) -> Optional[str]:
    """Run a Python script and return its stdout, or None on failure."""
    if not script_path.exists():
        return None
    try:
        result = subprocess.run(
            [python_cmd, str(script_path), *args],
            capture_output=True, text=True, timeout=timeout,
        )
        return result.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        logger.warning("Script %s failed: %s", script_path.name, exc)
        return None


class PeriodicMonitor:
    """Background periodic monitor for context usage, budget, and milestones.

    Monitors all registered agents, runs context and budget scripts at
    configured intervals, and saves milestone snapshots at key time points.
    """

    def __init__(
        self,
        project_root: Path,
        project_name: str,
        registry: AgentRegistry,
        config: Optional[MonitorConfig] = None,
    ):
        self.project_root = Path(project_root)
        self.project_name = project_name
        self.registry = registry
        self.config = config or MonitorConfig()
        self._python_cmd = _find_python()
        self._running = False
        self._update_thread: Optional[threading.Thread] = None
        self._milestone_thread: Optional[threading.Thread] = None
        self._start_epoch: float = 0.0
        self._last_milestone: int = 0
        self._log_path = self.project_root / "Agent-shared" / "logs" / "periodic_monitor.log"
        self._pid_path = self.project_root / "Agent-shared" / "logs" / "periodic_monitor.pid"

        # Script paths
        self._context_script = (
            self.project_root
            / "Agent-shared" / "skills" / "context-monitor" / "scripts" / "context_monitor.py"
        )
        self._budget_script = (
            self.project_root
            / "Agent-shared" / "skills" / "budget-tracking" / "scripts" / "budget_tracker.py"
        )

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------

    def _log(self, message: str) -> None:
        """Append timestamped message to monitor log file."""
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        line = f"[{ts}] {message}\n"
        try:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._log_path, "a", encoding="utf-8") as f:
                f.write(line)
        except OSError:
            pass
        logger.info(message)

    # ------------------------------------------------------------------
    # PID management
    # ------------------------------------------------------------------

    def _read_pid(self) -> Optional[int]:
        """Read PID from pid file."""
        try:
            return int(self._pid_path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return None

    def _is_pid_alive(self, pid: int) -> bool:
        """Check if a process with given PID is alive."""
        try:
            os.kill(pid, 0)
            return True
        except (OSError, ProcessLookupError):
            return False

    def _cleanup_existing(self) -> None:
        """Kill any existing monitor process (prevent double-start)."""
        old_pid = self._read_pid()
        if old_pid is not None and self._is_pid_alive(old_pid):
            self._log(f"Killing existing monitor process: {old_pid}")
            try:
                os.kill(old_pid, signal.SIGTERM)
            except OSError:
                pass

    def _write_pid(self) -> None:
        """Write current PID to pid file."""
        self._pid_path.parent.mkdir(parents=True, exist_ok=True)
        self._pid_path.write_text(str(os.getpid()), encoding="utf-8")

    def _remove_pid(self) -> None:
        """Remove pid file on exit."""
        try:
            self._pid_path.unlink(missing_ok=True)
        except OSError:
            pass

    # ------------------------------------------------------------------
    # Project start time tracking
    # ------------------------------------------------------------------

    def _get_or_create_start_time(self) -> float:
        """Read or create project_start_time.txt, return epoch seconds."""
        start_file = self.project_root / "Agent-shared" / "project_start_time.txt"
        start_file.parent.mkdir(parents=True, exist_ok=True)

        if start_file.exists():
            try:
                ts = start_file.read_text(encoding="utf-8").strip()
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                return dt.timestamp()
            except (ValueError, OSError):
                pass

        # Create new start time
        now = datetime.now(timezone.utc)
        start_file.write_text(now.strftime("%Y-%m-%dT%H:%M:%SZ"), encoding="utf-8")
        return now.timestamp()

    def _elapsed_minutes(self) -> int:
        """Return minutes elapsed since project start."""
        if self._start_epoch <= 0:
            return 0
        return int((time.time() - self._start_epoch) / 60)

    # ------------------------------------------------------------------
    # tmux session checks
    # ------------------------------------------------------------------

    def _sessions_alive(self) -> bool:
        """Check if any project tmux sessions still exist."""
        pm_session = f"{self.project_name}_PM"
        worker_session = f"{self.project_name}_Workers1"
        solo_session = f"{self.project_name}_SOLO"
        return (
            session_exists(pm_session)
            or session_exists(worker_session)
            or session_exists(solo_session)
        )

    # ------------------------------------------------------------------
    # Monitoring actions
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # vibe-local context tracking (tmux capture + Ollama API)
    # ------------------------------------------------------------------

    # vibe-coder's DEFAULT_CONTEXT_WINDOW (fallback if Ollama API unreachable)
    VIBE_LOCAL_DEFAULT_CONTEXT = 32768
    _ollama_context_limit: int = 0  # cached per monitor lifetime

    def _get_ollama_context_limit(self) -> int:
        """Query Ollama /api/ps for the runtime context_length of the loaded model.

        Ollama's /api/ps returns the actual KV cache size allocated by the runner,
        which reflects the num_ctx sent by the client (vibe-coder).
        Falls back to VIBE_LOCAL_DEFAULT_CONTEXT (32768) if unavailable.
        """
        if self._ollama_context_limit > 0:
            return self._ollama_context_limit

        host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
        try:
            result = subprocess.run(
                ["curl", "-s", f"{host}/api/ps"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0 and result.stdout:
                data = json.loads(result.stdout)
                models = data.get("models", [])
                if models:
                    ctx = models[0].get("context_length", 0)
                    if ctx > 0:
                        self._ollama_context_limit = ctx
                        self._log(f"ollama /api/ps: context_length={ctx}")
                        return ctx
        except (subprocess.TimeoutExpired, json.JSONDecodeError,
                FileNotFoundError, OSError, ValueError):
            pass
        self._ollama_context_limit = self.VIBE_LOCAL_DEFAULT_CONTEXT
        return self._ollama_context_limit

    def _get_vibe_local_cache_path(self, agent_id: str) -> Path:
        """Return path to vibe-local context cache JSONL."""
        return (self.project_root / "Agent-shared" / "monitor"
                / f"vibe_local_{agent_id}_context.jsonl")

    def _capture_vibe_local_context(self, agent) -> Optional[dict]:
        """Extract context usage from vibe-local's tmux status bar via capture-pane.

        Captures ``ctx:N%`` from the status bar, queries Ollama for context_length,
        computes estimated token count, and appends to a JSONL cache for time-series
        graphing.

        Returns a status-row dict on success, or *None*.
        """
        tmux_target = f"{agent.tmux_session}:{agent.tmux_window}.{agent.tmux_pane}"
        try:
            result = subprocess.run(
                ["tmux", "capture-pane", "-t", tmux_target, "-p"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode != 0:
                self._log(
                    f"context({agent.agent_id}): tmux capture-pane failed "
                    f"(rc={result.returncode})"
                )
                return None
            output = result.stdout
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
            self._log(f"context({agent.agent_id}): tmux capture-pane error: {exc}")
            return None

        # Status bar is at the bottom; use findall and take the last match
        # to avoid hitting ctx:N% in conversation text above the status line
        matches = re.findall(r"ctx:(\d+)%", output)
        if not matches:
            self._log(
                f"context({agent.agent_id}): ctx:N% not found in pane output"
            )
            return None

        pct = int(matches[-1])  # last match = status bar

        # Get runtime context_length from Ollama /api/ps (reflects vibe-coder's num_ctx)
        context_limit = self._get_ollama_context_limit()
        estimated_tokens = int(context_limit * pct / 100)

        self._log(
            f"context({agent.agent_id}): vibe-local ctx={pct}% "
            f"≈{estimated_tokens} tokens (limit={context_limit})"
        )

        # Append to JSONL cache for time-series
        now = datetime.now(timezone.utc)
        cache_path = self._get_vibe_local_cache_path(agent.agent_id)
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            entry = {
                "timestamp": now.isoformat(),
                "usage_pct": pct,
                "context_limit": context_limit,
                "estimated_tokens": estimated_tokens,
            }
            with open(cache_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        except OSError:
            pass

        return {
            "agent": agent.agent_id,
            "cli_type": agent.cli_type,
            "total_tokens": estimated_tokens,
            "context_limit": context_limit,
            "usage_pct": pct,
            "snapshots": 0,
            "last_updated": agent.last_updated or "",
            "source": "tmux_capture",
        }

    def _run_context_monitor(self, extra_args: Optional[list[str]] = None) -> None:
        """Run context monitor for all registered agents via 'all' mode."""
        registry_path = self.project_root / "Agent-shared" / "agent_and_pane_id_table.jsonl"
        if not registry_path.exists():
            return

        viz_dir = self.project_root / "User-shared" / "visualizations"
        viz_dir.mkdir(parents=True, exist_ok=True)

        # Use 'all' mode with --registry for unified log resolution
        # graph-type 'individual' generates detail but not count graphs
        args = [
            "all",
            "--registry", str(registry_path),
            "--status", "--json",
            "--visualize", "-o", str(viz_dir),
        ]
        if extra_args:
            args.extend(extra_args)
        output = _run_script(self._python_cmd, self._context_script, args)
        status_rows: list[dict] = []
        if output:
            # all mode outputs JSON array after the table
            try:
                # Find JSON array in output
                arr_start = output.index("[")
                arr_end = output.rindex("]") + 1
                status_rows = json.loads(output[arr_start:arr_end])
            except (ValueError, json.JSONDecodeError):
                # Fallback: try single JSON object
                try:
                    brace_end = output.index("\n}") + 2
                    status_rows = [json.loads(output[:brace_end])]
                except (ValueError, json.JSONDecodeError):
                    pass
            # Log summary lines
            for line in output.strip().split("\n")[-3:]:
                if line.strip():
                    self._log(f"context: {line.strip()}")

        # Add vibe-local capture-pane fallback
        agents = self.registry.list_all()
        for agent in agents:
            if agent.cli_type == "vibe-local" and agent.status not in ("stopped", "dead"):
                row = self._capture_vibe_local_context(agent)
                if row is not None:
                    status_rows.append(row)

        if status_rows:
            self._write_context_status_md(status_rows)

    def _run_budget_tracker(self) -> None:
        """Run budget tracker for the project."""
        viz_dir = self.project_root / "User-shared" / "visualizations"
        viz_dir.mkdir(parents=True, exist_ok=True)
        output = _run_script(
            self._python_cmd, self._budget_script,
            [str(self.project_root), "--summary", "--visualize",
             "-o", str(viz_dir / "budget_usage.png")],
        )
        if output:
            lines = [l for l in output.strip().split("\n") if l]
            if lines:
                self._log(f"budget: {lines[-1]}")

    # ------------------------------------------------------------------
    # Markdown status file output
    # ------------------------------------------------------------------

    def _write_context_status_md(self, status_rows: list[dict]) -> None:
        """Write Agent-shared/monitor/context_status.md from collected status data."""
        now = datetime.now(timezone.utc)
        ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")

        lines = [
            "# Context Monitor Status",
            f"Updated: {ts}",
            "",
            "| Agent | CLI | Tokens | % | Snapshots | Last Activity |",
            "|-------|-----|--------|---|-----------|---------------|",
        ]
        grand_total = 0
        for row in status_rows:
            agent = row.get("agent", "?")
            cli = row.get("cli_type", "?")
            total = row.get("total_tokens", 0)
            grand_total += total
            limit = row.get("context_limit", 1_000_000)
            if limit > 0:
                pct = total / limit * 100
            elif "usage_pct" in row:
                # vibe-local fallback: percentage extracted from tmux status bar
                pct = row["usage_pct"]
            else:
                pct = 0
            snaps = row.get("snapshots", 0)

            last_str = row.get("last_updated", "")
            activity = self._format_time_ago(last_str, now)

            tokens_fmt = self._format_tokens(total)
            lines.append(f"| {agent} | {cli} | {tokens_fmt} | {pct:.0f}% | {snaps} | {activity} |")

        lines.append("")
        lines.append(f"**Total tokens across all agents: {self._format_tokens(grand_total)}**")
        lines.append("")

        md_path = self.project_root / "Agent-shared" / "monitor" / "context_status.md"
        try:
            md_path.parent.mkdir(parents=True, exist_ok=True)
            md_path.write_text("\n".join(lines), encoding="utf-8")
            self._log(f"context_status.md updated ({len(status_rows)} agents)")
        except OSError as exc:
            self._log(f"Failed to write context_status.md: {exc}")

    @staticmethod
    def _format_tokens(count: int) -> str:
        """Format token count as human-readable string (e.g. 19.5M, 2.6K)."""
        if count >= 1_000_000:
            return f"{count / 1_000_000:.1f}M"
        if count >= 1_000:
            return f"{count / 1_000:.1f}K"
        return str(count)

    @staticmethod
    def _format_time_ago(iso_str: str, now: datetime) -> str:
        """Format an ISO timestamp as relative time (e.g. '2m ago')."""
        if not iso_str:
            return "N/A"
        try:
            ts = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
            delta = now - ts
            secs = int(delta.total_seconds())
            if secs < 0:
                return "just now"
            if secs < 60:
                return f"{secs}s ago"
            if secs < 3600:
                return f"{secs // 60}m ago"
            if secs < 86400:
                return f"{secs // 3600}h ago"
            return f"{secs // 86400}d ago"
        except (ValueError, TypeError):
            return "N/A"

    def _save_milestone_snapshot(self, milestone_min: int) -> None:
        """Save context and budget snapshots at a milestone time point."""
        self._log(f"Milestone {milestone_min}min reached, saving snapshots")

        viz_dir = self.project_root / "User-shared" / "visualizations"
        viz_dir.mkdir(parents=True, exist_ok=True)

        # Context snapshot
        self._run_context_monitor(["--max-minutes", str(milestone_min)])

        # Budget snapshot (delayed 10s for load distribution)
        time.sleep(10)
        snapshot_dir = self.project_root / "Agent-shared" / "budget" / "snapshots"
        snapshot_dir.mkdir(parents=True, exist_ok=True)

        self._run_budget_tracker()

        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")

        # Copy latest budget snapshot with milestone label
        latest = snapshot_dir / "latest.json"
        if latest.exists():
            dest = snapshot_dir / f"budget_milestone_{milestone_min}min_{ts}.json"
            try:
                dest.write_bytes(latest.read_bytes())
                self._log(f"Budget milestone saved: {dest.name}")
            except OSError:
                pass

        # Copy budget graph with milestone label
        budget_graph = viz_dir / "budget_usage.png"
        if budget_graph.exists():
            dest = viz_dir / f"budget_usage_{milestone_min}min.png"
            try:
                dest.write_bytes(budget_graph.read_bytes())
                self._log(f"Budget graph saved: {dest.name}")
            except OSError:
                pass

    # ------------------------------------------------------------------
    # Main loops
    # ------------------------------------------------------------------

    def _update_loop(self) -> None:
        """High-frequency update loop (context monitor + periodic budget)."""
        last_budget_min = -1

        while self._running:
            if not self._sessions_alive():
                self._log("No project tmux sessions found, stopping update loop")
                self._running = False
                return

            elapsed = self._elapsed_minutes()
            if elapsed > self.config.max_runtime_min:
                self._log(f"Max runtime reached ({self.config.max_runtime_min}min), stopping")
                self._running = False
                return

            # Context monitoring
            self._run_context_monitor()

            # Budget aggregation at configured interval
            budget_slot = elapsed // self.config.budget_interval_min
            if budget_slot != last_budget_min:
                last_budget_min = budget_slot
                self._run_budget_tracker()

            # Sleep in small increments to allow clean shutdown
            for _ in range(self.config.update_interval_sec):
                if not self._running:
                    return
                time.sleep(1)

    def _milestone_loop(self) -> None:
        """Low-frequency milestone check loop."""
        check_interval = self.config.milestone_interval_min * 60

        while self._running:
            if not self._sessions_alive():
                self._log("No project tmux sessions found, stopping milestone loop")
                self._running = False
                return

            elapsed = self._elapsed_minutes()
            if elapsed > self.config.max_runtime_min:
                self._running = False
                return

            # Check milestones
            for milestone in self.config.milestones:
                if elapsed >= milestone and self._last_milestone < milestone:
                    self._save_milestone_snapshot(milestone)
                    self._last_milestone = milestone

            # Sleep in small increments
            for _ in range(check_interval):
                if not self._running:
                    return
                time.sleep(1)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the periodic monitor (background threads)."""
        if self._running:
            return

        self._cleanup_existing()
        self._write_pid()
        self._start_epoch = self._get_or_create_start_time()
        self._running = True

        self._log(
            f"Periodic monitor started (PID: {os.getpid()}, "
            f"Project: {self.project_name})"
        )
        self._log(
            f"Config: update={self.config.update_interval_sec}s, "
            f"milestone={self.config.milestone_interval_min}min, "
            f"max_runtime={self.config.max_runtime_min}min, "
            f"budget={self.config.budget_interval_min}min"
        )

        self._update_thread = threading.Thread(
            target=self._update_loop, daemon=True, name="periodic-update"
        )
        self._milestone_thread = threading.Thread(
            target=self._milestone_loop, daemon=True, name="periodic-milestone"
        )
        self._update_thread.start()
        self._milestone_thread.start()

    def stop(self) -> None:
        """Stop the periodic monitor gracefully."""
        if not self._running:
            return
        self._running = False
        self._log("Monitor stop requested")

        for thread in (self._update_thread, self._milestone_thread):
            if thread is not None:
                thread.join(timeout=10)

        self._remove_pid()
        self._log("Monitor terminated")

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def elapsed_minutes(self) -> int:
        return self._elapsed_minutes()


def main() -> None:
    """CLI entry point for running the monitor as a standalone process."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Periodic monitor — background context/budget monitoring with milestone snapshots.",
    )
    parser.add_argument("project_root", type=Path, help="Project root directory")
    parser.add_argument("--project-name", default=None,
                        help="Project name (default: derived from tmux session or 'Team1')")
    parser.add_argument("--config", type=Path, default=None,
                        help="Path to monitor config JSON file")
    parser.add_argument("--interval", type=int, default=None,
                        help="Override update interval in seconds")
    parser.add_argument("--foreground", action="store_true",
                        help="Run in foreground (block until stopped)")
    args = parser.parse_args()

    project_root = args.project_root.resolve()

    # Derive project name
    project_name = args.project_name
    if not project_name:
        tmux_session = os.environ.get("TMUX", "")
        if tmux_session:
            try:
                result = subprocess.run(
                    ["tmux", "display-message", "-p", "#S"],
                    capture_output=True, text=True, check=True,
                )
                session_name = result.stdout.strip()
                for suffix in ("_PM", "_SOLO"):
                    if session_name.endswith(suffix):
                        project_name = session_name[: -len(suffix)]
                        break
                if not project_name:
                    # Try Workers pattern
                    import re
                    m = re.match(r"^(.*)_Workers\d+$", session_name)
                    if m:
                        project_name = m.group(1)
            except (subprocess.CalledProcessError, OSError):
                pass
        if not project_name:
            project_name = "Team1"

    # Load config
    config_path = args.config or (project_root / "Agent-shared" / "periodic_monitor_config.json")
    config = MonitorConfig.from_file(config_path)
    if args.interval is not None:
        config.update_interval_sec = args.interval

    # Registry
    registry_path = project_root / "Agent-shared" / "agent_and_pane_id_table.jsonl"
    registry = AgentRegistry(registry_path)

    monitor = PeriodicMonitor(project_root, project_name, registry, config)

    def _signal_handler(signum: int, frame: object) -> None:
        monitor.stop()

    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    monitor.start()

    if args.foreground:
        try:
            while monitor.is_running:
                time.sleep(1)
        except KeyboardInterrupt:
            monitor.stop()
    else:
        print(f"Monitor started (PID: {os.getpid()}, project: {project_name})")


if __name__ == "__main__":
    main()
