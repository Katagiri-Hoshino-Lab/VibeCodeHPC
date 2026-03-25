#!/usr/bin/env python3
"""
SOTA Visualizer - Self-contained Pipeline Edition

Ported from VibeCodeHPC-jp/Agent-shared/sota/sota_visualizer.py.
Designed to run standalone without external project dependencies.

Features:
- Memory-efficient pipeline processing
- Minimal storage IO
- SE-friendly customizable design
- Multi-project integration support
"""

import json
import argparse
import sys
import time
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple, Any

try:
    import matplotlib.pyplot as plt
    import matplotlib.ticker as ticker
    import matplotlib.dates as mdates
    import numpy as np
except ImportError:
    print("ERROR: matplotlib and numpy are required.")
    print("  pip install matplotlib numpy")
    sys.exit(1)


class SOTAVisualizer:
    """Efficient SOTA visualization pipeline."""

    def __init__(self, project_root: Path, config: Optional[Dict] = None):
        """
        Args:
            project_root: Project root path.
            config: Config dict (None = load from file or use defaults).
        """
        self.project_root = Path(project_root)
        self.config = config or self._load_config()

        # Data caches (memory efficiency)
        self.data_cache: Dict[str, Any] = {}
        self.changelog_cache: Dict[str, List[Dict]] = {}

        # Output directories
        self.output_base = self.project_root / "User-shared/visualizations/sota"
        self.output_dirs = {
            'project': self.output_base / 'project',
            'hardware': self.output_base / 'hardware',
            'family': self.output_base / 'family',
            'local': self.output_base / 'local',
        }

        # Project start time
        self.project_start_time = self._get_project_start_time()

        # Theoretical performance (read from hardware_info.md)
        self.theoretical_performance: Optional[float] = None

    def _load_config(self) -> Dict:
        """Load configuration file."""
        config_path = self.project_root / "Agent-shared/sota_pipeline_config.json"

        if config_path.exists():
            try:
                with open(config_path) as f:
                    return json.load(f)
            except Exception as e:
                print(f"Config load error: {e}, using defaults")

        # Default configuration
        return {
            "pipeline": {
                "levels": ["local", "family", "hardware", "project"],
                "critical_section": True,
                "max_local_agents": 10,
                "io_delay_ms": 500,
            },
            "dpi": {
                "local": {"linear": 60, "log": 40},
                "family": {"linear": 70, "log": 45},
                "hardware": {"linear": 80, "log": 50},
                "project": {"linear": 100, "log": 60},
                "debug": 30,
            },
            "axes": {
                "x_options": ["time", "count", "version"],
                "y_options": ["performance", "accuracy", "efficiency"],
                "show_error_bars": True,
                "accuracy_threshold": None,
            },
            "io_optimization": {
                "compress_level": 1,
                "buffer_writes": True,
                "cleanup_old_hours": 2,
            },
        }

    def _get_project_start_time(self) -> datetime:
        """Get project start time."""
        start_file = self.project_root / "Agent-shared/project_start_time.txt"

        if start_file.exists():
            try:
                content = start_file.read_text().strip()
                return datetime.fromisoformat(content.replace('Z', '+00:00'))
            except Exception:
                pass

        # Default: current time
        now = datetime.now(timezone.utc)
        start_file.parent.mkdir(parents=True, exist_ok=True)
        start_file.write_text(now.isoformat())
        return now

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def run(self, mode: str = 'pipeline', **params) -> bool:
        """
        Main entry point.

        Args:
            mode: Execution mode ('pipeline', 'single', 'debug', 'summary', 'export').
            **params: Additional parameters.

        Returns:
            True on success.
        """
        if mode == 'summary':
            return self._run_summary_mode(**params)
        elif mode == 'export':
            return self._run_export_mode(**params)
        elif mode == 'debug':
            params['debug'] = True
            return self._run_pipeline_mode(**params)
        elif mode == 'single':
            return self._run_single_mode(**params)
        else:
            return self._run_pipeline_mode(**params)

    # ------------------------------------------------------------------
    # Pipeline mode
    # ------------------------------------------------------------------

    def _run_pipeline_mode(self, **params) -> bool:
        """Pipeline mode (periodic execution / SE control)."""
        lock_file = self.project_root / "Agent-shared/.sota_pipeline.lock"

        if self.config['pipeline']['critical_section'] and not params.get('force'):
            if lock_file.exists():
                age = (datetime.now() - datetime.fromtimestamp(lock_file.stat().st_mtime)).seconds
                if age < 1800:  # 30 min
                    print(f"Pipeline locked ({age}s ago), skipping")
                    return False
                lock_file.unlink()

        lock_file.touch()
        start_time = datetime.now()

        try:
            print(f"[{start_time.strftime('%H:%M:%S')}] Pipeline started")

            # 1. Data collection (read all ChangeLog.md once)
            self._collect_all_data()

            # 2. DPI config
            dpi_config = self._get_dpi_config(params)

            # 3. Execution levels
            levels = params.get('levels', self.config['pipeline']['levels'])

            generated_files: List[Path] = []

            for level in levels:
                level_start = datetime.now()

                if level == 'local':
                    files = self._process_local_level(dpi_config['local'], params)
                elif level == 'family':
                    files = self._process_family_level(dpi_config['family'], params)
                elif level == 'hardware':
                    files = self._process_hardware_level(dpi_config['hardware'], params)
                elif level == 'project':
                    files = self._process_project_level(dpi_config['project'], params)
                else:
                    continue

                generated_files.extend(files)
                elapsed = (datetime.now() - level_start).seconds
                print(f"  {level}: {len(files)} graphs in {elapsed}s")

                # IO throttle
                if not params.get('no_delay'):
                    time.sleep(self.config['io_optimization'].get('io_delay_ms', 500) / 1000)

            total_elapsed = (datetime.now() - start_time).seconds
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Completed: {len(generated_files)} files in {total_elapsed}s")

            # Cleanup old files
            if self.config['io_optimization'].get('cleanup_old_hours'):
                self._cleanup_old_files()

            return True

        except Exception as e:
            print(f"Pipeline error: {e}")
            import traceback
            traceback.print_exc()
            return False

        finally:
            lock_file.unlink(missing_ok=True)

    # ------------------------------------------------------------------
    # Data collection & parsing
    # ------------------------------------------------------------------

    def _collect_all_data(self):
        """Collect all ChangeLog.md efficiently."""
        self.changelog_cache = {}

        for changelog in self.project_root.rglob("ChangeLog.md"):
            rel_path = changelog.parent.relative_to(self.project_root)
            entries = self._parse_changelog(changelog)
            if entries:
                self.changelog_cache[str(rel_path)] = entries

        print(f"  Collected: {len(self.changelog_cache)} ChangeLogs, "
              f"{sum(len(e) for e in self.changelog_cache.values())} entries")

    def _parse_changelog(self, path: Path) -> List[Dict]:
        """Parse ChangeLog.md (efficiency-oriented)."""
        import re
        entries: List[Dict] = []

        try:
            content = path.read_text(encoding='utf-8')
            lines = content.split('\n')

            current_entry: Dict[str, Any] = {}

            for line in lines:
                # Version line
                if line.startswith('### v'):
                    if current_entry and 'performance' in current_entry:
                        entries.append(current_entry.copy())
                    current_entry = {'version': line.replace('### ', '').strip()}

                # Performance extraction (multiple formats)
                elif 'GFLOPS' in line or 'TFLOPS' in line:
                    match = re.search(r'([\d.]+)\s*(GFLOPS|TFLOPS)', line)
                    if match:
                        value = float(match.group(1))
                        if match.group(2) == 'TFLOPS':
                            value *= 1000
                        current_entry['performance'] = value

                # Timestamp (backtick-delimited)
                elif 'generated_at' in line or '生成時刻' in line:
                    match = re.search(r'`(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)`', line)
                    if match:
                        time_str = match.group(1)
                        try:
                            timestamp = datetime.fromisoformat(time_str.replace('Z', '+00:00'))
                            current_entry['timestamp'] = timestamp
                            elapsed = (timestamp - self.project_start_time).total_seconds()
                            current_entry['elapsed_seconds'] = elapsed
                        except Exception:
                            pass

                # Accuracy (optional)
                elif 'accuracy' in line.lower():
                    match = re.search(r'([\d.]+)\s*%', line)
                    if match:
                        current_entry['accuracy'] = float(match.group(1))

                # Error (scientific notation supported)
                elif 'error' in line.lower():
                    match = re.search(r'([±]?\s*[\d.]+e?[+-]?\d*)', line)
                    if match:
                        error_str = match.group(1).replace('±', '').strip()
                        try:
                            current_entry['error'] = float(error_str)
                        except Exception:
                            pass

            # Last entry
            if current_entry and 'performance' in current_entry:
                entries.append(current_entry)

        except Exception as e:
            print(f"  Parse error {path}: {e}")

        return entries

    # ------------------------------------------------------------------
    # Level processors
    # ------------------------------------------------------------------

    def _process_local_level(self, dpi_config: Dict, params: Dict) -> List[Path]:
        """Local level (per PG)."""
        generated: List[Path] = []

        specific_dpis = self._parse_specific_dpis(params.get('specific', ''))

        local_dirs: Dict[str, List[Dict]] = {}
        for path, entries in self.changelog_cache.items():
            if entries:
                path_parts = path.split('/')
                if len(path_parts) >= 2:
                    dir_id = '/'.join(path_parts[-2:])
                else:
                    dir_id = path_parts[-1] if path_parts else path
                local_dirs[dir_id] = entries

        max_agents = params.get('max_local', self.config['pipeline']['max_local_agents'])

        for _i, (dir_id, entries) in enumerate(list(local_dirs.items())[:max_agents]):
            dpi = specific_dpis.get(dir_id, dpi_config['linear'])
            sota_entries = self._extract_sota_progression(entries)

            if sota_entries:
                for x_axis in params.get('x_axes', ['time']):
                    output_path = self._generate_graph(
                        f'local/{dir_id.replace("/", "_")}',
                        sota_entries,
                        f"SOTA: {dir_id}",
                        x_axis,
                        dpi,
                        params,
                    )
                    if output_path:
                        generated.append(output_path)

        return generated

    def _process_hardware_level(self, dpi_config: Dict, params: Dict) -> List[Path]:
        """Hardware level (aggregated from local)."""
        generated: List[Path] = []

        hardware_groups: Dict[str, List[Dict]] = {}
        hardware_merged: Dict[str, List[Dict]] = {}

        for path, entries in self.changelog_cache.items():
            hw_key = self._extract_hardware_key(path)
            if hw_key:
                if hw_key not in hardware_groups:
                    hardware_groups[hw_key] = []
                hardware_groups[hw_key].extend(entries)

                hw_base = hw_key.split('/')[0]
                if hw_base not in hardware_merged:
                    hardware_merged[hw_base] = []
                hardware_merged[hw_base].extend(entries)

        for hw_key, all_entries in hardware_groups.items():
            sota_entries = self._aggregate_sota_by_time(all_entries)
            if sota_entries:
                for x_axis in params.get('x_axes', ['time']):
                    output_path = self._generate_graph(
                        f'hardware/{hw_key.replace("/", "_")}',
                        sota_entries,
                        f"SOTA: {hw_key}",
                        x_axis,
                        dpi_config['linear'],
                        params,
                    )
                    if output_path:
                        generated.append(output_path)

        for hw_base, all_entries in hardware_merged.items():
            sota_entries = self._aggregate_sota_by_time(all_entries)
            if sota_entries:
                for x_axis in params.get('x_axes', ['time']):
                    output_path = self._generate_graph(
                        f'hardware/{hw_base}_all',
                        sota_entries,
                        f"SOTA: {hw_base} (All Compilers)",
                        x_axis,
                        dpi_config['linear'],
                        params,
                    )
                    if output_path:
                        generated.append(output_path)

        return generated

    def _process_project_level(self, dpi_config: Dict, params: Dict) -> List[Path]:
        """Project level (overall aggregation)."""
        generated: List[Path] = []

        all_entries: List[Dict] = []
        for entries in self.changelog_cache.values():
            all_entries.extend(entries)

        sota_entries = self._aggregate_sota_by_time(all_entries)

        if sota_entries:
            for x_axis in params.get('x_axes', ['time', 'count']):
                for log_scale in [False, True]:
                    dpi = dpi_config['log' if log_scale else 'linear']
                    output_path = self._generate_graph(
                        f'project/sota_project_{x_axis}{"_log" if log_scale else ""}',
                        sota_entries,
                        "SOTA: Project Overall",
                        x_axis,
                        dpi,
                        params,
                        log_scale=log_scale,
                    )
                    if output_path:
                        generated.append(output_path)

        return generated

    def _process_family_level(self, dpi_config: Dict, params: Dict) -> List[Path]:
        """Family level (2nd-gen fusion technologies and their parents)."""
        generated: List[Path] = []

        family_found: set = set()
        for path in self.changelog_cache.keys():
            if '_' in path:
                parts = path.split('/')
                for part in parts:
                    if '_' in part and any(tech in part for tech in ['OpenMP', 'MPI', 'CUDA', 'AVX']):
                        family_found.add(part)
                        break

        for family_key in family_found:
            parent_techs = family_key.split('_')
            multi_series_data: Dict[str, List[Dict]] = {}

            # Family's own data
            for path, entries in self.changelog_cache.items():
                if family_key in path:
                    path_parts = path.split('/')
                    if len(path_parts) >= 2:
                        series_key = '/'.join(path_parts[-2:])
                    else:
                        series_key = path_parts[-1] if path_parts else path
                    multi_series_data[series_key] = entries

            # Parent technology data
            for parent_tech in parent_techs:
                for path, entries in self.changelog_cache.items():
                    path_parts = path.split('/')
                    for part in path_parts:
                        if part == parent_tech:
                            if len(path_parts) >= 2:
                                series_key = '/'.join(path_parts[-2:])
                            else:
                                series_key = path_parts[-1] if path_parts else path
                            if series_key not in multi_series_data:
                                multi_series_data[series_key] = entries
                            break

            if multi_series_data:
                output_path = self._generate_multi_series_graph(
                    f'family/{family_key}',
                    multi_series_data,
                    f"Family: {family_key}",
                    'time',
                    dpi_config['linear'],
                    params,
                )
                if output_path:
                    generated.append(output_path)

        return generated

    # ------------------------------------------------------------------
    # Graph generation
    # ------------------------------------------------------------------

    def _generate_graph(self, name: str, entries: List[Dict], title: str,
                        x_axis: str, dpi: int, params: Dict, log_scale: bool = False) -> Optional[Path]:
        """Generate graph (IO-optimized)."""
        if not entries:
            return None

        try:
            fig, ax = plt.subplots(figsize=(10, 6))

            # Data preparation
            if x_axis == 'time':
                missing_time = [e.get('version', f'unknown_{i}') for i, e in enumerate(entries) if 'elapsed_seconds' not in e]
                if missing_time:
                    print(f"  Warning: Missing timestamps in ChangeLog: {', '.join(missing_time)}")
                    print(f"     Excluding {len(missing_time)} entries from graph")
                    entries = [e for e in entries if 'elapsed_seconds' in e]

                if not entries:
                    print(f"  Error: No time info available. Skipping this graph")
                    return None

                entries = sorted(entries, key=lambda e: e['elapsed_seconds'])
                x_data = [e['elapsed_seconds'] / 60 for e in entries]
                x_label = 'Time (minutes from start)'

                max_time = max(e['elapsed_seconds'] for e in entries)
                if max_time < 7200:
                    x_label = 'Time (minutes from start)'
                    x_formatter = lambda x, pos: f'{x:.0f}m'
                elif max_time < 86400:
                    x_data = [e['elapsed_seconds'] / 3600 for e in entries]
                    x_label = 'Time (hours from start)'
                    x_formatter = lambda x, pos: f'{x:.1f}h'
                else:
                    x_data = [e['elapsed_seconds'] / 86400 for e in entries]
                    x_label = 'Time (days from start)'
                    x_formatter = lambda x, pos: f'{x:.1f}d'

                ax.xaxis.set_major_formatter(plt.FuncFormatter(x_formatter))

            elif x_axis == 'count':
                x_data = list(range(1, len(entries) + 1))
                x_label = 'Generation Count'

            elif x_axis == 'version':
                x_data = list(range(len(entries)))
                x_label = 'Version'
                ax.set_xticks(x_data)
                ax.set_xticklabels(
                    [e.get('version', f'v{i}') for i, e in enumerate(entries)],
                    rotation=45,
                )
            else:
                x_data = list(range(len(entries)))
                x_label = x_axis.capitalize()

            y_data = [e['performance'] for e in entries]

            # Accuracy filtering
            if params.get('accuracy_threshold'):
                filtered = [(x, y, e) for x, y, e in zip(x_data, y_data, entries)
                            if e.get('accuracy', 100) >= params['accuracy_threshold']]
                if filtered:
                    x_data, y_data, entries = zip(*filtered)

            # Plot (step, blue)
            ax.step(x_data, y_data, 'b-', where='post', linewidth=2, label='SOTA', alpha=0.8)
            ax.plot(x_data, y_data, 'bo', markersize=6, alpha=0.8)

            # Error bars
            if self.config['axes']['show_error_bars'] and any('error' in e for e in entries):
                yerr = [e.get('error', 0) for e in entries]
                ax.errorbar(x_data, y_data, yerr=yerr, fmt='none', ecolor='gray', alpha=0.5)

            # Theoretical performance line
            if self.theoretical_performance and not params.get('no_theoretical'):
                ax.axhline(y=self.theoretical_performance, color='gray',
                           linestyle='--', alpha=0.5, label='Theoretical')

            # Tick limit (MAXTICKS prevention)
            ax.xaxis.set_major_locator(ticker.MaxNLocator(nbins=15))

            # Scale
            if log_scale:
                ax.set_yscale('log')

            ax.set_xlabel(x_label)
            ax.set_ylabel('Performance (GFLOPS)')
            ax.set_title(title)
            ax.grid(True, alpha=0.3)
            ax.legend()

            # Output path
            output_dir = self.output_base / name.rsplit('/', 1)[0]
            output_dir.mkdir(parents=True, exist_ok=True)
            output_path = output_dir / f"{name.rsplit('/', 1)[-1]}.png"

            # Save (minimal compression)
            try:
                plt.savefig(output_path, dpi=dpi, bbox_inches='tight',
                            compress_level=self.config['io_optimization']['compress_level'])
            except TypeError:
                plt.savefig(output_path, dpi=dpi, bbox_inches='tight')
            plt.close()

            return output_path

        except Exception as e:
            print(f"  Graph error {name}: {e}")
            plt.close()
            return None

    def _generate_multi_series_graph(self, name: str, multi_series_data: Dict[str, List[Dict]],
                                     title: str, x_axis: str, dpi: int, params: Dict) -> Optional[Path]:
        """Generate multi-series graph (for family level)."""
        if not multi_series_data:
            return None

        try:
            fig, ax = plt.subplots(figsize=(12, 8))
            colors = plt.cm.tab10(np.linspace(0, 1, 10))

            for idx, (series_key, entries) in enumerate(multi_series_data.items()):
                sota_entries = self._extract_sota_progression(entries)
                if not sota_entries:
                    continue

                valid_entries = [e for e in sota_entries if 'elapsed_seconds' in e]
                if not valid_entries:
                    continue

                valid_entries = sorted(valid_entries, key=lambda e: e['elapsed_seconds'])
                x_data = [e['elapsed_seconds'] / 60 for e in valid_entries]
                y_data = [e['performance'] for e in valid_entries]

                color = colors[idx % len(colors)]
                ax.step(x_data, y_data, where='post', linewidth=2,
                        label=series_key, color=color, alpha=0.8)
                ax.plot(x_data, y_data, 'o', markersize=4, color=color, alpha=0.8)

            ax.set_xlabel('Time (minutes from start)')
            ax.set_ylabel('Performance (GFLOPS)')
            ax.set_title(title)
            ax.grid(True, alpha=0.3)
            ax.legend(loc='best')
            ax.xaxis.set_major_locator(ticker.MaxNLocator(nbins=15))

            output_dir = self.output_base / name.rsplit('/', 1)[0]
            output_dir.mkdir(parents=True, exist_ok=True)
            output_path = output_dir / f"{name.rsplit('/', 1)[-1]}.png"

            plt.savefig(output_path, dpi=dpi, bbox_inches='tight')
            plt.close()

            return output_path

        except Exception as e:
            print(f"  Multi-series graph error {name}: {e}")
            plt.close()
            return None

    # ------------------------------------------------------------------
    # SOTA extraction helpers
    # ------------------------------------------------------------------

    def _extract_sota_progression(self, entries: List[Dict]) -> List[Dict]:
        """Extract SOTA updates only (monotonically increasing)."""
        if not entries:
            return []

        valid_entries = [e for e in entries if 'elapsed_seconds' in e]
        if not valid_entries:
            valid_entries = entries

        sorted_entries = sorted(valid_entries, key=lambda e: e.get('elapsed_seconds', float('inf')))

        sota: List[Dict] = []
        max_perf = 0.0

        for entry in sorted_entries:
            perf = entry.get('performance', 0)
            if perf > max_perf:
                max_perf = perf
                sota.append(entry)

        return sota

    def _aggregate_sota_by_time(self, entries: List[Dict]) -> List[Dict]:
        """Aggregate SOTA by time series."""
        if not entries:
            return []

        valid_entries = [e for e in entries if 'elapsed_seconds' in e]
        if not valid_entries:
            valid_entries = entries

        sorted_entries = sorted(valid_entries, key=lambda e: e.get('elapsed_seconds', float('inf')))

        sota: List[Dict] = []
        max_perf = 0.0

        for entry in sorted_entries:
            perf = entry.get('performance', 0)
            if perf > max_perf:
                max_perf = perf
                sota_entry = entry.copy()
                sota_entry['generation_count'] = len(sota) + 1
                sota.append(sota_entry)

        return sota

    # ------------------------------------------------------------------
    # Utility helpers
    # ------------------------------------------------------------------

    def _extract_agent_id(self, path: str) -> Optional[str]:
        """Extract agent ID from path (PG1.2 format)."""
        import re
        match = re.search(r'PG\d+(?:\.\d+)?', path)
        return match.group() if match else None

    def _extract_hardware_key(self, path: str) -> Optional[str]:
        """Extract hardware key from path."""
        parts = path.split('/')
        hw_patterns = ['single-node', 'multi-node', 'gpu-cluster']

        for i, part in enumerate(parts):
            if part in hw_patterns and i + 1 < len(parts):
                return f"{part}/{parts[i + 1]}"

        return None

    def _parse_specific_dpis(self, specific_str: str) -> Dict[str, int]:
        """Parse specific agent DPI specifications.

        Format: "PG1.2:120,PG2:80,SE1:100"
        """
        result: Dict[str, int] = {}
        if not specific_str:
            return result

        for item in specific_str.split(','):
            if ':' in item:
                agent, dpi_str = item.split(':', 1)
                agent = agent.strip()
                try:
                    result[agent] = int(dpi_str)
                except ValueError:
                    pass

        return result

    def _get_dpi_config(self, params: Dict) -> Dict:
        """Get DPI configuration."""
        if params.get('debug'):
            debug_dpi = self.config['dpi'].get('debug', 30)
            return {
                'local': {'linear': debug_dpi, 'log': debug_dpi - 5},
                'family': {'linear': debug_dpi, 'log': debug_dpi - 5},
                'hardware': {'linear': debug_dpi + 10, 'log': debug_dpi},
                'project': {'linear': debug_dpi + 20, 'log': debug_dpi + 10},
            }
        return self.config['dpi']

    def _cleanup_old_files(self):
        """Clean up old graph files (storage management)."""
        max_age_hours = self.config['io_optimization'].get('cleanup_old_hours', 2)
        if max_age_hours <= 0:
            return

        cutoff_time = time.time() - (max_age_hours * 3600)
        removed = 0

        for png in self.output_base.rglob("*.png"):
            if 'milestone' in png.name:
                continue
            if png.stat().st_mtime < cutoff_time:
                png.unlink()
                removed += 1

        if removed > 0:
            print(f"  Cleaned up {removed} old files")

    # ------------------------------------------------------------------
    # Additional modes
    # ------------------------------------------------------------------

    def _run_summary_mode(self, **params) -> bool:
        """Summary mode (no graph generation, data check only)."""
        print("=" * 60)
        print("SOTA Data Summary")
        print("=" * 60)

        self._collect_all_data()

        total_entries = sum(len(e) for e in self.changelog_cache.values())
        print(f"\nTotal: {len(self.changelog_cache)} ChangeLogs, {total_entries} entries")

        print("\n[LOCAL]")
        pg_count = sum(1 for p in self.changelog_cache.keys() if 'PG' in p)
        print(f"  PG agents: {pg_count}")

        print("\n[TOP PERFORMANCE]")
        all_perfs: List[Tuple[str, float]] = []
        for path, entries in self.changelog_cache.items():
            if entries:
                latest = max(entries, key=lambda e: e.get('performance', 0))
                all_perfs.append((path, latest.get('performance', 0)))

        for path, perf in sorted(all_perfs, key=lambda x: x[1], reverse=True)[:5]:
            print(f"  {path}: {perf:.1f} GFLOPS")

        print("\n[TICK CHECK]")
        max_time = max(
            (e.get('elapsed_seconds', 0) for entries in self.changelog_cache.values() for e in entries),
            default=0,
        )

        if max_time > 0:
            print(f"  Max elapsed: {max_time / 3600:.1f} hours")
            estimated_ticks = int(max_time / 60)
            print(f"  Estimated ticks (minutes): {estimated_ticks}")
            if estimated_ticks > 1000:
                print(f"  WARNING: Would exceed MAXTICKS!")
                print(f"  Fix: Dynamic time units + MaxNLocator(nbins=15)")

        return True

    def _run_export_mode(self, **params) -> bool:
        """Export mode (for multi-project integration)."""
        self._collect_all_data()

        export_dir = self.project_root / "Agent-shared/exports"
        export_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        export_path = export_dir / f"sota_export_{timestamp}.json"

        export_data = {
            'project': str(self.project_root.name),
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'start_time': self.project_start_time.isoformat(),
            'data': {},
            'metadata': {
                'total_changelogs': len(self.changelog_cache),
                'total_entries': sum(len(e) for e in self.changelog_cache.values()),
                'config': self.config,
            },
        }

        for path, entries in self.changelog_cache.items():
            export_data['data'][path] = [
                {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in entry.items()}
                for entry in entries
            ]

        with open(export_path, 'w') as f:
            json.dump(export_data, f, indent=2)

        print(f"Exported to: {export_path}")
        print(f"   Size: {export_path.stat().st_size / 1024:.1f} KB")

        return True

    def _run_single_mode(self, **params) -> bool:
        """Single graph generation mode (debug / individual check)."""
        level = params.get('level', 'project')
        specific = params.get('specific')

        self._collect_all_data()
        dpi = params.get('dpi', 100)

        if level == 'local' and specific:
            for path, entries in self.changelog_cache.items():
                if specific in path:
                    sota = self._extract_sota_progression(entries)
                    if sota:
                        output = self._generate_graph(
                            f'local/{specific}',
                            sota,
                            f"SOTA: {specific}",
                            params.get('x_axis', 'time'),
                            dpi,
                            params,
                        )
                        if output:
                            print(f"Generated: {output}")
                            return True

        print("No data found for specified criteria")
        return False


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='SOTA Visualizer - Self-contained Pipeline Edition',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Normal pipeline execution (periodic)
  python sota_visualizer.py

  # Debug mode (low resolution)
  python sota_visualizer.py --debug

  # Summary display (no graph generation)
  python sota_visualizer.py --summary

  # Specific PG with high resolution
  python sota_visualizer.py --specific PG1.2:150

  # Data export
  python sota_visualizer.py --export

  # SE custom execution
  python sota_visualizer.py --levels local,project --dpi 80
        """,
    )

    # Mode selection
    parser.add_argument('--pipeline', action='store_true', default=True,
                        help='Pipeline mode (default)')
    parser.add_argument('--debug', action='store_true',
                        help='Debug mode with low DPI')
    parser.add_argument('--summary', action='store_true',
                        help='Show summary without generating graphs')
    parser.add_argument('--export', action='store_true',
                        help='Export data for multi-project analysis')
    parser.add_argument('--single', action='store_true',
                        help='Single graph generation mode')

    # Pipeline control
    parser.add_argument('--levels', type=str,
                        help='Comma-separated levels (e.g., local,hardware,project)')
    parser.add_argument('--force', action='store_true',
                        help='Force execution even if locked')
    parser.add_argument('--no-delay', action='store_true',
                        help='No IO delay between levels')

    # Graph control
    parser.add_argument('--specific', type=str,
                        help='Specific agents with DPI (e.g., PG1.2:120,PG2:80)')
    parser.add_argument('--x-axis', type=str, default='time',
                        choices=['time', 'count', 'version'],
                        help='X-axis type')
    parser.add_argument('--dpi', type=int,
                        help='Override default DPI')
    parser.add_argument('--accuracy-threshold', type=float,
                        help='Filter by accuracy (e.g., 95.0)')
    parser.add_argument('--no-theoretical', action='store_true',
                        help='Hide theoretical performance line')

    # Level specification (single mode)
    parser.add_argument('--level', type=str, default='project',
                        choices=['local', 'family', 'hardware', 'project'],
                        help='Level for single mode')

    args = parser.parse_args()

    # Project root search
    current = Path.cwd()
    project_root = None

    while current != current.parent:
        if (current / "CLAUDE.md").exists():
            project_root = current
            break
        current = current.parent

    if not project_root:
        print("Error: Could not find project root (CLAUDE.md)")
        sys.exit(1)

    visualizer = SOTAVisualizer(project_root)

    params = {
        'force': args.force,
        'no_delay': args.no_delay,
        'specific': args.specific,
        'x_axis': args.x_axis,
        'accuracy_threshold': args.accuracy_threshold,
        'no_theoretical': args.no_theoretical,
    }

    if args.levels:
        params['levels'] = args.levels.split(',')

    if args.dpi:
        params['dpi'] = args.dpi

    if args.summary:
        success = visualizer.run('summary', **params)
    elif args.export:
        success = visualizer.run('export', **params)
    elif args.debug:
        success = visualizer.run('debug', **params)
    elif args.single:
        params['level'] = args.level
        success = visualizer.run('single', **params)
    else:
        success = visualizer.run('pipeline', **params)

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
