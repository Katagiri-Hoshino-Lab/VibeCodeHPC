# Quick Start

## Prerequisites

- **tmux** — Inter-agent communication layer
- **Python 3.10+** — Framework runtime
  - matplotlib, numpy — visualization (context/SOTA/budget graphs)
- **Node.js 18+** — Required by npm-based CLIs (Codex, Cline, Gemini, OpenCode, Qwen)
- **gh** (optional) — [GitHub CLI](https://cli.github.com/), recommended if using CD agent
- **CLI** — At least one (used as PM)

  [Claude Code](https://github.com/anthropics/claude-code) · [Codex CLI](https://github.com/openai/codex) · [Cline CLI](https://github.com/cline/cline) · [Gemini CLI](https://github.com/google-gemini/gemini-cli) · [OpenCode](https://github.com/opencode-ai/opencode) · [vibe-local](https://github.com/ochyai/vibe-local) · [Qwen Code](https://github.com/QwenLM/qwen-code) · [Kimi Code CLI](https://github.com/MoonshotAI/kimi-cli)

  Install from each repo's README. Run once to complete authentication. See [CLI Support Matrix](cli_support_matrix.md).

## Prepare 3 Inputs

1. `requirement_definition.md` — edit from [template](requirement_definition_template.md), or ask PM to create it interactively
2. `_remote_info/` — site-specific connection info ([details](../_remote_info/README.md))
3. `BaseCode/` — your code to optimize

## Launch

```bash
# Optional: configure SSH agent (only if remote execution needed)
eval "$(ssh-agent -s)"
ssh-add ~/.ssh/your_private_key

# Setup creates tmux sessions and launches PM inside them
python3 -m vibecodehpc setup --name MyProject -w 4
```

PM starts automatically in a tmux session. It reads the requirement definition and handles worker (SE, PG, CD) startup, CLI/model selection, and directory design.

## What Happens Next

1. PM reads requirements and surveys the environment
2. PM designs directory hierarchy and assigns agents
3. PG agents iterate: code → compile → run → benchmark
4. SE agents track statistics and generate reports
5. Results accumulate in `User-shared/` with a final report
