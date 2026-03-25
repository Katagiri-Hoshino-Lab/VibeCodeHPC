# SOTA Management File Formats

## Local SOTA (under PG directory)
```
# PG1.1/sota_local.txt
current_best: "285.7 GFLOPS"
achieved_by: "v1.2.1"
timestamp: "2025-07-16 14:30:00 UTC"
agent_id: "PG1.1"
```

## Hardware SOTA (hardware_info.md hierarchy)
```
# Flow/TypeII/single-node/sota_hardware.txt
current_best: "342.1 GFLOPS"
achieved_by: "PG1.2"
timestamp: "2025-07-16 15:00:00 UTC"
hardware_path: "gcc/cuda"
strategy: "CUDA_OpenMP"
```

## Project SOTA (project root)
```
# sota_project.txt
current_best: "450.8 GFLOPS"
achieved_by: "PG2.1"
timestamp: "2025-07-16 16:00:00 UTC"
hardware_path: "multi-node/gcc/mpi_openmp"
strategy: "MPI_OpenMP_AVX512"
```

## Python API Usage Example
```python
from sota_checker import SOTAChecker  # skills/sota-management/scripts/

checker = SOTAChecker(os.getcwd())
results = checker.check_sota_levels("285.7 GFLOPS")

for level, updated in results.items():
    if updated:
        print(f"  {level}: NEW SOTA!")

if any(results.values()):
    checker.update_sota_files(
        version="v1.2.3",
        timestamp="2025-07-16 14:30:00 UTC",
        agent_id="PG1.1"
    )
```
