"""Agent lifecycle manager.

Replaces start_agent.sh + agent_send.sh from VibeCodeHPC-jp.
Orchestrates agent spawn, messaging, and health checking.
"""

import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from vibecodehpc.adapters.base import AgentConfig, CLIType, HeadlessResult
from vibecodehpc.adapters.factory import create_adapter
from vibecodehpc.registry import AgentEntry, AgentRegistry
from vibecodehpc.tmux_utils import PaneInfo, send_keys, capture_pane


class AgentManager:
    """Orchestrates agent lifecycle using CLI adapters."""

    def __init__(self, project_root: Path, registry: AgentRegistry):
        self.project_root = project_root
        self.registry = registry

    def spawn_agent(
        self,
        agent_id: str,
        cli_type: CLIType,
        pane: PaneInfo,
        workdir: Path,
        role: str = "",
        instruction_content: str = "",
        hooks_config: Optional[dict] = None,
        settings: Optional[dict] = None,
        model_override: Optional[str] = None,
        extra_flags: Optional[list] = None,
    ) -> bool:
        """Spawn an agent in a tmux pane.

        1. Create workdir if needed
        2. Setup instruction file and hooks via adapter
        3. cd into workdir in tmux pane
        4. Send launch command
        5. Update registry
        """
        config = AgentConfig(
            agent_id=agent_id,
            workdir=workdir,
            project_root=self.project_root,
            cli_type=cli_type,
            tmux_target=pane.target,
            role=role,
            model_override=model_override,
            extra_flags=extra_flags or [],
        )

        adapter = create_adapter(config)

        # Check CLI availability
        if not adapter.check_available():
            return False

        # Create workdir
        workdir.mkdir(parents=True, exist_ok=True)

        # Setup instruction file
        if instruction_content:
            adapter.setup_instruction_file(instruction_content)

        # Setup hooks
        if hooks_config:
            adapter.setup_hooks(hooks_config)

        # Setup settings
        if settings:
            adapter.setup_settings(settings)

        # cd into workdir in pane
        send_keys(pane.target, f"cd {workdir}")

        # Export PYTHONPATH so `python3 -m vibecodehpc` works from any workdir
        send_keys(pane.target, f"export PYTHONPATH={self.project_root}:${{PYTHONPATH:-}}")

        # Set environment variables
        for key, value in config.env_vars.items():
            send_keys(pane.target, f"export {key}={value}")

        # Launch CLI
        launch_cmd = " ".join(adapter.build_launch_command())
        send_keys(pane.target, launch_cmd)

        # Register agent
        entry = AgentEntry(
            agent_id=agent_id,
            cli_type=cli_type.value,
            tmux_session=pane.session,
            tmux_window=pane.window,
            tmux_pane=pane.pane,
            working_dir=str(workdir),
            status="running",
            role=role,
            model=model_override,
            last_updated=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
        self.registry.register(entry)
        return True

    def send_message(self, agent_id: str, message: str) -> bool:
        """Send a message to an agent via its tmux pane."""
        target = self.registry.get_tmux_target(agent_id)
        if not target:
            return False
        result = send_keys(target, message)
        if result:
            self._log_send(agent_id, message)
        return result

    def _log_send(self, agent_id: str, message: str) -> None:
        """Append send_message call to Agent-shared/logs/send_log.txt."""
        log_file = self.project_root / "Agent-shared" / "logs" / "send_log.txt"
        log_file.parent.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f'[{timestamp}] {agent_id}: "{message}"\n')

    def broadcast(
        self, message: str, exclude: Optional[list[str]] = None
    ) -> dict[str, bool]:
        """Broadcast a message to all running agents."""
        exclude = exclude or []
        results = {}
        for entry in self.registry.list_by_status("running"):
            if entry.agent_id not in exclude:
                results[entry.agent_id] = self.send_message(entry.agent_id, message)
        return results

    def check_health(self) -> dict[str, bool]:
        """Check all agents' liveness."""
        results = {}
        for entry in self.registry.list_all():
            target = f"{entry.tmux_session}:{entry.tmux_window}.{entry.tmux_pane}"
            config = AgentConfig(
                agent_id=entry.agent_id,
                workdir=Path(entry.working_dir),
                project_root=self.project_root,
                cli_type=CLIType(entry.cli_type),
                tmux_target=target,
            )
            adapter = create_adapter(config)
            alive = adapter.detect_alive()
            results[entry.agent_id] = alive

            # Update status if dead
            if not alive and entry.status == "running":
                self.registry.update_status(entry.agent_id, "dead")
        return results

    def kill_agent(self, agent_id: str) -> bool:
        """Stop an agent by sending interrupt."""
        target = self.registry.get_tmux_target(agent_id)
        if not target:
            return False
        send_keys(target, "", enter=False)
        # Send Ctrl-C then exit
        subprocess.run(
            ["tmux", "send-keys", "-t", target, "C-c"],
            capture_output=True,
            check=False,
        )
        self.registry.update_status(agent_id, "stopped")
        return True

    def headless_query(
        self,
        cli_type: CLIType,
        prompt: str,
        workdir: Optional[Path] = None,
        model_override: Optional[str] = None,
    ) -> HeadlessResult:
        """Execute a one-shot headless query."""
        config = AgentConfig(
            agent_id="_headless",
            workdir=workdir or self.project_root,
            project_root=self.project_root,
            cli_type=cli_type,
            tmux_target="",
            model_override=model_override,
        )
        adapter = create_adapter(config)
        cmd = adapter.build_headless_command(prompt)

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(workdir or self.project_root),
        )
        return HeadlessResult(
            stdout=result.stdout,
            stderr=result.stderr,
            exit_code=result.returncode,
        )

    def get_agent_pane_content(self, agent_id: str, lines: int = 50) -> str:
        """Capture current tmux pane content for an agent."""
        target = self.registry.get_tmux_target(agent_id)
        if not target:
            return ""
        return capture_pane(target, lines)
