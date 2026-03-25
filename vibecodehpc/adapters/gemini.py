"""Gemini CLI adapter.

Gemini CLI supports a native hooks system with SessionStart, SessionEnd,
BeforeTool, AfterTool, and other events.  Hook commands receive JSON on
stdin with ``session_id``, ``cwd``, ``hook_event_name``, ``timestamp``
— the same protocol as Claude Code and Codex.

This adapter deploys the same hook scripts used by ClaudeAdapter
(session_start.py, stop_polling.py) and configures them via
``.gemini/settings.json`` hooks section.
"""

import json
import shutil
from pathlib import Path
from typing import Optional

from vibecodehpc.adapters.base import CLIAdapter

# Reuse Claude hook templates — Gemini uses the same stdin JSON protocol
_CLAUDE_TEMPLATE_DIR = (
    Path(__file__).resolve().parent.parent / "hooks" / "templates" / "claude"
)


class GeminiAdapter(CLIAdapter):
    """Adapter for Google Gemini CLI."""

    def get_executable(self) -> str:
        return "gemini"

    def get_instruction_filename(self) -> str:
        return "GEMINI.md"

    def get_hooks_dir(self) -> Path:
        return self.config.workdir / ".gemini" / "hooks"

    def get_skills_target_dir(self) -> Path:
        return self.config.workdir / ".gemini" / "skills"

    def setup_instruction_file(self, content: str) -> Path:
        filepath = self.config.workdir / "GEMINI.md"
        filepath.write_text(content, encoding="utf-8")
        return filepath

    def setup_hooks(self, hooks_config: dict) -> None:
        """Deploy hooks via .gemini/hooks/ scripts + settings.json hooks section."""
        hooks_dir = self.config.workdir / ".gemini" / "hooks"
        hooks_dir.mkdir(parents=True, exist_ok=True)

        # Write agent_id for hooks to reference
        (hooks_dir / "agent_id.txt").write_text(
            self.config.agent_id, encoding="utf-8"
        )

        # Initialize stop_count.txt
        (hooks_dir / "stop_count.txt").write_text("0", encoding="utf-8")
        self._write_stop_config(hooks_dir, hooks_config)

        # Deploy hook scripts (reuse Claude templates — same protocol)
        self._deploy_hook_scripts(hooks_dir, hooks_config)

        # Merge hooks into .gemini/settings.json
        self._write_hooks_settings(hooks_config)

    def _deploy_hook_scripts(self, hooks_dir: Path, hooks_config: dict) -> None:
        """Copy Claude hook scripts to .gemini/hooks/ (same stdin JSON protocol)."""
        script_map = {
            "on_stop": ("stop_polling.py", "stop.py"),
            "on_session_start": ("session_start.py", "session_start.py"),
        }

        for intent_key, (template_name, deploy_name) in script_map.items():
            if intent_key in hooks_config:
                src = _CLAUDE_TEMPLATE_DIR / template_name
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
        """Add hooks section to .gemini/settings.json."""
        settings_dir = self.config.workdir / ".gemini"
        settings_dir.mkdir(parents=True, exist_ok=True)
        settings_path = settings_dir / "settings.json"
        # resolve() guarantees absolute path — Gemini CLI has no
        # equivalent of $CLAUDE_PROJECT_DIR, so we must embed the
        # full path in settings.json.
        hooks_dir = (settings_dir / "hooks").resolve()

        existing = {}
        if settings_path.exists():
            existing = json.loads(settings_path.read_text(encoding="utf-8"))

        hooks: dict = existing.get("hooks", {})

        if "on_session_start" in hooks_config:
            hooks["SessionStart"] = [
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

        if "on_stop" in hooks_config:
            hooks["SessionEnd"] = [
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
        """Write Gemini settings with AGENTS.md/CLAUDE.md context file support."""
        import json

        settings_dir = self.config.workdir / ".gemini"
        settings_dir.mkdir(parents=True, exist_ok=True)
        settings_path = settings_dir / "settings.json"

        existing = {}
        if settings_path.exists():
            existing = json.loads(settings_path.read_text(encoding="utf-8"))

        # Disable auto-update (equivalent to Claude's DISABLE_AUTOUPDATER=1).
        # Gemini only supports settings.json for this.
        existing.setdefault("general", {})
        existing["general"]["enableAutoUpdate"] = False
        existing["general"]["enableAutoUpdateNotification"] = False

        # Enable AGENTS.md and CLAUDE.md as additional context files
        existing.setdefault("context", {})
        existing["context"]["fileName"] = ["GEMINI.md", "AGENTS.md", "CLAUDE.md"]

        # Auto-configure telemetry outfile for token usage monitoring
        existing.setdefault("telemetry", {})
        existing["telemetry"].setdefault("enabled", True)
        existing["telemetry"].setdefault("target", "local")
        telemetry_outfile = self.config.workdir / ".gemini" / "telemetry.jsonl"
        existing["telemetry"].setdefault("outfile", str(telemetry_outfile))
        # Ensure the outfile exists (Gemini CLI opens in append mode)
        telemetry_outfile.parent.mkdir(parents=True, exist_ok=True)
        telemetry_outfile.touch(exist_ok=True)

        # Trust project_root and workdir so --yolo is not downgraded
        # to ApprovalMode.DEFAULT by Gemini CLI's folder trust check.
        # IMPORTANT: Gemini CLI reads trust from ~/.gemini/trustedFolders.json,
        # NOT from workspace settings.json. Write to the global file.
        trusted_folders: list[str] = []
        for folder in (self.config.project_root, self.config.workdir):
            resolved = str(folder.resolve())
            if resolved not in trusted_folders:
                trusted_folders.append(resolved)
        self._update_global_folder_trust(trusted_folders)

        # Also set in workspace settings for documentation purposes
        existing.setdefault("security", {})
        existing["security"]["folderTrust"] = {
            "enabled": True,
            "trustedFolders": trusted_folders,
        }

        existing.update(settings)

        settings_path.write_text(
            json.dumps(existing, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    @staticmethod
    def _update_global_folder_trust(folders: list[str]) -> None:
        """Add folders to ~/.gemini/trustedFolders.json (global trust file)."""
        trust_file = Path.home() / ".gemini" / "trustedFolders.json"
        trust_file.parent.mkdir(parents=True, exist_ok=True)
        existing: dict = {}
        if trust_file.exists():
            try:
                existing = json.loads(trust_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                existing = {}
        changed = False
        for folder in folders:
            if folder not in existing:
                existing[folder] = "TRUST_FOLDER"
                changed = True
        if changed:
            trust_file.write_text(
                json.dumps(existing, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

    def build_launch_command(self) -> list[str]:
        # Gemini CLI defaults to Gemini 3 — no --model flag needed.
        # Only pass --model when the user explicitly overrides via config.
        cmd = ["gemini", "--yolo"]
        if self.config.model_override:
            cmd.extend(["--model", self.config.model_override])
        cmd.extend(self.config.extra_flags)
        return cmd

    def build_headless_command(
        self, prompt: str, output_format: str = "text"
    ) -> list[str]:
        cmd = ["gemini", "-p", prompt]
        if output_format != "text":
            cmd.extend(["--output-format", output_format])
        return cmd

    def get_native_multi_agent_info(self) -> dict:
        return {
            "supported": True,
            "mechanism": "subagents",
            "enable_flag": "Extension config",
            "notes": "Experimental subagents defined in extensions.",
        }
