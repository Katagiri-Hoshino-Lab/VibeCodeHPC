"""Periodic Enter sender — flush residual messages from tmux input buffers.

Python port of VibeCodeHPC-jp/communication/periodic_enter.sh.

When messages are sent via ``tmux send-keys`` while a CLI (e.g. Claude Code) is
busy processing, the text sits in the input buffer.  This module periodically
sends ``C-m`` (Enter) to every relevant pane so that buffered messages are
flushed and actually delivered, improving IPC reliability.
"""

import logging
import os
import signal
import sys
import threading
import time
from pathlib import Path
from typing import Optional

# Ensure vibecodehpc package is importable when run as a standalone script
# (e.g. python3 vibecodehpc/monitor/periodic_enter.py) without PYTHONPATH.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from vibecodehpc.tmux_utils import (
    capture_pane,
    run_tmux,
    session_exists,
)

logger = logging.getLogger(__name__)

# Default interval between Enter sweeps (seconds).
DEFAULT_INTERVAL_SEC = 60

# Patterns that indicate a CLI agent is running in the pane.
_CLI_PATTERNS = ("claude", "codex", "gemini", "opencode", "aider")


def _list_pane_targets(session: str) -> list[str]:
    """Return pane targets (session:window.pane) for all panes in *session*."""
    result = run_tmux(
        "list-panes", "-t", session, "-a",
        "-F", "#{session_name}:#{window_index}.#{pane_index}",
        check=False,
    )
    if result.returncode != 0:
        return []
    return [line for line in result.stdout.strip().split("\n") if line]


def _pane_has_cli(target: str) -> bool:
    """Return True if *target* pane appears to be running a CLI agent."""
    content = capture_pane(target, lines=30)
    lower = content.lower()
    return any(pat in lower for pat in _CLI_PATTERNS)


class PeriodicEnter:
    """Periodically send Enter (C-m) to CLI agent panes to flush input buffers.

    Parameters
    ----------
    project_name:
        Project name used to derive tmux session names
        (``{project_name}_PM``, ``{project_name}_Workers1``, …).
    interval_sec:
        Seconds between Enter sweeps.  Defaults to ``DEFAULT_INTERVAL_SEC``.
    """

    def __init__(
        self,
        project_name: str,
        interval_sec: int = DEFAULT_INTERVAL_SEC,
    ) -> None:
        self.project_name = project_name
        self.interval_sec = interval_sec
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._pid_path = Path(f"/tmp/vibecode_periodic_enter_{project_name}.pid")

    # ---- PID management --------------------------------------------------

    def _read_pid(self) -> Optional[int]:
        try:
            return int(self._pid_path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return None

    @staticmethod
    def _is_pid_alive(pid: int) -> bool:
        try:
            os.kill(pid, 0)
            return True
        except (OSError, ProcessLookupError):
            return False

    def _check_already_running(self) -> bool:
        """Return True (and log) if another instance is already running."""
        old_pid = self._read_pid()
        if old_pid is not None and self._is_pid_alive(old_pid):
            logger.info(
                "periodic_enter already running for %s (PID %d)",
                self.project_name, old_pid,
            )
            return True
        return False

    def _write_pid(self) -> None:
        self._pid_path.write_text(str(os.getpid()), encoding="utf-8")

    def _remove_pid(self) -> None:
        try:
            self._pid_path.unlink(missing_ok=True)
        except OSError:
            pass

    # ---- Session helpers -------------------------------------------------

    def _session_names(self) -> list[str]:
        """Return candidate tmux session names for this project."""
        return [
            f"{self.project_name}_PM",
            f"{self.project_name}_Workers1",
            f"{self.project_name}_Workers2",
        ]

    def _any_session_alive(self) -> bool:
        return any(session_exists(s) for s in self._session_names())

    # ---- Core loop -------------------------------------------------------

    def _send_enter_sweep(self) -> int:
        """Send C-m to all CLI panes. Return the number of panes touched."""
        count = 0
        for session_name in self._session_names():
            if not session_exists(session_name):
                continue
            for target in _list_pane_targets(session_name):
                if _pane_has_cli(target):
                    run_tmux("send-keys", "-t", target, "C-m", check=False)
                    count += 1
        return count

    def _loop(self) -> None:
        """Background loop: sleep, then sweep."""
        while self._running:
            # Sleep in 1-second increments for responsive shutdown.
            for _ in range(self.interval_sec):
                if not self._running:
                    return
                time.sleep(1)

            if not self._running:
                return

            if not self._any_session_alive():
                logger.info(
                    "No project sessions alive for %s, stopping periodic_enter",
                    self.project_name,
                )
                self._running = False
                return

            n = self._send_enter_sweep()
            if n:
                logger.debug("periodic_enter: sent C-m to %d pane(s)", n)

    # ---- Public API ------------------------------------------------------

    def start(self) -> bool:
        """Start the periodic Enter sender in a background thread.

        Returns False if another instance is already running.
        """
        if self._running:
            return True
        if self._check_already_running():
            return False

        self._write_pid()
        self._running = True

        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="periodic-enter",
        )
        self._thread.start()
        logger.info(
            "periodic_enter started [%s] (interval=%ds, PID=%d)",
            self.project_name, self.interval_sec, os.getpid(),
        )
        return True

    def stop(self) -> None:
        """Stop the sender gracefully."""
        if not self._running:
            return
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=10)
        self._remove_pid()
        logger.info("periodic_enter stopped [%s]", self.project_name)

    @property
    def is_running(self) -> bool:
        return self._running


# ------------------------------------------------------------------
# CLI entry point
# ------------------------------------------------------------------

def main() -> None:
    """Run periodic_enter as a standalone process."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Periodically send Enter to CLI panes to flush buffered messages.",
    )
    parser.add_argument("project_name", help="Project name (e.g. Team1, GEMM)")
    parser.add_argument(
        "--interval", type=int,
        default=int(os.environ.get("ENTER_INTERVAL", str(DEFAULT_INTERVAL_SEC))),
        help=f"Interval in seconds (default: {DEFAULT_INTERVAL_SEC}, env: ENTER_INTERVAL)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    sender = PeriodicEnter(args.project_name, interval_sec=args.interval)

    def _signal_handler(signum: int, frame: object) -> None:
        sender.stop()

    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    if not sender.start():
        raise SystemExit(1)

    try:
        while sender.is_running:
            time.sleep(1)
    except KeyboardInterrupt:
        sender.stop()


if __name__ == "__main__":
    main()
