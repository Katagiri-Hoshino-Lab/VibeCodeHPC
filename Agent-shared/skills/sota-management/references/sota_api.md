# SOTA Checker Python API Guide

Usage of `skills/sota-management/scripts/sota_checker.py`. Used by PG for SOTA determination and by SE for statistical analysis.

## Import

```python
from sota_checker import SOTAChecker  # skills/sota-management/scripts/
```

## Initialization

```python
checker = SOTAChecker(
    current_dir="/path/to/PG1.1/",
    config={
        "project_root": "/path/to/VibeCodeHPC/",  # Auto-detected if omitted
        "project_root_marker": "VibeCodeHPC",       # Marker for auto-detection
        "hardware_marker": "hardware_info.md",      # Marker for hardware hierarchy detection
        "unit": "GFLOPS",                           # Performance unit
    }
)
```

### Config Keys

| Key | Default | Description |
|-----|---------|-------------|
| `project_root` | Auto-detected | Explicit project root path |
| `project_root_marker` | `"VibeCodeHPC"` | Directory name prefix for root auto-detection |
| `hardware_marker` | `"hardware_info.md"` | Filename indicating the hardware hierarchy |
| `unit` | `"GFLOPS"` | Performance unit recorded in SOTA files |

## 4-Level Batch Check: `check_sota_levels()`

```python
results = checker.check_sota_levels("285.7 GFLOPS")
# => {"local": True, "family": False, "hardware": True, "project": False}

for level, is_new_sota in results.items():
    if is_new_sota:
        print(f"  {level}: NEW SOTA!")
```

The argument is a string in `"value unit"` format. The leading number is parsed as the performance value.

## Individual Level Checks

```python
# Individual checks are also available after calling check_sota_levels()
checker.check_local_sota()     # Within PG directory
checker.check_family_sota()    # Family (same middleware) reference via PG_visible_dir.md
checker.check_hardware_sota()  # hardware_info.md hierarchy
checker.check_project_sota()   # Project root
```

**Note**: Before calling individual methods, either set `self.performance` via `check_sota_levels()` or manually set `checker.performance = 285.7`.

## Updating SOTA Files: `update_sota_files()`

```python
if any(results.values()):
    updated = checker.update_sota_files(
        version="v1.2.3",
        timestamp="2025-07-16T14:30:00Z",
        agent_id="PG1.1"
    )
    # => {"local": True, "family": False, "hardware": True, "project": False}
```

### Files Updated

| Level | File | Condition |
|-------|------|-----------|
| local | `{current_dir}/sota_local.txt` | When local SOTA is updated |
| hardware | `{hw_dir}/sota_hardware.txt` | When hardware SOTA is updated |
| project | `{root}/sota_project.txt` | When project SOTA is updated |
| project history | `{root}/history/sota_project_history.txt` | When project SOTA is updated (append) |

`family` (Family SOTA) is a virtual level without a file.

## Directory Search Utilities

```python
# Search for parent directory containing hardware_info.md
hw_dir = checker.find_hardware_info_dir()

# Search for project root
root = checker.find_project_root()

# Relative path of current directory (for hardware_path)
hw_path = checker.get_hardware_path()  # => "gcc/OpenMP"

# Strategy name (inferred from directory name)
strategy = checker.get_strategy()  # => "OpenMP"
```

## Typical Usage Flow for PG

```python
import os
from sota_checker import SOTAChecker  # skills/sota-management/scripts/

# After obtaining performance value from job results
performance = "312.4 GFLOPS"

checker = SOTAChecker(os.getcwd())
results = checker.check_sota_levels(performance)

if any(results.values()):
    checker.update_sota_files(
        version="v1.2.3",
        timestamp="2025-08-20T11:00:00Z",
        agent_id="PG1.1"
    )
    print("SOTA updated at:", [k for k, v in results.items() if v])
```
