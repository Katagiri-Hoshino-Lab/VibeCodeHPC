# Evolutionary Flat Directory Design — Detailed Examples

## Problems with Top-Down Hierarchies
- Directory tree structure is ambiguous (ordering of parallelization module, compiler, etc. as parent/child is not unique)
- Implementations such as SIMD scatter across deep hierarchies, making them hard to track
- Adding only executables without directories forces job script and makefile modifications, complicating version control

## Flat Directory Examples

Reference permissions express hierarchical relationships without deep nesting:
```
root/
    A/  (instructions.md: "reference A only")
    B/  (instructions.md: "reference B only")
    A+B/ (instructions.md: "reference A and B only")
```

Typical HPC code:
```
MPI/
OpenMP/
OpenMP_MPI/
```

LLM distributed parallelism strategies:
```
PP/
TP/
PP_TP/
```

## Directory Naming Conventions

```
OK   OpenACC_CUDA   (apply OpenACC to loops first, then CUDA for the rest)
NG   CUDA_OpenACC

OK   MPI_AVX2       (coarse-grained → fine-grained; multi-core → single-core)
NG   AVX2_MPI

OK   PP_TP_EP       (pipeline vertical → tensor horizontal → FFN-layer expert)
```

Separate distinct parallelization/optimization strategies with `_`, ordered by natural implementation sequence.
Attach auxiliary info with `-` (e.g., `MPI-opt1`). Omit version when using the default.

## Root Directory Layout

The root directory specifies hardware only.
Example: `/Flow/TypeII/single-node/`
Place a `hardware_info.md` directly under it with detailed specs (bandwidth, cache, etc.).

A middleware layer directly under the root is recommended.
Example:
```
/Flow/TypeII/single-node/
                        /gcc11.3.0/
                        /intel2022.3/
```

### Middleware Naming Convention
When multiple modules are used, list them left-to-right in `module load` order.
Examples:
- `/go1.24.4/opencode0.0.55/`
- `/singularity4.1.2/container-name/`

## Evolutionary Progression by Generation

### Generation 1: Seed Phase
```
/AVX2/
/CUDA/
/MPI/
/OpenMP/
```

### Generation 2: Crossover Phase
```
/AVX2/
/CUDA/
/CUDA-sharedMem/      (deepening)
/MPI/
/OpenMP/
/OpenMP_AVX2/         (fusion)
/OpenMP_MPI/          (fusion)
```

### Generation 3: Selective Breeding Phase
```
/AVX2/
/CUDA/
/CUDA-sharedMem/
/MPI/
/MPI_CUDA-sharedMem/       (fusion)
/OpenMP/
/OpenMP_CUDA/              (fusion)
/OpenMP_AVX2/
/OpenMP_MPI/
/OpenMP_MPI_AVX2/          (fusion)
```

At most one worker operates under each evolutionary flat directory. Within that directory, the worker is free to create subdirectories of any depth.
