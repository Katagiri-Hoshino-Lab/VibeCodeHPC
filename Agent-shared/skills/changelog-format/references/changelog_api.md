# ChangeLog Python API Guide

Usage of the `vibecodehpc.analytics.changelog` module. Used by SE for statistical analysis and report generation.

## Import

```python
from vibecodehpc.analytics.changelog import create_changelog_entry, append_to_changelog
```

## Creating Entries: `create_changelog_entry()`

Generates a Markdown entry string for appending to ChangeLog.md.

```python
entry = create_changelog_entry(
    version="1.2.3",
    changes="Blocking optimization and thread count tuning",
    result="Achieved 65.1% of theoretical performance — 312.4 GFLOPS",
    comment="Changed block size from 64 to 128",
    config={
        "timestamp": "2025-08-20T10:30:00Z",  # Defaults to current UTC if omitted
        "performance_unit": "GFLOPS",           # Default: "GFLOPS"
    }
)
```

### Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `version` | Yes | Semantic version (e.g., `"1.2.3"`) |
| `changes` | Yes | Description of changes |
| `result` | No | Result summary (default: `"pending"`) |
| `comment` | No | Comment |
| `config` | No | Configuration dict (see below) |

### Config Keys

| Key | Default | Description |
|-----|---------|-------------|
| `timestamp` | Current UTC | ISO-8601 timestamp |
| `performance_unit` | `"GFLOPS"` | Unit label for performance values |

### Output Format

```markdown
### v1.2.3
**Changes**: "Blocking optimization and thread count tuning"
**Result**: Achieved 65.1% of theoretical performance — 312.4 GFLOPS
**Comment**: "Changed block size from 64 to 128"

<details>

- **generated_at**: `2025-08-20T10:30:00Z`
- [ ] **compile**
    - status: `pending`
- [ ] **job**
    - id: `pending`
    - status: `pending`
- [ ] **test**
    - status: `pending`
    - performance: `pending`
    - unit: `GFLOPS`
- [ ] **sota**
    - scope: `pending`

</details>
```

## Appending to File: `append_to_changelog()`

Appends the generated entry to a ChangeLog.md file (newest entries on top).

```python
append_to_changelog(
    changelog_path="Flow/TypeII/single-node/gcc/OpenMP/PG1.1/ChangeLog.md",
    entry=entry,
    config={
        "header_marker": "## Change Log",  # Default value
    }
)
```

### Behavior
- If the file does not exist: creates a new file with a header
- If the file exists: inserts the entry immediately after `header_marker` (newest first)
- If the marker is not found: appends to the end of the file

## Usage Example for SE: Batch Processing for Statistical Analysis

```python
from pathlib import Path
from vibecodehpc.analytics.changelog import create_changelog_entry

# Aggregating data from multiple PG ChangeLog.md files
project_root = Path(".")
for cl in project_root.glob("**/ChangeLog.md"):
    content = cl.read_text()
    # Extract and aggregate performance values
    # ...
```
