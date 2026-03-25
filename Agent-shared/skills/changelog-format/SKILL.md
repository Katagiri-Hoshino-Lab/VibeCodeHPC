---
name: changelog-format
description: "ChangeLog.md format spec for VibeCodeHPC. Use when writing or validating ChangeLog entries with compile/job/test/sota fields."
---

# ChangeLog Format

## Entry Structure

```markdown
### vX.Y.Z
**Changes**: "brief description"
**Result**: key metric `value`
**Comment**: "implementation notes"

<details>

- **generated_at**: `YYYY-MM-DDTHH:MM:SSZ` (UTC)
- [x/✗] **compile**
    - status: `success|warning|error`
    - message: "error/warning text" (if applicable)
    - log: `path/to/log`
- [x/✗] **job**
    - id: `job_id`
    - resource_group: `group_name`  # required for budget
    - start_time / end_time: `ISO8601`  # required for budget
    - runtime_sec: `seconds`
    - status: `success|error|timeout|cancelled|running`
- [x/✗] **test**
    - performance: `value`
    - unit: `GFLOPS|seconds|...`
    - accuracy: `value` (if applicable)
- [x/✗] **sota**
    - scope: `local|family|hardware|project` (on update only)
- **params**: nodes, block_size, etc.

</details>
```

## Rules
- Newest version on top (descending order)
- `<details>` folding is mandatory
- `resource_group`, `start_time`, `end_time`, `runtime_sec` required for budget tracking (regex-parsed)
- PM may override field definitions within `<details>` via project-specific template

## CLI Script

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/changelog.py --help
python3 ${CLAUDE_SKILL_DIR}/scripts/changelog.py create --version 1.2.0 --changes "Optimized loop tiling"
python3 ${CLAUDE_SKILL_DIR}/scripts/changelog.py append /path/to/ChangeLog.md --version 1.2.0 --changes "Added vectorization"
python3 ${CLAUDE_SKILL_DIR}/scripts/changelog.py validate /path/to/ChangeLog.md
```

## API Reference
- `references/changelog_api.md` — Python analytics API for SE statistical analysis

## PM Override Reference
- `references/pm_override_template.md` — Example template for PM to customize ChangeLog fields within `<details>` (project-specific params, metrics, SOTA extensions)
