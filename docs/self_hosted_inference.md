# Self-Hosted Inference for VibeCodeHPC Agents

How to run your own inference engine for VibeCodeHPC agents, point Claude Code (and Codex CLI) at it, and what to watch on the server side when many agents share it. The complete batch-job setup is in [samples/self_hosted_inference_on_hpc](samples/self_hosted_inference_on_hpc/README.md).

## Where to run what

Two choices are independent: where the agents' CLIs (the harness) run, and where the model is served.

| | Model from a vendor API | Model served on your own machine | Model served inside the HPC job |
|---|---|---|---|
| **Harness on your PC** | Default VibeCodeHPC setup; jobs go to the cluster over SSH | Needs a GPU at hand | Needs a route from the PC to the compute node, which sites rarely allow |
| **Harness inside the HPC job** | Needs outbound internet from compute nodes | Needs a route from the compute node back to your machine | Everything stays on the node ([sample](samples/self_hosted_inference_on_hpc/README.md)) |

VibeCodeHPC works in every cell. Running the harness on your own PC is the simplest; check outbound network access and the load you put on shared login nodes before moving it to the cluster. The last cell is the one for closed compute nodes: the model, the agents and their tools all run inside one allocation, and nothing leaves it.

## Choosing an engine

| Engine | APIs | Notes from running it on one 4-GPU node |
|---|---|---|
| vLLM (official container image) | Anthropic Messages, OpenAI Responses and Chat | Claude Code and `codex exec` work against it directly. Speculative decoding (MTP heads, n-gram, draft models) and CPU KV offload are flags |
| SGLang (official container image) | OpenAI Chat (others not checked) | Serves the same large MoE model; no CLI was run against it, so use vLLM when the agents run Claude Code |
| llama.cpp server | OpenAI Chat | Not run there; large models need a format conversion first |

Use the official container image of the engine and convert it once to the site's container format (Singularity/Apptainer). Keep the weights as published.

## Endpoints

Claude Code speaks the Anthropic Messages API (`/v1/messages`). Codex CLI and most other CLIs speak the OpenAI API (`/v1/chat/completions` or `/v1/responses`). vLLM serves all of them from one process, so one server can back a mixed organisation.

## Claude Code: environment

Export these before `python3 -m vibecodehpc setup`. The tmux server inherits the environment of the shell that starts it, and every pane inherits it from the tmux server. If a tmux server is already running, it keeps its old environment: stop it first or use `tmux set-environment -g`.

| Variable | Value | Why |
|---|---|---|
| `ANTHROPIC_BASE_URL` | `http://127.0.0.1:8000` | The server address, without `/v1` |
| `ANTHROPIC_AUTH_TOKEN` | any non-empty string | Claude Code needs a credential; vLLM ignores it unless started with `--api-key` |
| `ANTHROPIC_API_KEY` | unset | Keeps a real key from being sent to the local server |
| `ANTHROPIC_MODEL` | served model name | The main model |
| `ANTHROPIC_DEFAULT_OPUS_MODEL`, `ANTHROPIC_DEFAULT_SONNET_MODEL`, `ANTHROPIC_DEFAULT_HAIKU_MODEL`, `ANTHROPIC_SMALL_FAST_MODEL` | served model name | Claude Code also calls a small model for background tasks. A name the server does not know fails |
| `CLAUDE_CODE_SUBAGENT_MODEL` | served model name | Sub-agents |
| `CLAUDE_CODE_MAX_OUTPUT_TOKENS` | e.g. `32000` | Prompt plus output must stay below the server's `--max-model-len` |
| `CLAUDE_CODE_EFFORT_LEVEL`, `CLAUDE_CODE_ALWAYS_ENABLE_EFFORT=1` | optional | Claude Code sends the effort level only for model names it knows unless forced. Whether it changes anything depends on how the server maps it onto the model's chat template; check the reasoning length |
| `DISABLE_AUTOUPDATER`, `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC`, `DISABLE_TELEMETRY`, `DISABLE_ERROR_REPORTING` | `1` | No outbound traffic from a closed node |
| `http_proxy`, `https_proxy` (and upper case) | unset; `NO_PROXY=127.0.0.1,localhost` | Compute nodes often export a proxy, and requests to localhost through it fail |

On an unattended node, also pre-answer the first-run screens with `vibecodehpc/scripts/seed_claude_home.py`. v2 presses Enter once after starting the CLI; that passes the folder-trust prompt but not onboarding or the bypass-permissions warning.

## Codex CLI: provider

Do not set `OPENAI_BASE_URL` globally (see the [CLI Support Matrix](cli_support_matrix.md)). Define a provider in `~/.codex/config.toml` instead, for example in a job-local HOME:

```toml
model = "local"
model_provider = "local"

[model_providers.local]
name = "local vLLM"
base_url = "http://127.0.0.1:8000/v1"
wire_api = "responses"   # or "chat", whichever your server and Codex version support
```

Key names follow the Codex configuration reference; check them against your Codex version. This path has not been exercised in the measured setup, which used Claude Code only.

## Server settings

- **Tool calls.** Start vLLM with the tool-call parser for your model (`--enable-auto-tool-choice --tool-call-parser ...`) and its reasoning parser if it has one. Without the tool parser, tool calls come back as plain text and agents cannot act.
- **Concurrency.** `--max-num-seqs` should cover every agent plus their sub-agents. Requests beyond it queue, and agents look unresponsive.
- **Context length.** `--max-model-len` bounds prompt plus output. Agents' prompts grow towards it before auto-compact; leave room for the output cap.
- **Text-only models.** Refuse media inputs on the server (`--limit-mm-per-prompt '{"image":0,"video":0,"audio":0}'`) and in the agents (`deny_media_read.py` hook, `seed_claude_home.py --text-only`). The server answers an image with "At most 0 image(s) may be provided in one prompt", and once an image block is in a conversation every later request of that conversation fails. VibeCodeHPC's monitor writes PNG figures that agents try to read.
- **Speculative decoding.** `serve.sh` takes it as an argument (`mtp:K`, `ngram:K`, `METHOD:K:DRAFT_PATH`). Measure the acceptance on your own workload: `org_summary.py` reports the mean acceptance length and the acceptance rate per draft position.

## Prefix caching on hybrid models

Agents send many requests that share a long prefix: system prompt, tool definitions and the conversation so far. Prefix caching is what keeps the prefill cost of those requests low.

Models that mix sliding-window and full-attention layers need extra care. In the vLLM version we used, with the default `prefix_cache_retention_interval` of 0, the cache of sliding-window layers was kept only at the end of each prompt and at positions already known to be a shared-prefix boundary. A new shared prefix therefore missed on the second request and hit only from the third on: the second request prefilled everything again.

With `--prefix-cache-retention-interval 4096` (a multiple of the KV block size), sliding-window state is kept at those intervals. In our measurement a 64K-token prompt sharing 90% with the previous one hit from the second request, at the expected rate, and the time to first token fell to about one fifth.

Not measured: cache pressure with many different prefixes, other interval values, and the combination with speculative decoding and KV offload. The flag depends on the vLLM version; check `vllm serve --help`. `serve.sh` passes it with `LLM_PREFIX_RETENTION`.

## KV cache of hybrid models and KV connectors

vLLM's hybrid memory allocator stores only the window for sliding-window layers. A KV connector that does not support it makes vLLM turn the allocator off, with a log line containing "Turning off hybrid". Every sliding-window layer then stores the full length, and the KV per token grows several-fold for a model whose layers are mostly sliding-window. Long requests that fitted before may no longer fit.

After enabling a connector, check `server.log` for that line and compare the KV token capacity with a run without the connector. `serve.sh` enables vLLM's own CPU offload connector with `LLM_CPU_OFFLOAD_GB`, and the sample job retries once without it if the server dies before it is ready.

## Timing assumptions

VibeCodeHPC's rules (ACK within 3 minutes, an agent silent for 5 minutes is suspect) assume a fast cloud API. With many agents on one local server, replies are slower; relax the deadlines in `requirement_definition.md`. Raise `max_runtime_min` in `Agent-shared/periodic_monitor_config.json` to the length of the job, or the monitor stops after 120 minutes.

## Claude Code's built-in cross-session messaging

Claude Code has its own messaging between sessions (`ListAgents`, `SendMessage`), through a per-session socket or named pipe on the same machine. According to the Claude Code documentation at the time of writing:

- Sessions in WSL2 and native Windows sessions cannot reach each other, even on the same PC. Keep all agents on the same side.
- Sessions started with `--bare` do not create an inbox.
- A receiving session can accept, hold or refuse messages (`crossSessionInbound`).

VibeCodeHPC does not depend on this: `vibecodehpc send` types into tmux panes, sending the text and Enter separately. That works with every CLI but is outside Claude Code's documented interfaces.

## Checklist

- [ ] The server answers `curl http://127.0.0.1:8000/health` and lists the served name at `/v1/models`.
- [ ] A one-line `claude -p "say ok"` with the environment above returns text, and a request that needs a tool (`claude -p "list the files here"`) makes a tool call.
- [ ] `--max-num-seqs` covers all agents; `CLAUDE_CODE_MAX_OUTPUT_TOKENS` plus the largest prompt stays below `--max-model-len`.
- [ ] For a text-only model, the media hook is installed and the server refuses media.
- [ ] For a hybrid model, `server.log` has no "Turning off hybrid" line unless intended, and prefix-cache hits appear from the second request (`org_metrics.sh`).
