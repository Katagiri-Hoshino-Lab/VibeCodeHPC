# CLI Support Matrix

Updated: 2026-03-25

## Overview

> Set up authentication (subscription / browser login) **before** running `vibecodehpc setup`.

| CLI | Status | Notes |
|-----|--------|-------|
| Claude Code | ✅ Default CLI | |
| Codex CLI | ✅ | Do NOT set `OPENAI_BASE_URL` globally |
| Cline CLI | ✅ | |
| Gemini CLI | ✅ | |
| OpenCode | ✅ | |
| vibe-local | ✅ Ollama required | |
| Qwen Code | ☑ | Native auth only (OpenRouter ✕) |
| Kimi Code CLI | ☑ | Native auth only (OpenRouter ✕) |

---

## Known Limitations

- **Qwen Code / Kimi Code CLI via OpenRouter**: Tool calling does not work. Use native auth instead.
  - Qwen Code is optimized for Qwen3-Coder; non-Qwen models produce text-only responses ([#70](https://github.com/QwenLM/qwen-code/issues/70))
  - Kimi Code CLI requires native OAuth token, not OpenRouter proxy
- **vibe-local**: Requires Ollama with a local model deployed. Context window defaults to 32K. Use `--context-window` via `cli_args` to increase.
- **Gemini CLI**: `--yolo` mode requires folder trust (auto-configured by adapter since v0.11.1)
- **Codex CLI**: Setting `OPENAI_BASE_URL` globally redirects Codex to wrong endpoint. Only set per-agent via `env_vars` if needed.

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
