"""Qwen Code adapter.

Qwen Code is a Gemini CLI fork.  It shares the same TUI interaction
model (``--yolo`` for autonomous mode, ``-p`` for headless) but uses
its own instruction file (``QWEN.md``) and settings directory
(``.qwen/``).

Qwen Code does NOT support a native hooks system, so this adapter
uses the Codex/AGENTS.md anti-idle fallback pattern for the stop hook
and deploys hook scripts under ``.qwen/hooks/`` for future use.

**Telemetry** is always forcibly disabled for safety — both
``telemetry.enabled`` and ``usageStatisticsEnabled`` are set to false
in ``.qwen/settings.json``.
"""

import json
import os
import shutil
from pathlib import Path
from typing import Optional

from vibecodehpc.adapters.base import CLIAdapter

# Reuse Claude hook templates — same stdin JSON protocol
_CLAUDE_TEMPLATE_DIR = (
    Path(__file__).resolve().parent.parent / "hooks" / "templates" / "claude"
)


class QwenAdapter(CLIAdapter):
    """Adapter for Qwen Code CLI (Gemini CLI fork)."""

    def get_executable(self) -> str:
        return "qwen"

    def get_instruction_filename(self) -> str:
        return "QWEN.md"

    def get_hooks_dir(self) -> Path:
        return self.config.workdir / ".qwen" / "hooks"

    def get_skills_target_dir(self) -> Path:
        return self.config.workdir / ".qwen" / "skills"

    def setup_instruction_file(self, content: str) -> Path:
        filepath = self.config.workdir / "QWEN.md"
        filepath.write_text(content, encoding="utf-8")
        return filepath

    def setup_hooks(self, hooks_config: dict) -> None:
        """Deploy hooks via .qwen/hooks/ scripts + AGENTS.md anti-idle fallback.

        Qwen Code does not have a native hooks engine, so we use the
        same AGENTS.md anti-idle directive pattern as Codex.
        """
        hooks_dir = self.config.workdir / ".qwen" / "hooks"
        hooks_dir.mkdir(parents=True, exist_ok=True)

        # Write agent_id for hooks to reference
        (hooks_dir / "agent_id.txt").write_text(
            self.config.agent_id, encoding="utf-8"
        )

        # Initialize stop_count.txt
        (hooks_dir / "stop_count.txt").write_text("0", encoding="utf-8")
        self._write_stop_config(hooks_dir, hooks_config)

        # Deploy hook scripts (reuse Claude templates)
        self._deploy_hook_scripts(hooks_dir, hooks_config)

        # AGENTS.md anti-idle fallback (no native hooks engine)
        if "on_stop" in hooks_config:
            self._append_anti_idle_directive()

    def _deploy_hook_scripts(self, hooks_dir: Path, hooks_config: dict) -> None:
        """Copy Claude hook scripts to .qwen/hooks/."""
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
        """Write Qwen settings with telemetry forcibly disabled."""
        settings_dir = self.config.workdir / ".qwen"
        settings_dir.mkdir(parents=True, exist_ok=True)
        settings_path = settings_dir / "settings.json"

        existing = {}
        if settings_path.exists():
            existing = json.loads(settings_path.read_text(encoding="utf-8"))

        # Disable auto-update
        existing.setdefault("general", {})
        existing["general"]["enableAutoUpdate"] = False
        existing["general"]["enableAutoUpdateNotification"] = False

        # Enable AGENTS.md and CLAUDE.md as additional context files
        existing.setdefault("context", {})
        existing["context"]["fileName"] = ["QWEN.md", "AGENTS.md", "CLAUDE.md"]

        # SAFETY: Forcibly disable ALL telemetry
        # 1) OpenTelemetry SDK (telemetry.enabled)
        existing.setdefault("telemetry", {})
        existing["telemetry"]["enabled"] = False
        # 2) QwenLogger / Aliyun RUM (privacy.usageStatisticsEnabled)
        #    Sends usage stats to gb4w8c3ygj-default-sea.rum.aliyuncs.com
        #    Default is true — must be explicitly disabled
        existing.setdefault("privacy", {})
        existing["privacy"]["usageStatisticsEnabled"] = False

        existing.update(settings)

        # Re-enforce telemetry disable AFTER user settings merge
        # (prevents accidental re-enable via settings dict)
        existing.setdefault("telemetry", {})
        existing["telemetry"]["enabled"] = False
        existing.setdefault("privacy", {})
        existing["privacy"]["usageStatisticsEnabled"] = False

        settings_path.write_text(
            json.dumps(existing, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def _needs_openrouter_bridge(self) -> bool:
        """Return True when OPENROUTER_API_KEY is available for bridging."""
        return bool(os.environ.get("OPENROUTER_API_KEY"))

    def _needs_openai_auth(self) -> bool:
        """Return True when OpenAI-compatible auth is needed.

        Only needed when explicitly using OpenAI-compatible API (OpenRouter bridge).
        Native Qwen auth (qwen auth login / DashScope) does not need this flag.
        """
        if self.config.env_vars.get("OPENAI_API_KEY"):
            return True
        if self.config.env_vars.get("OPENAI_BASE_URL"):
            return True
        return False

    def build_launch_command(self) -> list[str]:
        cmd = ["DISABLE_AUTOUPDATER=1"]
        # Bridge OPENROUTER_API_KEY → OPENAI_API_KEY/BASE_URL for Qwen
        if self._needs_openrouter_bridge() and not os.environ.get("OPENAI_API_KEY"):
            cmd.append("OPENAI_API_KEY=$OPENROUTER_API_KEY")
            cmd.append("OPENAI_BASE_URL=https://openrouter.ai/api/v1")
        cmd.extend(["qwen", "--yolo"])
        if self._needs_openai_auth():
            cmd.extend(["--auth-type", "openai"])
        if self.config.model_override:
            cmd.extend(["--model", self.config.model_override])
        cmd.extend(self.config.extra_flags)
        return cmd

    def build_headless_command(
        self, prompt: str, output_format: str = "text"
    ) -> list[str]:
        cmd = ["qwen", "-p", prompt]
        if output_format != "text":
            cmd.extend(["--output-format", output_format])
        return cmd

    def get_native_multi_agent_info(self) -> dict:
        return {
            "supported": False,
            "mechanism": "none",
            "enable_flag": None,
            "notes": "Qwen Code (Gemini CLI fork) does not support native multi-agent.",
        }
