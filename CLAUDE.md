# VibeCodeHPC

Multi-CLI Multi-Agent Auto-Tuning Framework.

## Project Overview
General-purpose multi-agent orchestration framework. HPC optimization is one workflow — pluggable strategies support any auto-tuning task.

## Language Priority
Python → TypeScript (port) → Shell (minimal wrappers)

## Design Principles
- No external orchestration framework (no CrewAI/AutoGen/LangGraph)
- Agent directory isolation without git worktree
- Use each CLI's native multi-agent capabilities directly
- No hardcoded paths — must run on WSL/macOS/Linux/supercomputers
- tmux-based IPC
- Unified TUI display

## Package Structure
```
vibecodehpc/
├── adapters/     # CLI adapters (8 CLIs supported, see docs/cli_support_matrix.md)
│   └── base.py   # CLIAdapter ABC
├── registry.py   # AgentRegistry (JSONL-backed)
├── tmux_utils.py # tmux session/pane management
├── agent_manager.py # spawn/message/health
├── hooks/        # CLI-agnostic hook intents
└── monitor/      # periodic_monitor, periodic_enter
```

## Component Classification
- **Core**: tmux communication, registry, hooks, ChangeLog+SOTA, budget, SSH/HPC integration
- **Role**: PM, SE, PG, CD (experimental), SOLO (alternative)
- **Skill**: Optimization templates, parallelization, sub-agent, report generation
- **Workflow**: Multi-agent auto-tuning, optimization cycle, evolutionary exploration

## Reference Resources
- `../VibeCodeHPC-jp/` — Original implementation (read-only)
- `../3rd-party-repos/VibeCodeHPC_iWAPT/` — Paper and figures
- `../3rd-party-repos/openclaw/` — Skills/extension reference
- `dev/` — Development docs (ARCHITECTURE, REQUIREMENTS, CLI_METADATA, TODO, etc.)

## Available Tools
- `python3 -m vibecodehpc setup` — create tmux sessions and agent panes
- `python3 -m vibecodehpc send <agent> "msg"` — inter-agent messaging
- `python3 -m vibecodehpc status` / `health` — agent status check
- `vibecodehpc/monitor/periodic_monitor.py` — background context/budget monitoring
- `vibecodehpc/monitor/periodic_enter.py` — auto-send Enter to prevent IPC message stall
- `Agent-shared/skills/*/scripts/*.py` — analytics tools (budget, SOTA, changelog, context)

## Project Root Discovery
Workers run in isolated workdirs (e.g. `Agent-workdir/SE1/`). To find shared resources, traverse upward from the current working directory to find the **project root**.

**Heuristic (2-of-3)**: The project root is the first ancestor directory containing **at least two** of: `CLAUDE.md`, `Agent-shared/`, `instructions/`.

**IMPORTANT**: `vibecodehpc/` is the Python package directory — it is a **child** of the project root, NOT the project root itself. Never create `Agent-shared/`, `Agent-workdir/`, or `User-shared/` inside `vibecodehpc/`.

Use the project root to reference:
- `CLAUDE.md` — project-wide instructions
- `Agent-shared/` — shared logs, skills, registry
- `instructions/` — role-specific instruction templates

## Critical Rules
- **Never foreground sleep** (Claude Code): Foreground `sleep` blocks incoming messages.
  - ❌ `sleep 60` — blocks IPC, agent appears dead
  - ✅ `sleep 60 &` — background, messages still received
  - ✅ Polling loop: `while true; do check_something; sleep 10 & wait $!; done`
- **Background monitoring pattern**: Use `bash(sleep N &)` for periodic checks.
  - ✅ `bash(sleep 180 &)` then check worker ChangeLog.md, job queue, agent health
  - ✅ `while true; do check_status; sleep 60 & wait $!; done` — polling loop
  - Purpose: PM and SE roles must maintain monitoring cadence, not go idle after initial deployment
- **TCP-style reply obligation**: All agents must acknowledge messages promptly.
  - **3-min rule**: Reply within 3 min of receiving a message (at minimum, send an ACK)
  - **5-min rule**: No log output for 5 min → suspect agent crash
  - **Health check**: Use `tmux capture-pane` or `vibecodehpc health` to verify agent liveness
  - Always include your agent_id in messages (e.g. `[SE1] ACK, starting cuBLAS build`)
- Sub-agents (e.g. `claude -p`) must NOT be registered in the registry
- OpenTelemetry is optional (not core)
- Do not use Desktop MCP Server

## Roles

Each agent reads `instructions/<role>.md` for full details.

| Role | File | Responsibility |
|------|------|----------------|
| PM | `instructions/PM.md` | Orchestration, requirement definition, resource allocation, budget |
| SE | `instructions/SE.md` | Worker monitoring, SOTA visualization, environment setup |
| PG | `instructions/PG.md` | Code optimization, SSH/SFTP execution, ChangeLog recording |
| CD | `instructions/CD.md` | GitHub management, security review (experimental) |

Basic flow: PM → SE → PG → PM. CD operates asynchronously.

## Agent Initialization

**All agents** must perform these steps after receiving their initialization message:

1. **Read common rules**: `CLAUDE.md` (this file)
2. **Read role instructions**: `instructions/<your-role>.md`
3. **Read project layout**: `directory_pane_map.md` (project root)
4. **Read requirements**: `requirement_definition.md`
5. **Confirm identity**: Check your agent_id (from initialization message or `.claude/hooks/agent_id.txt`)
6. **Confirm directory**: Run `pwd` and verify it matches your assignment in `directory_pane_map.md`

Reload these files after auto-compact or context loss.

## Communication

All inter-agent communication uses the framework CLI:
```bash
python3 -m vibecodehpc send <target> "message"
```

**Rules:**
- Your text output is invisible to other agents — always use `vibecodehpc send`
- Include your agent_id in every message: `[PG1.1] Compile succeeded, 285.7 GFLOPS`
- Message format: `[agent_id] [type] content` — types: Report, Request, ACK, Warning, Urgent
- Reply to messages even if just an ACK — silence looks like a crash

## Agent Behavior Patterns

### Polling (PM, SE, PG, CD)
Continuously check files and status, act autonomously at 2-5 min intervals.
- PG: submit job → poll results → optimize → repeat
- SE: monitor ChangeLog.md → update SOTA graphs → report anomalies
- PM: monitor all agents → reallocate resources → manage budget

### Flow-driven (PM initial phases only)
Sequential task execution: requirement definition → environment investigation → hierarchy design → agent deployment. Transitions to polling after deployment.

### High context usage
When context approaches limits, do **not** sleep to stall — update your TODO list, prioritize remaining work, and let auto-compact proceed naturally.

## Objective Reporting

Avoid subjective praise or emotional language. Report facts and metrics.
- Bad: "Amazing breakthrough", "World-class performance"
- Good: "Achieved 65% of theoretical peak", "Reduced runtime by 3.2s", "0 compile warnings"

When results are poor, report honestly and propose next steps.
