# CLI Support Matrix

Updated: 2026-10-14

## Overview

> Set up authentication (subscription / browser login) **before** running `vibecodehpc setup`.

| CLI | Status | Self-hosted endpoint | Notes |
|-----|--------|----------------------|-------|
| Claude Code | ✅ Default CLI | Anthropic Messages API (registry `endpoint`) | |
| Codex CLI | ✅ | OpenAI Responses API (registry `endpoint`) | Do NOT set `OPENAI_BASE_URL` globally |
| Cline CLI | ✅ | — | |
| Gemini CLI | ✅ | — | |
| OpenCode | ✅ | — | |
| vibe-local | ✅ Ollama required | Ollama (local by design) | |
| Qwen Code | ☑ | OpenAI Chat API via `env` (`OPENAI_BASE_URL`), not verified | Native auth only (OpenRouter ✕) |
| Kimi Code CLI | ☑ | — | Native auth only (OpenRouter ✕) |

"—" means the adapter has no endpoint setting; see [Self-Hosted Model Servers](#self-hosted-model-servers).

---

## Known Limitations

- **Qwen Code / Kimi Code CLI via OpenRouter**: Tool calling does not work. Use native auth instead.
  - Qwen Code is optimized for Qwen3-Coder; non-Qwen models produce text-only responses ([#70](https://github.com/QwenLM/qwen-code/issues/70))
  - Kimi Code CLI requires native OAuth token, not OpenRouter proxy
- **vibe-local**: Requires Ollama with a local model deployed. Context window defaults to 32K. Use `--context-window` via `cli_args` to increase.
- **Gemini CLI**: `--yolo` mode requires folder trust (auto-configured by adapter since v0.11.1)
- **Codex CLI**: Setting `OPENAI_BASE_URL` globally redirects Codex to wrong endpoint. For a self-hosted server use the registry `endpoint` field, which sets a per-agent provider with `-c` overrides.

---

## Self-Hosted Model Servers

To point an agent at your own model server, add `endpoint` to its row in `Agent-shared/agent_and_pane_id_table.jsonl`. `vibecodehpc launch` then sets up that pane before starting the CLI. Nothing changes for rows without it.

```json
{"agent_id": "PG1.1", "cli_type": "claude", "model": "local", "endpoint": {"base_url": "http://127.0.0.1:8000"}, ...}
{"agent_id": "PG1.2", "cli_type": "codex", "model": "local", "endpoint": {"base_url": "http://127.0.0.1:8000/v1"}, ...}
```

| Key | Used by | Meaning |
|-----|---------|---------|
| `base_url` | all | Server address. Claude Code: without `/v1`. Codex: with `/v1` |
| `model` | all | Served model name, if the row has no `model` |
| `api_key_env` | all | Name of a variable holding the server's key, if it checks one |
| `effort` | Claude Code | Effort level, sent also for model names Claude Code does not know |
| `wire_api` | Codex | `responses` (default) or `chat` |

What the adapter does:

- **Claude Code**: exports `ANTHROPIC_BASE_URL`, `ANTHROPIC_AUTH_TOKEN` and every model slot (`ANTHROPIC_MODEL`, the default Opus/Sonnet/Haiku models, `CLAUDE_CODE_SUBAGENT_MODEL`) set to the served name, and unsets `ANTHROPIC_API_KEY`.
- **Codex CLI**: appends `-c` overrides that define a provider with the given `base_url` and select it. No config file is changed.

The row may also carry `env`, a map of extra variables exported before launch. Values may reference variables (`"$MY_TOKEN"`); do not write secrets into the registry.

Servers and the APIs they offer:

| Server | Anthropic Messages (`/v1/messages`) | OpenAI Responses (`/v1/responses`) | OpenAI Chat (`/v1/chat/completions`) | Checked with |
|--------|:---:|:---:|:---:|---|
| vLLM (official container image, arm64 build) | ✅ | ✅ | ✅ | Claude Code (interactive and `-p`) and `codex exec` on one 4-GPU node |
| SGLang (official container image) | not checked | not checked | ✅ | server only, no CLI |
| llama.cpp server | not checked | not checked | ✅ (per its documentation) | not run |

The tool-call parser of the server must match the model, or tool calls come back as plain text. For headless loops against such a server see [samples/self_hosted_endpoint](samples/self_hosted_endpoint/README.md).

---

<details>
<summary>Authentication</summary>

| CLI | Login Command | API Key Location |
|-----|--------------|-----------------|
| Claude Code | `claude auth login` | `~/.claude/.credentials.json` |
| Codex CLI | `codex login` | `~/.codex/auth.json` |
| Cline CLI | `cline auth -p <provider>` | `~/.cline/data/globalState.json` |
| Gemini CLI | `GOOGLE_API_KEY` env var | `~/.config/configstore/` |
| OpenCode | `opencode providers login` | `~/.local/share/opencode/` |
| vibe-local | — (Ollama, no auth) | — |
| Qwen Code | `/auth` (interactive) | `~/.config/configstore/` |
| Kimi Code CLI | `kimi login` | `~/.kimi/kimi.json` |

</details>

<details>
<summary>Context Monitor Implementation</summary>

All 8 CLIs are supported by the context monitor. Log locations and cache handling:

| CLI | Log Location | Cache in input? |
|-----|-------------|:--------------------:|
| Claude Code | `~/.claude/projects/<encoded>/session.jsonl` | No |
| Codex CLI | `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl` | Yes |
| Cline CLI | `~/.cline/data/tasks/<id>/ui_messages.json` | No |
| Gemini CLI | `~/.gemini/tmp/<id>/chats/session-*.json` | Yes |
| OpenCode | `~/.local/share/opencode/opencode.db` (SQLite) | N/A |
| vibe-local | tmux capture-pane `ctx:N%` + Ollama `/api/ps` | N/A |
| Qwen Code | `~/.qwen/projects/<encoded>/chats/*.jsonl` | Yes |
| Kimi Code CLI | `~/.kimi/sessions/<hash>/<uuid>/wire.jsonl` | No |

</details>

<details>
<summary>Tool Calling Compatibility (per-provider)</summary>

| CLI | Native API | OpenRouter | Ollama |
|-----|-----------|------------|--------|
| Claude Code | ✅ | ✅ | ☑ |
| Codex CLI | ✅ | ☑ | ☑ |
| Cline CLI | ✅ | ✅ | ☑ |
| Gemini CLI | ✅ | ☑ | ☑ |
| OpenCode | ✅ | ✅ | ☑ |
| vibe-local | — | — | ✅ Ollama required |
| Qwen Code | ✅ (DashScope) | **No** | **No** ([#176](https://github.com/QwenLM/qwen-code/issues/176)) |
| Kimi Code CLI | ✅ (native) | ☑ | ☑ |

</details>

<details>
<summary>Idle Prevention (per CLI)</summary>

Polling agents must not stop after one task. Each adapter uses what its CLI offers (`vibecodehpc/hooks/intents.py`, `StopAction`). For every CLI, `periodic_enter` also sends Enter from the tmux side so that messages are not left in an input box.

| CLI | Mechanism |
|-----|-----------|
| Claude Code | Stop hook: exit code 2 blocks the stop and re-injects ChangeLog/ToDo |
| Codex CLI | Stop hook in `.codex/hooks.json` (feature flag `codex_hooks`), plus an AGENTS.md directive as fallback |
| Cline CLI | `UserPromptSubmit` hook mapped from the stop intent |
| Gemini CLI | Stop hook in `.gemini/settings.json` |
| OpenCode | Plugin (session registration); idle handled from the tmux side |
| vibe-local | None; its built-in agent loop keeps running |
| Qwen Code | Hooks, plus an AGENTS.md directive as fallback |
| Kimi Code CLI | AGENTS.md directive only (no hooks) |

</details>
