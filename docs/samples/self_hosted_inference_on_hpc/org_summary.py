#!/usr/bin/env python3
"""Summarise what a VibeCodeHPC organisation did in one job, from files only.

Two steps, run by the job script:

    org_summary.py snap  PROJECT_ROOT OUT.json
        counts at the start (before v2 starts)
    org_summary.py final PROJECT_ROOT LOG_DIR T_START T_END [--label L]
        counts at the end minus LOG_DIR/org_before.json -> LOG_DIR/org_summary.json

Counts (nothing estimated):

- rows of the checker's accepted / rejected files and of the agents'
  candidate files (``--candidates`` glob);
- ChangeLog entries (``### v`` headings) per agent;
- measurement submissions and ``vibecodehpc send`` log lines;
- files under Agent-workdir/ and User-shared/ modified in [T_START, T_END];
- from LOG_DIR/org_metrics.jsonl (org_metrics.sh): generated and prompt
  tokens, prefix-cache hits, preemptions, KV usage, and for speculative
  decoding the mean acceptance length and the acceptance rate per draft
  position, between the samples nearest T_START and T_END;
- from the Claude Code conversation files: assistant turns and usage
  tokens per agent in the window, the agent found by the conversation's
  working directory (registry ``working_dir``; PM = project root).

Comparing two jobs (for example with and without speculative decoding)
is fair only if both start from the same project state and conversations;
the job script can restore both from one tar (VCHPC_RUN_BASE_TAR).
"""

from __future__ import annotations

import argparse
import datetime
import glob
import json
import os
import time
from pathlib import Path

ACCEPTED = "User-shared/verified/verified.jsonl"
REJECTED = "User-shared/verified/rejected.jsonl"
COUNTERS = (
    "generation_tokens_total", "prompt_tokens_total", "request_success_total",
    "num_preemptions_total", "prefix_cache_hits_total", "prefix_cache_queries_total",
    "external_prefix_cache_hits_total", "external_prefix_cache_queries_total",
    "spec_decode_num_drafts_total", "spec_decode_num_draft_tokens_total",
    "spec_decode_num_accepted_tokens_total",
)
GAUGES = ("kv_cache_usage_perc", "num_requests_running", "num_requests_waiting")
PER_POS = "vllm:spec_decode_num_accepted_tokens_per_pos_total"


def count_lines(path: str | Path) -> int:
    try:
        with open(path, errors="replace") as fh:
            return sum(1 for line in fh if line.strip())
    except OSError:
        return 0


def read_jsonl(path: str | Path) -> list[dict]:
    rows = []
    try:
        with open(path, errors="replace") as fh:
            for line in fh:
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        pass
    return rows


def counts(root: Path, candidates: str) -> dict:
    """File-based counters of the project at this moment."""
    out = {
        "accepted_rows": count_lines(root / ACCEPTED),
        "rejected_rows": count_lines(root / REJECTED),
        "candidate_rows": sum(count_lines(p) for p in
                              glob.glob(str(root / candidates), recursive=True)),
        "measure_jobs": count_lines(root / "Agent-shared/measure_jobs.jsonl"),
        "send_log_lines": count_lines(root / "Agent-shared/logs/send_log.txt"),
        "changelog_entries": {},
    }
    for path in sorted(root.glob("Agent-workdir/**/ChangeLog.md")):
        with path.open(errors="replace") as fh:
            n = sum(1 for line in fh if line.startswith("### v"))
        out["changelog_entries"][str(path.parent.relative_to(root))] = n
    return out


def difference(before: dict, after: dict) -> dict:
    out = {}
    for key, value in after.items():
        if isinstance(value, dict):
            old = before.get(key, {})
            out[key] = {k: value.get(k, 0) - old.get(k, 0)
                        for k in sorted(set(value) | set(old))}
            out[key + "_total"] = sum(out[key].values())
        elif isinstance(value, (int, float)):
            out[key] = value - before.get(key, 0)
    return out


def metric(sample: dict, name: str) -> float:
    """Sum of a metric over all its label sets."""
    return sum(v for k, v in sample.items() if k.split("{")[0] == name)


def per_position(sample: dict) -> dict[int, float]:
    out: dict[int, float] = {}
    for k, v in sample.items():
        if k.split("{")[0] == PER_POS and 'position="' in k:
            pos = int(k.split('position="')[1].split('"')[0])
            out[pos] = out.get(pos, 0) + v
    return out


def server_window(log_dir: Path, t0: float, t1: float) -> dict:
    """Counter differences and gauge statistics between t0 and t1."""
    rows = [r for r in read_jsonl(log_dir / "org_metrics.jsonl") if r.get("metrics")]
    if not rows:
        return {"note": "no metrics samples"}
    a_row = min(rows, key=lambda r: abs(r["t"] - t0))
    b_row = min(rows, key=lambda r: abs(r["t"] - t1))
    a, b = a_row["metrics"], b_row["metrics"]
    inside = [r["metrics"] for r in rows if t0 <= r["t"] <= t1]
    out: dict = {"sample_t0": a_row["t"], "sample_t1": b_row["t"],
                 "samples_in_window": len(inside)}
    for name in COUNTERS:
        out[name] = metric(b, "vllm:" + name) - metric(a, "vllm:" + name)
    seconds = max(1, b_row["t"] - a_row["t"])
    out["gen_tok_per_s"] = round(out["generation_tokens_total"] / seconds, 1)
    out["prompt_tok_per_s"] = round(out["prompt_tokens_total"] / seconds, 1)
    if out["prefix_cache_queries_total"] > 0:
        out["prefix_cache_hit_rate"] = round(
            out["prefix_cache_hits_total"] / out["prefix_cache_queries_total"], 4)

    drafts = out["spec_decode_num_drafts_total"]
    if drafts > 0:
        accepted = out["spec_decode_num_accepted_tokens_total"]
        out["mean_acceptance_length"] = round(1 + accepted / drafts, 3)
        out["acceptance_rate"] = round(
            accepted / max(1, out["spec_decode_num_draft_tokens_total"]), 3)
        pa, pb = per_position(a), per_position(b)
        out["accept_rate_per_pos"] = [
            round((pb[p] - pa.get(p, 0)) / drafts, 4) for p in sorted(pb)]

    for name in GAUGES:
        values = [metric(m, "vllm:" + name) for m in inside]
        if values:
            out[name + "_mean"] = round(sum(values) / len(values), 4)
            out[name + "_max"] = round(max(values), 4)
    return out


def timestamp(text: str | None) -> float | None:
    try:
        return datetime.datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except (ValueError, AttributeError):
        return None


def turns_by_agent(root: Path, t0: float, t1: float) -> dict:
    """Assistant turns and usage tokens per agent from conversation files."""
    agents = {os.path.normpath(root): "PM"}
    for row in read_jsonl(root / "Agent-shared/agent_and_pane_id_table.jsonl"):
        workdir = os.path.normpath(root / (row.get("working_dir") or "."))
        agents.setdefault(workdir, row.get("agent_id"))
    config_dir = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
    result: dict[str, dict] = {}
    for path in (config_dir / "projects").glob("*/*.jsonl"):
        agent, messages = None, {}
        for entry in read_jsonl(path):
            if agent is None and entry.get("cwd"):
                cwd = os.path.normpath(entry["cwd"])
                agent = agents.get(cwd, "other:" + cwd)
            if entry.get("type") != "assistant":
                continue
            t = timestamp(entry.get("timestamp"))
            if t is None or not t0 <= t <= t1:
                continue
            message = entry.get("message") or {}
            # Streaming writes one entry per content block; count each message once.
            messages[message.get("id") or entry.get("uuid")] = (
                message.get("usage") or {}, bool(entry.get("isSidechain")))
        if not messages:
            continue
        acc = result.setdefault(agent or "unknown", {
            "turns": 0, "sidechain_turns": 0, "output_tokens": 0,
            "input_tokens": 0, "cache_read_input_tokens": 0})
        for usage, sidechain in messages.values():
            acc["sidechain_turns" if sidechain else "turns"] += 1
            for k in ("output_tokens", "input_tokens", "cache_read_input_tokens"):
                acc[k] += int(usage.get(k) or 0)
    return dict(sorted(result.items()))


def files_modified(root: Path, t0: float, t1: float) -> int:
    n = 0
    for top in ("Agent-workdir", "User-shared"):
        for dirpath, _, names in os.walk(root / top):
            for name in names:
                try:
                    if t0 <= os.path.getmtime(os.path.join(dirpath, name)) <= t1:
                        n += 1
                except OSError:
                    continue
    return n


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--candidates", default="Agent-workdir/**/candidates*.jsonl",
                   help="glob of the agents' candidate files")
    sub = p.add_subparsers(dest="step", required=True)
    snap = sub.add_parser("snap")
    snap.add_argument("root", type=Path)
    snap.add_argument("out", type=Path)
    final = sub.add_parser("final")
    final.add_argument("root", type=Path)
    final.add_argument("log_dir", type=Path)
    final.add_argument("t_start", type=float)
    final.add_argument("t_end", type=float)
    final.add_argument("--label", default="", help="e.g. the speculative mode")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    root = args.root.resolve()
    if args.step == "snap":
        data = {"t": int(time.time()), **counts(root, args.candidates)}
        args.out.write_text(json.dumps(data, indent=1), encoding="utf-8")
        return

    log_dir = args.log_dir
    before_path = log_dir / "org_before.json"
    before = json.loads(before_path.read_text()) if before_path.exists() else {}
    after = counts(root, args.candidates)
    window = {"t_start": args.t_start, "t_end": args.t_end,
              "minutes": round((args.t_end - args.t_start) / 60, 1)}
    window_path = log_dir / "org_window.json"
    if window_path.exists():
        window.update(json.loads(window_path.read_text()))
    summary = {
        "label": args.label,
        "window": window,
        "before": before,
        "after": after,
        "delta": difference(before, after),
        "files_modified_in_window": files_modified(root, args.t_start, args.t_end),
        "server": server_window(log_dir, args.t_start, args.t_end),
    }
    try:
        summary["turns_by_agent"] = turns_by_agent(root, args.t_start, args.t_end)
    except OSError as exc:
        summary["turns_by_agent"] = {"error": str(exc)}
    (log_dir / "org_summary.json").write_text(
        json.dumps(summary, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary["delta"], ensure_ascii=False))


if __name__ == "__main__":
    main()
