#!/usr/bin/env python3
"""Stateless HPC budget tracker — reads ChangeLog.md files and computes resource consumption.

Self-contained script (no package dependencies). Designed to be run by agents
via ``python3 budget_tracker.py --help``.

Usage examples:
  python3 budget_tracker.py /path/to/project --report
  python3 budget_tracker.py /path/to/project --summary
  python3 budget_tracker.py /path/to/project --visualize -o budget.png
  python3 budget_tracker.py /path/to/project --jobs
"""

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# ── Default configuration ────────────────────────────────────────────────
DEFAULT_RATES: Dict[str, Dict] = {
    "cx-share": {"gpu": 1, "rate": 0.007},
    "cx-interactive": {"gpu": 1, "rate": 0.007},
    "cx-debug": {"gpu": 1, "rate": 0.007},
    "cx-single": {"gpu": 4, "rate": 0.007},
    "cx-small": {"gpu": 4, "rate": 0.007},
    "cx-middle": {"gpu": 4, "rate": 0.007},
    "cx-large": {"gpu": 4, "rate": 0.007},
    "cx-middle2": {"gpu": 4, "rate": 0.014},
    "cxgfs-small": {"gpu": 4, "rate": 0.007},
    "cxgfs-middle": {"gpu": 4, "rate": 0.007},
}

DEFAULT_BUDGET_LIMITS: Dict[str, float] = {
    "Minimum (100pt)": 100,
    "Expected (500pt)": 500,
    "Deadline (1000pt)": 1000,
}


class BudgetTracker:
    """Stateless budget aggregation from ChangeLog.md files."""

    def __init__(self, project_root: Path, config: Optional[Dict] = None):
        self.project_root = Path(project_root)
        cfg = config or {}
        self.rates: Dict[str, Dict] = cfg.get("rates", DEFAULT_RATES)
        self.budget_limits: Dict[str, float] = cfg.get("budget_limits", DEFAULT_BUDGET_LIMITS)
        self.exclude_patterns: List[str] = cfg.get("exclude_patterns", ["Agent-shared", ".git"])
        self._project_start_override: Optional[str] = cfg.get("project_start_time")
        self._snapshot_dir: Optional[Path] = (
            Path(cfg["snapshot_dir"]) if cfg.get("snapshot_dir") else None
        )

    def extract_jobs(self) -> List[Dict]:
        """Extract job info from all ChangeLog.md files under *project_root*."""
        all_jobs: List[Dict] = []
        for changelog in self.project_root.glob("**/ChangeLog.md"):
            if any(pat in str(changelog) for pat in self.exclude_patterns):
                continue
            all_jobs.extend(self.parse_changelog(changelog))
        return all_jobs

    def parse_changelog(self, changelog_path: Path) -> List[Dict]:
        """Parse a single ChangeLog.md and return a list of job dicts."""
        jobs: List[Dict] = []
        try:
            content = changelog_path.read_text(encoding="utf-8")
        except OSError:
            return jobs

        version_pattern = r"### v(\d+\.\d+\.\d+)(.*?)(?=###|\Z)"
        for match in re.finditer(version_pattern, content, re.DOTALL):
            version, section = match.groups()
            job_match = re.search(
                r"- \[.\] \*\*job\*\*(.*?)(?=- \[.\] \*\*|\Z)", section, re.DOTALL
            )
            if not job_match:
                continue

            job_section = job_match.group(1)
            job_info: Dict = {
                "version": version,
                "path": str(changelog_path),
                "job_id": self._extract_field(job_section, "id"),
                "resource_group": self._extract_field(job_section, "resource_group"),
                "start_time": self._extract_field(job_section, "start_time"),
                "end_time": self._extract_field(job_section, "end_time"),
                "cancelled_time": self._extract_field(job_section, "cancelled_time"),
                "runtime_sec": self._extract_field(job_section, "runtime_sec"),
                "status": self._extract_field(job_section, "status"),
            }

            if not (job_info["job_id"] and job_info["resource_group"]):
                continue

            if not job_info["runtime_sec"] and job_info["start_time"] and job_info["end_time"]:
                try:
                    start = datetime.fromisoformat(job_info["start_time"].replace("Z", "+00:00"))
                    end = datetime.fromisoformat(job_info["end_time"].replace("Z", "+00:00"))
                    job_info["runtime_sec"] = str(int((end - start).total_seconds()))
                except (ValueError, TypeError):
                    pass

            jobs.append(job_info)
        return jobs

    def calculate_timeline(
        self, jobs: List[Dict], as_of: Optional[datetime] = None
    ) -> List[Tuple[datetime, float]]:
        """Compute an event-based budget consumption timeline."""
        project_start = self._resolve_project_start()
        events: List[Dict] = []

        for job in jobs:
            if not job.get("start_time"):
                continue
            end_time_str = job.get("end_time") or job.get("cancelled_time")
            if not end_time_str:
                if job.get("status") == "running":
                    end_time_str = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                else:
                    continue
            try:
                start_time = datetime.fromisoformat(job["start_time"].replace("Z", "+00:00"))
                end_time = datetime.fromisoformat(end_time_str.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                continue

            resource_group = job.get("resource_group", "cx-small")
            rate_info = self.rates.get(resource_group, {"gpu": 4, "rate": 0.007})
            points_per_sec = rate_info["rate"] * rate_info["gpu"]
            events.append({"time": start_time, "type": "start", "rate": points_per_sec})
            events.append({"time": end_time, "type": "end", "rate": points_per_sec})

        events.sort(key=lambda x: x["time"])

        timeline: List[Tuple[datetime, float]] = [(project_start, 0.0)]
        current_rate = 0.0
        total_points = 0.0
        last_time = project_start

        for event in events:
            duration = (event["time"] - last_time).total_seconds()
            if duration > 0:
                total_points += current_rate * duration
            timeline.append((event["time"], total_points))
            if event["type"] == "start":
                current_rate += event["rate"]
            else:
                current_rate -= event["rate"]
            last_time = event["time"]

        return timeline

    def generate_report(self, as_of: Optional[datetime] = None) -> Dict:
        """Generate a budget report and optionally save a snapshot."""
        jobs = self.extract_jobs()
        timeline = self.calculate_timeline(jobs, as_of)
        current_total = timeline[-1][1] if timeline else 0

        cutoff_time = as_of or datetime.now(timezone.utc)
        timestamp = cutoff_time.strftime("%Y-%m-%dT%H-%M-%SZ")

        report: Dict = {
            "timestamp": timestamp,
            "total_points": current_total,
            "job_count": len([j for j in jobs if j.get("start_time")]),
            "running_jobs": len([j for j in jobs if j.get("status") == "running"]),
            "timeline_points": len(timeline),
        }

        report_full: Dict = {
            **report,
            "jobs": jobs,
            "timeline": [(t.isoformat(), p) for t, p in timeline],
        }

        snapshot_dir = self._resolve_snapshot_dir()
        if snapshot_dir is not None:
            snapshot_dir.mkdir(parents=True, exist_ok=True)
            with open(snapshot_dir / "latest.json", "w") as f:
                json.dump(report_full, f, indent=2, default=str)

        return report

    def summarise(self, as_of: Optional[datetime] = None) -> Dict:
        """Return a summary dict (total points, job counts, budget percentages, phase)."""
        jobs = self.extract_jobs()
        timeline = self.calculate_timeline(jobs, as_of)
        total = timeline[-1][1] if timeline else 0.0
        running = len([j for j in jobs if j.get("status") == "running"])
        completed = len([j for j in jobs if j.get("status") == "completed"])

        percentages = {
            label: (total / limit * 100) if limit > 0 else 0
            for label, limit in self.budget_limits.items()
        }

        phase = self.determine_phase(total, self.budget_limits)

        return {
            "total_points": total,
            "completed_jobs": completed,
            "running_jobs": running,
            "budget_percentages": percentages,
            "phase": phase,
        }

    @staticmethod
    def determine_phase(total_points: float, budget_limits: Dict[str, float]) -> int:
        """Determine the current project phase (0-5) based on budget consumption.

        Phase boundaries (from SKILL.md):
          0: 0 — minimum
          1: minimum — 50% of target
          2: 50-80% of target
          3: 80-100% of target
          4: target — 90% of deadline
          5: 90-100% of deadline
        """
        # Extract limits by key prefix to stay independent of exact label wording
        minimum = 0.0
        target = 0.0
        deadline = 0.0
        for label, value in budget_limits.items():
            lower = label.lower()
            if "minimum" in lower:
                minimum = value
            elif "expected" in lower or "target" in lower:
                target = value
            elif "deadline" in lower:
                deadline = value

        if total_points < minimum:
            return 0
        if total_points < target * 0.5:
            return 1
        if total_points < target * 0.8:
            return 2
        if total_points < target:
            return 3
        if total_points < deadline * 0.9:
            return 4
        return 5

    def visualize_budget(
        self, output_path: Optional[Path] = None, as_of: Optional[datetime] = None
    ) -> Optional[Path]:
        """Generate a budget usage timeline graph (requires matplotlib + scipy)."""
        try:
            import matplotlib.pyplot as plt
            import matplotlib.dates as mdates
            from matplotlib import rcParams
            import numpy as np
            from scipy import stats
        except ImportError as e:
            print(f"Error: visualization requires matplotlib and scipy: {e}", file=sys.stderr)
            return None

        try:
            rcParams["font.sans-serif"] = ["DejaVu Sans", "Helvetica", "Arial", "sans-serif"]
        except Exception:
            pass

        jobs = self.extract_jobs()
        timeline = self.calculate_timeline(jobs, as_of)
        if not timeline:
            print("No timeline data to visualize.", file=sys.stderr)
            return None

        times = [t[0] for t in timeline]
        points = [t[1] for t in timeline]

        fig, ax = plt.subplots(figsize=(14, 7))
        fig.set_facecolor("white")
        ax.set_facecolor("white")
        ax.plot(times, points, linewidth=2, color="blue", label="Budget Usage",
                marker="o", markersize=4)
        ax.fill_between(times, points, alpha=0.3, color="blue")

        running_jobs = [j for j in jobs if j.get("status") == "running"]

        if len(times) >= 2:
            times_numeric = [(t - times[0]).total_seconds() for t in times]
            recent_start = max(0, int(len(times) * 0.7))
            recent_times = times_numeric[recent_start:]
            recent_points = points[recent_start:]

            if len(recent_times) >= 2:
                slope, intercept, _r, _p, _se = stats.linregress(recent_times, recent_points)
                last_time = times[-1]
                future_time = last_time + timedelta(hours=1)
                pred_times_numeric = [
                    (last_time - times[0]).total_seconds(),
                    (future_time - times[0]).total_seconds(),
                ]
                pred_points = [slope * t + intercept for t in pred_times_numeric]
                ax.plot([last_time, future_time], pred_points, "--", linewidth=2,
                        color="purple", label=f"Prediction ({slope * 3600:.1f} pt/hr)", alpha=0.7)

        colors_list = ["green", "orange", "red"]
        for (label, limit), color in zip(self.budget_limits.items(), colors_list):
            ax.axhline(y=limit, color=color, linestyle="--", alpha=0.7, label=label)

        ax.set_xlabel("Time (UTC)")
        ax.set_ylabel("Points")
        ax.set_title("HPC Budget Usage Timeline")
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d %H:%M"))
        ax.xaxis.set_major_locator(mdates.AutoDateLocator())
        fig.autofmt_xdate()
        ax.grid(True, alpha=0.3)
        ax.legend(loc="upper left")
        ax.set_ylim(bottom=0)

        if output_path is None:
            output_path = self.project_root / "budget_usage.png"
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        plt.tight_layout()
        plt.savefig(output_path, dpi=100, bbox_inches="tight")
        plt.close()
        return output_path

    @staticmethod
    def _extract_field(text: str, field: str) -> Optional[str]:
        pattern = rf"- {field}:\s*`([^`]*)`"
        match = re.search(pattern, text)
        return match.group(1) if match else None

    def _resolve_project_start(self) -> datetime:
        if self._project_start_override:
            try:
                return datetime.fromisoformat(
                    self._project_start_override.replace("Z", "+00:00")
                )
            except (ValueError, TypeError):
                pass
        start_file = self.project_root / "Agent-shared" / "project_start_time.txt"
        if start_file.exists():
            try:
                return datetime.fromisoformat(
                    start_file.read_text().strip().replace("Z", "+00:00")
                )
            except (ValueError, TypeError):
                pass
        return datetime.now(timezone.utc) - timedelta(hours=1)

    def _resolve_snapshot_dir(self) -> Optional[Path]:
        if self._snapshot_dir is not None:
            return self._snapshot_dir
        return self.project_root / "Agent-shared" / "budget" / "snapshots"


def main():
    parser = argparse.ArgumentParser(
        description="HPC Budget Tracker — compute resource consumption from ChangeLog.md files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
examples:
  %(prog)s /path/to/project --summary
  %(prog)s /path/to/project --report --json
  %(prog)s /path/to/project --jobs
  %(prog)s /path/to/project --visualize -o budget.png
  %(prog)s /path/to/project --config rates.json --summary
""",
    )
    parser.add_argument("project_root", help="Project root directory containing ChangeLog.md files")
    parser.add_argument("--summary", action="store_true", help="Print budget summary (points, jobs, percentages)")
    parser.add_argument("--report", action="store_true", help="Generate full budget report")
    parser.add_argument("--jobs", action="store_true", help="List all extracted jobs")
    parser.add_argument("--visualize", action="store_true", help="Generate budget timeline graph (requires matplotlib+scipy)")
    parser.add_argument("-o", "--output", help="Output file path for --visualize or --report")
    parser.add_argument("--json", action="store_true", help="Output in JSON format")
    parser.add_argument("--config", help="JSON config file with rates/budget_limits overrides")
    parser.add_argument("--exclude", nargs="*", default=["Agent-shared", ".git"],
                        help="Path patterns to exclude (default: Agent-shared .git)")

    args = parser.parse_args()

    config = {}
    if args.config:
        with open(args.config) as f:
            config = json.load(f)
    config["exclude_patterns"] = args.exclude

    tracker = BudgetTracker(Path(args.project_root), config)

    if args.visualize:
        out = tracker.visualize_budget(Path(args.output) if args.output else None)
        if out:
            print(f"Graph saved: {out}")
        else:
            print("Visualization failed (missing matplotlib/scipy or no data).", file=sys.stderr)
            sys.exit(1)
    elif args.jobs:
        jobs = tracker.extract_jobs()
        if args.json:
            print(json.dumps(jobs, indent=2, default=str))
        else:
            print(f"Found {len(jobs)} jobs:")
            for j in jobs:
                status = j.get("status", "?")
                rg = j.get("resource_group", "?")
                print(f"  {j['version']} | {j['job_id']} | {rg} | {status}")
    elif args.report:
        report = tracker.generate_report()
        if args.json:
            print(json.dumps(report, indent=2, default=str))
        else:
            print(f"Budget Report ({report['timestamp']}):")
            print(f"  Total points: {report['total_points']:.2f}")
            print(f"  Jobs: {report['job_count']} (running: {report['running_jobs']})")
    else:
        # Default: summary
        summary = tracker.summarise()
        if args.json:
            print(json.dumps(summary, indent=2, default=str))
        else:
            print(f"Budget Summary:")
            print(f"  Total points: {summary['total_points']:.2f}")
            print(f"  Completed jobs: {summary['completed_jobs']}")
            print(f"  Running jobs: {summary['running_jobs']}")
            print(f"  Phase: {summary['phase']}")
            print(f"  Budget usage:")
            for label, pct in summary["budget_percentages"].items():
                print(f"    {label}: {pct:.1f}%")


if __name__ == "__main__":
    main()
