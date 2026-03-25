"""VibeCodeHPC CLI entrypoint.

Usage:
    python3 -m vibecodehpc setup --name PROJECT --workers 4
    python3 -m vibecodehpc launch SE --all
    python3 -m vibecodehpc send PM "message"
    python3 -m vibecodehpc status
    python3 -m vibecodehpc health
"""

import argparse
import sys
import time
from pathlib import Path

from vibecodehpc.adapters.base import AgentConfig, CLIType, infer_cli_from_model
from vibecodehpc.adapters.factory import create_adapter
from vibecodehpc.config import VibeCodeConfig
from vibecodehpc.hooks.intents import (
    build_default_polling_hooks,
    hooks_to_dict,
)
from vibecodehpc.monitor.periodic_enter import PeriodicEnter
from vibecodehpc.monitor.periodic_monitor import PeriodicMonitor
from vibecodehpc.registry import AgentEntry, AgentRegistry
from vibecodehpc.tmux_utils import (
    kill_sessions_by_prefix,
    session_exists,
    setup_multi_agent_sessions,
    send_keys,
)
from vibecodehpc.agent_manager import AgentManager

# Landmark files used for project root detection (2-of-3 heuristic)
_ROOT_LANDMARKS = ("CLAUDE.md", "Agent-shared", "instructions")

# --- Friendly error helpers ---------------------------------------------------

_JSONL_EXAMPLE = (
    '  {"agent_id":"SE1","cli_type":"claude","tmux_session":"proj_Workers1",'
    '"tmux_window":0,"tmux_pane":0,"working_dir":"Agent-workdir/SE1",'
    '"role":"SE","model":"sonnet","status":"not_started"}'
)

_VALID_CLI_TYPES = sorted(
    [e.value for e in CLIType],  # type: ignore[attr-defined]
)


def _err_jsonl_not_found(registry_path: Path) -> str:
    """Error message when the registry JSONL file does not exist."""
    return (
        f"Registry file not found: {registry_path}\n"
        "\n"
        "PM must create this file before launching agents.\n"
        "Steps:\n"
        "  1. Decide agent structure (SE/PG count, IDs, CLI types)\n"
        "  2. Create workdirs:  mkdir -p Agent-workdir/SE1 Agent-workdir/PG1.1 ...\n"
        f"  3. Write {registry_path.name} with one JSON object per line.\n"
        "\n"
        "Format example (one line per agent):\n"
        f"{_JSONL_EXAMPLE}\n"
        "\n"
        "Required fields: agent_id, cli_type, tmux_session, tmux_window, tmux_pane, working_dir\n"
        f"Valid cli_type values: {', '.join(_VALID_CLI_TYPES)}"
    )


def _err_jsonl_empty(registry_path: Path) -> str:
    """Error message when the registry JSONL file is empty."""
    return (
        f"Registry file is empty: {registry_path}\n"
        "\n"
        "PM must add agent entries (one JSON object per line).\n"
        "\n"
        "Format example:\n"
        f"{_JSONL_EXAMPLE}"
    )


def _err_agent_not_found(agent_id: str, entries: list) -> str:
    """Error message when a specific agent_id is not in the registry."""
    available = [e.agent_id for e in entries]
    return (
        f"Agent '{agent_id}' not found in registry.\n"
        f"Available agents: {', '.join(available) if available else '(none)'}"
    )


def _err_workdir_missing(entry, project_root: Path) -> str:
    """Error message when an agent's working_dir does not exist."""
    workdir = entry.working_dir
    return (
        f"working_dir '{workdir}' does not exist for agent {entry.agent_id}.\n"
        f"PM: create it with:  mkdir -p {workdir}"
    )


def _err_cli_type_invalid(entry) -> str:
    """Error message when cli_type is empty or not a recognized value."""
    return (
        f"cli_type '{entry.cli_type}' is not valid for agent {entry.agent_id}.\n"
        f"PM: edit the jsonl to set a valid cli_type.\n"
        f"Valid values: {', '.join(_VALID_CLI_TYPES)}"
    )


def _find_project_root(start: Path | None = None) -> Path:
    """Find project root by traversing upward from *start* (default: cwd).

    Uses a 2-of-3 heuristic: the directory containing at least two of
    ``CLAUDE.md``, ``Agent-shared/``, and ``instructions/`` is the root.
    Raises SystemExit if not found.
    """
    current = (start or Path.cwd()).resolve()
    c = current
    while c != c.parent:
        hits = sum(1 for lm in _ROOT_LANDMARKS if (c / lm).exists())
        if hits >= 2:
            return c
        c = c.parent
    # Last resort: cwd itself (matches legacy behaviour)
    return Path.cwd()


def _resolve_cli_and_model(args) -> tuple[str, str | None]:
    """Resolve --cli and --model arguments.

    When --model is given without --cli, infer the CLI from the model name.
    Returns (cli_value, model_value_or_None).
    """
    model = getattr(args, "model", None) or None
    cli_explicitly_set = args.cli != "claude" or "--cli" in sys.argv or "-c" in sys.argv
    if model and not cli_explicitly_set:
        inferred = infer_cli_from_model(model)
        return inferred.value, model
    return args.cli, model


def cmd_setup(args):
    """Set up tmux sessions, launch PM CLI, and optionally start monitors.

    Setup is intentionally minimal: it creates tmux panes and starts the PM.
    Agent ID assignment, workdir creation, CLI selection, and registry
    population are all deferred to the PM (after it reads the requirements).
    """
    cli_value, model_value = _resolve_cli_and_model(args)

    config = VibeCodeConfig.load(Path.cwd())
    config.project_name = args.name or config.project_name or Path.cwd().name

    # --- Guard: prevent duplicate session creation ---
    pm_session_name = f"{config.project_name}_PM"
    if session_exists(pm_session_name):
        if args.force:
            killed = kill_sessions_by_prefix(config.project_name + "_")
            for s in killed:
                print(f"Killed existing session: {s}")
        elif args.resume:
            # Resume mode: relaunch PM CLI only, do not touch panes
            print(f"Resuming PM in existing session: {pm_session_name}")
            pm_tmux_target = f"{pm_session_name}:0.0"
            project_root = Path.cwd()
            send_keys(pm_tmux_target, f"cd {project_root}")
            send_keys(pm_tmux_target, f"export PYTHONPATH={project_root}:${{PYTHONPATH:-}}")
            pm_agent_config = AgentConfig(
                agent_id="PM",
                workdir=project_root,
                project_root=project_root,
                cli_type=CLIType(cli_value),
                tmux_target=pm_tmux_target,
                role="PM",
                model_override=model_value,
            )
            pm_adapter = create_adapter(pm_agent_config)
            pm_launch_cmd = " ".join(pm_adapter.build_launch_command())
            send_keys(pm_tmux_target, pm_launch_cmd)
            print(f"  PM: relaunched '{pm_launch_cmd}' in {pm_tmux_target}")
            print("Waiting 3s for PM trust prompt...")
            time.sleep(3)
            send_keys(pm_tmux_target, "C-m", enter=False, literal=False)
            print("Sent Enter to PM pane to dismiss trust prompt")
            return
        else:
            print(
                f"Session '{pm_session_name}' already exists. "
                f"Use --force to recreate or --resume to reattach PM.",
                file=sys.stderr,
            )
            sys.exit(1)

    print(f"Setting up VibeCodeHPC project: {config.project_name}")
    print(f"Worker panes: {args.workers}, PM CLI: {cli_value}")

    # --- 1) Create tmux sessions (PM + Worker panes) ---
    pm_session, worker_panes = setup_multi_agent_sessions(
        config.project_name,
        args.workers,
        config.max_panes_per_session,
    )

    project_root = Path.cwd()


    print(f"PM session: {pm_session}")
    print(f"Workers: {len(worker_panes)} panes")

    # PM discovers pane info via `tmux list-panes` at runtime.
    # requirement_definition.md is the user's document — setup does not modify it.

    # --- 2) Launch CLI for PM only ---
    pm_tmux_target = f"{pm_session}:0.0"
    send_keys(pm_tmux_target, f"cd {project_root}")
    send_keys(pm_tmux_target, f"export PYTHONPATH={project_root}:${{PYTHONPATH:-}}")

    pm_agent_config = AgentConfig(
        agent_id="PM",
        workdir=project_root,
        project_root=project_root,
        cli_type=CLIType(cli_value),
        tmux_target=pm_tmux_target,
        role="PM",
        model_override=model_value,
    )
    pm_adapter = create_adapter(pm_agent_config)
    pm_launch_cmd = " ".join(pm_adapter.build_launch_command())
    send_keys(pm_tmux_target, pm_launch_cmd)
    print(f"  PM: launched '{pm_launch_cmd}' in {pm_tmux_target}")

    # Trust prompt workaround (PM only)
    print("Waiting 3s for PM trust prompt...")
    time.sleep(3)
    send_keys(pm_tmux_target, "C-m", enter=False, literal=False)
    print("Sent Enter to PM pane to dismiss trust prompt")

    # --- Send session info + init instruction to PM ---
    time.sleep(2)
    worker_sessions = sorted({p.session for p in worker_panes})
    init_msg = (
        f"Read CLAUDE.md, instructions/PM.md, requirement_definition.md. "
        f"tmux sessions: PM={pm_session}, Workers={', '.join(worker_sessions)} "
        f"({len(worker_panes)} panes). "
        f"Act autonomously unless requirement_definition.md specifies Vibe Coding mode. "
        f"Do not ask for confirmation. Start Phase 1."
    )
    send_keys(pm_tmux_target, init_msg)
    print(f"  PM: init message sent")

    # --- 3) periodic_monitor (on by default, opt-out via --no-monitor) ---
    if not args.no_monitor:
        import subprocess
        monitor_cmd = [
            sys.executable, "-m", "vibecodehpc.monitor.periodic_monitor",
            str(project_root),
            "--foreground",
            "--project-name", config.project_name,
        ]
        subprocess.Popen(
            monitor_cmd,
            cwd=str(project_root),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        print("periodic_monitor started (background process)")
    else:
        print("periodic_monitor: off (--no-monitor specified)")

    # --- 4) periodic_enter (off by default, opt-in via --periodic-enter) ---
    if args.periodic_enter:
        periodic = PeriodicEnter(config.project_name)
        if periodic.start():
            print(f"periodic_enter started (interval={periodic.interval_sec}s)")
        else:
            print("periodic_enter already running, skipped")
    else:
        print("periodic_enter: off (use --periodic-enter to enable)")

    # Show attach commands
    print(f"\nTo attach:")
    print(f"  PM:  tmux attach -t {pm_session}")
    worker_sessions = sorted({p.session for p in worker_panes})
    for ws in worker_sessions:
        print(f"  {ws}: tmux attach -t {ws}")


def _launch_entry(entry: AgentEntry, project_root: Path, config: VibeCodeConfig | None = None) -> bool:
    """Launch CLI for a single registry entry. Returns True on success.

    Always deploys hooks/skills/settings before launching the CLI.
    The jsonl is the single source of truth for cli_type and model.
    """
    tmux_target = f"{entry.tmux_session}:{entry.tmux_window}.{entry.tmux_pane}"
    # Resolve relative working_dir against project_root
    workdir = (project_root / entry.working_dir).resolve()

    # jsonl is the single source of truth — no config.yaml fallback
    cli_type_str = entry.cli_type
    model_override = entry.model

    agent_config = AgentConfig(
        agent_id=entry.agent_id,
        workdir=workdir,
        project_root=project_root,
        cli_type=CLIType(cli_type_str),
        tmux_target=tmux_target,
        role=entry.role or "",
        model_override=model_override,
        extra_flags=entry.cli_args or [],
    )
    adapter = create_adapter(agent_config)

    # Verify CLI binary is available before deploying anything
    if not adapter.check_available():
        exe = adapter.get_executable()
        print(
            f"CLI '{exe}' not found for agent {entry.agent_id} (cli_type={cli_type_str}).\n"
            f"Ensure '{exe}' is in PATH. For source-built CLIs:\n"
            f"  ln -s /path/to/{exe} ~/.local/bin/{exe}\n"
            f"  or: export PATH=/path/to/{exe}-dir:$PATH\n"
            f"Skipping {entry.agent_id}.",
            file=sys.stderr,
        )
        return False

    # Deploy hooks/skills/settings (always, at launch time)
    if config is None:
        config = VibeCodeConfig.load(project_root)
    hooks_config = _build_hooks_config(config)
    adapter.setup_hooks(hooks_config)

    skills_source = project_root / "Agent-shared" / "skills"
    if skills_source.is_dir():
        adapter.deploy_skills(skills_source)

    adapter.setup_settings({})

    # cd into workdir
    send_keys(tmux_target, f"cd {workdir}")

    # Export PYTHONPATH so `python3 -m vibecodehpc` works from any workdir
    send_keys(tmux_target, f"export PYTHONPATH={project_root}:${{PYTHONPATH:-}}")

    # Clear any garbage in the line buffer before sending the launch command.
    # tmux pane rendering can leak escape sequences into the input buffer.
    import subprocess as _sp
    _sp.run(["tmux", "send-keys", "-t", tmux_target, "C-u"], capture_output=True)

    launch_cmd = " ".join(adapter.build_launch_command())
    send_keys(tmux_target, launch_cmd)
    return True


def cmd_launch(args):
    """Launch CLI for registered agent(s).

    Requires ``agent_and_pane_id_table.jsonl`` to exist (PM must create it).
    Also validates that each agent's ``working_dir`` exists on disk.
    """
    project_root = _find_project_root()
    registry_path = project_root / "Agent-shared" / "agent_and_pane_id_table.jsonl"

    if not registry_path.exists():
        print(_err_jsonl_not_found(registry_path), file=sys.stderr)
        sys.exit(1)

    registry = AgentRegistry(registry_path)
    config = VibeCodeConfig.load(project_root)

    entries = registry.list_all()
    if not entries:
        print(_err_jsonl_empty(registry_path), file=sys.stderr)
        sys.exit(1)

    # Determine which agents to launch
    if args.all:
        targets = [e for e in entries if e.agent_id != "PM" and e.status != "running"]
        if not targets:
            print("No non-running workers to launch.")
            return
    elif args.agent_id:
        entry = next((e for e in entries if e.agent_id == args.agent_id), None)
        if not entry:
            print(_err_agent_not_found(args.agent_id, entries), file=sys.stderr)
            sys.exit(1)
        targets = [entry]
    else:
        print("Specify an agent ID or use --all.", file=sys.stderr)
        sys.exit(1)

    # Validate each target before launching any
    for entry in targets:
        # Validate cli_type
        if not entry.cli_type or entry.cli_type not in _VALID_CLI_TYPES:
            print(_err_cli_type_invalid(entry), file=sys.stderr)
            sys.exit(1)

        # Validate working_dir existence
        workdir = Path(entry.working_dir) if entry.working_dir else None
        if not workdir or not workdir.exists():
            print(_err_workdir_missing(entry, project_root), file=sys.stderr)
            sys.exit(1)

    # Launch each target
    launched = []
    for entry in targets:
        _launch_entry(entry, project_root, config)
        registry.update_status(entry.agent_id, "running")
        tmux_target = f"{entry.tmux_session}:{entry.tmux_window}.{entry.tmux_pane}"
        print(f"  {entry.agent_id}: launched ({entry.cli_type}) in {tmux_target}")
        launched.append(entry)

    # Trust prompt workaround: wait then send Enter to all launched panes
    if launched:
        print(f"Waiting 3s for trust prompts ({len(launched)} agent(s))...")
        time.sleep(3)
        for entry in launched:
            tmux_target = f"{entry.tmux_session}:{entry.tmux_window}.{entry.tmux_pane}"
            send_keys(tmux_target, "C-m", enter=False, literal=False)
        print(f"Sent Enter to {len(launched)} pane(s) to dismiss trust prompts")


def _build_hooks_config(config: VibeCodeConfig) -> dict:
    """Build hooks config dict from global config.

    session_start is always enabled (framework-enforced).
    stop hook is included when config.hooks.stop_block is True.
    """
    hooks = build_default_polling_hooks()
    serialized = hooks_to_dict(hooks)

    # session_start is always on — never remove it
    # stop hook depends on config
    if not config.hooks.stop_block:
        serialized.pop("on_stop", None)

    return serialized


def cmd_send(args):
    """Send message to an agent."""
    project_root = _find_project_root()
    registry_path = project_root / "Agent-shared" / "agent_and_pane_id_table.jsonl"

    if not registry_path.exists():
        print(_err_jsonl_not_found(registry_path), file=sys.stderr)
        sys.exit(1)

    registry = AgentRegistry(registry_path)
    manager = AgentManager(project_root, registry)

    target = args.target
    message = " ".join(args.message)

    if target == "ALL":
        entries = registry.list_all()
        if not entries:
            print(_err_jsonl_empty(registry_path), file=sys.stderr)
            sys.exit(1)
        results = manager.broadcast(message)
        for agent_id, ok in results.items():
            status = "OK" if ok else "FAIL"
            print(f"  {agent_id}: {status}")
    else:
        # Validate that the target agent exists
        entries = registry.list_all()
        entry = next((e for e in entries if e.agent_id == target), None)
        if not entry:
            print(_err_agent_not_found(target, entries), file=sys.stderr)
            sys.exit(1)
        ok = manager.send_message(target, message)
        if ok:
            print(f"Sent to {target}")
        else:
            tmux_target = f"{entry.tmux_session}:{entry.tmux_window}.{entry.tmux_pane}"
            print(
                f"Failed to send to {target} (tmux target: {tmux_target}).\n"
                f"Check that the tmux pane exists: tmux has-session -t {entry.tmux_session}",
                file=sys.stderr,
            )
            sys.exit(1)


def cmd_status(args):
    """Show agent status."""
    project_root = _find_project_root()
    registry_path = project_root / "Agent-shared" / "agent_and_pane_id_table.jsonl"

    if not registry_path.exists():
        print(_err_jsonl_not_found(registry_path), file=sys.stderr)
        sys.exit(1)

    registry = AgentRegistry(registry_path)

    entries = registry.list_all()
    if not entries:
        print(_err_jsonl_empty(registry_path), file=sys.stderr)
        sys.exit(1)

    print(f"{'ID':<10} {'CLI':<10} {'Model':<16} {'Role':<6} {'Status':<12} {'tmux target'}")
    print("-" * 76)
    for e in entries:
        target = f"{e.tmux_session}:{e.tmux_window}.{e.tmux_pane}"
        model = e.model or "(default)"
        print(f"{e.agent_id:<10} {e.cli_type:<10} {model:<16} {e.role or '-':<6} {e.status:<12} {target}")


def cmd_health(args):
    """Check agent health."""
    project_root = _find_project_root()
    registry_path = project_root / "Agent-shared" / "agent_and_pane_id_table.jsonl"

    if not registry_path.exists():
        print(_err_jsonl_not_found(registry_path), file=sys.stderr)
        sys.exit(1)

    registry = AgentRegistry(registry_path)

    entries = registry.list_all()
    if not entries:
        print(_err_jsonl_empty(registry_path), file=sys.stderr)
        sys.exit(1)

    manager = AgentManager(project_root, registry)

    results = manager.check_health()
    for agent_id, alive in results.items():
        status = "alive" if alive else "DEAD"
        print(f"  {agent_id}: {status}")


def main():
    parser = argparse.ArgumentParser(
        prog="vibecodehpc",
        description="VibeCodeHPC Multi-CLI Multi-Agent Framework",
    )
    sub = parser.add_subparsers(dest="command")

    # setup
    p_setup = sub.add_parser("setup", help="Setup tmux sessions and launch PM")
    p_setup.add_argument("--name", "-n", help="Project name")
    p_setup.add_argument("--workers", "-w", type=int, default=4, help="Number of worker panes")
    p_setup.add_argument(
        "--cli", "-c", default="claude",
        choices=["claude", "cline", "codex", "gemini", "kimi", "opencode", "vibe-local"],
        help="CLI tool for PM (default: claude)",
    )
    p_setup.add_argument(
        "--model", "-m", default=None,
        help="Model name for PM (e.g. opus, gpt-4.1, gemini-2.5-pro). "
             "When set without --cli, auto-infers the CLI from model name.",
    )
    # --force / --resume (mutually exclusive)
    setup_mode = p_setup.add_mutually_exclusive_group()
    setup_mode.add_argument(
        "--force", action="store_true", default=False,
        help="Kill existing sessions and recreate from scratch",
    )
    setup_mode.add_argument(
        "--resume", action="store_true", default=False,
        help="Relaunch PM CLI in existing session (no pane changes)",
    )

    p_setup.add_argument(
        "--no-monitor", action="store_true", default=False,
        help="Disable periodic monitoring (default: on)",
    )
    p_setup.add_argument(
        "--periodic-enter", action="store_true", default=False,
        help="Enable periodic Enter sender (default: off)",
    )

    # launch
    p_launch = sub.add_parser("launch", help="Launch CLI for registered agent(s)")
    p_launch.add_argument("agent_id", nargs="?", help="Agent ID to launch (omit with --all)")
    p_launch.add_argument("--all", action="store_true", help="Launch all non-running workers")

    # send
    p_send = sub.add_parser("send", help="Send message to agent")
    p_send.add_argument("target", help="Target agent ID or ALL")
    p_send.add_argument("message", nargs="+", help="Message text")

    # status
    sub.add_parser("status", help="Show agent status")

    # health
    sub.add_parser("health", help="Check agent health")

    args = parser.parse_args()

    if args.command == "setup":
        cmd_setup(args)
    elif args.command == "launch":
        cmd_launch(args)
    elif args.command == "send":
        cmd_send(args)
    elif args.command == "status":
        cmd_status(args)
    elif args.command == "health":
        cmd_health(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
