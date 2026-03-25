"""CLI-agnostic hook intent definitions.

Hook intents describe WHAT should happen at lifecycle events,
without specifying HOW (that's the adapter's job).
"""

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Optional


class HookEvent(Enum):
    SESSION_START = "on_session_start"
    STOP = "on_stop"
    PRE_TOOL_USE = "on_pre_tool_use"
    POST_TOOL_USE = "on_tool_use"
    POST_WRITE = "on_post_write"
    NOTIFICATION = "on_notification"


class StopAction(Enum):
    BLOCK_AND_REINJECT = "block_and_reinject"  # Claude: exit code 2
    INSTRUCTION_BASED = "instruction_based"  # Codex: AGENTS.md directive
    EXTERNAL_MONITOR = "external_monitor"  # Gemini/OpenCode: idle detector


@dataclass
class HookIntent:
    """A CLI-agnostic description of desired hook behavior."""

    event: HookEvent
    action: str
    matcher: str = ""  # Tool name matcher (e.g. "Bash|ssh")
    script_path: Optional[str] = None
    config: dict = field(default_factory=dict)


@dataclass
class StopHookIntent(HookIntent):
    """Intent for Stop/idle prevention hooks."""

    event: HookEvent = HookEvent.STOP
    action: str = "block_and_reinject"
    reinject_files: list = field(default_factory=list)
    max_stop_count: int = 3
    probabilistic_embed: bool = True


@dataclass
class SessionStartIntent(HookIntent):
    """Intent for session initialization hooks."""

    event: HookEvent = HookEvent.SESSION_START
    action: str = "inject_context"
    register_agent: bool = True
    inject_files: list = field(default_factory=list)


@dataclass
class ToolGuardIntent(HookIntent):
    """Intent for tool use validation hooks (PostToolUse)."""

    event: HookEvent = HookEvent.POST_TOOL_USE
    action: str = "validate"
    matcher: str = "Bash"
    blocked_patterns: list = field(default_factory=list)


@dataclass
class PreToolGuardIntent(HookIntent):
    """Intent for pre-tool-use validation hooks (PreToolUse)."""

    event: HookEvent = HookEvent.PRE_TOOL_USE
    action: str = "warn"
    matcher: str = "Bash"
    warn_patterns: list = field(default_factory=lambda: ["ssh", "sftp", "scp"])


@dataclass
class PostWriteCheckIntent(HookIntent):
    """Intent for post-write validation hooks (version ChangeLog check)."""

    event: HookEvent = HookEvent.POST_WRITE
    action: str = "validate_changelog"
    matcher: str = "Write|Edit|MultiEdit"
    version_pattern: str = r"_v\d+\.\d+\.\d+\.\w+$"


def build_default_polling_hooks() -> dict:
    """Build default hook intents for a polling agent."""
    return {
        "on_stop": StopHookIntent(
            reinject_files=["ChangeLog.md", "ToDoList.md"],
            max_stop_count=3,
            probabilistic_embed=True,
        ),
        "on_session_start": SessionStartIntent(
            register_agent=True,
        ),
        "on_tool_use": ToolGuardIntent(
            matcher="Bash|ssh|sftp",
            blocked_patterns=["rm -rf /", ":(){ :|:& };:"],
        ),
        "on_pre_tool_use": PreToolGuardIntent(
            matcher="Bash",
            warn_patterns=["ssh", "sftp", "scp"],
        ),
        "on_post_write": PostWriteCheckIntent(),
    }


def build_default_event_hooks() -> dict:
    """Build default hook intents for an event-driven agent."""
    return {
        "on_session_start": SessionStartIntent(
            register_agent=True,
        ),
        "on_tool_use": ToolGuardIntent(
            matcher="Bash|ssh|sftp",
        ),
    }


def hooks_to_dict(hooks: dict) -> dict:
    """Serialize a dict of HookIntent instances to plain dicts.

    Adapters' ``setup_hooks()`` use ``.get()`` on the values,
    so dataclass instances must be converted first.
    """
    result = {}
    for key, value in hooks.items():
        if hasattr(value, "__dataclass_fields__"):
            d = asdict(value)
            # Convert Enum values to their string form
            d["event"] = d["event"].value if hasattr(d.get("event"), "value") else d.get("event")
            result[key] = d
        elif isinstance(value, dict):
            result[key] = value
        else:
            result[key] = value
    return result
