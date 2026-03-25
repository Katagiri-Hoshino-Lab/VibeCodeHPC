"""tmux session/pane management utilities.

Replaces the core logic of communication/setup.sh (879 lines) from VibeCodeHPC-jp.
"""

import subprocess
import math
from dataclasses import dataclass
from typing import Optional


@dataclass
class PaneInfo:
    """Information about a tmux pane."""

    session: str
    window: int
    pane: int
    pid: Optional[int] = None

    @property
    def target(self) -> str:
        return f"{self.session}:{self.window}.{self.pane}"


@dataclass
class GridLayout:
    """Pane grid layout specification."""

    rows: int
    cols: int

    @property
    def total(self) -> int:
        return self.rows * self.cols


def run_tmux(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    """Run a tmux command and return the result."""
    return subprocess.run(
        ["tmux", *args],
        capture_output=True,
        text=True,
        check=check,
    )


def session_exists(name: str) -> bool:
    """Check if a tmux session exists."""
    result = run_tmux("has-session", "-t", name, check=False)
    return result.returncode == 0


def create_session(name: str, detached: bool = True) -> bool:
    """Create a new tmux session."""
    if session_exists(name):
        return False
    args = ["new-session", "-s", name]
    if detached:
        args.append("-d")
    result = run_tmux(*args, check=False)
    return result.returncode == 0


def kill_session(name: str) -> bool:
    """Kill a tmux session."""
    result = run_tmux("kill-session", "-t", name, check=False)
    return result.returncode == 0


def calculate_grid(pane_count: int) -> GridLayout:
    """Calculate optimal grid layout for a given number of panes.

    Matches VibeCodeHPC-jp's grid calculation logic:
    1 -> 1x1, 2 -> 1x2, 3-4 -> 2x2, 5-6 -> 2x3,
    7-9 -> 3x3, 10-12 -> 3x4, 13-16 -> 4x4, 17-20 -> 4x5
    """
    if pane_count <= 1:
        return GridLayout(1, 1)
    if pane_count <= 2:
        return GridLayout(1, 2)

    cols = math.ceil(math.sqrt(pane_count))
    rows = math.ceil(pane_count / cols)
    return GridLayout(rows, cols)


def create_pane_grid(
    session: str, window: int, pane_count: int
) -> list[PaneInfo]:
    """Create a grid of panes in a tmux window.

    Returns list of PaneInfo for created panes.
    The first pane (index 0) already exists when the session/window is created.
    """
    panes = [PaneInfo(session=session, window=window, pane=0)]

    target_base = f"{session}:{window}"

    for i in range(1, pane_count):
        # Alternate horizontal and vertical splits for grid layout
        if i % 2 == 1:
            run_tmux("split-window", "-t", target_base, "-h", check=False)
        else:
            run_tmux("split-window", "-t", target_base, "-v", check=False)

    # Re-tile for even layout
    run_tmux("select-layout", "-t", target_base, "tiled", check=False)

    # Query actual pane indices
    result = run_tmux(
        "list-panes",
        "-t",
        target_base,
        "-F",
        "#{pane_index}:#{pane_pid}",
        check=False,
    )
    if result.returncode == 0:
        panes = []
        for line in result.stdout.strip().split("\n"):
            if ":" in line:
                parts = line.split(":")
                panes.append(
                    PaneInfo(
                        session=session,
                        window=window,
                        pane=int(parts[0]),
                        pid=int(parts[1]) if len(parts) > 1 else None,
                    )
                )

    return panes[:pane_count]


def send_keys(
    target: str, keys: str, enter: bool = True, literal: bool = True
) -> bool:
    """Send keys to a tmux pane.

    Sends text first, waits 0.5s, then sends Enter separately
    to prevent input truncation in CLI TUIs.

    Args:
        target: tmux pane target (e.g. "session:0.1").
        keys: Text or key name to send.
        enter: Whether to press Enter after sending keys.
        literal: If True (default), use ``tmux send-keys -l`` so that
            shell meta-characters such as ``()``, ``$``, ``"``, ``'``
            are sent verbatim.  Set to False when *keys* is a tmux
            key name like ``C-c`` or ``C-m``.
    """
    import time

    if keys:
        if literal:
            result = run_tmux(
                "send-keys", "-t", target, "-l", keys, check=False
            )
        else:
            result = run_tmux(
                "send-keys", "-t", target, keys, check=False
            )
        if result.returncode != 0:
            return False
    if enter:
        if keys:
            time.sleep(0.5)
        result = run_tmux("send-keys", "-t", target, "C-m", check=False)
        return result.returncode == 0
    return True


def capture_pane(target: str, lines: int = 50) -> str:
    """Capture the current content of a tmux pane."""
    result = run_tmux(
        "capture-pane",
        "-t",
        target,
        "-p",
        "-S",
        str(-lines),
        check=False,
    )
    return result.stdout if result.returncode == 0 else ""


def list_sessions() -> list[str]:
    """List all tmux session names."""
    result = run_tmux("list-sessions", "-F", "#{session_name}", check=False)
    if result.returncode == 0:
        return [s for s in result.stdout.strip().split("\n") if s]
    return []


def kill_sessions_by_prefix(prefix: str) -> list[str]:
    """Kill all tmux sessions whose name starts with *prefix*.

    Returns the list of session names that were killed.
    """
    killed: list[str] = []
    for name in list_sessions():
        if name.startswith(prefix):
            if kill_session(name):
                killed.append(name)
    return killed


def setup_multi_agent_sessions(
    project_name: str,
    worker_count: int,
    max_panes_per_session: int = 12,
) -> tuple[str, list[PaneInfo]]:
    """Set up tmux sessions for multi-agent operation.

    Creates:
    - PM session: {project_name}_PM (single pane)
    - Worker sessions: {project_name}_Workers{N} (grid of panes)

    Returns (pm_session_name, list of worker PaneInfos).
    """
    pm_session = f"{project_name}_PM"
    create_session(pm_session)

    if worker_count == 0:
        # Single agent mode
        return pm_session, []

    worker_panes = []
    sessions_needed = math.ceil(worker_count / max_panes_per_session)

    remaining = worker_count
    for s in range(sessions_needed):
        session_name = f"{project_name}_Workers{s + 1}"
        panes_in_session = min(remaining, max_panes_per_session)

        create_session(session_name)
        panes = create_pane_grid(session_name, 0, panes_in_session)
        worker_panes.extend(panes)
        remaining -= panes_in_session

    return pm_session, worker_panes
