# Directory & Pane Map

> PM generates this file at project root. Update immediately after every agent deployment or reassignment. This is the **single visual reference** for all agents and the user.

## Example A: HPC Optimization (compiler/strategy split)

```
📂VibeCodeHPC-v1.0.0 🤖PM
├── 📁GitHub 🤖CD ⬛
└── 📂Flow/TypeII
    ├── 📂single-node 🤖SE1 🟨
    │   ├── 📄hardware_info.md
    │   ├── 📂gcc11.4.0
    │   │   ├── 📁OpenMP 🤖PG1.1 🟦
    │   │   ├── 📁MPI 🤖PG1.2 🟦
    │   │   └── 📁AVX2 🤖PG1.3 🟦
    │   ├── 📂intel2024
    │   │   ├── 📁OpenMP 🤖PG1.4 🟪
    │   │   └── 📁MPI 🤖PG1.5 🟪
    │   └── 📂nvidia_hpc
    │       └── 📁CUDA 🤖PG1.6 🟫
    └── 📂multi-node 🤖SE2 🟡
        ├── 📄hardware_info.md
        ├── 📂gcc11.4.0
        │   └── 📁MPI 🤖PG2.1 🔵
        └── 📂intel2024
            └── 📁MPI 🤖PG2.2 🟣
```

### tmux Layout (10 workers, 4x3 grid)

| | | | |
|:---|:---|:---|:---|
| 🟨SE1 single-node | 🟦PG1.1 gcc/OMP | 🟦PG1.2 gcc/MPI | 🟦PG1.3 gcc/AVX2 |
| 🟪PG1.4 intel/OMP | 🟪PG1.5 intel/MPI | 🟫PG1.6 nvidia/CUDA | 🟡SE2 multi-node |
| 🔵PG2.1 gcc/MPI | 🟣PG2.2 intel/MPI | ⬛CD | ⬜ |

---

## Example B: Multi-CLI Competition (CLI/model split)

```
📂VibeCodeHPC-main 🤖PM 🟧 claude/opus-4.6
└── 📂Local
    ├── 📁sota 🤖SE1 🟩 codex/gpt-5.4
    ├── 📁context 🤖SE2 🟧 claude/opus-4.6
    └── 📂gcc
        └── 📂OpenMP
            ├── 📁work1 🤖PG1.1 🟫 cline/sonnet-4.6
            ├── 📁work2 🤖PG1.2 🟥 vibe-local/qwen3.5:35b
            ├── 📁work3 🤖PG1.3 🟦 gemini/Gemini-3
            │
            ├── 📁work4 🤖PG2.1 🟪 qwen/qwen3.5-plus
            ├── 📁work5 🤖PG2.2 ⬛ opencode/qwen3-next-80b
            └── 📁work6 🤖PG2.3 🟨 kimi/kimi-code
```

### tmux Layout (8 workers, 2 sessions)

#### Workers1
| | |
|:---|:---|
| 🟩SE1 codex/gpt-5.4 | 🟫PG1.1 cline/sonnet-4.6 |
| 🟥PG1.2 vibe/qwen3.5 | 🟦PG1.3 gemini/Gemini-3 |

#### Workers2
| | |
|:---|:---|
| 🟧SE2 claude/opus-4.6 | 🟪PG2.1 qwen/qwen3.5+ |
| ⬛PG2.2 opencode/qwen3-80b | 🟨PG2.3 kimi/kimi-code |

---

## Supported CLIs

claude, codex, cline, gemini, opencode, vibe-local, qwen, kimi

> Details: `docs/cli_support_matrix.md`

## Notes

- **Update immediately** after every `vibecodehpc launch` or agent reassignment
- PM chooses Example A or B based on project type. Mix both if needed.

### Design Intent
- Each compiler/hardware gets its own 📂 → no Makefile/flag collisions
- Each strategy (OpenMP/MPI/CUDA) is a flat 📁 → PG works independently
- SE supervises by scope (single-node vs multi-node) or team
- Colors = compiler group (A) or CLI brand (B) — one glance identification
- No meaningless intermediate directories
