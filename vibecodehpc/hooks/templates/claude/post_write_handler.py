#!/usr/bin/env python3
"""VibeCodeHPC PostToolUse Hook for version file ChangeLog validation (Claude Code).

Detects _vX.Y.Z file creation via Write/Edit and checks ChangeLog.md consistency.
Ported from VibeCodeHPC-jp/hooks/templates/post_write_version_check.py.

Key changes:
- Removed sub-agent (claude -p) call for ChangeLog check — does local check instead
- Simplified to local file parsing (no subprocess dependency)
"""

import json
import re
import sys
from pathlib import Path


def find_project_root(start_path: Path) -> Path | None:
    """Find project root.

    Uses a 2-of-3 heuristic: the directory containing at least two of
    ``CLAUDE.md``, ``Agent-shared/``, and ``instructions/`` is the root.
    Note: vibecodehpc/ alone is NOT sufficient -- it is the Python package,
    not the project root.
    """
    _landmarks = ("CLAUDE.md", "Agent-shared", "instructions")
    current = start_path.resolve()
    while current != current.parent:
        hits = sum(1 for lm in _landmarks if (current / lm).exists())
        if hits >= 2:
            return current
        current = current.parent
    return None


def _find_changelog(file_path: Path, cwd: Path) -> Path | None:
    """Find ChangeLog.md by searching multiple candidate locations.

    Search order:
    1. Same directory as the written file
    2. cwd (the agent's working directory)
    3. Parent directories of the written file up to project root
    """
    project_root = find_project_root(cwd)
    stop_at = project_root.parent if project_root else Path("/")

    # 1. Same directory as the written file
    file_dir = file_path.resolve().parent
    candidate = file_dir / "ChangeLog.md"
    if candidate.exists():
        return candidate

    # 2. cwd
    candidate = cwd / "ChangeLog.md"
    if candidate.exists():
        return candidate

    # 3. Walk up from file_dir toward project root
    current = file_dir.parent
    while current != stop_at and current != current.parent:
        candidate = current / "ChangeLog.md"
        if candidate.exists():
            return candidate
        current = current.parent

    return None


def check_changelog(version: str, cwd: Path, file_path: Path | None = None) -> tuple[bool, str]:
    """Check if ChangeLog.md has an entry for the given version."""
    changelog_path = None
    if file_path is not None:
        changelog_path = _find_changelog(Path(file_path), cwd)
    if changelog_path is None:
        changelog_path = cwd / "ChangeLog.md"
    if not changelog_path.exists():
        return False, f"ChangeLog.md not found (searched from {file_path or cwd})"

    try:
        content = changelog_path.read_text(encoding="utf-8")
    except OSError as e:
        return False, str(e)

    # Check for version entry
    if f"v{version}" not in content:
        return False, f"v{version} entry not found in ChangeLog.md"

    # Check for required fields (resource_group, start_time/end_time)
    # Find the section for this version
    sections = content.split(f"v{version}")
    if len(sections) < 2:
        return False, f"v{version} section is empty"

    section = sections[1].split("### v")[0]  # up to next version entry

    missing = []
    if "resource_group" not in section:
        missing.append("resource_group")
    if "start_time" not in section and "end_time" not in section:
        missing.append("start_time/end_time")

    if missing:
        return False, f"v{version}: missing fields: {', '.join(missing)}"

    return True, ""


def main():
    try:
        input_data = json.load(sys.stdin)

        tool_name = input_data.get("tool_name", "")
        if tool_name not in ("Write", "Edit", "MultiEdit"):
            sys.exit(0)

        file_path = input_data.get("tool_input", {}).get("file_path", "")

        # Check for _vX.Y.Z pattern
        version_match = re.search(r"_v(\d+\.\d+\.\d+)\.\w+$", file_path)
        if not version_match:
            sys.exit(0)

        version = version_match.group(1)
        cwd = Path(input_data.get("cwd", "."))

        is_valid, error_msg = check_changelog(version, cwd, file_path)

        if not is_valid:
            print(
                f"""ChangeLog.md is missing required information for v{version}

{error_msg}

Please add an entry in the following format:

### v{version}
**generated_at**: `YYYY-MM-DDTHH:MM:SSZ`
**Changes**: "Description of changes"
**Result**: Performance value `XXX GFLOPS`

<details>
- [ ] **job**
    - resource_group: `cx-small etc.`
    - start_time: `start time`
    - end_time: `end time`
</details>
""",
                file=sys.stderr,
            )
            sys.exit(2)  # Block until ChangeLog is updated

        sys.exit(0)

    except Exception:
        sys.exit(0)


if __name__ == "__main__":
    main()
