# Requirement Definition

> Samples: [DGEMM 8-CLI (EN)](samples/dgemm_multicli_8agents.md) | [CFD 6-agent (JP)](samples/ja/cfd_multi_6agents.md) | [DGEMM 12-agent (EN)](samples/dgemm_large_12agents.md)

## Project Information
- **Project name**: [project name]
- **Date**: [YYYY-MM-DD]

## Optimization Target

### Code Source
- [ ] Local files: placed in `BaseCode/`
- [ ] GitHub repository: [URL]
- [ ] Other: [description]

### Target Files
- **Main file**: [filename]
- **Dependencies**: [file list]

## Optimization Goals

### Performance Target
[Specific target. e.g., 2x current performance, 50% of theoretical peak]

### Reporting
- [x] Report % of theoretical peak alongside absolute GFLOPS (PM calculates peak from hardware-info skill)

### Priority
- [ ] Minimize execution time
- [ ] Maximize throughput
- [ ] Minimize memory usage
- [ ] Improve scalability
- [ ] Maximize energy efficiency
- [ ] Other: [description]

## Overview

### Application Overview
[Brief description of the application]

### Optimization Approach
[Preferred approach. If unspecified, PM decides automatically]

---

## Constraints

### Hardware
- **System name**: [target environment — supercomputer name, cloud instance, etc.]
- **Available nodes**: [node types, GPU models, etc.]

### Remote Execution Environment
- **Working directory**: [path on remote system; place details in `_remote_info/`]

### Job Resources
#### Staged Scale-Up
[Node count usage policy]

#### Resource Constraints
- Max execution time: [limit]
- Other constraints: [description]

#### Job Execution Mode
- [ ] Batch job (recommended)
- [ ] Interactive job
- [ ] Login node execution (not recommended)

> If unspecified, batch jobs are used. Most supercomputers prohibit computation on login nodes.

### Middleware (Compiler / Parallelization Modules)

#### Compiler
- [ ] [Select available compilers; refer to `_remote_info/`]

#### Parallelization Libraries
- [ ] MPI
- [ ] OpenMP
- [ ] CUDA
- [ ] OpenACC
- [ ] AVX/AVX2/AVX512 (SIMD)
- [ ] Other: [description]

#### Numerical Libraries
- [ ] Do not use (self-implemented only)
- [ ] Use for performance comparison (MKL, cuBLAS, etc.)
- [ ] Use actively

### Parallelization Strategy
[Implementation order and scope. If unspecified, PM decides automatically (evolutionary exploration)]

### Accuracy Requirements
- [ ] Same accuracy as existing tests
- [ ] Error tolerance: [description]
- [ ] Other: [description]

### Budget (Jobs)
- **Floor**: [minimum points to spend before stopping]
- **Target**: [expected budget for normal optimization]
- **Ceiling**: [hard upper limit, must not exceed]

#### Point Consumption Rate (Reference)
[System-specific rate. e.g., 0.007 points per elapsed second per GPU]

### Time Limit
- **Floor**: [minimum working time. e.g., 1 hour]
- **Target**: [standard working time]
- **Ceiling**: [maximum working time. e.g., 3 hours]

---

## Agent Configuration

### Mode
- [ ] SOLO mode (single agent handles all roles)
- [ ] Multi-agent (PM, SE, PG, CD deployed individually)

### Operation Mode
- [ ] Autonomous (PM proceeds through all phases without asking for confirmation — recommended for unattended optimization)
- [ ] Vibe Coding (PM pauses at each phase for user feedback — interactive, incremental development)

### Worker Count
Corresponds to `-w` in `python3 -m vibecodehpc setup --name <name> -w <N>`.

| Workers | SE | PG | CD | Notes |
|---------|----|----|-----|-------|
| 2 | 1 | 1 | 0 | Minimum |
| 4 | 1 | 3 | 0 | Small |
| 8 | 2 | 5 | 1 | Stable (SE >= 2) |
| 12 | 2 | 9 | 1 | Recommended |

- **SE count**: [specify; 2+ enables cross-monitoring]
- **PG count**: [specify]

### Agent Configuration Table

| Role | Agent ID | CLI | Model | Specialization | CLI Args | Notes |
|------|----------|-----|-------|----------------|----------|-------|
| PM | PM | claude | opus | - | | |
| SE | SE1 | codex | gpt-5.4 | - | | |
| SE | SE2 | claude | opus | - | | |
| PG | PG1.1 | cline | sonnet-4.6 | OpenMP | | |
| PG | PG1.2 | vibe-local | qwen3.5:35b | OpenMP | --context-window 65536 | Ollama |
| PG | PG1.3 | gemini | Gemini-3 | OpenMP | | CLI default |
| PG | PG2.1 | qwen | qwen3.5-plus | OpenMP | | Native auth |
| PG | PG2.2 | opencode | qwen3-next-80b | OpenMP | | |
| PG | PG2.3 | kimi | kimi-code | OpenMP | | Native auth |

> - List **all** agents explicitly. No default model.
> - **CLI Args**: Extra flags passed at launch (e.g. `--context-window 65536`)
> - See [CLI Support Matrix](cli_support_matrix.md) for auth and compatibility

### CLI Fallback Policy
- [ ] Allow PM to substitute unavailable CLIs with alternatives (flexible — optimization is the goal)
- [ ] Strict: fail and report if specified CLI is not available (for multi-CLI validation experiments)

### PG Specialization

| Specialization | Count | Notes |
|---------------|-------|-------|
| OpenMP | [N] | |
| CUDA | [N] | |
| MPI | [N] | |
| [other] | [N] | |

> Specialization is used as the directory name and defines each PG's parallelization scope.

### CD (GitHub Integration)
- [ ] Enable
- [ ] Disable
- [ ] Gradual introduction

When using CD:
- **Repository**: [URL or org/repo]
- **Branch policy**: [description. e.g., create a branch named after the project]

---

### Security Requirements
- [ ] Anonymize user/project information before GitHub push
- [ ] Relativize budget information (hide total budget)
- [ ] Avoid absolute paths (ensure portability)
- [ ] Other: [description]

### Additional Instructions

#### All Agents
[Instructions for all agents]

#### SE-specific
[SE-specific instructions. e.g., periodically verify all results are plotted in SOTA graphs]

#### PG-specific
[PG-specific instructions. e.g., record both execution time and throughput]

#### CD-specific
[CD-specific instructions. e.g., .gitignore policy, push frequency]

---

## Auto-Generated Information (filled by PM)
- **Missing items**: [PM fills automatically]
- **Recommended configuration**: [PM fills automatically]
- **Initial agent placement**: [PM fills automatically]


## Sample Requirement Definitions
- [DGEMM multi-CLI competition (8 agents, English)](samples/dgemm_multicli_8agents.md)
- [CFD multi-agent (6 agents, Japanese)](samples/ja/cfd_multi_6agents.md)
- [DGEMM large-scale (12 PGs, English)](samples/dgemm_large_12agents.md)
