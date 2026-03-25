"""Global configuration management for VibeCodeHPC.

Config hierarchy (lowest to highest priority):
1. Built-in defaults
2. config.yaml in project root
3. Environment variables
4. CLI arguments
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional


@dataclass
class HooksConfig:
    """Hooks behavior configuration."""

    enabled: bool = True  # Master switch for hooks
    stop_block: bool = True  # Block stop events to keep agents polling (default on)
    context_reinject: bool = False  # Re-inject files on stop (heavy, optional)
    context_reinject_max_bytes: int = 5000  # Limit re-injection size
    session_start_context: bool = True  # Inject context on session start
    tool_guard: bool = True  # SSH/SFTP validation
    stop_threshold: int = 30  # Default stop count before graceful shutdown


@dataclass
class AgentRoleConfig:
    """Per-role configuration."""

    instruction_file: str = ""  # Path to role instructions
    required_files: list = field(default_factory=list)
    polling: bool = True  # Polling vs event-driven
    stop_threshold: Optional[int] = None  # Override global


@dataclass
class AgentCLIConfig:
    """Per-agent CLI and model override."""

    cli: Optional[str] = None
    model: Optional[str] = None


@dataclass
class VibeCodeConfig:
    """Top-level VibeCodeHPC configuration."""

    project_root: Path = field(default_factory=Path.cwd)
    project_name: str = ""

    # CLI defaults
    default_cli: str = "claude"
    permission_bypass: bool = True

    # Agent layout
    max_panes_per_session: int = 12
    agent_workdir_base: str = ""  # Relative to project_root

    # Hooks (optional — strong models may not need them)
    hooks: HooksConfig = field(default_factory=HooksConfig)

    # Roles
    roles: dict = field(default_factory=lambda: {
        "PM": AgentRoleConfig(
            instruction_file="instructions/PM.md",
            required_files=[
                "CLAUDE.md",
                "Agent-shared/directory_pane_map.txt",
                "Agent-shared/skills/hpc-strategies/references/typical_hpc_structure.md",
            ],
            stop_threshold=50,
        ),
        "SE": AgentRoleConfig(
            instruction_file="instructions/SE.md",
            required_files=[
                "CLAUDE.md",
                "Agent-shared/directory_pane_map.txt",
            ],
            stop_threshold=30,
        ),
        "PG": AgentRoleConfig(
            instruction_file="instructions/PG.md",
            required_files=[
                "CLAUDE.md",
                "Agent-shared/skills/changelog-format/SKILL.md",
            ],
            stop_threshold=20,
        ),
        "CD": AgentRoleConfig(
            instruction_file="instructions/CD.md",
            required_files=["CLAUDE.md"],
            stop_threshold=40,
        ),
        "SOLO": AgentRoleConfig(
            instruction_file="instructions/SOLO.md",
            required_files=["CLAUDE.md"],
            stop_threshold=100,
        ),
    })

    # Per-agent CLI/model overrides (keyed by agent_id or role)
    agents: Dict[str, AgentCLIConfig] = field(default_factory=dict)

    # Strategies (offloadable templates)
    strategies_dir: str = "Agent-shared/strategies"

    # Telemetry (optional)
    telemetry_enabled: bool = False
    otel_endpoint: str = ""

    def get_agent_cli(self, agent_id: str, role: str = "") -> str:
        """Return CLI for *agent_id*, falling back to role then default_cli."""
        if agent_id in self.agents and self.agents[agent_id].cli:
            return self.agents[agent_id].cli
        if role and role in self.agents and self.agents[role].cli:
            return self.agents[role].cli
        return self.default_cli

    def get_agent_model(
        self, agent_id: str, role: str = "", fallback: Optional[str] = None,
    ) -> Optional[str]:
        """Return model for *agent_id*, falling back to role then *fallback*."""
        if agent_id in self.agents and self.agents[agent_id].model:
            return self.agents[agent_id].model
        if role and role in self.agents and self.agents[role].model:
            return self.agents[role].model
        return fallback

    @classmethod
    def load(
        cls,
        project_root: Optional[Path] = None,
        agents_config: Optional[Path] = None,
    ) -> "VibeCodeConfig":
        """Load config from project root config.yaml + env vars.

        Args:
            project_root: Project root directory.
            agents_config: Optional path to a separate agents config YAML/JSON
                overriding the ``agents`` section.
        """
        root = project_root or Path.cwd()
        config = cls(project_root=root)

        config_file = root / "config.yaml"
        if config_file.exists():
            try:
                import yaml
                data = yaml.safe_load(config_file.read_text(encoding="utf-8"))
                if data:
                    config._apply_dict(data)
            except ImportError:
                # Try JSON fallback
                config_file = root / "config.json"
                if config_file.exists():
                    import json
                    data = json.loads(config_file.read_text(encoding="utf-8"))
                    if data:
                        config._apply_dict(data)

        # Separate agents config file (--agents-config)
        if agents_config and agents_config.exists():
            config._load_agents_config(agents_config)

        # Env var overrides
        if os.environ.get("VIBECODE_CLI"):
            config.default_cli = os.environ["VIBECODE_CLI"]
        if os.environ.get("VIBECODE_HOOKS_ENABLED"):
            config.hooks.enabled = os.environ["VIBECODE_HOOKS_ENABLED"] == "1"
        if os.environ.get("VIBECODE_STOP_BLOCK"):
            config.hooks.stop_block = os.environ["VIBECODE_STOP_BLOCK"] == "1"
        if os.environ.get("VIBECODE_TELEMETRY"):
            config.telemetry_enabled = os.environ["VIBECODE_TELEMETRY"] == "1"

        return config

    def _load_agents_config(self, path: Path) -> None:
        """Load per-agent config from a standalone YAML/JSON file."""
        content = path.read_text(encoding="utf-8")
        data: Optional[dict] = None
        if path.suffix in (".yaml", ".yml"):
            try:
                import yaml
                data = yaml.safe_load(content)
            except ImportError:
                pass
        if data is None:
            import json
            data = json.loads(content)
        if isinstance(data, dict):
            # Accept both top-level agents dict and wrapped {"agents": {...}}
            agents_data = data.get("agents", data)
            if isinstance(agents_data, dict):
                self._apply_dict({"agents": agents_data})

    def _apply_dict(self, data: dict):
        """Apply dict values to config."""
        if "project_name" in data:
            self.project_name = data["project_name"]
        if "default_cli" in data:
            self.default_cli = data["default_cli"]
        if "max_panes_per_session" in data:
            self.max_panes_per_session = data["max_panes_per_session"]

        hooks_data = data.get("hooks", {})
        if hooks_data:
            for key in ("enabled", "stop_block", "context_reinject",
                        "context_reinject_max_bytes", "session_start_context",
                        "tool_guard", "stop_threshold"):
                if key in hooks_data:
                    setattr(self.hooks, key, hooks_data[key])

        agents_data = data.get("agents", {})
        if isinstance(agents_data, dict):
            for agent_key, agent_val in agents_data.items():
                if isinstance(agent_val, dict):
                    self.agents[agent_key] = AgentCLIConfig(
                        cli=agent_val.get("cli"),
                        model=agent_val.get("model"),
                    )

        if "telemetry" in data:
            tel = data["telemetry"]
            self.telemetry_enabled = tel.get("enabled", False)
            self.otel_endpoint = tel.get("endpoint", "")
