"""Abstract base class for AI coding CLI adapters."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional
import logging
import shutil
import subprocess

logger = logging.getLogger(__name__)


class CLIType(Enum):
    CLAUDE = "claude"
    CLINE = "cline"
    CODEX = "codex"
    GEMINI = "gemini"
    KIMI = "kimi"
    OPENCODE = "opencode"
    QWEN = "qwen"
    VIBE_LOCAL = "vibe-local"


def infer_cli_from_model(model_name: str) -> CLIType:
    """Infer the CLI type from a model name string.

    Falls back to CLAUDE (works with OpenRouter and other providers).
    """
    lower = model_name.lower()
    if any(kw in lower for kw in ("gpt", "o1", "o3", "codex")):
        return CLIType.CODEX
    if "gemini" in lower:
        return CLIType.GEMINI
    if any(kw in lower for kw in ("kimi", "moonshot")):
        return CLIType.KIMI
    if "qwen" in lower:
        return CLIType.QWEN
    # claude/opus/sonnet/haiku → CLAUDE, and default fallback
    return CLIType.CLAUDE


@dataclass
class AgentConfig:
    """CLI-agnostic agent configuration."""

    agent_id: str
    workdir: Path
    project_root: Path
    cli_type: CLIType
    tmux_target: str  # "session:window.pane"
    role: str = ""  # PM/SE/PG/CD/SOLO
    agent_type: str = "polling"  # polling or event-driven
    model_override: Optional[str] = None
    env_vars: dict = field(default_factory=dict)
    extra_flags: list = field(default_factory=list)


@dataclass
class HeadlessResult:
    """Result from a headless (one-shot) invocation."""

    stdout: str
    stderr: str
    exit_code: int
    session_id: Optional[str] = None


class CLIAdapter(ABC):
    """
    Abstract base class for AI coding CLI adapters.

    Each adapter normalizes one CLI tool's interface for VibeCodeHPC's
    tmux-based multi-agent orchestration. The adapter does NOT replace
    the CLI's native multi-agent support -- it provides lifecycle and
    IPC plumbing so the orchestration layer can treat all CLIs uniformly.
    """

    def __init__(self, config: AgentConfig):
        self.config = config

    # ── Binary / availability ────────────────────────────────

    @abstractmethod
    def get_executable(self) -> str:
        """Return the CLI binary name or path."""
        ...

    def check_available(self) -> bool:
        """Return True if the CLI binary is installed and accessible."""
        try:
            result = subprocess.run(
                ["which", self.get_executable()],
                capture_output=True,
                text=True,
            )
            return result.returncode == 0
        except FileNotFoundError:
            return False

    # ── Configuration setup (pre-launch) ─────────────────────

    @abstractmethod
    def setup_instruction_file(self, content: str) -> Path:
        """
        Write the project instruction file in the format the CLI expects.

        Returns the path to the created file.
        """
        ...

    @abstractmethod
    def setup_hooks(self, hooks_config: dict) -> None:
        """
        Deploy hooks/plugins into the agent's workdir.

        hooks_config contains CLI-agnostic hook intents:
        {
            "on_stop": {"action": "block_and_reinject", ...},
            "on_session_start": {"action": "inject_context", ...},
            "on_tool_use": {"matcher": "Bash|ssh", ...},
        }
        """
        ...

    @abstractmethod
    def setup_settings(self, settings: dict) -> None:
        """Write CLI-specific settings/config file."""
        ...

    # ── Agent lifecycle ──────────────────────────────────────

    @abstractmethod
    def build_launch_command(self) -> list[str]:
        """
        Build the shell command to launch the CLI in interactive mode.

        Does NOT include workdir (handled by pre-launch cd).
        """
        ...

    @abstractmethod
    def build_headless_command(
        self, prompt: str, output_format: str = "text"
    ) -> list[str]:
        """Build command for non-interactive (one-shot) execution."""
        ...

    def build_resume_command(self, session_id: Optional[str] = None) -> list[str]:
        """Build command to resume a previous session. Default: fresh launch."""
        return self.build_launch_command()

    # ── IPC (tmux-based, shared across all adapters) ─────────

    def send_message(self, message: str) -> bool:
        """Send a message to the agent via tmux send-keys.

        Sends Escape first to clear any pending multiline input (needed for
        Gemini CLI), then text, waits 0.5s, then Enter (C-m) separately.
        This prevents input truncation and stuck-input issues in CLI TUIs.
        """
        import time

        target = self.config.tmux_target
        try:
            # Escape clears multiline input buffers (required for Gemini CLI)
            subprocess.run(
                ["tmux", "send-keys", "-t", target, "Escape"],
                check=True,
                capture_output=True,
            )
            time.sleep(0.3)
            subprocess.run(
                ["tmux", "send-keys", "-t", target, message],
                check=True,
                capture_output=True,
            )
            time.sleep(0.5)
            subprocess.run(
                ["tmux", "send-keys", "-t", target, "C-m"],
                check=True,
                capture_output=True,
            )
            return True
        except subprocess.CalledProcessError:
            return False

    def send_interrupt(self) -> bool:
        """Send Escape to pause the agent."""
        target = self.config.tmux_target
        try:
            subprocess.run(
                ["tmux", "send-keys", "-t", target, "Escape"],
                check=True,
                capture_output=True,
            )
            return True
        except subprocess.CalledProcessError:
            return False

    # ── Liveness ─────────────────────────────────────────────

    def detect_alive(self) -> bool:
        """Check if the CLI process is still running in its tmux pane."""
        target = self.config.tmux_target
        try:
            result = subprocess.run(
                ["tmux", "list-panes", "-t", target, "-F", "#{pane_pid}"],
                capture_output=True,
                text=True,
            )
            return result.returncode == 0 and result.stdout.strip() != ""
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False

    # ── Hooks directory ───────────────────────────────────────

    def get_hooks_dir(self) -> Optional[Path]:
        """Return the CLI-specific hooks/plugins directory under workdir.

        Returns None if the CLI does not support hooks.
        Subclasses override to provide their CLI's path convention.
        """
        return None

    # ── Skills deployment ────────────────────────────────────

    def get_skills_target_dir(self) -> Optional[Path]:
        """Return the CLI-specific skills directory under workdir.

        Returns None if the CLI does not support Agent Skills.
        Subclasses override to provide their CLI's path convention.
        """
        return None

    def deploy_skills(self, source_dir: Path) -> list[Path]:
        """Copy skills from *source_dir* into the CLI-specific skills path.

        Each subdirectory of *source_dir* that contains a SKILL.md is
        treated as a skill and copied into ``get_skills_target_dir()/<name>/``.

        Returns the list of deployed skill directories.
        """
        target_root = self.get_skills_target_dir()
        if target_root is None:
            logger.debug(
                "%s: skills deployment skipped (not supported)",
                type(self).__name__,
            )
            return []

        deployed: list[Path] = []
        for skill_dir in sorted(source_dir.iterdir()):
            skill_md = skill_dir / "SKILL.md"
            if not skill_dir.is_dir() or not skill_md.exists():
                continue

            dest = target_root / skill_dir.name
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(skill_dir, dest)
            deployed.append(dest)
            logger.info(
                "%s: deployed skill '%s' → %s",
                type(self).__name__,
                skill_dir.name,
                dest,
            )

        return deployed

    # ── Introspection ────────────────────────────────────────

    @abstractmethod
    def get_instruction_filename(self) -> str:
        """Return the instruction file name this CLI expects."""
        ...

    @abstractmethod
    def get_native_multi_agent_info(self) -> dict:
        """Return info about the CLI's native multi-agent support."""
        ...
