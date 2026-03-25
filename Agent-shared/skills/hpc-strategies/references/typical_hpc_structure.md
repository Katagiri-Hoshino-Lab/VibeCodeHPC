# Typical HPC Code Structure — Detailed Examples

## Tier 1: Environment Directory
- LLM reads module lists, makefiles, and shell scripts to create directories automatically
- Defines the primary configuration: how to set up the environment, build, and run

## Tier 2: Strategy Directory
- Division of labor at the module level: CUDA, MPI, OMP, SIMD, compiler optimization levels, etc.
- Algorithm-level optimizations (non-blocking communication, transposition, loop unrolling, etc.) are left to each PG

## Initial Layout After Setup
```
VibeCodeHPC/
├── Common rules
├── PM
├── GitHub/ (CD)
└── Flow/TypeII/
    └── single-node/
        ├── SE1
        ├── intel2024/
        │   ├── AVX512/ (PG1.1)
        │   ├── MPI/    (PG1.2)
        │   └── OpenMP/ (PG1.3)
        ├── gcc11.3.0/
        │   ├── AVX2/   (PG1.4)
        │   ├── OpenMP/ (PG1.5)
        │   ├── MPI/    (PG1.6)
        │   └── CUDA/   (PG1.7)
        └── hpc_sdk23.1/
            └── OpenACC/ (PG1.8)
```

## After Some Time (Evolutionary Expansion)
```
VibeCodeHPC/
├── PM
├── GitHub/ (CD)
└── Flow/TypeII/
    └── single-node/
        ├── SE1
        ├── intel2024/
        │   ├── AVX512/
        │   ├── MPI/ (PG1.2)
        │   ├── OpenMP/
        │   └── OpenMP-MPI/ (PG1.3)
        ├── gcc11.3.0/
        │   ├── AVX2/
        │   ├── OpenMP/
        │   ├── OpenMP-MPI/      (PG1.4)
        │   ├── OpenMP-MPI-AVX2/ (PG1.5)
        │   ├── MPI/
        │   └── CUDA/            (PG1.6)
        └── hpc_sdk23.1/
            └── OpenACC/ (PG1.7)
```

## Further Evolution (Multi-Node Expansion)
```
VibeCodeHPC/
├── PM
├── GitHub/ (CD)
└── Flow/TypeII/
    ├── single-node/
    │   ├── SE1
    │   ├── intel2024/
    │   │   ├── MPI/              (PG1.1)
    │   │   ├── OpenMP-MPI/       (PG1.2)
    │   │   └── OpenMP-MPI-AVX512/(PG1.3)
    │   ├── gcc11.3.0/
    │   │   ├── OpenMP-MPI/       (PG1.4)
    │   │   ├── OpenMP-MPI-AVX2/  (PG1.5)
    │   │   └── OpenMP-CUDA/      (PG1.2.4)
    │   └── hpc_sdk23.1/
    └── multi-node/
        ├── SE2
        └── gcc11.3.0/
            ├── MPI/    (PG2.1)  ← formerly PG1.6, reassigned
            └── OpenACC/(PG2.2)  ← formerly PG1.7, reassigned
```

## Agent Placement Tips
- Expanding to new hardware (e.g., multi-node) requires at least SE + PG (2 agents minimum)
- Keeping idle agents in reserve is a valid strategy
- Be aware that code-generation knowledge may drop out of context; prefer using sub-agents to preserve it

## SE Monitoring Checklist
- Reference scope: are appropriate reference permissions set for each PG?
- Is PG generating incorrect code?
- Share useful test code across PGs
- Is PG running `module load` and `make` correctly?
- Are ChangeLog.md entries being recorded properly?
