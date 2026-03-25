---
name: budget-tracking
description: "Compute budget management with phase-based termination criteria. Use when checking budget, determining project phase, or making stop decisions."
---

# Budget Tracking

## Phases

| Phase | Range | Action |
|-------|-------|--------|
| 0 | 0 — minimum | Verify basic operation, fix environment issues |
| 1 | — 50% of target | Aggressive exploration, broad parameter search |
| 2 | 50-80% | Focus on promising approaches, cost-efficiency |
| 3 | 80-100% of target | Best optimization only, start summarizing |
| 4 | target — 90% of deadline | Pre-approve new jobs, prepare final report |
| 5 | 90-100% of deadline | No new jobs, terminate all work within 5 min |

## Budget Thresholds (set in requirement_definition.md)
1. **Minimum**: Basic verification budget
2. **Target**: Expected optimization budget
3. **Deadline**: Absolute maximum

## Consumption Formula
```
project_usage = current_used - start_used
consumption_% = (project_usage / deadline) × 100
```
Note: `used` is cumulative annual value — always diff from project start.

## Critical Rules
- Login node execution is forbidden (policy violation)
- Zero point consumption → warn agent immediately
- Budget check commands are supercomputer-specific (see `_remote_info/`)

> Details: `references/phase_details.md`

## Operational Notes
- `determine_phase()` is called automatically by `summarise()` and included in `--summary` output.
- Phase is computed from `DEFAULT_BUDGET_LIMITS` keys: Minimum, Expected (target), Deadline.
- Agents should check phase before submitting new jobs and adjust strategy accordingly.

## CLI Script

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/budget_tracker.py --help
python3 ${CLAUDE_SKILL_DIR}/scripts/budget_tracker.py /path/to/project --summary
python3 ${CLAUDE_SKILL_DIR}/scripts/budget_tracker.py /path/to/project --report --json
python3 ${CLAUDE_SKILL_DIR}/scripts/budget_tracker.py /path/to/project --jobs --json
python3 ${CLAUDE_SKILL_DIR}/scripts/budget_tracker.py /path/to/project --visualize -o budget.png
```
