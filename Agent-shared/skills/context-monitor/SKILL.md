---
name: context-monitor
description: "Context window usage monitoring and auto-compact recovery. Use when context is filling up or after auto-compact occurs. Optional for strong models."
---

# Context Monitor

## Thresholds

| Level | Action |
|-------|--------|
| < 70% | Normal operation |
| 70-85% | Persist current state to files, update task list |
| 85-95% | Save intermediate results, minimize new file reads |
| ~95% | Auto-compact triggers — context will be compressed |

> Note: The thresholds above are behavioral guidelines for agents.
> The `context_monitor.py` script uses `warning_threshold` (70%) and
> `auto_compact_threshold` (95%) for visualization and alerting.
> The 85% intermediate action is the agent's own responsibility.

## Pre-Compact Checklist
- Write work state summary to file (SOTA values, current version, next action)
- Update ChangeLog.md with latest results
- List reference file paths for post-compact recovery

## Post-Compact Recovery
1. Read task file / ChangeLog.md
2. Restore minimal working context
3. Resume from interruption point

## CLI Script

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/context_monitor.py --help
python3 ${CLAUDE_SKILL_DIR}/scripts/context_monitor.py claude --find-latest --status
python3 ${CLAUDE_SKILL_DIR}/scripts/context_monitor.py codex --find-latest --status --json
python3 ${CLAUDE_SKILL_DIR}/scripts/context_monitor.py gemini /path/to/telemetry.jsonl --visualize -o ./viz
python3 ${CLAUDE_SKILL_DIR}/scripts/context_monitor.py claude /path/to/session.jsonl --visualize --context-limit 200000
```

Supported parsers: `claude`, `codex`, `gemini`, `opencode`

## Multi-Agent Considerations
- Delegate large tasks to sub-agents to distribute context load
- SE/PM should monitor agent context consumption trends
- Use `PG_visible_dir.md` to limit unnecessary file reads
