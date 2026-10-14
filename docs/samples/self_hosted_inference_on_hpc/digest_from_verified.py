#!/usr/bin/env python3
"""Write a ranked digest of results from rows an independent checker accepted.

A slow or over-eager PM may publish a summary with numbers nobody has
checked. Here the summary is made by a program instead: numbers come only
from the checker's output (one JSON object per line), never from the
agents' own reports. PM may add a one-line note per result in a separate
file ({"key": ..., "why": ...} per line); nothing else from the agents
enters the digest.

The checker is task specific and runs elsewhere (for example a loop in the
job script that re-runs the reference test on every candidate the agents
write). This script only ranks and formats its accepted rows.

When the top result changes, one line is appended to a notice file, so a
human or another program can follow progress without reading the digest.

Usage (fields may be dotted paths into nested objects):
    python3 digest_from_verified.py [--project-root DIR]
        --key FIELD --sort FIELD[:asc|:desc] [--sort ...]
        --column FIELD[=Header] [--column ...]
        [--group-by FIELD] [--top 10] [--accept STATUS ...]
        [--verified FILE] [--rejected FILE] [--notes FILE]
        [--out FILE] [--notice FILE]

Example (a kernel tuning task):
    python3 digest_from_verified.py --key id --sort gflops:desc \
        --sort time_s:asc --group-by variant \
        --column gflops=GFLOPS --column time_s="Time (s)" --column variant
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any


def read_jsonl(path: Path) -> list[dict]:
    rows = []
    if path.exists():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict):
                rows.append(row)
    return rows


def get(row: dict, field: str) -> Any:
    """Value at a dotted path, or None."""
    value: Any = row
    for part in field.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def as_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def rank(rows: list[dict], sorts: list[tuple[str, bool]]) -> list[dict]:
    """Stable multi-key sort; missing values go last for every key."""
    rows = list(rows)
    for field, descending in reversed(sorts):
        values = [get(r, field) for r in rows]
        numeric = all(as_number(v) is not None for v in values if v is not None)

        def key(row: dict, field: str = field, numeric: bool = numeric,
                descending: bool = descending):
            # First element puts present values ahead in either direction.
            v = get(row, field)
            if v is None:
                return (not descending, 0.0 if numeric else "")
            return (descending, as_number(v) if numeric else str(v))

        rows.sort(key=key, reverse=descending)
    return rows


def pick(rows: list[dict], group_by: str | None, top: int) -> tuple[list[dict], dict]:
    """First row of each group, up to *top*; counts of the other rows per group."""
    if not group_by:
        return rows[:top], {}
    best, others = [], {}
    seen = set()
    for row in rows:
        group = json.dumps(get(row, group_by), sort_keys=True)
        if group in seen:
            others[group] = others.get(group, 0) + 1
            continue
        seen.add(group)
        best.append(row)
    return best[:top], others


def cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.4g}"
    if not isinstance(value, str):
        value = json.dumps(value, ensure_ascii=False)
    return value.replace("|", "/").replace("\n", " ")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--project-root", type=Path, default=Path.cwd())
    p.add_argument("--key", default="key", help="field that identifies a result")
    p.add_argument("--sort", action="append", default=[],
                   help="FIELD[:asc|:desc], highest priority first")
    p.add_argument("--column", action="append", default=[],
                   help="FIELD[=Header] shown in the table")
    p.add_argument("--group-by", default=None,
                   help="show only the best row per value of this field")
    p.add_argument("--top", type=int, default=10)
    p.add_argument("--status-field", default="status")
    p.add_argument("--accept", action="append", default=None,
                   help="accepted status values [verified]")
    p.add_argument("--verified", default="User-shared/verified/verified.jsonl")
    p.add_argument("--rejected", default="User-shared/verified/rejected.jsonl")
    p.add_argument("--notes", default="User-shared/digest_notes.jsonl")
    p.add_argument("--out", default="User-shared/DIGEST.md")
    p.add_argument("--notice", default="User-shared/NOTICE.jsonl")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    root = args.project_root.resolve()
    accept = set(args.accept or ["verified"])
    sorts = []
    for spec in args.sort:
        field, _, order = spec.partition(":")
        sorts.append((field, order.lower() != "asc"))
    columns = []
    for spec in args.column:
        field, _, header = spec.partition("=")
        columns.append((field, header or field))

    rows = [r for r in read_jsonl(root / args.verified)
            if get(r, args.status_field) in accept]
    n_rejected = len(read_jsonl(root / args.rejected))
    notes = {str(n.get("key")): n.get("why", "") for n in read_jsonl(root / args.notes)}
    top, others = pick(rank(rows, sorts), args.group_by, args.top)

    now = time.strftime("%Y-%m-%d %H:%M")
    order = ", ".join(f"{f} ({'high' if d else 'low'} first)" for f, d in sorts)
    out = [
        "# DIGEST",
        "",
        f"Generated by digest_from_verified.py at {now} from the checker's output "
        f"only: {len(rows)} accepted rows, {n_rejected} rejected. "
        "Numbers reported by the agents themselves are not used.",
        "",
        f"Order: {order or 'as written by the checker'}."
        + (f" One row per {args.group_by}." if args.group_by else ""),
        "",
    ]
    if not top:
        out.append("No accepted results yet.")
    else:
        header = ["#"] + [h for _, h in columns] + ["Note (PM)", args.key]
        if args.group_by:
            header.insert(-1, f"Other rows of this {args.group_by}")
        out.append("| " + " | ".join(header) + " |")
        out.append("|" + "---|" * len(header))
        for i, row in enumerate(top, 1):
            key = get(row, args.key)
            cells = [str(i)] + [cell(get(row, f)) for f, _ in columns]
            cells.append(cell(notes.get(str(key), ""))[:80])
            if args.group_by:
                group = json.dumps(get(row, args.group_by), sort_keys=True)
                cells.append(str(others.get(group, 0)))
            cells.append(cell(key))
            out.append("| " + " | ".join(cells) + " |")

    out_path = root / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_name(out_path.name + ".tmp")
    tmp.write_text("\n".join(out) + "\n", encoding="utf-8")
    os.replace(tmp, out_path)

    state = out_path.with_name("." + out_path.stem.lower() + "_top")
    top_key = cell(get(top[0], args.key)) if top else ""
    previous = state.read_text(encoding="utf-8") if state.exists() else None
    if top and top_key != previous:
        state.write_text(top_key, encoding="utf-8")
        line = {"time": now, "from": "digest_from_verified.py", "digest": args.out,
                "top": {h: get(top[0], f) for f, h in columns},
                "key": get(top[0], args.key), "accepted": len(rows)}
        with (root / args.notice).open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(line, ensure_ascii=False) + "\n")
    print("digest", now, "accepted", len(rows), "shown", len(top))


if __name__ == "__main__":
    main()
