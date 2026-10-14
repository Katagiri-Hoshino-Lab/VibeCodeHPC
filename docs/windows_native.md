# Windows Native (Optional, Experimental)

> **Optional and experimental.** The default IPC stays tmux. Nothing here changes the behaviour of `python3 -m vibecodehpc`; merging it has no effect on tmux users. Lines changed in the existing tmux path: 0. The new code is imported only when you select it.

## Why

VibeCodeHPC runs each agent in a tmux pane and talks to it by typing into the pane. Native Windows (without WSL) has no tmux. Claude Code on native Windows has what is needed instead:

- background sessions: `claude --bg`, listed by `claude agents --json`, watched with `claude attach <id>`, ended with `claude stop <id>` and `claude rm <id>`;
- cross-session messaging between sessions on the same machine (`ListAgents`, `SendMessage`, per-session socket or named pipe; native Windows from Claude Code 2.1.234);
- hooks, which can add text to a session's context or keep it from stopping.

## What does not cross

- Sessions in WSL2 and native Windows sessions cannot message each other, even on the same PC. Run all agents on one side.
- The core CLI `python -m vibecodehpc` imports the registry module, which uses `fcntl`, so it does not start on native Windows. The optional backend has its own entry point, `python -m vibecodehpc.ipc`, which does not import it.

## Design

| Piece | File | Role |
|---|---|---|
| Interface | `vibecodehpc/ipc/base.py` | `IPCBackend`: `send`, `receive`, `health`, `launch`. One class per transport, like `CLIAdapter` per CLI |
| tmux backend | `vibecodehpc/ipc/tmux_backend.py` | The existing `tmux_utils` functions behind the interface, unchanged |
| cross_session backend | `vibecodehpc/ipc/cross_session.py` | Background sessions, a file inbox, hooks; no tmux |
| Inbox hook | `vibecodehpc/hooks/templates/claude/inbox_inject.py` | Hands queued messages to the session (standard library only) |
| Entry point | `python -m vibecodehpc.ipc` | `send`, `receive`, `health`, `launch` through the chosen backend |

Selection, in order: `--backend`, the variable `VIBECODEHPC_IPC_BACKEND`, `ipc_backend:` in `config.yaml`, else `tmux`. `vibecodehpc.ipc.get_backend` imports the chosen module only when asked; no default code path calls it.

How messages travel with `cross_session`:

| From → to | Path |
|---|---|
| Framework → agent, first message | Initial prompt of `claude --bg` at launch |
| Framework → agent, later | Appended to `Agent-shared/ipc/inbox/<agent_id>.jsonl`; the hook adds it to the context at the next `UserPromptSubmit` or `PostToolUse`, or blocks the next `Stop` with it so the agent continues |
| Agent → agent | Claude Code's `SendMessage` to the other session (discovered with `ListAgents`) |
| Health | `claude agents --json`: listed and not `done` means alive |
| A human watching | `claude attach <id>` (the id is in `Agent-shared/ipc/sessions.json`) |

The launch command is the adapter's own (`ClaudeAdapter.build_launch_command()`, same flags and model as with tmux) with `--bg` added. `--launcher wt` opens a visible Windows Terminal tab instead of a background session.

## Usage

```powershell
# once: open the project root in Claude Code and accept the trust prompt
# (claude --bg refuses workspaces that are not trusted; subdirectories inherit it)
$env:VIBECODEHPC_IPC_BACKEND = "cross_session"
python -m vibecodehpc.ipc launch PG1.1 --workdir Agent-workdir\PG1.1 --model sonnet `
    --first-message "You are PG1.1. Read CLAUDE.md, instructions/PG.md and requirement_definition.md."
python -m vibecodehpc.ipc send PG1.1 "[PM] [Request] Report your current status."
python -m vibecodehpc.ipc health PG1.1
```

## Limits

- The inbox does not wake an idle session. A message waits for the session's next event (a tool call, a new turn, or the end of the current turn). A `SendMessage` from another Claude session, for example PM, does wake it.
- Only Claude Code is wired. Other CLIs have no background sessions or cross-session messaging of this kind.
- The cross_session backend does not write the registry; background ids are kept in `Agent-shared/ipc/sessions.json`. `python -m vibecodehpc send` types into tmux panes and cannot reach these agents; use `python -m vibecodehpc.ipc send`.
- PM's instructions still describe the tmux workflow. A PM on native Windows needs a requirement-definition note: use `python -m vibecodehpc.ipc` for launch and health, and `SendMessage` to talk to agents.

## Test status

| Check | Result |
|---|---|
| `py_compile` of the new modules with Windows Python 3.10 | pass |
| Offline on native Windows: inbox send and drain, hook output for `UserPromptSubmit` and `Stop`, idempotent hook install, backend selection, the CLI | pass |
| Live on native Windows: `claude -p` in a work directory with the hook receives an inbox message | pass |
| Live on native Windows: `claude --bg` started from Python, id from `claude agents --json`, health, `stop`, `rm` | pass |
| Live: `SendMessage` between two native Windows sessions | not run: the peer list covers every session on the machine, including unrelated ones |
| `--launcher wt` | not run |
