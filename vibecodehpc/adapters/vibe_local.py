"""vibe-local adapter for local LLM inference via Ollama."""

import json
import os
from pathlib import Path
from typing import Optional

from vibecodehpc.adapters.base import CLIAdapter


# Default path to vibe-coder.py — override via VIBE_LOCAL_PATH env var
_DEFAULT_VIBE_CODER = "vibe-coder"

# Default Ollama API endpoint (Win側)
_DEFAULT_OLLAMA_HOST = "http://localhost:11434"


class VibeLocalAdapter(CLIAdapter):
    """Adapter for vibe-local (ochyai/vibe-local).

    vibe-local is a single-file Python CLI (vibe-coder.py) that runs
    on Ollama for fully offline local LLM inference. It supports:
    - 16+ built-in tools (Bash, Read, Write, Edit, Glob, Grep, etc.)
    - Sub-agents and parallel agents
    - MCP server integration
    - Skills loading from .vibe-local/skills/
    """

    def _vibe_coder_path(self) -> str:
        """Resolve path to vibe-coder.py."""
        return os.environ.get("VIBE_LOCAL_PATH", _DEFAULT_VIBE_CODER)

    def _ollama_host(self) -> str:
        """Return OLLAMA_HOST from env or default."""
        return os.environ.get("OLLAMA_HOST", _DEFAULT_OLLAMA_HOST)

    def get_executable(self) -> str:
        return "python3"

    def check_available(self) -> bool:
        """Check Ollama API reachability via OLLAMA_HOST (not binary existence).

        vibe-local uses Ollama running on the Windows host side, accessed
        over the network. Binary existence checks are meaningless — instead
        we probe the Ollama API endpoint.
        """
        import urllib.request
        import urllib.error

        host = self._ollama_host()
        try:
            req = urllib.request.Request(f"{host}/api/tags", method="GET")
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status == 200
        except (urllib.error.URLError, OSError, ValueError):
            return False

    def get_instruction_filename(self) -> str:
        return "AGENTS.md"  # vibe-local reads skills/, not a single instruction file

    def get_skills_target_dir(self) -> Path:
        """vibe-local reads skills from .vibe-local/skills/ or skills/."""
        return self.config.workdir / ".vibe-local" / "skills"

    def setup_instruction_file(self, content: str) -> Path:
        """Write instructions as a skill file (vibe-local loads .md from skills/)."""
        skills_dir = self.config.workdir / ".vibe-local" / "skills"
        skills_dir.mkdir(parents=True, exist_ok=True)
        filepath = skills_dir / "instructions.md"
        filepath.write_text(content, encoding="utf-8")
        return filepath

    def setup_hooks(self, hooks_config: dict) -> None:
        # vibe-local has no hooks system.
        # Polling behavior is handled by its built-in agent loop.
        pass

    def setup_settings(self, settings: dict) -> None:
        """Write vibe-local config file (key=value format)."""
        config_dir = self.config.workdir / ".vibe-local"
        config_dir.mkdir(parents=True, exist_ok=True)
        config_path = config_dir / "config"

        lines = []
        key_map = {
            "model": "MODEL",
            "sidecar_model": "SIDECAR_MODEL",
            "ollama_host": "OLLAMA_HOST",
            "max_tokens": "MAX_TOKENS",
            "temperature": "TEMPERATURE",
            "context_window": "CONTEXT_WINDOW",
        }
        for k, v in settings.items():
            env_key = key_map.get(k, k.upper())
            lines.append(f"{env_key}={v}")

        config_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        # MCP config if present
        if "mcp_servers" in settings:
            mcp_path = config_dir / "mcp.json"
            mcp_path.write_text(
                json.dumps(
                    {"mcpServers": settings["mcp_servers"]},
                    indent=2,
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

    def build_launch_command(self) -> list[str]:
        vibe_path = self._vibe_coder_path()
        # If path looks like a standalone script/binary (no .py extension),
        # call it directly. Otherwise use python3 as interpreter.
        if vibe_path.endswith(".py"):
            cmd = ["python3", vibe_path, "-y"]
        else:
            cmd = [vibe_path, "-y"]
        if self.config.model_override:
            cmd.extend(["--model", self.config.model_override])
        cmd.extend(self.config.extra_flags)
        return cmd

    def build_headless_command(
        self, prompt: str, output_format: str = "text"
    ) -> list[str]:
        vibe_path = self._vibe_coder_path()
        if vibe_path.endswith(".py"):
            cmd = ["python3", vibe_path, "-p", prompt, "-y"]
        else:
            cmd = [vibe_path, "-p", prompt, "-y"]
        if self.config.model_override:
            cmd.extend(["--model", self.config.model_override])
        return cmd

    def get_native_multi_agent_info(self) -> dict:
        return {
            "supported": True,
            "mechanism": "sub_agent_and_parallel",
            "enable_flag": "Built-in (SubAgentTool + ParallelAgentTool)",
            "notes": (
                "vibe-local supports sub-agents (max 20 turns, read-only by default) "
                "and parallel agents (max 4, via MultiAgentCoordinator). "
                "Sidecar model can be used for sub-agents to reduce VRAM usage."
            ),
        }
