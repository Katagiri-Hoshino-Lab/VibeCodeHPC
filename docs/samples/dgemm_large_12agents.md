# Requirement Definition

## Project Information
- **Project name**: DGEMM_MultiCLI_EX1
- **Date**: 2026-03-17

## Optimization Target

### Code Source
- [x] Local files: placed in `BaseCode/`

### Target Files
- **Main file**: dgemm.c (matrix_multiply function)
- **Dependencies**: Makefile, test_dgemm.c

## Optimization Goals

### Performance Target
Maximize GFLOPS on a single node. Target: 70% of theoretical peak across all strategies.

### Priority
- [ ] Minimize execution time
- [x] Maximize throughput
- [ ] Minimize memory usage
- [x] Improve scalability
- [ ] Maximize energy efficiency

## Overview

### Application Overview
Double-precision general matrix multiplication (DGEMM). Dense linear algebra kernel widely used in scientific computing. Matrix sizes: 1024x1024 to 8192x8192.

### Optimization Approach
Evolutionary exploration across 4 parallelization strategies, each explored by 3 PGs with different compilers/approaches.

---

## Constraints

### Hardware
- **System name**: ABCI (AI Bridging Cloud Infrastructure)
- **Available nodes**: V-node (NVIDIA V100 × 4), compute node (Intel Xeon Gold 6148 × 2)

### Remote Execution Environment
- **Working directory**: as specified in `_remote_info/`/{project name}

### Job Resources
#### Staged Scale-Up
Start with single GPU, expand to multi-GPU after baseline established.

#### Resource Constraints
- Max execution time: 15 min/job
- Other constraints: rt_G.small queue only

#### Job Execution Mode
- [x] Batch job (recommended)

### Middleware (Compiler / Parallelization Modules)

#### Compiler
- [x] gcc (default version)
- [x] Intel oneAPI
- [x] NVIDIA HPC SDK
- Refer to `_remote_info/`. Use default version unless specific reason.

#### Parallelization Libraries
- [x] MPI
- [x] OpenMP
- [x] CUDA
- [x] OpenACC
- [x] AVX/AVX2/AVX512 (SIMD)

#### Numerical Libraries
- [x] Use for performance comparison (MKL, cuBLAS)

### Parallelization Strategy
Evolutionary exploration. 4 strategies in Generation 1, fuse top performers in Generation 2.

### Accuracy Requirements
- [x] Same accuracy as existing tests
- Error tolerance: relative error < 1e-10 vs naive implementation

### Budget (Jobs)
- **Floor**: 200 points
- **Target**: 1000 points
- **Ceiling**: 2000 points

#### Point Consumption Rate (Reference)
V-node: 0.50 points per elapsed hour per node

---

## Agent Configuration

### Mode
- [ ] SOLO mode
- [x] Multi-agent (PM + SE2 + PG12 + CD = 16 agents, `-w 15`)

### Agent Configuration Table

| Role | Count | CLI | Model | Specialization |
|------|-------|-----|-------|----------------|
| PM | 1 | claude | opus | - |
| SE | 2 | claude | sonnet | - |
| PG | 3 | codex | gpt-5.4 | CUDA |
| PG | 3 | codex | gpt-5.4 | OpenACC |
| PG | 3 | gemini | gemini-3 | OpenMP |
| PG | 3 | opencode | deepseek | MPI |
| CD | 1 | claude | sonnet | - |

### CD (GitHub Integration)
- [x] Enable
- **Repository**: org/DGEMM-MultiCLI-EX1
- **Branch policy**: create branch named after project

### Time Limit
- **Floor**: 90 min
- **Target**: 120 min
- **Ceiling**: 180 min

### Security Requirements
- [x] Anonymize user/project information before GitHub push
- [x] Relativize budget information (hide total budget)
- [x] Avoid absolute paths (ensure portability)

### Additional Instructions

#### All Agents
- Record both GFLOPS and execution time; use GFLOPS as primary metric
- Keep optimization scripts local, transfer to supercomputer for execution
- Do not run computation on login nodes (compilation is allowed)
- Compare results against MKL/cuBLAS reference for validation
- All communication in English

#### SE-specific
- Verify all PG results appear in the integrated SOTA graph
- Plot per-compiler and per-strategy breakdowns
- Flag PGs stuck below 30% of theoretical peak after 30 min

#### PG-specific
- Test matrix sizes: 1024, 2048, 4096, 8192
- Record cache miss rates when available (perf stat)
- Archive non-improving versions rather than deleting

#### CD-specific
- Push anonymized code after each SOTA update
- Exclude `_remote_info/`, `.cache/`, `GitHub/` from pushes
- Maintain reproducible build instructions in README

---

## Auto-Generated Information (filled by PM)
- **Missing items**: [PM fills automatically]
- **Recommended configuration**: [PM fills automatically]
- **Initial agent placement**: [PM fills automatically]
