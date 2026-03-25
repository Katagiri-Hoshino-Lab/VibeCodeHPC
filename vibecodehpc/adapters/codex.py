"""Codex CLI adapter.

Codex CLI (codex-rs) supports a hooks engine with SessionStart and Stop
events using the same exit-code-2 protocol as Claude Code.  The hooks
are configured via ``.codex/hooks.json`` and enabled by the feature flag
``features.codex_hooks = true`` in ``config.toml``.

This adapter deploys the same hook scripts used by ClaudeAdapter
(session_start.py, stop_polling.py) and additionally keeps the
AGENTS.md anti-idle directive as a fallback for environments where
the hooks feature flag is not available.
"""

import json
import shutil
from pathlib import Path
from typing import Optional

from vibecodehpc.adapters.base import CLIAdapter

# Reuse Claude hook templates — Codex uses the same protocol
_CLAUDE_TEMPLATE_DIR = (
    Path(__file__).resolve().parent.parent / "hooks" / "templates" / "claude"
)


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


class CodexAdapter(CLIAdapter):
    """Adapter for OpenAI Codex CLI (Rust-based)."""

    def get_executable(self) -> str:
        return "codex"

    def get_instruction_filename(self) -> str:
        return "AGENTS.md"

    def get_hooks_dir(self) -> Path:
        return self.config.workdir / ".codex" / "hooks"

    def get_skills_target_dir(self) -> Path:
        return self.config.workdir / ".agents" / "skills"

    def setup_instruction_file(self, content: str) -> Path:
        filepath = self.config.workdir / "AGENTS.md"
        filepath.write_text(content, encoding="utf-8")
        return filepath

    def setup_hooks(self, hooks_config: dict) -> None:
        """Deploy hooks via .codex/hooks.json + AGENTS.md fallback."""
        hooks_dir = self.config.workdir / ".codex" / "hooks"
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

        # Generate .codex/hooks.json
        self._write_hooks_json(hooks_config)

        # AGENTS.md anti-idle fallback (for envs without codex_hooks flag)
        if "on_stop" in hooks_config:
            self._append_anti_idle_directive()

    def _deploy_hook_scripts(self, hooks_dir: Path, hooks_config: dict) -> None:
        """Copy Claude hook scripts to .codex/hooks/ (same exit-code-2 protocol)."""
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

    def _write_hooks_json(self, hooks_config: dict) -> None:
        """Write .codex/hooks.json in the same format as Claude's settings."""
        codex_dir = self.config.workdir / ".codex"
        codex_dir.mkdir(parents=True, exist_ok=True)
        # resolve() guarantees absolute path — Codex CLI has no
        # equivalent of $CLAUDE_PROJECT_DIR, so we must embed the
        # full path in hooks.json.
        hooks_dir = (codex_dir / "hooks").resolve()

        hooks: dict = {}

        if "on_session_start" in hooks_config:
            hooks["SessionStart"] = [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": f"python3 {hooks_dir / 'session_start.py'}",
                        }
                    ],
                }
            ]

        if "on_stop" in hooks_config:
            hooks["Stop"] = [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": f"python3 {hooks_dir / 'stop.py'}",
                        }
                    ],
                }
            ]

        hooks_json_path = codex_dir / "hooks.json"
        hooks_json_path.write_text(
            json.dumps({"hooks": hooks}, indent=2, ensure_ascii=False) + "\n",
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
        """Write Codex config.toml with hooks feature flag and CLAUDE.md fallback."""
        config_dir = self.config.workdir / ".codex"
        config_dir.mkdir(parents=True, exist_ok=True)
        config_path = config_dir / "config.toml"

        config: dict = {}
        if config_path.exists():
            try:
                import tomllib
                config = tomllib.loads(config_path.read_text(encoding="utf-8"))
            except ImportError:
                pass

        # Disable auto-update check on startup (equivalent to Claude's
        # DISABLE_AUTOUPDATER=1).  Codex only supports config.toml for this.
        config["check_for_update_on_startup"] = False

        # Enable CLAUDE.md as fallback instruction file
        config.setdefault("project_doc_fallback_filenames", ["CLAUDE.md"])

        # Enable hooks engine feature flag
        config.setdefault("features", {})
        config["features"]["codex_hooks"] = True

        config.update(settings)

        try:
            import tomli_w
            config_path.write_bytes(tomli_w.dumps(config).encode())
        except ImportError:
            # Fallback: write TOML manually
            lines = []
            for k, v in config.items():
                if isinstance(v, dict):
                    lines.append(f"[{k}]")
                    for sk, sv in v.items():
                        lines.append(
                            f"{sk} = {_toml_value(sv)}"
                        )
                else:
                    lines.append(f"{k} = {_toml_value(v)}")
            config_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def build_launch_command(self) -> list[str]:
        cmd = ["codex", "--yolo"]
        if self.config.model_override:
            cmd.extend(["--model", self.config.model_override])
        cmd.extend(self.config.extra_flags)
        return cmd

    def build_headless_command(
        self, prompt: str, output_format: str = "text"
    ) -> list[str]:
        cmd = ["codex", "exec", prompt]
        if output_format == "json":
            cmd.append("--json")
        return cmd

    def build_resume_command(self, session_id: Optional[str] = None) -> list[str]:
        cmd = ["codex"]
        if session_id:
            cmd.extend(["exec", "--resume", session_id])
        else:
            cmd.append("--yolo")
        cmd.extend(self.config.extra_flags)
        return cmd

    def get_native_multi_agent_info(self) -> dict:
        return {
            "supported": True,
            "mechanism": "experimental_multi",
            "enable_flag": "/experimental command within session",
            "notes": "Experimental multi-agent via /experimental command.",
        }
