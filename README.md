# VibeCodeHPC

**Multi-CLI Multi-Agent Auto-Tuning Framework**

Multiple AI coding CLIs coordinate via tmux — no external orchestration framework required. Pluggable strategies adapt it to various tasks.

![Multi-agent execution on desktop](docs/images/desktop_vscode_tmux_agents.png)

## Typical Workflow (built-in default)

![VibeCodeHPC Workflow](docs/images/vibecodehpc_workflow.png)

Without a custom requirement definition, VibeCodeHPC runs this HPC auto-tuning workflow out of the box. Custom strategies can replace or extend it.

## Key Features

- **Hierarchical Multi-Agent**: PM → SE ↔ PG × N → CD
- **Pluggable Strategies**: HPC parallelization, local LLM deployment, GPU optimization — add your own
- **Evolutionary Exploration**: Flat directory structure for parallel search
- **tmux IPC**: Inter-agent communication with no special runtime
- **4-tier SOTA Tracking**: Local → Family → Hardware → Project

## Project Structure (CFD optimization example)

User prepares 3 items:
- `requirement_definition.md` — edit from [template](docs/requirement_definition_template.md), or ask PM to create it interactively
- `_remote_info/` — site-specific info ([details](_remote_info/README.md))
- `BaseCode/` — your code to optimize

Everything else is created by agents at runtime.

```
📂 VibeCodeHPC/ 🤖 PM ⬛
├── 📝 requirement_definition.md        # ← User edits
├── 📁 _remote_info/                    # ← User provides
├── 📁 BaseCode/                        # ← User provides
│
├── 📁 User-shared/                     # → Results here
├── 📂 Agent-shared/
│   ├── 📁 skills/                      #   Knowledge + scripts
│   └── 📁 logs/                        #   Agent communication history
│
├── 📄 CLAUDE.md                        # Common rules
├── 📁 instructions/                    # PM, SE, PG, CD
├── 📁 vibecodehpc/                     # Framework
```

<details>
<summary>Runtime directories (created by PM)</summary>

```
├── 📄 directory_pane_map.md
├── 📁 GitHub/ 🤖 CD ⬜
│
└── 📂 Flow/TypeII/single-node/ 🤖 SE1 🟦
    ├── 📄 hardware_info.md
    ├── 📂 gcc/
    │   └── 📂 OpenMP/ 🤖 PG1.1 🟩
    │       └── 📄 ChangeLog.md
    ├── 📂 nvidia/
    │   ├── 📁 CUDA/ 🤖 PG1.2 🟧
    │   └── 📁 OpenACC/ 🤖 PG1.3 🟪
    └── 📂 intel/
        └── 📁 OpenMP/ 🤖 PG1.4 🟥
```

Layout is determined by PM based on the requirement definition. Compiler/strategy hierarchy is configurable.
</details>

## Built-in Monitoring

![Context usage per agent (60 min)](docs/images/context_usage_all_agents_60min.png)

![Performance timeline per PG (65 min)](docs/images/perf_timeline_65min.png)

## Getting Started

See [docs/quickstart.md](docs/quickstart.md)

## Multi-CLI Support

![8 CLIs running simultaneously](docs/images/multi_cli_support.png)

Claude Code, Codex CLI, Cline CLI, Gemini CLI, OpenCode, vibe-local, Qwen Code, Kimi Code CLI

> [CLI Support Matrix](docs/cli_support_matrix.md)

## Paper & Demo

- 📄 [arXiv (v3)](https://arxiv.org/abs/2510.00031) — iWAPT 2026
- 🎬 [Demo video (EN subtitles)](https://drive.google.com/file/d/1Od4E6FJwHwOCYOejNobnaR9LWypO5ZlG/view?usp=sharing)

## Other Languages

[日本語](docs/ja/)

## License

[MIT License](LICENSE)
