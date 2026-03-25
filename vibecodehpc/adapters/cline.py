"""Cline CLI 2.0 adapter.

Cline CLI supports 4 hook events: TaskStart, PreToolUse, PostToolUse,
UserPromptSubmit.  Instructions are placed in ``.clinerules/``.
Autonomous mode is enabled via ``-y`` (YOLO mode), which also serves
as headless mode with stdout output.

This adapter deploys hook scripts from templates/cline/ and configures
them via ``.cline/settings.json``.
"""

import json
import shutil
from pathlib import Path
from typing import Optional

from vibecodehpc.adapters.base import CLIAdapter

# Template directory for Cline-specific hooks
_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "hooks" / "templates" / "cline"

# Reuse Claude hook templates for shared scripts (same stdin JSON protocol)
_CLAUDE_TEMPLATE_DIR = (
    Path(__file__).resolve().parent.parent / "hooks" / "templates" / "claude"
)


class ClineAdapter(CLIAdapter):
    """Adapter for Cline CLI 2.0."""

    def get_executable(self) -> str:
        return "cline"

    def get_instruction_filename(self) -> str:
        return ".clinerules"

    def get_hooks_dir(self) -> Path:
        return self.config.workdir / ".cline" / "hooks"

    def get_skills_target_dir(self) -> Path:
        return self.config.workdir / ".cline" / "skills"

    def setup_instruction_file(self, content: str) -> Path:
        rules_dir = self.config.workdir / ".clinerules"
        rules_dir.mkdir(parents=True, exist_ok=True)
        filepath = rules_dir / "rules.md"
        filepath.write_text(content, encoding="utf-8")
        return filepath

    def setup_hooks(self, hooks_config: dict) -> None:
        """Deploy hooks via .cline/hooks/ scripts + settings.json hooks section.

        Cline CLI 2.0 supports 4 hook events:
        - TaskStart (maps from on_session_start)
        - PreToolUse (maps from on_pre_tool_use)
        - PostToolUse (maps from on_tool_use)
        - UserPromptSubmit (maps from on_stop)
        """
        hooks_dir = self.config.workdir / ".cline" / "hooks"
        hooks_dir.mkdir(parents=True, exist_ok=True)

        # Write agent_id for hooks to reference
        (hooks_dir / "agent_id.txt").write_text(
            self.config.agent_id, encoding="utf-8"
        )

        # Initialize stop_count.txt
        (hooks_dir / "stop_count.txt").write_text("0", encoding="utf-8")
        self._write_stop_config(hooks_dir, hooks_config)

        # Deploy hook scripts
        self._deploy_hook_scripts(hooks_dir, hooks_config)

        # Build settings.json with hooks section
        self._write_hooks_settings(hooks_config)

    def _deploy_hook_scripts(self, hooks_dir: Path, hooks_config: dict) -> None:
        """Copy hook scripts to .cline/hooks/.

        Reuses Claude hook templates where the stdin JSON protocol is compatible.
        """
        # Map: hook intent key -> (template_name, deploy_name, source_dir)
        script_map = {
            "on_stop": ("stop_polling.py", "stop.py", _CLAUDE_TEMPLATE_DIR),
            "on_session_start": ("session_start.py", "session_start.py", _CLAUDE_TEMPLATE_DIR),
            "on_tool_use": ("post_tool_handler.py", "post_tool_handler.py", _CLAUDE_TEMPLATE_DIR),
            "on_pre_tool_use": ("pre_tool_handler.py", "pre_tool_handler.py", _CLAUDE_TEMPLATE_DIR),
        }

        for intent_key, (template_name, deploy_name, src_dir) in script_map.items():
            if intent_key in hooks_config:
                src = src_dir / template_name
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

    def _write_hooks_settings(self, hooks_config: dict) -> None:
        """Add hooks section to .cline/settings.json.

        Cline CLI 2.0 hook events:
        - TaskStart -> on_session_start
        - PreToolUse -> on_pre_tool_use
        - PostToolUse -> on_tool_use
        - UserPromptSubmit -> on_stop
        """
        settings_dir = self.config.workdir / ".cline"
        settings_dir.mkdir(parents=True, exist_ok=True)
        settings_path = settings_dir / "settings.json"
        hooks_dir = (settings_dir / "hooks").resolve()

        existing = {}
        if settings_path.exists():
            existing = json.loads(settings_path.read_text(encoding="utf-8"))

        hooks: dict = existing.get("hooks", {})

        if "on_session_start" in hooks_config:
            hooks["TaskStart"] = [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": f"python3 {hooks_dir / 'session_start.py'}",
                            "timeout": 5000,
                        }
                    ],
                }
            ]

        if "on_pre_tool_use" in hooks_config:
            matcher = hooks_config["on_pre_tool_use"].get("matcher", "Bash")
            hooks["PreToolUse"] = [
                {
                    "matcher": matcher,
                    "hooks": [
                        {
                            "type": "command",
                            "command": f"python3 {hooks_dir / 'pre_tool_handler.py'}",
                            "timeout": 5000,
                        }
                    ],
                }
            ]

        if "on_tool_use" in hooks_config:
            matcher = hooks_config["on_tool_use"].get("matcher", "Bash")
            hooks["PostToolUse"] = [
                {
                    "matcher": matcher,
                    "hooks": [
                        {
                            "type": "command",
                            "command": f"python3 {hooks_dir / 'post_tool_handler.py'}",
                            "timeout": 5000,
                        }
                    ],
                }
            ]

        if "on_stop" in hooks_config:
            hooks["UserPromptSubmit"] = [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": f"python3 {hooks_dir / 'stop.py'}",
                            "timeout": 5000,
                        }
                    ],
                }
            ]

        if hooks:
            existing["hooks"] = hooks

        settings_path.write_text(
            json.dumps(existing, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def setup_settings(self, settings: dict) -> None:
        settings_dir = self.config.workdir / ".cline"
        settings_dir.mkdir(parents=True, exist_ok=True)
        settings_path = settings_dir / "settings.json"

        existing = {}
        if settings_path.exists():
            existing = json.loads(settings_path.read_text(encoding="utf-8"))

        # Disable auto-update
        existing.setdefault("general", {})
        existing["general"]["enableAutoUpdate"] = False

        existing.update(settings)

        settings_path.write_text(
            json.dumps(existing, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def build_launch_command(self) -> list[str]:
        cmd = ["CLINE_NO_AUTO_UPDATE=1", "cline", "-y"]
        if self.config.model_override:
            cmd.extend(["--model", self.config.model_override])
        cmd.extend(self.config.extra_flags)
        return cmd

    def build_headless_command(
        self, prompt: str, output_format: str = "text"
    ) -> list[str]:
        cmd = ["cline", "-y", "-p", prompt]
        if output_format != "text":
            cmd.extend(["--output-format", output_format])
        return cmd

    def build_resume_command(self, session_id: Optional[str] = None) -> list[str]:
        cmd = ["cline", "-y", "--continue"]
        if session_id:
            cmd.extend(["--resume", session_id])
        if self.config.model_override:
            cmd.extend(["--model", self.config.model_override])
        return cmd

    def get_native_multi_agent_info(self) -> dict:
        return {
            "supported": True,
            "mechanism": "sub_agent",
            "enable_flag": None,
            "notes": "Cline CLI 2.0 supports sub-agents and auto-compact natively.",
        }
