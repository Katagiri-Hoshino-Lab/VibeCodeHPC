# Sample: headless CLI agents on a self-hosted model server

Two small scripts that run one agent as a loop of headless turns, with the CLI pointed at your own model server. Use them to check that a server works with a CLI before running a full VibeCodeHPC organisation on it, or to compare CLIs on the same server.

In a VibeCodeHPC organisation you do not need these scripts: set `endpoint` in the agent's registry row instead (see [CLI Support Matrix](../../cli_support_matrix.md#self-hosted-model-servers)). The environment and flags here are the same ones the adapters set.

| File | CLI | API |
|---|---|---|
| `cc_agent.sh` | Claude Code, `claude -p` then `--continue` | Anthropic Messages (`/v1/messages`) |
| `codex_agent.sh` | Codex CLI, `codex exec` then `exec resume <thread id>` | OpenAI Responses (`/v1/responses`) |
| `codex_config.toml` | Codex CLI | provider template filled in by `codex_agent.sh` |

## Usage

```bash
# a server on this node, e.g. vllm serve <model> --served-model-name local --port 8000 ...
LLM_NAME=local bash cc_agent.sh first.md next.md /path/to/workdir 25
LLM_NAME=local bash codex_agent.sh first.md next.md /path/to/workdir 25
```

`first.md` is the first prompt (role and task); `next.md` is sent on every later turn ("continue; report what changed"). The loop ends after the given minutes or when `WORKDIR/STOP` exists. Each agent gets its own HOME (Claude Code) or CODEX_HOME (Codex), so several agents on one node do not share settings or conversations.

| Variable | Default | Meaning |
|---|---|---|
| `LLM_BASE_URL` | `http://127.0.0.1:8000` (Claude Code), `http://127.0.0.1:8000/v1` (Codex) | Server address |
| `LLM_NAME` | `local` | Served model name |
| `LLM_MAX_LEN` | `262144` | Codex: the server's max model length |
| `CLAUDE_BIN`, `CODEX_BIN` | `claude`, `codex` | Executables |
| `AGENT_HOME`, `AGENT_CODEX_HOME` | under `WORKDIR` | Per-agent configuration directories |

## Notes

- Proxy variables are unset: compute nodes often export a proxy, and requests to localhost through it fail.
- The server needs a tool-call parser that matches the model; without it tool calls come back as plain text.
- `codex_config.toml` sets `approval_policy = "never"` and `sandbox_mode = "danger-full-access"` because the agent runs unattended in its own directory. Tighten them for other uses.
- Both scripts were used against vLLM's official container image on one GPU node, with Claude Code 2.1 and Codex CLI 0.160. Flags may differ in other versions.
