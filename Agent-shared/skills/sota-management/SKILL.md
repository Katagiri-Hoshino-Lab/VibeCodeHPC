---
name: sota-management
description: "4-level SOTA performance tracking for VibeCodeHPC. Use when checking or updating best performance records."
---

# SOTA Management

## Hierarchy

| Level | Scope | File | Manager |
|-------|-------|------|---------|
| Local | PG directory best | `sota_local.txt` | PG |
| Family | Same middleware parent-child | Virtual (from PG_visible_dir.md) | Auto |
| Hardware | Same hardware config | `sota_hardware.txt` | SE |
| Project | Project-wide best | `sota_project.txt` | PM |

## Check Timing
- After PG records test performance in ChangeLog.md
- During SE/PM statistical analysis

## Python API
`${CLAUDE_SKILL_DIR}/scripts/sota_checker.py` — checks and updates all 4 levels. Run with `--help` for usage.

## Benefits
- Fast comparison via dedicated files (no ChangeLog scanning)
- Hierarchical isolation
- Family SOTA auto-computed from visibility scope

> Details: `references/file_formats.md`, `references/sota_api.md`

## CLI Script

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/sota_checker.py --help
python3 ${CLAUDE_SKILL_DIR}/scripts/sota_checker.py /path/to/PG1.1 check "350.0 GFLOPS"
python3 ${CLAUDE_SKILL_DIR}/scripts/sota_checker.py /path/to/PG1.1 update "350.0 GFLOPS" --version 1.2.0 --agent PG1.1
python3 ${CLAUDE_SKILL_DIR}/scripts/sota_checker.py /path/to/PG1.1 info --json
```

## Visualizer Script

`scripts/sota_visualizer.py` — self-contained SOTA visualization pipeline.
Generates 4-level graphs (local/family/hardware/project) from ChangeLog.md data.

Requires: `matplotlib`, `numpy`

```bash
# Pipeline mode (default, periodic execution)
python3 ${CLAUDE_SKILL_DIR}/scripts/sota_visualizer.py

# Debug mode (low DPI)
python3 ${CLAUDE_SKILL_DIR}/scripts/sota_visualizer.py --debug

# Summary only (no graph generation)
python3 ${CLAUDE_SKILL_DIR}/scripts/sota_visualizer.py --summary

# Data export for multi-project analysis
python3 ${CLAUDE_SKILL_DIR}/scripts/sota_visualizer.py --export

# Custom levels and DPI
python3 ${CLAUDE_SKILL_DIR}/scripts/sota_visualizer.py --levels local,project --dpi 80
```
