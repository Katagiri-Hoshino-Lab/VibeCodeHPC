"""``python -m vibecodehpc.ipc``: send / receive / health / launch through a chosen backend.

The backend comes from ``--backend``, ``VIBECODEHPC_IPC_BACKEND`` or
``ipc_backend:`` in config.yaml (default tmux). This entry point imports
neither the fcntl-based registry nor the tmux CLI, so the cross_session
backend runs on native Windows.

    python -m vibecodehpc.ipc --backend cross_session launch PG1.1 --workdir Agent-workdir/PG1.1 \
        --model sonnet --first-message "You are PG1.1. Read CLAUDE.md ..."
    python -m vibecodehpc.ipc --backend cross_session send PG1.1 "[PM] [Request] ..."
    python -m vibecodehpc.ipc --backend cross_session health PG1.1
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from vibecodehpc.ipc import BACKENDS, get_backend


def launch_command(cli: str, model: str | None, agent_id: str, workdir: Path,
                   project_root: Path, extra: list[str]) -> list[str]:
    """The adapter's own launch command (flags, model), unchanged."""
    from vibecodehpc.adapters.base import AgentConfig, CLIType
    from vibecodehpc.adapters.factory import create_adapter
    adapter = create_adapter(AgentConfig(
        agent_id=agent_id, workdir=workdir, project_root=project_root,
        cli_type=CLIType(cli), tmux_target="", model_override=model, extra_flags=extra))
    return adapter.build_launch_command()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m vibecodehpc.ipc",
                                description="Optional IPC backends (experimental).")
    p.add_argument("--backend", choices=sorted(BACKENDS), default=None)
    p.add_argument("--project-root", type=Path, default=Path.cwd())
    sub = p.add_subparsers(dest="command", required=True)
    s = sub.add_parser("send", help="deliver a message")
    s.add_argument("agent_id")
    s.add_argument("message", nargs="+")
    s.add_argument("--from", dest="sender", default="framework")
    r = sub.add_parser("receive", help="take pending messages (prints JSON)")
    r.add_argument("agent_id")
    h = sub.add_parser("health", help="is the agent's session alive")
    h.add_argument("agent_id")
    la = sub.add_parser("launch", help="start an agent's CLI")
    la.add_argument("agent_id")
    la.add_argument("--workdir", type=Path, required=True)
    la.add_argument("--cli", default="claude")
    la.add_argument("--model", default=None)
    la.add_argument("--first-message", default="")
    la.add_argument("--launcher", choices=("bg", "wt"), default="bg",
                    help="cross_session: background session or a Windows Terminal tab")
    la.add_argument("extra", nargs="*", help="extra CLI flags (after --)")
    args = p.parse_args(argv)

    root = args.project_root.resolve()
    backend = get_backend(args.backend, root)
    if args.command == "send":
        message = " ".join(args.message)
        ok = backend.send(args.agent_id, message, sender=args.sender)
        print(f"{'Sent to' if ok else 'Failed to send to'} {args.agent_id} ({backend.name})")
        return 0 if ok else 1
    if args.command == "receive":
        print(json.dumps(backend.receive(args.agent_id), ensure_ascii=False))
        return 0
    if args.command == "health":
        state = backend.health(args.agent_id)
        print({True: "alive", False: "not running", None: "unknown"}[state])
        return 0 if state else 1
    if backend.name == "cross_session":
        backend.launcher = args.launcher
    workdir = (root / args.workdir).resolve()
    command = launch_command(args.cli, args.model, args.agent_id, workdir, root, args.extra)
    handle = backend.launch(args.agent_id, command, workdir, args.first_message)
    print(f"Launched {args.agent_id} ({backend.name}): {handle or 'no id printed'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
