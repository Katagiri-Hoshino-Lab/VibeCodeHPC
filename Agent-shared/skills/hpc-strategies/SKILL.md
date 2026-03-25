---
name: hpc-strategies
description: "Evolutionary flat-directory exploration strategy for HPC optimization. Use when designing directory hierarchies or planning multi-generation parallelization strategies."
---

# HPC Optimization Strategies

## Evolutionary Flat-Directory Design

### Generations
1. **Seed**: Individual techniques (`/OpenMP/`, `/MPI/`, `/CUDA/`)
2. **Crossover**: Fuse promising results (`/OpenMP_MPI/`, `/OpenMP_AVX2/`)
3. **Breeding**: Combine best hybrids (`/OpenMP_MPI_AVX2/`)

### Naming
- Parallelization strategies: `_` separator in implementation order (`OpenMP_MPI_AVX2`)
- Metadata: `-` separator (`CUDA-sharedMem`)
- One worker per flat directory

### Directory Structure
```
<hardware>/<compiler>/
├── OpenMP/       # Gen 1
├── MPI/          # Gen 1
├── CUDA/         # Gen 1
├── OpenMP_MPI/   # Gen 2
└── OpenMP_MPI_AVX2/  # Gen 3
```

### Why Flat
Nested hierarchies cause duplicate implementations when combining A+B+C. Flat structure with visibility control (via `PG_visible_dir.md`) prevents this.

> Details: `references/evolutionary_flat_dir.md`, `references/typical_hpc_structure.md`
