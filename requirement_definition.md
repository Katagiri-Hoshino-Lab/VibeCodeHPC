# Requirement Definition

## Project Information
- **Project name**: DGEMM_MultiCLI_E2E
- **Date**: 2026-03-20

## Optimization Target

### Code Source
- [x] Local files: placed in `BaseCode/`

### Target Files
- **Main file**: dgemm.c (dgemm_naive function)
- **Dependencies**: Makefile

## Optimization Goals

### Performance Target
Maximize GFLOPS on a single node (CPU only). Baseline: ~1.0 GFLOPS (naive triple loop, N=1024). Target: 10x baseline or better.

### Priority
- [ ] Minimize execution time
- [x] Maximize throughput
- [ ] Minimize memory usage
- [ ] Improve scalability
- [ ] Maximize energy efficiency

## Overview

### Application Overview
Double-precision general matrix multiplication (DGEMM). C = alpha * A * B + beta * C. Dense linear algebra kernel. Matrix size: N=1024 fixed. FP64 only.

### Optimization Approach
OpenMP + AVX2 (SIMD) on CPU. No CUDA (GPU reserved for Ollama). No MPI (single node). Primary goal is multi-CLI adapter validation, not peak performance.

---

## Constraints

### Hardware
- **System name**: Local PC (WSL2 Ubuntu on Windows)
- **CPU**: Intel Core i7-13700K (24 cores: 8 Performance + 16 Efficiency)
- **RAM**: 64 GB DDR5
- **GPU**: NVIDIA RTX 4070 Ti 12GB — **reserved for Ollama, do not use for DGEMM jobs**

### Remote Execution Environment
- **Working directory**: Local execution via Slurm (no SSH required)
- Slurm is available in WSL2. Use `sbatch` for all job submissions.

### Job Resources
#### Staged Scale-Up
Single node only. No scale-up.

#### Resource Constraints
- Max execution time: 5 min/job
- Partition: `local`
- `--cpus-per-task=8`
- No GPU allocation (`--gres` not used)

#### Job Execution Mode
- [x] Batch job (recommended)

> All computation must use `sbatch`. Do not run computational workloads directly on the shell.

### Middleware (Compiler / Parallelization Modules)

#### Compiler
- [x] gcc (system default)

#### Parallelization Libraries
- [x] OpenMP
- [x] AVX/AVX2 (SIMD)

#### Numerical Libraries
- [x] Do not use (self-implemented only)

### Parallelization Strategy
OpenMP threading + AVX2 intrinsics. Loop tiling, cache blocking, register blocking are encouraged. Each PG explores its own approach independently.

### Accuracy Requirements
- [x] Same accuracy as existing tests
- Error tolerance: relative error < 1e-10 vs naive implementation checksum

### Budget (Time-based)
- **Floor**: 20 min (minimum working time)
- **Target**: 25 min (expected optimization time)
- **Ceiling**: 30 min (hard upper limit)

### Job Count Limits
- **Floor**: 5 jobs
- **Target**: 20 jobs
- **Ceiling**: 50 jobs

---

## Agent Configuration

### Mode
- [ ] SOLO mode
- [x] Multi-agent (PM + SE2 + PG6 = 9 agents)

### Operation Mode
- [x] Autonomous (proceed without asking for confirmation)
- [ ] Vibe Coding (interactive, pause for user feedback)

### Agent Configuration Table

| Role | Agent ID | CLI | Model | Specialization | CLI Args | Notes |
|------|----------|-----|-------|----------------|----------|-------|
| PM | PM | claude | claude-opus-4 | - | | Orchestration + monitoring (Max) |
| SE | SE1 | codex | gpt-5.4 | - | | Monitoring team 1 (subscription) |
| SE | SE2 | claude | claude-opus-4 | - | | Monitoring team 2 (Max) |
| PG | PG1.1 | cline | anthropic/claude-sonnet-4.6 | OpenMP | | Team 1 (OpenRouter) |
| PG | PG1.2 | vibe-local | qwen3.5:35b | OpenMP | --context-window 200000 | Team 1 (Ollama) |
| PG | PG1.3 | gemini | | OpenMP | | Team 1 (native auth) |
| PG | PG2.1 | qwen | qwen3.5-plus | OpenMP | | Team 2 (native auth) |
| PG | PG2.2 | opencode | openrouter/qwen/qwen3-next-80b-a3b | OpenMP | | Team 2 (OpenRouter) |
| PG | PG2.3 | kimi | kimi-code | OpenMP | | Team 2 (native auth) |

### Environment Variables (per-agent)

| Agent | Variable | Value |
|-------|----------|-------|
| PG1.1 | OPENROUTER_API_KEY | $OPENROUTER_API_KEY |
| PG1.2 | OLLAMA_HOST | http://localhost:11434 |
| PG1.3 | (none) | Gemini pre-authenticated |
| PG2.1 | (none) | Qwen native auth (`qwen auth login`) |
| PG2.2 | (none) | OpenCode pre-authenticated |
| PG2.3 | (none) | Kimi native auth (`kimi /login`) |

### PG Specialization

| Specialization | Count | Notes |
|---------------|-------|-------|
| OpenMP | 6 | PG1.1-PG2.3 (multi-CLI competition) |

### CD (GitHub Integration)
- [x] Disable

### Time Limit
- **Floor**: 20 min
- **Target**: 25 min
- **Ceiling**: 30 min

---

### Security Requirements
- [x] Avoid absolute paths (ensure portability)
- [x] Telemetry disabled for all CLIs
- [ ] Anonymize user/project information before GitHub push (CD disabled)

### Additional Instructions

#### All Agents
- Use `sbatch` for all job submissions. Partition: `local`, `--cpus-per-task=8`
- **Do not use GPU** — GPU is reserved for Ollama (vibe-local)
- N=1024 fixed for all DGEMM runs
- Record both GFLOPS and execution time; use GFLOPS as primary metric
- FP64 (double precision) only
- All communication in English

#### SE-specific
- Verify all PG ChangeLog.md entries follow the correct format (per `skills/changelog-format/SKILL.md`)
- Report CLI-specific issues (build failures, hook errors, communication problems) per agent
- Focus on **adapter compatibility validation** over performance optimization
- Flag any PG that fails to produce a valid ChangeLog entry within 10 min

#### PG-specific
- Matrix size: N=1024 fixed (do not change)
- Compare improvement ratio vs naive baseline (0.96 GFLOPS)
- Archive non-improving versions rather than deleting
- Record compiler flags used in ChangeLog params section

---

## Success Criteria (Primary: Multi-CLI Validation)

1. **All 8 CLI types** (claude, codex, cline, kimi, vibe-local, gemini, qwen, opencode) start successfully
2. **All PGs** produce at least one valid ChangeLog.md entry in the correct format
3. **SOTA tracking** functions correctly across all agents
4. **Inter-agent communication** (vibecodehpc send) works between different CLI types
5. Performance numbers are **reference only** (N=1024 is small; absolute GFLOPS is not the goal)

---

## Auto-Generated Information (filled by PM)
- **Missing items**: [PM fills automatically]
- **Recommended configuration**: [PM fills automatically]
- **Initial agent placement**: [PM fills automatically]

---
## Auto-Generated: tmux Pane Map (by vibecodehpc setup)
- PM session: `proj_PM` (pane 0.0)
