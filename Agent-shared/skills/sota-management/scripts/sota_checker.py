#!/usr/bin/env python3
"""Multi-level SOTA (State-Of-The-Art) performance checker and updater.

Self-contained script (no package dependencies). Designed to be run by agents
via ``python3 sota_checker.py --help``.

Usage examples:
  python3 sota_checker.py /path/to/agent/dir check "350.0 GFLOPS"
  python3 sota_checker.py /path/to/agent/dir update "350.0 GFLOPS" --version 1.2.0 --agent PG1.1
  python3 sota_checker.py /path/to/agent/dir info
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, Optional


class SOTAChecker:
    """Hierarchical SOTA checker / updater (4 levels: local/family/hardware/project)."""

    def __init__(self, current_dir, config: Optional[Dict] = None):
        self.current_dir = Path(current_dir).resolve()
        self.performance: Optional[float] = None

        cfg = config or {}
        self._explicit_project_root: Optional[Path] = (
            Path(cfg["project_root"]) if cfg.get("project_root") else None
        )
        self._project_root_marker: str = cfg.get("project_root_marker", "VibeCodeHPC")
        self._hardware_marker: str = cfg.get("hardware_marker", "hardware_info.md")
        self._unit: str = cfg.get("unit", "GFLOPS")

    def check_sota_levels(self, performance_metric: str) -> Dict[str, bool]:
        """Check all four hierarchy levels. Returns {level: is_new_sota}."""
        self.performance = float(performance_metric.split()[0])
        return {
            "local": self.check_local_sota(),
            "family": self.check_family_sota(),
            "hardware": self.check_hardware_sota(),
            "project": self.check_project_sota(),
        }

    def check_local_sota(self) -> bool:
        sota_file = self.current_dir / "sota_local.txt"
        if not sota_file.exists():
            return True
        return self.performance > self._read_best(sota_file)

    def check_family_sota(self) -> bool:
        visible_file = self.current_dir / "PG_visible_dir.md"
        if not visible_file.exists():
            return False
        paths = self._parse_virtual_parent_paths(visible_file)
        max_family_perf = 0.0
        for path in paths:
            full_path = self.current_dir / path
            if full_path.exists():
                for sf in full_path.glob("*/sota_local.txt"):
                    max_family_perf = max(max_family_perf, self._read_best(sf))
        return self.performance > max_family_perf

    def check_hardware_sota(self) -> bool:
        hw_dir = self.find_hardware_info_dir()
        if not hw_dir:
            return False
        sota_file = hw_dir / "sota_hardware.txt"
        if not sota_file.exists():
            return True
        return self.performance > self._read_best(sota_file)

    def check_project_sota(self) -> bool:
        root = self.find_project_root()
        if not root:
            return False
        sota_file = root / "sota_project.txt"
        if not sota_file.exists():
            return True
        return self.performance > self._read_best(sota_file)

    def update_sota_files(self, version: str, timestamp: str, agent_id: str) -> Dict[str, bool]:
        """Check all levels and update the corresponding SOTA files."""
        sota_info = {
            "local": self.check_local_sota(),
            "family": self.check_family_sota(),
            "hardware": self.check_hardware_sota(),
            "project": self.check_project_sota(),
        }
        if sota_info["local"]:
            self._write_sota(self.current_dir / "sota_local.txt", version, timestamp, agent_id)
        if sota_info["hardware"]:
            hw_dir = self.find_hardware_info_dir()
            if hw_dir:
                self._write_sota(hw_dir / "sota_hardware.txt", version, timestamp, agent_id, extended=True)
        if sota_info["project"]:
            root = self.find_project_root()
            if root:
                self._write_sota(root / "sota_project.txt", version, timestamp, agent_id, extended=True)
                history_file = root / "history" / "sota_project_history.txt"
                history_file.parent.mkdir(exist_ok=True)
                with open(history_file, "a") as f:
                    f.write(
                        f"[{timestamp}] {self.performance} {self._unit}"
                        f" by {agent_id} ({self.get_strategy()})\n"
                    )
        return sota_info

    def find_hardware_info_dir(self) -> Optional[Path]:
        current = self.current_dir
        while current != current.parent:
            if (current / self._hardware_marker).exists():
                return current
            current = current.parent
        return None

    def find_project_root(self) -> Optional[Path]:
        if self._explicit_project_root is not None:
            return self._explicit_project_root
        current = self.current_dir
        while current != current.parent:
            if current.name.startswith(self._project_root_marker):
                return current
            current = current.parent
        return None

    def get_hardware_path(self) -> str:
        root = self.find_project_root()
        if root:
            try:
                return str(self.current_dir.relative_to(root).parent)
            except ValueError:
                pass
        return "unknown"

    def get_strategy(self) -> str:
        parts = self.current_dir.parts
        return parts[-2] if len(parts) >= 2 else "unknown"

    @staticmethod
    def _read_best(sota_file: Path) -> float:
        try:
            with open(sota_file, "r") as f:
                return float(f.readline().split('"')[1].split()[0])
        except (ValueError, IndexError, OSError):
            return 0.0

    @staticmethod
    def _parse_virtual_parent_paths(md_file: Path):
        with open(md_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
        in_section = False
        paths = []
        for line in lines:
            stripped = line.strip()
            if "### Virtual parent" in stripped:
                in_section = True
                continue
            if stripped.startswith("###") and in_section:
                break
            if in_section and stripped.startswith("../") and "\U0001f4c1" in stripped:
                paths.append(stripped.split("\U0001f4c1")[0])
        return paths

    def _write_sota(self, path: Path, version: str, timestamp: str, agent_id: str, extended: bool = False):
        with open(path, "w") as f:
            f.write(f'current_best: "{self.performance} {self._unit}"\n')
            f.write(f'achieved_by: "{version if not extended else agent_id}"\n')
            f.write(f'timestamp: "{timestamp}"\n')
            if extended:
                f.write(f'hardware_path: "{self.get_hardware_path()}"\n')
                f.write(f'strategy: "{self.get_strategy()}"\n')
            if not extended:
                f.write(f'agent_id: "{agent_id}"\n')


def get_virtual_family_sota(current_dir):
    """Standalone function: compute the virtual family SOTA from PG_visible_dir.md."""
    current_path = Path(current_dir)
    visible_file = current_path / "PG_visible_dir.md"
    if not visible_file.exists():
        return 0.0, None
    paths = SOTAChecker._parse_virtual_parent_paths(visible_file)
    family_sota = 0.0
    best_info = None
    for path in paths:
        full_path = current_path / path
        if full_path.exists():
            for sota_file in full_path.glob("*/sota_local.txt"):
                try:
                    with open(sota_file, "r") as f:
                        perf = float(f.readline().split('"')[1].split()[0])
                        if perf > family_sota:
                            family_sota = perf
                            best_info = str(sota_file)
                except (ValueError, IndexError, OSError):
                    continue
    return family_sota, best_info


def main():
    parser = argparse.ArgumentParser(
        description="Multi-level SOTA checker — check/update performance records at 4 hierarchy levels.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
levels:
  local     PG directory best (sota_local.txt)
  family    Same middleware family (via PG_visible_dir.md)
  hardware  Same hardware config (sota_hardware.txt)
  project   Project-wide best (sota_project.txt)

examples:
  %(prog)s /path/to/PG1.1 check "350.0 GFLOPS"
  %(prog)s /path/to/PG1.1 update "350.0 GFLOPS" --version 1.2.0 --agent PG1.1
  %(prog)s /path/to/PG1.1 info
  %(prog)s /path/to/PG1.1 check "350.0 GFLOPS" --json
""",
    )
    parser.add_argument("current_dir", help="Agent's working directory (PG directory)")
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # check
    check_p = subparsers.add_parser("check", help="Check if performance is SOTA at each level")
    check_p.add_argument("performance", help='Performance metric (e.g. "350.0 GFLOPS")')
    check_p.add_argument("--json", action="store_true", help="Output in JSON format")
    check_p.add_argument("--unit", default="GFLOPS", help="Performance unit (default: GFLOPS)")
    check_p.add_argument("--project-root", help="Explicit project root path")

    # update
    update_p = subparsers.add_parser("update", help="Check and update SOTA files")
    update_p.add_argument("performance", help='Performance metric (e.g. "350.0 GFLOPS")')
    update_p.add_argument("--version", required=True, help="Version string (e.g. 1.2.0)")
    update_p.add_argument("--agent", required=True, help="Agent ID (e.g. PG1.1)")
    update_p.add_argument("--timestamp", help="ISO-8601 timestamp (default: now UTC)")
    update_p.add_argument("--json", action="store_true", help="Output in JSON format")
    update_p.add_argument("--unit", default="GFLOPS", help="Performance unit (default: GFLOPS)")
    update_p.add_argument("--project-root", help="Explicit project root path")

    # info
    info_p = subparsers.add_parser("info", help="Show current SOTA values at each level")
    info_p.add_argument("--json", action="store_true", help="Output in JSON format")
    info_p.add_argument("--project-root", help="Explicit project root path")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    config = {}
    if hasattr(args, "unit"):
        config["unit"] = args.unit
    if hasattr(args, "project_root") and args.project_root:
        config["project_root"] = args.project_root

    checker = SOTAChecker(args.current_dir, config)

    if args.command == "check":
        results = checker.check_sota_levels(args.performance)
        if args.json:
            print(json.dumps(results, indent=2))
        else:
            perf = float(args.performance.split()[0])
            print(f"SOTA Check: {perf} {config.get('unit', 'GFLOPS')}")
            for level, is_new in results.items():
                marker = "NEW SOTA" if is_new else "not beaten"
                print(f"  {level:10s}: {marker}")

    elif args.command == "update":
        from datetime import datetime, timezone
        checker.performance = float(args.performance.split()[0])
        ts = args.timestamp or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        results = checker.update_sota_files(args.version, ts, args.agent)
        if args.json:
            print(json.dumps(results, indent=2))
        else:
            print(f"SOTA Update: {checker.performance} {config.get('unit', 'GFLOPS')}")
            for level, updated in results.items():
                marker = "UPDATED" if updated else "unchanged"
                print(f"  {level:10s}: {marker}")

    elif args.command == "info":
        info = {}
        # Local
        local_file = Path(args.current_dir).resolve() / "sota_local.txt"
        info["local"] = checker._read_best(local_file) if local_file.exists() else None
        # Hardware
        hw_dir = checker.find_hardware_info_dir()
        if hw_dir:
            hw_file = hw_dir / "sota_hardware.txt"
            info["hardware"] = checker._read_best(hw_file) if hw_file.exists() else None
        else:
            info["hardware"] = None
        # Project
        root = checker.find_project_root()
        if root:
            proj_file = root / "sota_project.txt"
            info["project"] = checker._read_best(proj_file) if proj_file.exists() else None
        else:
            info["project"] = None

        if args.json:
            print(json.dumps(info, indent=2))
        else:
            print(f"Current SOTA values:")
            for level, val in info.items():
                print(f"  {level:10s}: {val if val is not None else 'not set'}")


if __name__ == "__main__":
    main()
