---
name: hardware-info
description: "Hardware spec collection and theoretical peak performance calculation for HPC environments. Prerequisite: skills/ssh-management for remote access."
---

# Hardware Info

## Theoretical Peak Performance

### CPU (FP64)
```
FLOPS = cores × freq(GHz) × 2(FMA) × SIMD_width
SIMD: SSE=2, AVX/AVX2=4, AVX-512=8 (FP64)
```

### GPU (FP64)
```
FLOPS = SMs × FP64_cores_per_SM × freq × 2(FMA)
Multi-GPU: multiply by GPU count
```

### Memory Bandwidth
```
BW = channels × bus_width(bit)/8 × freq(MT/s)
```

## Requirements
1. SE creates `hardware_info.md` at project start with actual commands on compute nodes
2. Theoretical peak must be calculated with formula shown
3. At least one PG verifies via batch job
4. B/F ratio (Byte/FLOP) must be noted for memory-bound vs compute-bound classification

> Details: `references/collection_commands.md`, `references/hardware_info_template.md`
