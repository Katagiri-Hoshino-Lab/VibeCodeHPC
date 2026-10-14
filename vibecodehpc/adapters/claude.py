"""Claude Code CLI adapter."""

import json
import shutil
from pathlib import Path
from typing import Optional

from vibecodehpc.adapters.base import CLIAdapter, EndpointSettings

# Template directory relative to this file
_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "hooks" / "templates" / "claude"

# Every model slot Claude Code may call; all must name a model the server knows.
_MODEL_SLOTS = (
    "ANTHROPIC_MODEL",
    "ANTHROPIC_SMALL_FAST_MODEL",
    "ANTHROPIC_DEFAULT_OPUS_MODEL",
    "ANTHROPIC_DEFAULT_SONNET_MODEL",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL",
    "CLAUDE_CODE_SUBAGENT_MODEL",
)


class ClaudeAdapter(CLIAdapter):
    """Adapter for Claude Code CLI."""

    def get_executable(self) -> str:
        return "claude"

    def get_instruction_filename(self) -> str:
        return "CLAUDE.md"

    def get_hooks_dir(self) -> Path:
        return self.config.workdir / ".claude" / "hooks"

    def get_skills_target_dir(self) -> Path:
        return self.config.workdir / ".claude" / "skills"

    def setup_instruction_file(self, content: str) -> Path:
        filepath = self.config.workdir / "CLAUDE.md"
        filepath.write_text(content, encoding="utf-8")
        return filepath

    def setup_hooks(self, hooks_config: dict) -> None:
        hooks_dir = self.config.workdir / ".claude" / "hooks"
        hooks_dir.mkdir(parents=True, exist_ok=True)

        # Write agent_id for hooks to reference
        (hooks_dir / "agent_id.txt").write_text(
            self.config.agent_id, encoding="utf-8"
        )

        # Initialize stop_count.txt
        (hooks_dir / "stop_count.txt").write_text("0", encoding="utf-8")
        self._write_stop_config(hooks_dir, hooks_config)

        # Deploy hook scripts from templates
        self._deploy_hook_scripts(hooks_dir, hooks_config)

        # Build settings.local.json
        settings: dict = {
            "hooks": {},
            "env": {"DISABLE_AUTOUPDATER": "1"},
        }

        if "on_stop" in hooks_config:
            settings["hooks"]["Stop"] = [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": (
                                'python3 "$CLAUDE_PROJECT_DIR"'
                                "/.claude/hooks/stop.py"
                            ),
                        }
                    ],
                }
            ]

        if "on_session_start" in hooks_config:
            settings["hooks"]["SessionStart"] = [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": (
                                'python3 "$CLAUDE_PROJECT_DIR"'
                                "/.claude/hooks/session_start.py"
                            ),
                        }
                    ],
                }
            ]

        if "on_tool_use" in hooks_config:
            matcher = hooks_config["on_tool_use"].get("matcher", "Bash")
            settings["hooks"]["PostToolUse"] = [
                {
                    "matcher": matcher,
                    "hooks": [
                        {
                            "type": "command",
                            "command": (
                                'python3 "$CLAUDE_PROJECT_DIR"'
                                "/.claude/hooks/post_tool_handler.py"
                            ),
                        }
                    ],
                }
            ]

        if "on_pre_tool_use" in hooks_config:
            matcher = hooks_config["on_pre_tool_use"].get("matcher", "Bash")
            settings["hooks"]["PreToolUse"] = [
                {
                    "matcher": matcher,
                    "hooks": [
                        {
                            "type": "command",
                            "command": (
                                'python3 "$CLAUDE_PROJECT_DIR"'
                                "/.claude/hooks/pre_tool_handler.py"
                            ),
                        }
                    ],
                }
            ]

        if "on_post_write" in hooks_config:
            settings["hooks"].setdefault("PostToolUse", []).append(
                {
                    "matcher": "Write|Edit|MultiEdit",
                    "hooks": [
                        {
                            "type": "command",
                            "command": (
                                'python3 "$CLAUDE_PROJECT_DIR"'
                                "/.claude/hooks/post_write_handler.py"
                            ),
                        }
                    ],
                }
            )

        # Write settings.local.json
        settings_dir = self.config.workdir / ".claude"
        settings_dir.mkdir(parents=True, exist_ok=True)
        settings_path = settings_dir / "settings.local.json"
        settings_path.write_text(
            json.dumps(settings, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def _deploy_hook_scripts(self, hooks_dir: Path, hooks_config: dict) -> None:
        """Copy hook template scripts to the agent's hooks directory."""
        # Map of hook intent key → (template filename, deployed filename)
        script_map = {
            "on_stop": ("stop_polling.py", "stop.py"),
            "on_session_start": ("session_start.py", "session_start.py"),
            "on_tool_use": ("post_tool_handler.py", "post_tool_handler.py"),
            "on_pre_tool_use": ("pre_tool_handler.py", "pre_tool_handler.py"),
            "on_post_write": ("post_write_handler.py", "post_write_handler.py"),
        }

        for intent_key, (template_name, deploy_name) in script_map.items():
            if intent_key in hooks_config:
                src = _TEMPLATE_DIR / template_name
                if src.exists():
                    dst = hooks_dir / deploy_name
                    shutil.copy2(src, dst)
                    dst.chmod(0o755)

    def _write_stop_config(self, hooks_dir: Path, hooks_config: dict) -> None:
        """Persist stop-hook config for the shared stop template."""
        if "on_stop" not in hooks_config:
            return

        stop_cfg = hooks_config.get("on_stop", {})
        config = {
            "action": stop_cfg.get("action", "block_and_reinject"),
            "max_stop_count": stop_cfg.get("max_stop_count", 3),
        }
        (hooks_dir / "stop_config.json").write_text(
            json.dumps(config, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def setup_settings(self, settings: dict) -> None:
        settings_dir = self.config.workdir / ".claude"
        settings_dir.mkdir(parents=True, exist_ok=True)
        settings_path = settings_dir / "settings.local.json"

        # Merge with existing if present
        existing = {}
        if settings_path.exists():
            existing = json.loads(settings_path.read_text(encoding="utf-8"))
        existing.update(settings)

        settings_path.write_text(
            json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def build_launch_command(self) -> list[str]:
        cmd = ["claude", "--dangerously-skip-permissions"]
        if self.config.model_override:
            cmd.extend(["--model", self.config.model_override])
        cmd.extend(self.config.extra_flags)
        return cmd

    def endpoint_settings(self, endpoint: dict) -> EndpointSettings:
        """Anthropic Messages API (``/v1/messages``) on a self-hosted server.

        Optional ``effort`` sets the effort level and forces Claude Code to
        send it, which it otherwise does only for model names it knows.
        """
        key_env = endpoint.get("api_key_env")
        env = {
            "ANTHROPIC_BASE_URL": endpoint["base_url"],
            # Claude Code needs a credential even when the server checks none.
            "ANTHROPIC_AUTH_TOKEN": f"${{{key_env}}}" if key_env else "local",
        }
        model = self.config.model_override or endpoint.get("model")
        if model:
            env.update({slot: model for slot in _MODEL_SLOTS})
        if endpoint.get("effort"):
            env["CLAUDE_CODE_EFFORT_LEVEL"] = endpoint["effort"]
            env["CLAUDE_CODE_ALWAYS_ENABLE_EFFORT"] = "1"
        # A real key in the environment would be sent to the local server.
        return EndpointSettings(env=env, unset=["ANTHROPIC_API_KEY"])

    def build_headless_command(
        self, prompt: str, output_format: str = "text"
    ) -> list[str]:
        cmd = ["claude", "-p", prompt]
        if output_format != "text":
            cmd.extend(["--output-format", output_format])
        return cmd

    def build_resume_command(self, session_id: Optional[str] = None) -> list[str]:
        cmd = ["claude", "--continue", "--dangerously-skip-permissions"]
        if session_id:
            cmd.extend(["--resume", session_id])
        if self.config.model_override:
            cmd.extend(["--model", self.config.model_override])
        return cmd

    def get_native_multi_agent_info(self) -> dict:
        return {
            "supported": True,
            "mechanism": "agent_teams",
            "enable_flag": "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1",
            "notes": "Experimental. Requires v2.1.32+. Uses tmux or iTerm2 split panes.",
        }
