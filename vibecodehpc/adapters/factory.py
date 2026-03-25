"""Factory for creating CLI adapters."""

from vibecodehpc.adapters.base import AgentConfig, CLIAdapter, CLIType


def create_adapter(config: AgentConfig) -> CLIAdapter:
    """Return the correct adapter for the given CLI type."""
    from vibecodehpc.adapters.claude import ClaudeAdapter
    from vibecodehpc.adapters.cline import ClineAdapter
    from vibecodehpc.adapters.codex import CodexAdapter
    from vibecodehpc.adapters.gemini import GeminiAdapter
    from vibecodehpc.adapters.kimi import KimiAdapter
    from vibecodehpc.adapters.opencode import OpenCodeAdapter
    from vibecodehpc.adapters.qwen import QwenAdapter

    adapters = {
        CLIType.CLAUDE: ClaudeAdapter,
        CLIType.CLINE: ClineAdapter,
        CLIType.CODEX: CodexAdapter,
        CLIType.GEMINI: GeminiAdapter,
        CLIType.KIMI: KimiAdapter,
        CLIType.OPENCODE: OpenCodeAdapter,
        CLIType.QWEN: QwenAdapter,
    }

    # dev-only adapters (loaded if available)
    try:
        from vibecodehpc.adapters.vibe_local import VibeLocalAdapter
        adapters[CLIType.VIBE_LOCAL] = VibeLocalAdapter
    except ImportError:
        pass

    adapter_class = adapters.get(config.cli_type)
    if not adapter_class:
        raise ValueError(f"Unknown CLI type: {config.cli_type}")
    return adapter_class(config)
