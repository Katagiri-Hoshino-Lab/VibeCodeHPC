"""OpenCode CLI adapter.

OpenCode (anomalyco/opencode) uses a TypeScript/Bun plugin system.
Plugins are auto-discovered from .opencode/plugins/*.{ts,js} and receive
lifecycle events via a pub/sub bus (session.created, tool.execute.before, etc.).

Currently implemented plugin hook:
  event (session.created) → agent registry update
"""

import json
from pathlib import Path
from typing import Optional

from vibecodehpc.adapters.base import CLIAdapter

# Path to the TypeScript plugin template shipped with vibecodehpc.
_TEMPLATE_PATH = (
    Path(__file__).resolve().parent.parent
    / "hooks"
    / "templates"
    / "opencode"
    / "vibecodehpc_plugin.ts"
)


def _render_plugin(*, project_root: str, agent_id: str) -> str:
    """Read the TypeScript template and replace placeholder tokens."""
    template = _TEMPLATE_PATH.read_text(encoding="utf-8")
    template = template.replace("__PROJECT_ROOT__", project_root.replace("\\", "/"))
    template = template.replace("__AGENT_ID__", agent_id)
    return template


class OpenCodeAdapter(CLIAdapter):
    """Adapter for OpenCode CLI."""

    def get_executable(self) -> str:
        return "opencode"

    def get_hooks_dir(self) -> Path:
        return self.config.workdir / ".opencode" / "plugins"

    def get_instruction_filename(self) -> str:
        return "opencode.json"

    def setup_instruction_file(self, content: str) -> Path:
        """Write AGENTS.md (OpenCode reads it natively, with CLAUDE.md fallback)."""
        filepath = self.config.workdir / "AGENTS.md"
        filepath.write_text(content, encoding="utf-8")
        return filepath

    def setup_hooks(self, hooks_config: dict) -> None:
        """Deploy VibeCodeHPC plugin to .opencode/plugins/vibecodehpc_plugin.ts.

        The plugin handles:
        - event (session.created) → writes session_id to registry + agent table
        """
        plugins_dir = self.config.workdir / ".opencode" / "plugins"
        plugins_dir.mkdir(parents=True, exist_ok=True)

        # Write agent_id for the plugin to reference
        (plugins_dir.parent / "agent_id.txt").write_text(
            self.config.agent_id, encoding="utf-8"
        )

        # Render and deploy the TypeScript plugin
        plugin_content = _render_plugin(
            project_root=str(self.config.project_root),
            agent_id=self.config.agent_id,
        )
        plugin_path = plugins_dir / "vibecodehpc_plugin.ts"
        plugin_path.write_text(plugin_content, encoding="utf-8")

    def setup_settings(self, settings: dict) -> None:
        """Write/merge opencode.json with the current OpenCode config schema."""
        config_path = self.config.workdir / "opencode.json"
        existing: dict = {}
        if config_path.exists():
            existing = json.loads(config_path.read_text(encoding="utf-8"))
        # Auto-approve all tool executions (equivalent to --dangerously-skip-permissions)
        existing.setdefault("permission", "allow")
        existing.update(settings)
        config_path.write_text(
            json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def build_launch_command(self) -> list[str]:
        cmd = ["opencode"]
        if self.config.model_override:
            cmd.extend(["--model", self.config.model_override])
        cmd.extend(self.config.extra_flags)
        return cmd

    def build_headless_command(
        self, prompt: str, output_format: str = "text"
    ) -> list[str]:
        """Build non-interactive command: ``opencode run <prompt>``.

        --format json produces JSONL events on stdout.
        """
        cmd = ["opencode", "run"]
        if output_format == "json":
            cmd.extend(["--format", "json"])
        cmd.append(prompt)
        return cmd

    def build_resume_command(self, session_id: Optional[str] = None) -> list[str]:
        """Resume an existing session or continue the last one."""
        cmd = self.build_launch_command()
        if session_id:
            cmd.extend(["--session", session_id])
        else:
            cmd.append("--continue")
        return cmd

    def get_native_multi_agent_info(self) -> dict:
        return {
            "supported": True,
            "mechanism": "agents_config",
            "enable_flag": "opencode.json agent section",
            "notes": "Subagent mode via agent config (explore, build, general, etc.).",
        }
