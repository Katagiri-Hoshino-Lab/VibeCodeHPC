#!/usr/bin/env python3
"""ChangeLog.md entry creation and management.

Self-contained script (no package dependencies). Designed to be run by agents
via ``python3 changelog.py --help``.

Usage examples:
  python3 changelog.py create --version 1.2.0 --changes "Optimized loop tiling"
  python3 changelog.py append /path/to/ChangeLog.md --version 1.2.0 --changes "Added vectorization"
  python3 changelog.py validate /path/to/ChangeLog.md
"""

import argparse
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional


def _utcnow_iso() -> str:
    """Return current UTC time as an ISO-8601 string with Z suffix."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def create_changelog_entry(
    version: str,
    changes: str,
    result: str = "pending",
    comment: str = "",
    config: Optional[Dict] = None,
) -> str:
    """Generate a ChangeLog entry string in VibeCodeHPC format."""
    cfg = config or {}
    timestamp = cfg.get("timestamp") or _utcnow_iso()
    unit = cfg.get("performance_unit", "GFLOPS")

    return f"""\
### v{version}
**Changes**: "{changes}"
**Result**: {result}
**Comment**: "{comment}"

<details>

- **generated_at**: `{timestamp}`
- [ ] **compile**
    - status: `pending`
- [ ] **job**
    - id: `pending`
    - status: `pending`
- [ ] **test**
    - status: `pending`
    - performance: `pending`
    - unit: `{unit}`
- [ ] **sota**
    - scope: `pending`

</details>
"""


def append_to_changelog(
    changelog_path, entry: str, config: Optional[Dict] = None
) -> None:
    """Append *entry* to a ChangeLog.md file (newest first)."""
    cfg = config or {}
    marker = cfg.get("header_marker", "## Change Log")
    changelog_path = Path(changelog_path)

    if not changelog_path.exists():
        header = f"# ChangeLog.md\ngenerated: {_utcnow_iso()}\n\n{marker}\n\n"
        changelog_path.write_text(header + entry, encoding="utf-8")
    else:
        content = changelog_path.read_text(encoding="utf-8")
        if marker in content:
            parts = content.split(marker, 1)
            new_content = parts[0] + marker + "\n\n" + entry + "\n" + parts[1].lstrip()
            changelog_path.write_text(new_content, encoding="utf-8")
        else:
            changelog_path.write_text(content + "\n" + entry, encoding="utf-8")


def validate_changelog(changelog_path: Path) -> List[Dict]:
    """Validate a ChangeLog.md file and return a list of issues."""
    issues: List[Dict] = []
    if not changelog_path.exists():
        return [{"level": "error", "message": f"File not found: {changelog_path}"}]

    content = changelog_path.read_text(encoding="utf-8")

    # Check for version entries
    versions = re.findall(r"### v(\d+\.\d+\.\d+)", content)
    if not versions:
        issues.append({"level": "warning", "message": "No version entries found"})

    # Check for required fields in each version
    version_pattern = r"### v(\d+\.\d+\.\d+)(.*?)(?=### v|\Z)"
    for match in re.finditer(version_pattern, content, re.DOTALL):
        version, section = match.groups()
        required_fields = ["compile", "job", "test"]
        for field in required_fields:
            if f"**{field}**" not in section:
                issues.append({
                    "level": "warning",
                    "message": f"v{version}: missing **{field}** section",
                })

        # Check budget-critical fields in job section
        job_match = re.search(r"\*\*job\*\*(.*?)(?=\*\*test\*\*|\*\*compile\*\*|\Z)", section, re.DOTALL)
        if job_match:
            job_section = job_match.group(1)
            for budget_field in ["resource_group", "start_time", "end_time", "runtime_sec"]:
                if budget_field not in job_section:
                    issues.append({
                        "level": "info",
                        "message": f"v{version}: job section missing {budget_field} (needed for budget tracking)",
                    })

        # Check details folding
        if "<details>" not in section:
            issues.append({
                "level": "warning",
                "message": f"v{version}: missing <details> folding (required by spec)",
            })

    # Check version ordering (newest first)
    if len(versions) >= 2:
        for i in range(len(versions) - 1):
            v1 = tuple(int(x) for x in versions[i].split("."))
            v2 = tuple(int(x) for x in versions[i + 1].split("."))
            if v1 < v2:
                issues.append({
                    "level": "warning",
                    "message": f"Version ordering: v{versions[i]} appears before v{versions[i+1]} (should be newest first)",
                })

    if not issues:
        issues.append({"level": "info", "message": f"Valid: {len(versions)} version entries found"})

    return issues


def main():
    parser = argparse.ArgumentParser(
        description="ChangeLog.md entry creation and management for VibeCodeHPC.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
examples:
  %(prog)s create --version 1.2.0 --changes "Optimized loop tiling"
  %(prog)s create --version 1.2.0 --changes "Added vectorization" --unit seconds
  %(prog)s append /path/to/ChangeLog.md --version 1.2.0 --changes "Fixed memory layout"
  %(prog)s validate /path/to/ChangeLog.md
  %(prog)s validate /path/to/ChangeLog.md --json
""",
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # create
    create_p = subparsers.add_parser("create", help="Generate a changelog entry (printed to stdout)")
    create_p.add_argument("--version", required=True, help="Semantic version (e.g. 1.2.0)")
    create_p.add_argument("--changes", required=True, help="Description of changes")
    create_p.add_argument("--result", default="pending", help="Result summary (default: pending)")
    create_p.add_argument("--comment", default="", help="Optional comment")
    create_p.add_argument("--unit", default="GFLOPS", help="Performance unit (default: GFLOPS)")
    create_p.add_argument("--timestamp", help="Override timestamp (ISO-8601, default: now UTC)")

    # append
    append_p = subparsers.add_parser("append", help="Create and append entry to a ChangeLog.md file")
    append_p.add_argument("changelog", help="Path to ChangeLog.md file")
    append_p.add_argument("--version", required=True, help="Semantic version (e.g. 1.2.0)")
    append_p.add_argument("--changes", required=True, help="Description of changes")
    append_p.add_argument("--result", default="pending", help="Result summary (default: pending)")
    append_p.add_argument("--comment", default="", help="Optional comment")
    append_p.add_argument("--unit", default="GFLOPS", help="Performance unit (default: GFLOPS)")
    append_p.add_argument("--timestamp", help="Override timestamp (ISO-8601, default: now UTC)")

    # validate
    validate_p = subparsers.add_parser("validate", help="Validate a ChangeLog.md file")
    validate_p.add_argument("changelog", help="Path to ChangeLog.md file")
    validate_p.add_argument("--json", action="store_true", help="Output in JSON format")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "create":
        config = {"performance_unit": args.unit}
        if args.timestamp:
            config["timestamp"] = args.timestamp
        entry = create_changelog_entry(args.version, args.changes, args.result, args.comment, config)
        print(entry)

    elif args.command == "append":
        config = {"performance_unit": args.unit}
        if args.timestamp:
            config["timestamp"] = args.timestamp
        entry = create_changelog_entry(args.version, args.changes, args.result, args.comment, config)
        append_to_changelog(args.changelog, entry)
        print(f"Entry v{args.version} appended to {args.changelog}")

    elif args.command == "validate":
        import json
        issues = validate_changelog(Path(args.changelog))
        if args.json:
            print(json.dumps(issues, indent=2))
        else:
            for issue in issues:
                level = issue["level"].upper()
                print(f"  [{level}] {issue['message']}")


if __name__ == "__main__":
    main()
