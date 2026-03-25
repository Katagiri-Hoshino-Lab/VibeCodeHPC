# ChangeLog PM Override Example

**Note**: This is an example for creating `ChangeLog_format_PM_override.md`.
PM should use this example as a reference to create one tailored to the actual project.

This document defines **additional rules only** on top of the base format (`ChangeLog_format` in SKILL.md).
The base format structure cannot be changed.

## PM Override Items

### 1. Standardize Performance Metrics
- **Unit specification**: Must be stated in the `unit` field of the `test` section
  - Matrix computation: `GFLOPS` or `MFLOPS`
  - Simulation: `iterations/sec` or `seconds`
- **Precision**: One decimal place (e.g., `285.7`)

### 2. Project-Specific Required Params
Add the following to the base format's `params` section:
- `compile_flags`: Compiler options used (required)
- `mpi_processes`: Number of MPI processes (required when using MPI)
- `omp_threads`: Number of OpenMP threads (required when using OpenMP)

### 3. Handling Compile Warnings
When `compile` has `status: warning`:
- Summarize parallelization-related warnings in `message` (1-2 lines)
- Add a `compile_warnings` field for details if needed (optional)

### 4. Additional Information on SOTA Updates
Optionally add the following to the `sota` section:
- `previous`: Previous record value
- `improvement`: Improvement rate (% notation)

### 5. GPU Thermal/Power Monitoring (Optional)
Add the following to the `params` section for GPU workloads:
- `gpu_temp_max`: Peak GPU temperature during job (°C) — detect thermal throttling
- `gpu_power_avg`: Average GPU power draw during job (W) — energy efficiency analysis

Collection method (run alongside job):
```bash
nvidia-smi dmon -s pt -d 1 -f gpu_monitor.csv &
MONITOR_PID=$!
# ... run job ...
kill $MONITOR_PID
# Extract: awk for max temp, avg power from gpu_monitor.csv
```
**Why**: Consecutive jobs may cause thermal throttling, reducing GFLOPS. Recording temperature helps identify performance degradation from heat buildup.

## Example (Matrix Computation Project)

```markdown
### v1.2.3
**Changes**: "Implemented OpenMP collapse(2) and MPI domain decomposition"
**Result**: Performance improvement confirmed `285.7`
**Comment**: "collapse clause parallelizes inner loop, added MPI domain decomposition"

<details>

- [x] **compile**
    - status: `warning`
    - message: "OpenMP: warning that parallelization is disabled for some loops"
    - compile_warnings: "loop at line 45: not vectorized due to data dependency"
    - log: `/results/compile_v1.2.3.log`
- [x] **job**
    - id: `12345`
    - status: `success`
- [x] **test**
    - status: `pass`
    - performance: `285.7`
    - unit: `GFLOPS`
- [x] **sota**
    - scope: `hardware`
    - previous: `241.3`
    - improvement: `+18.4%`
- **params**:
    - nodes: `4`
    - compile_flags: `-O3 -fopenmp -march=native`
    - mpi_processes: `16`
    - omp_threads: `8`
    - gpu_temp_max: `78`
    - gpu_power_avg: `215.3`

</details>
```

## Diff Summary

Additions to the base format:
1. `test` `unit` field (already in base format)
2. `compile_warnings` field (optional)
3. `sota` `previous` and `improvement` (optional)
4. `params` `compile_flags`, `mpi_processes`, `omp_threads` (conditionally required)

## Important Notes

1. **Preserve Markdown Structure**
   - Never modify `<details>` tags
   - Maintain field hierarchy
   - **Important**: PM can only modify item fields inside `<details>`
   - **The folded format (4-line summary display) must always be preserved**

2. **Python Parser Compatibility**
   - Field names: alphanumeric characters and underscores only
   - Numeric values can be written without quotes
   - Units must be in a separate field

3. **Operational Rules**
   - PM creates this at project start using this example as reference
   - Minimize mid-project changes
   - Ensure all agents are notified
   - PG agents must strictly preserve the folded format
