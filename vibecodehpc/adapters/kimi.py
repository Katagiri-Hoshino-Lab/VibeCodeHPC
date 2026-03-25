"""Kimi CLI adapter.

Kimi CLI (MoonshotAI) supports AGENTS.md instructions, skills/, and
MCP extensions.  Hooks are not yet implemented (as of 2026-03), so
this adapter uses the AGENTS.md anti-idle fallback pattern (like Codex).

Agent mode is activated by Ctrl-X in interactive sessions.  Headless
mode uses ``--print`` for stdout output.  Settings are stored in
``~/.kimi/config.toml`` (TOML format).

Security note: Moonshot AI (China) — telemetry policy is opaque and
API keys are stored in plaintext.  This adapter disables telemetry
where possible.
"""

import json
import os
from pathlib import Path
from typing import Optional

from vibecodehpc.adapters.base import CLIAdapter


def _toml_value(v) -> str:
    """Format a Python value as a TOML literal (fallback serializer)."""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, str):
        return f'"{v}"'
    if isinstance(v, list):
        inner = ", ".join(f'"{x}"' if isinstance(x, str) else str(x) for x in v)
        return f"[{inner}]"
    return str(v)


class KimiAdapter(CLIAdapter):
    """Adapter for Kimi CLI (MoonshotAI).

    Hooks are not yet supported by Kimi CLI.  Anti-idle behaviour is
    achieved via AGENTS.md instruction-based fallback.
    """

    def get_executable(self) -> str:
        return "kimi"

    def get_instruction_filename(self) -> str:
        return "AGENTS.md"

    def get_hooks_dir(self) -> Optional[Path]:
        # Kimi CLI does not support hooks yet
        return None

    def get_skills_target_dir(self) -> Path:
        return self.config.workdir / ".kimi" / "skills"

    def setup_instruction_file(self, content: str) -> Path:
        filepath = self.config.workdir / "AGENTS.md"
        filepath.write_text(content, encoding="utf-8")
        return filepath

    def setup_hooks(self, hooks_config: dict) -> None:
        """Kimi has no hooks support — use AGENTS.md anti-idle fallback.

        Writes agent_id.txt for framework compatibility even though
        hooks are not deployed.
        """
        kimi_dir = self.config.workdir / ".kimi"
        kimi_dir.mkdir(parents=True, exist_ok=True)

        # Write agent_id for framework tooling to reference
        (kimi_dir / "agent_id.txt").write_text(
            self.config.agent_id, encoding="utf-8"
        )

        # AGENTS.md anti-idle fallback (instruction-based stop prevention)
        if "on_stop" in hooks_config:
            self._append_anti_idle_directive()

    def _append_anti_idle_directive(self) -> None:
        """Append anti-idle directive to AGENTS.md as fallback."""
        agents_path = self.config.workdir / "AGENTS.md"
        anti_idle = (
            "\n\n## Anti-Idle Directive\n"
            "You are a polling agent. Never stop working. "
            "If you have no pending tasks, check the following:\n"
            "1. ChangeLog.md for recent updates\n"
            "2. Your assigned directory for new files\n"
            "3. Messages from other agents\n"
            "Continue working until explicitly told to stop.\n"
        )
        if agents_path.exists():
            existing = agents_path.read_text(encoding="utf-8")
            agents_path.write_text(existing + anti_idle, encoding="utf-8")

    def setup_settings(self, settings: dict) -> None:
        """Write Kimi config.toml with telemetry disabled.

        Kimi CLI uses ~/.kimi/config.toml globally, but we write a
        project-local .kimi/config.toml for isolation.
        """
        config_dir = self.config.workdir / ".kimi"
        config_dir.mkdir(parents=True, exist_ok=True)
        config_path = config_dir / "config.toml"

        config: dict = {}
        if config_path.exists():
            try:
                import tomllib
                config = tomllib.loads(config_path.read_text(encoding="utf-8"))
            except ImportError:
                pass

        # Disable telemetry (security: opaque policy)
        config["telemetry"] = False

        # Disable auto-update
        config["check_for_update_on_startup"] = False

        # Auto-configure OpenRouter provider only when per-agent env_vars request it
        use_openrouter = bool(self.config.env_vars.get("OPENAI_API_KEY") or
                              self.config.env_vars.get("OPENROUTER_API_KEY"))
        if use_openrouter:
            if "providers" not in config:
                config["providers"] = {}
            if "openrouter" not in config.get("providers", {}):
                config["providers"]["openrouter"] = {
                    "type": "openai_legacy",
                    "base_url": "https://openrouter.ai/api/v1",
                    "api_key": "set-via-OPENAI_API_KEY-env",
                }

        # Auto-configure model definition when model_override is set
        # Kimi CLI requires models to be defined in [models.xxx] sections
        if self.config.model_override:
            model_name = self.config.model_override
            safe_key = model_name.replace("/", "-").replace(".", "-")
            if "models" not in config:
                config["models"] = {}
            if safe_key not in config.get("models", {}):
                provider = "openrouter" if use_openrouter else "kimi"
                config["models"][safe_key] = {
                    "provider": provider,
                    "model": model_name,
                    "max_context_size": 200000,
                }
            config["default_model"] = safe_key

        config.update(settings)

        try:
            import tomli_w
            config_path.write_bytes(tomli_w.dumps(config).encode())
        except ImportError:
            # Fallback: write TOML manually (supports 2-level nesting)
            lines = []
            # Top-level scalars first
            for k, v in config.items():
                if not isinstance(v, dict):
                    lines.append(f"{k} = {_toml_value(v)}")
            # Then sections
            for k, v in config.items():
                if isinstance(v, dict):
                    # Check if values are dicts (2-level: [section.subsection])
                    has_nested = any(isinstance(sv, dict) for sv in v.values())
                    if has_nested:
                        for sk, sv in v.items():
                            if isinstance(sv, dict):
                                lines.append(f"\n[{k}.{sk}]")
                                for ssk, ssv in sv.items():
                                    lines.append(f"{ssk} = {_toml_value(ssv)}")
                            else:
                                lines.append(f"\n[{k}]")
                                lines.append(f"{sk} = {_toml_value(sv)}")
                    else:
                        lines.append(f"\n[{k}]")
                        for sk, sv in v.items():
                            lines.append(f"{sk} = {_toml_value(sv)}")
            config_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _needs_openrouter_bridge(self) -> bool:
        """Return True when per-agent env_vars request OpenRouter bridging."""
        return bool(self.config.env_vars.get("OPENAI_API_KEY") or
                     self.config.env_vars.get("OPENROUTER_API_KEY"))

    def _local_config_path(self) -> Path:
        """Return the path to the project-local config.toml."""
        return self.config.workdir / ".kimi" / "config.toml"

    def build_launch_command(self) -> list[str]:
        # Kimi CLI enters agent mode via Ctrl-X in interactive session.
        # For tmux-based orchestration, we launch normally and send Ctrl-X
        # after startup to enable agent mode.
        cmd = ["KIMI_CLI_NO_AUTO_UPDATE=1"]
        # Bridge OPENROUTER_API_KEY → OPENAI_API_KEY for Kimi (openai_legacy)
        if self._needs_openrouter_bridge():
            cmd.append("OPENAI_API_KEY=$OPENROUTER_API_KEY")
        cmd.append("kimi")
        # Use project-local config so workdir/.kimi/config.toml is not ignored
        cmd.extend(["--config-file", str(self._local_config_path())])
        if self.config.model_override:
            cmd.extend(["--model", self.config.model_override])
        cmd.extend(self.config.extra_flags)
        return cmd

    def build_headless_command(
        self, prompt: str, output_format: str = "text"
    ) -> list[str]:
        cmd = ["kimi", "--config-file", str(self._local_config_path()),
               "--print", prompt]
        if output_format != "text":
            cmd.append("--quiet")
        return cmd

    def build_resume_command(self, session_id: Optional[str] = None) -> list[str]:
        # Kimi CLI does not have session resume — fall back to fresh launch
        return self.build_launch_command()

    def get_native_multi_agent_info(self) -> dict:
        return {
            "supported": True,
            "mechanism": "task_tool",
            "enable_flag": None,
            "notes": (
                "Kimi CLI supports sub-agents via Task tool. "
                "Auto-compact available (/compact). "
                "Security: Moonshot AI telemetry policy is opaque."
            ),
        }
