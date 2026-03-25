#!/usr/bin/env python3
"""Context usage monitoring and visualization.

Self-contained script (no package dependencies beyond matplotlib/numpy).
Designed to be run by agents via ``python3 context_monitor.py --help``.

Supports Claude Code, Codex, Gemini, and OpenCode log formats.

Usage examples:
  python3 context_monitor.py claude /path/to/session.jsonl --status
  python3 context_monitor.py codex /path/to/rollout.jsonl --visualize -o viz/
  python3 context_monitor.py gemini /path/to/telemetry.jsonl --status
  python3 context_monitor.py all --registry agents.jsonl --status
  python3 context_monitor.py all --registry agents.jsonl --visualize -o viz/
"""

from __future__ import annotations

import gzip
import json
import pickle
import os
import platform
import re
import sqlite3
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.dates as mdates  # noqa: E402
import numpy as np  # noqa: E402

try:
    plt.style.use("seaborn-v0_8-darkgrid")
except Exception:
    try:
        plt.style.use("seaborn-darkgrid")
    except Exception:
        pass
plt.rcParams["figure.figsize"] = (14, 10)
plt.rcParams["font.size"] = 10


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class UsageSnapshot:
    """A single token-usage observation at a point in time."""
    timestamp: datetime
    input_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    output_tokens: int = 0

    @property
    def total(self) -> int:
        return (
            self.input_tokens
            + self.cache_creation_tokens
            + self.cache_read_tokens
            + self.output_tokens
        )

    def to_dict(self) -> Dict[str, int]:
        return {
            "input": self.input_tokens,
            "cache_creation": self.cache_creation_tokens,
            "cache_read": self.cache_read_tokens,
            "output": self.output_tokens,
            "total": self.total,
        }


@dataclass
class ContextConfig:
    """Configurable context limits (injected, not hardcoded)."""
    context_limit: int = 1_000_000
    auto_compact_threshold: float = 0.95
    warning_threshold: float = 0.70
    warning_line: int = 200_000
    auto_compact_line: Optional[int] = None

    @property
    def auto_compact_tokens(self) -> int:
        """Absolute token count for auto-compact threshold."""
        return int(self.context_limit * self.auto_compact_threshold)

    @property
    def warning_tokens(self) -> int:
        """Absolute token count for warning threshold."""
        return int(self.context_limit * self.warning_threshold)


# ---------------------------------------------------------------------------
# Abstract log parser
# ---------------------------------------------------------------------------

class LogParser(ABC):
    """CLI-agnostic interface for parsing conversation logs into UsageSnapshots."""

    #: Override to ``True`` in subclasses whose snapshots already contain
    #: session-cumulative values (e.g. Codex ``total_token_usage``).
    snapshots_are_cumulative: bool = False

    @abstractmethod
    def parse(self, source: Path) -> List[UsageSnapshot]:
        """Parse *source* and return a list of UsageSnapshots in time order."""
        ...

    @abstractmethod
    def get_latest(self, source: Path) -> Optional[UsageSnapshot]:
        """Efficiently return only the latest snapshot (tail-read optimized)."""
        ...

    @staticmethod
    def to_deltas(snapshots: List[UsageSnapshot]) -> List[UsageSnapshot]:
        """Convert cumulative snapshots to per-request deltas.

        Each output snapshot contains the *increment* from the previous one.
        The first snapshot is kept as-is (delta from zero).
        """
        if not snapshots:
            return []
        result = [snapshots[0]]
        for prev, curr in zip(snapshots, snapshots[1:]):
            result.append(UsageSnapshot(
                timestamp=curr.timestamp,
                input_tokens=max(0, curr.input_tokens - prev.input_tokens),
                cache_creation_tokens=max(0, curr.cache_creation_tokens - prev.cache_creation_tokens),
                cache_read_tokens=max(0, curr.cache_read_tokens - prev.cache_read_tokens),
                output_tokens=max(0, curr.output_tokens - prev.output_tokens),
            ))
        return result


# ---------------------------------------------------------------------------
# Gemini CLI telemetry JSONL parser
# ---------------------------------------------------------------------------

class GeminiLogParser(LogParser):
    """Parses Gemini CLI token-usage data.

    Supports four data layouts:

    1) **JSONL flat metrics** — one JSON object per line with
       ``name == "gemini_cli.token.usage"`` and per-type values.
    2) **JSONL OTel export** — ``dataPoints`` array inside each line.
    3) **Pretty-printed OTel LogRecords** — concatenated multi-line JSON
       objects (``hrTime``, ``attributes`` dict with ``input_token_count``
       etc.).  This is what Gemini CLI >= 2025-Q3 writes by default.
    4) **Chat session JSON** — ``~/.gemini/tmp/<project>/chats/session-*.json``
       files containing a ``messages`` array where model responses carry a
       ``tokens`` dict (``input``, ``output``, ``cached``, ``thoughts``,
       ``tool``, ``total``).  This is the primary format in Gemini CLI >= 2026.

    All layouts are merged into :class:`UsageSnapshot` instances keyed by
    second-resolution timestamp.
    """

    # Default outfile location when no explicit path is given
    DEFAULT_OUTFILE = Path.home() / ".gemini" / "tmp" / "telemetry.jsonl"

    # projects.json maps working_dir → shortId
    PROJECTS_JSON = Path.home() / ".gemini" / "projects.json"

    METRIC_NAME = "gemini_cli.token.usage"

    @classmethod
    def _load_projects_map(cls) -> Dict[str, str]:
        """Load ``~/.gemini/projects.json`` → {working_dir: shortId}."""
        if not cls.PROJECTS_JSON.exists():
            return {}
        try:
            data = json.loads(cls.PROJECTS_JSON.read_text(encoding="utf-8"))
            return data.get("projects", {})
        except (json.JSONDecodeError, OSError):
            return {}

    @classmethod
    def find_session_file(cls, working_dir: Optional[str] = None) -> Optional[Path]:
        """Locate the most recent chat session JSON for *working_dir*.

        Resolution: ``~/.gemini/projects.json`` maps working_dir → shortId,
        then ``~/.gemini/tmp/<shortId>/chats/session-*.json`` (most recent).
        """
        projects = cls._load_projects_map()
        if working_dir:
            short_id = projects.get(working_dir)
            if short_id:
                chats_dir = Path.home() / ".gemini" / "tmp" / short_id / "chats"
                if chats_dir.is_dir():
                    sessions = sorted(chats_dir.glob("session-*.json"),
                                      key=lambda p: p.stat().st_mtime, reverse=True)
                    if sessions:
                        return sessions[0]
        # Fallback: most recent session across all projects
        gemini_tmp = Path.home() / ".gemini" / "tmp"
        if not gemini_tmp.exists():
            return None
        all_sessions = sorted(
            gemini_tmp.rglob("chats/session-*.json"),
            key=lambda p: p.stat().st_mtime, reverse=True,
        )
        return all_sessions[0] if all_sessions else None

    # Map Gemini type → UsageSnapshot field (for flat/OTel metric layouts)
    _TYPE_MAP = {
        "input": "input_tokens",
        "output": "output_tokens",
        "thought": "output_tokens",   # thought tokens counted as output
        "cache": "cache_read_tokens",
        "tool": "input_tokens",       # tool tokens counted as input
    }

    # Map OTel LogRecord attribute names → UsageSnapshot fields
    _LOGRECORD_ATTR_MAP = {
        "input_token_count": "input_tokens",
        "output_token_count": "output_tokens",
        "thoughts_token_count": "output_tokens",
        "cached_content_token_count": "cache_read_tokens",
        "tool_token_count": "input_tokens",
    }

    def __init__(self, outfile: Optional[Path] = None):
        self.outfile = outfile or self.DEFAULT_OUTFILE

    # ---- LogParser interface ------------------------------------------------

    def parse(self, source: Path) -> List[UsageSnapshot]:
        if not source.exists():
            return []
        content = source.read_text(encoding="utf-8", errors="ignore")
        return self._parse_content(content)

    def get_latest(self, source: Path) -> Optional[UsageSnapshot]:
        if not source.exists():
            return None
        with open(source, "rb") as fh:
            fh.seek(0, 2)
            file_size = fh.tell()
            search_size = min(file_size, 10 * 1024 * 1024)
            fh.seek(max(0, file_size - search_size))
            content = fh.read().decode("utf-8", errors="ignore")
        snaps = self._parse_content(content)
        return snaps[-1] if snaps else None

    # ---- Helpers -----------------------------------------------------------

    def _parse_content(self, content: str) -> List[UsageSnapshot]:
        """Parse telemetry content, auto-detecting format.

        Tries Layout 4 (chat session JSON) first, then JSONL (Layouts 1-2),
        then pretty-printed OTel (Layout 3).
        """
        # Layout 4: chat session JSON with messages[].tokens
        try:
            doc = json.loads(content)
            if isinstance(doc, dict) and "messages" in doc:
                snaps = self._parse_chat_session(doc)
                if snaps:
                    return snaps
        except (json.JSONDecodeError, ValueError):
            pass

        buckets: Dict[str, Dict[str, Any]] = {}

        # Layouts 1 & 2: JSONL (one JSON object per line)
        for line in content.split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                if not isinstance(entry, dict):
                    continue
                self._accumulate_entry(entry, buckets)
            except (json.JSONDecodeError, ValueError):
                continue

        # Layout 3: pretty-printed concatenated JSON
        if not buckets:
            objects = self._extract_json_objects(content)
            for obj in objects:
                self._accumulate_entry(obj, buckets)

        return self._buckets_to_snapshots(buckets)

    @staticmethod
    def _extract_json_objects(text: str) -> List[dict]:
        """Extract top-level JSON objects from concatenated pretty-printed text."""
        objects: List[dict] = []
        depth = 0
        start: Optional[int] = None
        for i, c in enumerate(text):
            if c == "{":
                if depth == 0:
                    start = i
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0 and start is not None:
                    try:
                        objects.append(json.loads(text[start : i + 1]))
                    except (json.JSONDecodeError, ValueError):
                        pass
                    start = None
        return objects

    # Map chat session token keys → UsageSnapshot fields
    _CHAT_TOKEN_MAP = {
        "input": "input_tokens",
        "output": "output_tokens",
        "thoughts": "output_tokens",    # thought tokens counted as output
        "cached": "cache_read_tokens",
        "tool": "input_tokens",         # tool tokens counted as input
    }

    @classmethod
    def _parse_chat_session(cls, doc: dict) -> List[UsageSnapshot]:
        """Layout 4: parse ``~/.gemini/tmp/<proj>/chats/session-*.json``.

        Each message with a ``tokens`` dict produces one snapshot.
        """
        snapshots: List[UsageSnapshot] = []
        for msg in doc.get("messages", []):
            tokens = msg.get("tokens")
            if not isinstance(tokens, dict):
                continue
            ts_str = msg.get("timestamp")
            if not ts_str:
                continue
            try:
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                continue
            snap = UsageSnapshot(timestamp=ts)
            for tok_key, field in cls._CHAT_TOKEN_MAP.items():
                val = tokens.get(tok_key, 0)
                try:
                    setattr(snap, field, getattr(snap, field) + int(val))
                except (ValueError, TypeError):
                    pass
            # Gemini's promptTokenCount (input) includes cachedContentTokenCount.
            # Subtract to avoid double-counting in UsageSnapshot.total.
            if snap.cache_read_tokens > 0 and snap.input_tokens >= snap.cache_read_tokens:
                snap.input_tokens -= snap.cache_read_tokens
            snapshots.append(snap)
        return snapshots

    @classmethod
    def _accumulate_entry(cls, entry: dict, buckets: Dict[str, Dict[str, Any]]) -> None:
        """Route an entry to the appropriate accumulator."""
        # Layout 3: OTel LogRecord with hrTime + attributes containing token counts
        if "hrTime" in entry:
            cls._accumulate_logrecord(entry, buckets)
            return

        # Layouts 1 & 2: flat metric or OTel metric export
        name = entry.get("name") or entry.get("metric")
        if name != cls.METRIC_NAME:
            return

        ts_str = entry.get("timestamp")
        if not ts_str:
            ts_nano = entry.get("timestamp_unix_nano") or entry.get("timeUnixNano")
            if ts_nano:
                try:
                    ts_str = datetime.fromtimestamp(
                        int(ts_nano) / 1e9, tz=timezone.utc
                    ).isoformat()
                except (ValueError, OSError):
                    return
        if not ts_str:
            return

        ts_key = ts_str[:19]
        bucket = buckets.setdefault(ts_key, {
            "ts_str": ts_str,
            "input_tokens": 0,
            "cache_creation_tokens": 0,
            "cache_read_tokens": 0,
            "output_tokens": 0,
        })

        data_points = entry.get("dataPoints") or entry.get("data_points")
        if isinstance(data_points, list):
            for dp in data_points:
                cls._apply_data_point(dp, bucket)
        else:
            cls._apply_data_point(entry, bucket)

    @classmethod
    def _accumulate_logrecord(cls, entry: dict, buckets: Dict[str, Dict[str, Any]]) -> None:
        """Extract token counts from an OTel LogRecord entry.

        The ``attributes`` field may be a dict or a list of [key, value] pairs.
        Only records that contain at least one ``*_token_count`` attribute
        are included.
        """
        attrs = entry.get("attributes", {})
        if isinstance(attrs, list):
            attrs = {pair[0]: pair[1] for pair in attrs if isinstance(pair, list) and len(pair) == 2}
        if not isinstance(attrs, dict):
            return

        # Check if this record has any token count attributes
        has_tokens = any(k in attrs for k in cls._LOGRECORD_ATTR_MAP)
        if not has_tokens:
            return

        # Extract timestamp from hrTime [seconds, nanoseconds]
        hr_time = entry.get("hrTime")
        if not isinstance(hr_time, list) or len(hr_time) < 2:
            return
        try:
            ts = datetime.fromtimestamp(
                int(hr_time[0]) + int(hr_time[1]) / 1e9, tz=timezone.utc
            )
        except (ValueError, TypeError, OSError):
            return

        ts_key = ts.isoformat()[:19]
        bucket = buckets.setdefault(ts_key, {
            "ts_str": ts.isoformat(),
            "input_tokens": 0,
            "cache_creation_tokens": 0,
            "cache_read_tokens": 0,
            "output_tokens": 0,
        })

        for attr_name, field in cls._LOGRECORD_ATTR_MAP.items():
            value = attrs.get(attr_name)
            if value is not None:
                try:
                    bucket[field] += int(value)
                except (ValueError, TypeError):
                    pass

    @classmethod
    def _apply_data_point(cls, dp: dict, bucket: Dict[str, Any]) -> None:
        attrs = dp.get("attributes", {})
        token_type = attrs.get("type", "")
        field = cls._TYPE_MAP.get(token_type)
        if not field:
            return
        value = dp.get("value") or dp.get("asInt") or dp.get("asDouble") or 0
        try:
            bucket[field] += int(value)
        except (ValueError, TypeError):
            pass

    @staticmethod
    def _buckets_to_snapshots(buckets: Dict[str, Dict[str, Any]]) -> List[UsageSnapshot]:
        snapshots: List[UsageSnapshot] = []
        for _ts_key, b in sorted(buckets.items()):
            ts_str = b["ts_str"]
            try:
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                continue
            snapshots.append(UsageSnapshot(
                timestamp=ts,
                input_tokens=b["input_tokens"],
                cache_creation_tokens=b["cache_creation_tokens"],
                cache_read_tokens=b["cache_read_tokens"],
                output_tokens=b["output_tokens"],
            ))
        return snapshots


# ---------------------------------------------------------------------------
# Qwen Code JSONL parser (Gemini CLI fork)
# ---------------------------------------------------------------------------

class QwenLogParser(LogParser):
    """Parses Qwen Code chat session JSONL files.

    Qwen Code (a Gemini CLI fork) stores conversation logs at:
    ``~/.qwen/projects/<sanitized-cwd>/chats/<sessionId>.jsonl``

    Path encoding is identical to Claude Code: all non-alphanumeric
    characters replaced with ``-``.

    Token data appears in two record types within the JSONL:

    1) ``type: "system", subtype: "ui_telemetry"`` -- per-API-call metrics in
       ``systemPayload.uiEvent``:
       ``input_token_count``, ``output_token_count``,
       ``cached_content_token_count``, ``thoughts_token_count``,
       ``tool_token_count``, ``total_token_count``.

    2) ``type: "assistant"`` -- ``usageMetadata`` dict with camelCase keys:
       ``promptTokenCount``, ``candidatesTokenCount``,
       ``thoughtsTokenCount``, ``totalTokenCount``,
       ``cachedContentTokenCount``.

    Layout (1) is preferred as it includes all breakdowns.
    """

    _PATH_RE = re.compile(r"[^a-zA-Z0-9]")

    # Map ui_telemetry event fields -> UsageSnapshot fields
    _TELEMETRY_FIELD_MAP = {
        "input_token_count": "input_tokens",
        "output_token_count": "output_tokens",
        "cached_content_token_count": "cache_read_tokens",
        "thoughts_token_count": "output_tokens",     # thoughts counted as output
        "tool_token_count": "input_tokens",           # tool tokens counted as input
    }

    # Map assistant usageMetadata fields -> UsageSnapshot fields
    _USAGE_METADATA_MAP = {
        "promptTokenCount": "input_tokens",
        "candidatesTokenCount": "output_tokens",
        "thoughtsTokenCount": "output_tokens",
        "cachedContentTokenCount": "cache_read_tokens",
    }

    @classmethod
    def encode_project_dir(cls, working_dir: str) -> str:
        """Encode a filesystem path into Qwen-projects directory name.

        Identical to Claude Code: all non-alphanumeric chars -> '-'.
        """
        if platform.system() == "Windows":
            working_dir = working_dir.replace("\\", "/")
        return cls._PATH_RE.sub("-", working_dir)

    @classmethod
    def qwen_projects_dir(cls) -> Path:
        return Path.home() / ".qwen" / "projects"

    @classmethod
    def session_log_path(cls, working_dir: str, session_id: str) -> Path:
        dir_name = cls.encode_project_dir(working_dir)
        return cls.qwen_projects_dir() / dir_name / "chats" / f"{session_id}.jsonl"

    @classmethod
    def find_session_file(cls, working_dir: Optional[str] = None) -> Optional[Path]:
        """Locate the most recent chat JSONL for *working_dir*.

        Resolution: ``~/.qwen/projects/<sanitized-cwd>/chats/<sessionId>.jsonl``
        If *working_dir* is given, search in its specific project directory.
        Otherwise, find the most recent session across all projects.
        """
        if working_dir:
            dir_name = cls.encode_project_dir(working_dir)
            chats_dir = cls.qwen_projects_dir() / dir_name / "chats"
            if chats_dir.is_dir():
                sessions = sorted(
                    chats_dir.glob("*.jsonl"),
                    key=lambda p: p.stat().st_mtime,
                    reverse=True,
                )
                if sessions:
                    return sessions[0]
        # Fallback: most recent across all projects
        projects_dir = cls.qwen_projects_dir()
        if not projects_dir.exists():
            return None
        all_sessions = sorted(
            projects_dir.rglob("chats/*.jsonl"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        return all_sessions[0] if all_sessions else None

    def parse(self, source: Path) -> List[UsageSnapshot]:
        if not source.exists():
            return []
        # Two-pass: prefer ui_telemetry (layout 1); fall back to assistant
        # usageMetadata (layout 2) only if no telemetry records found.
        # Both record types exist for each API call — using both would double-count.
        telemetry_snaps: List[UsageSnapshot] = []
        assistant_snaps: List[UsageSnapshot] = []
        with open(source, "r", encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                if not isinstance(entry, dict):
                    continue
                snap = self._extract_telemetry(entry)
                if snap is not None:
                    telemetry_snaps.append(snap)
                    continue
                snap = self._extract_assistant(entry)
                if snap is not None:
                    assistant_snaps.append(snap)
        return telemetry_snaps if telemetry_snaps else assistant_snaps

    def get_latest(self, source: Path) -> Optional[UsageSnapshot]:
        if not source.exists():
            return None
        # Read tail of file for efficiency
        with open(source, "rb") as fh:
            fh.seek(0, 2)
            file_size = fh.tell()
            search_size = min(file_size, 2 * 1024 * 1024)
            fh.seek(max(0, file_size - search_size))
            tail = fh.read().decode("utf-8", errors="ignore")
        latest_telemetry: Optional[UsageSnapshot] = None
        latest_assistant: Optional[UsageSnapshot] = None
        for line in tail.split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            snap = self._extract_telemetry(entry)
            if snap is not None:
                latest_telemetry = snap
                continue
            snap = self._extract_assistant(entry)
            if snap is not None:
                latest_assistant = snap
        return latest_telemetry or latest_assistant

    @classmethod
    def _parse_timestamp(cls, entry: dict) -> Optional[datetime]:
        """Parse ISO 8601 timestamp from a JSONL entry."""
        ts_str = entry.get("timestamp")
        if not ts_str:
            return None
        try:
            return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None

    @classmethod
    def _extract_telemetry(cls, entry: dict) -> Optional[UsageSnapshot]:
        """Extract snapshot from a ui_telemetry record (layout 1)."""
        if not (entry.get("type") == "system"
                and entry.get("subtype") == "ui_telemetry"):
            return None
        ts = cls._parse_timestamp(entry)
        if ts is None:
            return None
        payload = entry.get("systemPayload", {})
        ui_event = payload.get("uiEvent", {})
        # Only process successful API responses (not errors)
        if ui_event.get("event.name") != "qwen-code.api_response":
            return None
        snap = UsageSnapshot(timestamp=ts)
        for field_name, attr in cls._TELEMETRY_FIELD_MAP.items():
            val = ui_event.get(field_name, 0)
            try:
                setattr(snap, attr, getattr(snap, attr) + int(val))
            except (ValueError, TypeError):
                pass
        # Qwen (Gemini fork): input_token_count includes cached_content_token_count.
        # Subtract to avoid double-counting in UsageSnapshot.total.
        if snap.cache_read_tokens > 0 and snap.input_tokens >= snap.cache_read_tokens:
            snap.input_tokens -= snap.cache_read_tokens
        return snap

    @classmethod
    def _extract_assistant(cls, entry: dict) -> Optional[UsageSnapshot]:
        """Extract snapshot from an assistant record with usageMetadata (layout 2)."""
        if entry.get("type") != "assistant":
            return None
        ts = cls._parse_timestamp(entry)
        if ts is None:
            return None
        usage = entry.get("usageMetadata")
        if not isinstance(usage, dict):
            return None
        snap = UsageSnapshot(timestamp=ts)
        for field_name, attr in cls._USAGE_METADATA_MAP.items():
            val = usage.get(field_name, 0)
            try:
                setattr(snap, attr, getattr(snap, attr) + int(val))
            except (ValueError, TypeError):
                pass
        # Qwen (Gemini fork): promptTokenCount includes cachedContentTokenCount.
        if snap.cache_read_tokens > 0 and snap.input_tokens >= snap.cache_read_tokens:
            snap.input_tokens -= snap.cache_read_tokens
        return snap


# ---------------------------------------------------------------------------
# Claude Code JSONL parser
# ---------------------------------------------------------------------------

class ClaudeCodeLogParser(LogParser):
    """Parses Claude Code ~/.claude/projects/<dir>/<session>.jsonl files."""

    # Claude Code path-encoding rule: all non-alphanumeric chars → '-'
    _PATH_RE = re.compile(r"[^a-zA-Z0-9]")

    @classmethod
    def encode_project_dir(cls, working_dir: str) -> str:
        """Encode a filesystem path into Claude-projects directory name."""
        if platform.system() == "Windows":
            working_dir = working_dir.replace("\\", "/")
        return cls._PATH_RE.sub("-", working_dir)

    @classmethod
    def claude_projects_dir(cls) -> Path:
        return Path.home() / ".claude" / "projects"

    @classmethod
    def session_log_path(cls, working_dir: str, session_id: str) -> Path:
        dir_name = cls.encode_project_dir(working_dir)
        return cls.claude_projects_dir() / dir_name / f"{session_id}.jsonl"

    # ---- LogParser interface ------------------------------------------------

    def parse(self, source: Path) -> List[UsageSnapshot]:
        snapshots: List[UsageSnapshot] = []
        if not source.exists():
            return snapshots
        with open(source, "r", encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                snap = self._parse_line(line)
                if snap is not None:
                    snapshots.append(snap)
        return snapshots

    def get_latest(self, source: Path) -> Optional[UsageSnapshot]:
        if not source.exists():
            return None
        with open(source, "rb") as fh:
            fh.seek(0, 2)
            file_size = fh.tell()
            search_size = min(file_size, 10 * 1024 * 1024)
            fh.seek(max(0, file_size - search_size))
            content = fh.read().decode("utf-8", errors="ignore")
        for line in reversed(content.strip().split("\n")):
            snap = self._parse_line(line)
            if snap is not None:
                return snap
        return None

    # ---- Helpers -----------------------------------------------------------

    @staticmethod
    def _parse_line(line: str) -> Optional[UsageSnapshot]:
        line = line.strip()
        if not line:
            return None
        try:
            entry = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            return None
        msg = entry.get("message")
        if not isinstance(msg, dict):
            return None
        usage = msg.get("usage")
        if not isinstance(usage, dict):
            return None
        ts_str = entry.get("timestamp")
        if not ts_str:
            return None
        try:
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None
        return UsageSnapshot(
            timestamp=ts,
            input_tokens=usage.get("input_tokens", 0),
            cache_creation_tokens=usage.get("cache_creation_input_tokens", 0),
            cache_read_tokens=usage.get("cache_read_input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
        )


# ---------------------------------------------------------------------------
# OpenCode SQLite parser
# ---------------------------------------------------------------------------

class OpenCodeLogParser(LogParser):
    """Parses OpenCode ``~/.local/share/opencode/opencode.db`` SQLite database.

    The ``message`` table schema (relevant columns):
        session_id TEXT, data TEXT (JSON), time_created INTEGER (ms epoch)

    The ``data`` JSON contains:
        tokens: {total?, input, output, reasoning, cache: {read, write}}
        cost: float
    """

    DB_FILENAME = "opencode.db"

    @classmethod
    def db_path(cls, project_root: Optional[Path] = None) -> Path:
        """Return the path to OpenCode's SQLite database.

        OpenCode uses XDG Base Directory:
        ``$XDG_DATA_HOME/opencode/opencode.db`` (default ``~/.local/share/opencode/``).
        The ``OPENCODE_DATA_DIR`` env var overrides the data directory.
        """
        override = os.environ.get("OPENCODE_DATA_DIR")
        if override:
            return Path(override) / cls.DB_FILENAME
        xdg = os.environ.get("XDG_DATA_HOME")
        if xdg:
            return Path(xdg) / "opencode" / cls.DB_FILENAME
        return Path.home() / ".local" / "share" / "opencode" / cls.DB_FILENAME

    # ---- LogParser interface ------------------------------------------------

    def parse(self, source: Path) -> List[UsageSnapshot]:
        if not source.exists():
            return []
        try:
            return self._query_snapshots(source)
        except (sqlite3.Error, OSError):
            return []

    def get_latest(self, source: Path) -> Optional[UsageSnapshot]:
        if not source.exists():
            return None
        try:
            rows = self._query_snapshots(source, latest_only=True)
            return rows[0] if rows else None
        except (sqlite3.Error, OSError):
            return None

    # ---- Query with optional session_id filter -----------------------------

    def parse_session(self, source: Path, session_id: str) -> List[UsageSnapshot]:
        """Parse only messages belonging to *session_id*."""
        if not source.exists():
            return []
        try:
            return self._query_snapshots(source, session_id=session_id)
        except (sqlite3.Error, OSError):
            return []

    # ---- Internal ----------------------------------------------------------

    @staticmethod
    def _query_snapshots(
        db_path: Path,
        *,
        session_id: Optional[str] = None,
        latest_only: bool = False,
    ) -> List[UsageSnapshot]:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            cur = con.cursor()
            if session_id:
                sql = (
                    "SELECT data, time_created FROM message "
                    "WHERE session_id = ? ORDER BY time_created"
                )
                cur.execute(sql, (session_id,))
            else:
                sql = "SELECT data, time_created FROM message ORDER BY time_created"
                cur.execute(sql)
            rows = cur.fetchall()
        finally:
            con.close()

        snapshots: List[UsageSnapshot] = []
        for data_str, ts_str in rows:
            snap = OpenCodeLogParser._row_to_snapshot(data_str, ts_str)
            if snap is not None:
                snapshots.append(snap)

        if latest_only and snapshots:
            return [snapshots[-1]]
        return snapshots

    @staticmethod
    def _row_to_snapshot(data_str: str, ts_val) -> Optional[UsageSnapshot]:
        try:
            data = json.loads(data_str)
        except (json.JSONDecodeError, TypeError):
            return None

        tokens = data.get("tokens")
        if not isinstance(tokens, dict):
            return None

        cache = tokens.get("cache") or {}
        input_tokens = tokens.get("input", 0)
        output_tokens = tokens.get("output", 0)
        cache_read = cache.get("read", 0)
        cache_write = cache.get("write", 0)

        try:
            # OpenCode stores time_created as integer milliseconds since epoch
            if isinstance(ts_val, (int, float)):
                ts = datetime.fromtimestamp(ts_val / 1000, tz=timezone.utc)
            else:
                # Fallback: try as ISO string for forward compatibility
                ts = datetime.fromisoformat(str(ts_val).replace("Z", "+00:00"))
        except (ValueError, TypeError, OSError):
            return None

        return UsageSnapshot(
            timestamp=ts,
            input_tokens=input_tokens,
            cache_creation_tokens=cache_write,
            cache_read_tokens=cache_read,
            output_tokens=output_tokens,
        )


# ---------------------------------------------------------------------------
# Codex JSONL parser
# ---------------------------------------------------------------------------

class CodexLogParser(LogParser):
    """Parses Codex CLI ~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl files.

    TokenCount events carry cumulative token usage reported by the Codex CLI.
    The parser extracts ``total_token_usage`` from each ``TokenCount`` event
    and maps fields to :class:`UsageSnapshot`:

    - ``input_tokens`` → ``input_tokens``
    - ``cached_input_tokens`` → ``cache_read_tokens``
    - ``output_tokens`` + ``reasoning_output_tokens`` → ``output_tokens``
    - ``cache_creation_tokens`` is always 0 (Codex has no equivalent)
    """

    snapshots_are_cumulative = False  # Using last_token_usage (per-request)

    @staticmethod
    def sessions_root() -> Path:
        """Return ``~/.codex/sessions``."""
        return Path.home() / ".codex" / "sessions"

    @classmethod
    def find_session_file(cls, session_id: Optional[str] = None) -> Optional[Path]:
        """Locate the rollout JSONL for *session_id*.

        If *session_id* is ``None``, ``CODEX_THREAD_ID`` env-var is tried,
        then the most-recently-modified rollout file is returned.
        """
        sid = session_id or os.environ.get("CODEX_THREAD_ID")
        root = cls.sessions_root()
        if not root.exists():
            return None

        rollouts = sorted(
            root.rglob("rollout-*.jsonl"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if not rollouts:
            return None

        if sid:
            for r in rollouts:
                meta_id = cls._read_session_meta_id(r)
                if meta_id == sid:
                    return r
            return None

        return rollouts[0]

    @staticmethod
    def _read_session_meta_id(path: Path) -> Optional[str]:
        """Read the SessionMeta ``id`` from the first line of a rollout file."""
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                first = fh.readline().strip()
                if not first:
                    return None
                entry = json.loads(first)
                payload = entry.get("payload", {})
                # Legacy: payload.SessionMeta / payload.session_meta
                meta = payload.get("SessionMeta") or payload.get("session_meta")
                if isinstance(meta, dict):
                    return meta.get("id")
                # Current: type=="session_meta" with id at payload level
                if entry.get("type") == "session_meta" and isinstance(payload, dict):
                    return payload.get("id")
        except (json.JSONDecodeError, OSError):
            pass
        return None

    # ---- LogParser interface ------------------------------------------------

    def parse(self, source: Path) -> List[UsageSnapshot]:
        snapshots: List[UsageSnapshot] = []
        if not source.exists():
            return snapshots
        with open(source, "r", encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                snap = self._parse_line(line)
                if snap is not None:
                    snapshots.append(snap)
        return snapshots

    def get_latest(self, source: Path) -> Optional[UsageSnapshot]:
        if not source.exists():
            return None
        with open(source, "rb") as fh:
            fh.seek(0, 2)
            file_size = fh.tell()
            search_size = min(file_size, 10 * 1024 * 1024)
            fh.seek(max(0, file_size - search_size))
            content = fh.read().decode("utf-8", errors="ignore")
        for line in reversed(content.strip().split("\n")):
            snap = self._parse_line(line)
            if snap is not None:
                return snap
        return None

    # ---- Helpers -----------------------------------------------------------

    @staticmethod
    def _parse_line(line: str) -> Optional[UsageSnapshot]:
        line = line.strip()
        if not line:
            return None
        try:
            entry = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            return None

        # Navigate to total_token_usage — support two Codex rollout layouts:
        # 1) Legacy:  payload.TokenCount.info.total_token_usage
        # 2) Current: payload.type=="token_count", payload.info.total_token_usage
        payload = entry.get("payload")
        if not isinstance(payload, dict):
            return None

        usage: Optional[dict] = None

        # Layout 1: payload.TokenCount.info.total_token_usage
        token_count = payload.get("TokenCount")
        if isinstance(token_count, dict):
            info = token_count.get("info")
            if isinstance(info, dict):
                usage = info.get("last_token_usage") or info.get("total_token_usage")

        # Layout 2: event_msg with payload.type == "token_count"
        if usage is None and payload.get("type") == "token_count":
            info = payload.get("info")
            if isinstance(info, dict):
                usage = info.get("last_token_usage") or info.get("total_token_usage")

        if not isinstance(usage, dict):
            return None

        ts_raw = entry.get("timestamp")
        if not ts_raw:
            return None
        try:
            if isinstance(ts_raw, (int, float)):
                ts = datetime.fromtimestamp(ts_raw, tz=timezone.utc)
            else:
                ts = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
        except (ValueError, TypeError, OSError):
            return None

        output = usage.get("output_tokens", 0) + usage.get("reasoning_output_tokens", 0)
        # Codex: input_tokens includes cached_input_tokens (not exclusive)
        # Subtract to avoid double-counting in UsageSnapshot.total
        raw_input = usage.get("input_tokens", 0)
        cached = usage.get("cached_input_tokens", 0)
        return UsageSnapshot(
            timestamp=ts,
            input_tokens=raw_input - cached,
            cache_creation_tokens=0,
            cache_read_tokens=cached,
            output_tokens=output,
        )

# ---------------------------------------------------------------------------
# Cline CLI ui_messages.json parser
# ---------------------------------------------------------------------------

class ClineLogParser(LogParser):
    """Parses Cline CLI ``~/.cline/data/tasks/<task_id>/ui_messages.json`` files.

    Cline stores conversation data as a JSON array of message objects.
    Token usage is embedded in ``api_req_started`` messages whose ``text``
    field is a JSON string containing:

    - ``tokensIn``   -> ``input_tokens``
    - ``tokensOut``  -> ``output_tokens``
    - ``cacheWrites`` -> ``cache_creation_tokens``
    - ``cacheReads``  -> ``cache_read_tokens``
    - ``cost``        -> (not mapped to UsageSnapshot, logged separately)

    The ``ts`` field is a Unix epoch in milliseconds.
    """

    TASKS_DIR = Path.home() / ".cline" / "data" / "tasks"

    @classmethod
    def find_latest_task(cls) -> Optional[Path]:
        """Find the most recently modified ``ui_messages.json`` across all tasks."""
        if not cls.TASKS_DIR.exists():
            return None
        candidates = sorted(
            cls.TASKS_DIR.rglob("ui_messages.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        return candidates[0] if candidates else None

    # ---- LogParser interface ------------------------------------------------

    def parse(self, source: Path) -> List[UsageSnapshot]:
        if not source.exists():
            return []
        try:
            data = json.loads(source.read_text(encoding="utf-8", errors="ignore"))
        except (json.JSONDecodeError, OSError):
            return []
        if not isinstance(data, list):
            return []
        snapshots: List[UsageSnapshot] = []
        for msg in data:
            snap = self._parse_message(msg)
            if snap is not None:
                snapshots.append(snap)
        return snapshots

    def get_latest(self, source: Path) -> Optional[UsageSnapshot]:
        if not source.exists():
            return None
        try:
            data = json.loads(source.read_text(encoding="utf-8", errors="ignore"))
        except (json.JSONDecodeError, OSError):
            return None
        if not isinstance(data, list):
            return None
        for msg in reversed(data):
            snap = self._parse_message(msg)
            if snap is not None:
                return snap
        return None

    # ---- Helpers -----------------------------------------------------------

    @staticmethod
    def _parse_message(msg: dict) -> Optional[UsageSnapshot]:
        if not isinstance(msg, dict):
            return None
        if msg.get("say") != "api_req_started":
            return None
        text = msg.get("text")
        if not text:
            return None
        try:
            inner = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            return None

        tokens_in = inner.get("tokensIn", 0)
        tokens_out = inner.get("tokensOut", 0)
        cache_writes = inner.get("cacheWrites", 0)
        cache_reads = inner.get("cacheReads", 0)

        # Skip entries with no token data (initial request before response)
        if not any((tokens_in, tokens_out, cache_writes, cache_reads)):
            return None

        ts_ms = msg.get("ts")
        if not ts_ms:
            return None
        try:
            ts = datetime.fromtimestamp(int(ts_ms) / 1000, tz=timezone.utc)
        except (ValueError, TypeError, OSError):
            return None

        return UsageSnapshot(
            timestamp=ts,
            input_tokens=tokens_in or 0,
            cache_creation_tokens=cache_writes or 0,
            cache_read_tokens=cache_reads or 0,
            output_tokens=tokens_out or 0,
        )


# ---------------------------------------------------------------------------
# Kimi CLI wire.jsonl parser
# ---------------------------------------------------------------------------

class KimiLogParser(LogParser):
    """Parses Kimi CLI ``~/.kimi/sessions/<hash>/<uuid>/wire.jsonl`` files.

    Kimi stores session Wire events as JSONL.  ``StatusUpdate`` messages
    contain per-step token usage via a ``token_usage`` object:

    - ``input_other``          -> ``input_tokens``
    - ``output``               -> ``output_tokens``
    - ``input_cache_read``     -> ``cache_read_tokens``
    - ``input_cache_creation`` -> ``cache_creation_tokens``

    Additionally, ``context_tokens`` and ``max_context_tokens`` provide
    the context window usage, but those are informational (not mapped to
    UsageSnapshot which tracks per-request token consumption).

    The envelope ``timestamp`` is a Unix epoch in seconds (float).
    """

    SESSIONS_DIR = Path.home() / ".kimi" / "sessions"

    @classmethod
    def find_latest_session(cls, session_id: Optional[str] = None) -> Optional[Path]:
        """Find the most recently modified ``wire.jsonl``.

        If *session_id* is given, look for a matching directory name.
        Otherwise return the most recently modified wire.jsonl across all
        session dirs.
        """
        if not cls.SESSIONS_DIR.exists():
            return None

        if session_id:
            # session_id may match the <uuid> directory name
            for wire in cls.SESSIONS_DIR.rglob("wire.jsonl"):
                if wire.parent.name == session_id:
                    return wire

        candidates = sorted(
            cls.SESSIONS_DIR.rglob("wire.jsonl"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        return candidates[0] if candidates else None

    # ---- LogParser interface ------------------------------------------------

    def parse(self, source: Path) -> List[UsageSnapshot]:
        snapshots: List[UsageSnapshot] = []
        if not source.exists():
            return snapshots
        with open(source, "r", encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                snap = self._parse_line(line)
                if snap is not None:
                    snapshots.append(snap)
        return snapshots

    def get_latest(self, source: Path) -> Optional[UsageSnapshot]:
        if not source.exists():
            return None
        with open(source, "rb") as fh:
            fh.seek(0, 2)
            file_size = fh.tell()
            search_size = min(file_size, 10 * 1024 * 1024)
            fh.seek(max(0, file_size - search_size))
            content = fh.read().decode("utf-8", errors="ignore")
        for line in reversed(content.strip().split("\n")):
            snap = self._parse_line(line)
            if snap is not None:
                return snap
        return None

    # ---- Helpers -----------------------------------------------------------

    @staticmethod
    def _parse_line(line: str) -> Optional[UsageSnapshot]:
        line = line.strip()
        if not line:
            return None
        try:
            entry = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            return None

        msg = entry.get("message")
        if not isinstance(msg, dict):
            return None
        if msg.get("type") != "StatusUpdate":
            return None

        payload = msg.get("payload")
        if not isinstance(payload, dict):
            return None

        usage = payload.get("token_usage")
        if not isinstance(usage, dict):
            return None

        ts_raw = entry.get("timestamp")
        if not ts_raw:
            return None
        try:
            ts = datetime.fromtimestamp(float(ts_raw), tz=timezone.utc)
        except (ValueError, TypeError, OSError):
            return None

        return UsageSnapshot(
            timestamp=ts,
            input_tokens=usage.get("input_other", 0),
            cache_creation_tokens=usage.get("input_cache_creation", 0),
            cache_read_tokens=usage.get("input_cache_read", 0),
            output_tokens=usage.get("output", 0),
        )


# ---------------------------------------------------------------------------
# Session resolver (registry integration)
# ---------------------------------------------------------------------------

class SessionResolver:
    """Maps agent_id → log file paths using the AgentRegistry JSONL."""

    def __init__(
        self,
        registry_path: Path,
        parser: LogParser,
        project_root: Path,
    ):
        self.registry_path = registry_path
        self.parser = parser
        self.project_root = project_root

    def resolve(self) -> Dict[str, List[Path]]:
        """Return {agent_id: [log_file_paths]} from registry entries.

        Resolves log file locations based on the agent's cli_type:
        - claude:   ~/.claude/projects/<encoded_workdir>/<session_id>.jsonl
        - codex:    ~/.codex/sessions/ (matched by session_id in rollout metadata)
        - gemini:   <workdir>/.gemini/telemetry.jsonl
        - opencode: <workdir>/.opencode/opencode.db
        - cline:    ~/.cline/data/tasks/<task_id>/ui_messages.json
        - kimi:     ~/.kimi/sessions/<hash>/<uuid>/wire.jsonl
        """
        if not self.registry_path.exists():
            return {}
        agent_files: Dict[str, List[Path]] = {}
        with open(self.registry_path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                agent_id = data.get("agent_id")
                session_id = data.get("session_id") or data.get("claude_session_id")
                cli_type = data.get("cli_type", "")
                working_dir = data.get("working_dir", "") or data.get("cwd", "")
                if working_dir:
                    full_path = str(self.project_root / working_dir)
                else:
                    full_path = str(self.project_root)

                if not agent_id:
                    continue

                log_path: Optional[Path] = None

                if cli_type == "claude":
                    if not session_id:
                        continue
                    log_path = ClaudeCodeLogParser.session_log_path(full_path, session_id)
                elif cli_type == "codex":
                    if session_id:
                        log_path = CodexLogParser.find_session_file(session_id)
                elif cli_type == "gemini":
                    log_path = GeminiLogParser.find_session_file(full_path)
                elif cli_type == "opencode":
                    log_path = Path(full_path) / ".opencode" / "opencode.db"
                elif cli_type == "cline":
                    if session_id:
                        p = ClineLogParser.TASKS_DIR / session_id / "ui_messages.json"
                        if p.exists():
                            log_path = p
                    if log_path is None:
                        log_path = ClineLogParser.find_latest_task()
                elif cli_type == "kimi":
                    log_path = KimiLogParser.find_latest_session(session_id or None)
                else:
                    continue

                if log_path is not None and log_path.exists():
                    agent_files.setdefault(agent_id, []).append(log_path)
        return agent_files


# ---------------------------------------------------------------------------
# Context monitor (core)
# ---------------------------------------------------------------------------

class ContextMonitor:
    """CLI-agnostic context usage monitor with visualization."""

    def __init__(
        self,
        config: ContextConfig,
        parser: LogParser,
        output_dir: Path,
        *,
        use_cache: bool = True,
        cache_dir: Optional[Path] = None,
        max_minutes: Optional[int] = None,
    ):
        self.config = config
        self.parser = parser
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.max_minutes = max_minutes
        self.use_cache = use_cache
        self.cache_dir = cache_dir or (output_dir.parent / ".cache" / "context_monitor")
        if self.use_cache:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._is_cumulative = False

    # ---- Cache -------------------------------------------------------------

    def _cache_path(self, agent_id: str, source: Path) -> Path:
        return self.cache_dir / f"{agent_id}_{source.stem}.pkl.gz"

    def _load_cache(self, cache_path: Path, source: Path) -> Optional[List[UsageSnapshot]]:
        if not self.use_cache or not cache_path.exists():
            return None
        if source.stat().st_mtime > cache_path.stat().st_mtime:
            return None
        try:
            with gzip.open(cache_path, "rb") as fh:
                return pickle.load(fh)  # noqa: S301
        except Exception:
            return None

    def _save_cache(self, cache_path: Path, data: List[UsageSnapshot]) -> None:
        if not self.use_cache:
            return
        try:
            with gzip.open(cache_path, "wb") as fh:
                pickle.dump(data, fh, protocol=pickle.HIGHEST_PROTOCOL)
        except Exception:
            pass

    # ---- Data loading ------------------------------------------------------

    def load_snapshots(
        self,
        source: Path,
        agent_id: str,
        *,
        last_n: Optional[int] = None,
        max_minutes: Optional[int] = None,
    ) -> List[UsageSnapshot]:
        """Load snapshots from *source*, with optional cache, time and count limits."""
        cp = self._cache_path(agent_id, source)
        cached = self._load_cache(cp, source)
        if cached is not None:
            filtered = self._apply_time_filter(cached, max_minutes)
            if last_n and len(filtered) > last_n:
                return filtered[-last_n:]
            return filtered

        snapshots = self.parser.parse(source)
        self._save_cache(cp, snapshots)

        filtered = self._apply_time_filter(snapshots, max_minutes)
        if last_n and len(filtered) > last_n:
            return filtered[-last_n:]
        return filtered

    @staticmethod
    def _apply_time_filter(
        snapshots: List[UsageSnapshot], max_minutes: Optional[int]
    ) -> List[UsageSnapshot]:
        if not max_minutes or not snapshots:
            return snapshots
        first_ts = min(s.timestamp for s in snapshots)
        cutoff = first_ts + timedelta(minutes=max_minutes)
        return [s for s in snapshots if s.timestamp <= cutoff]

    # ---- Token calculation -------------------------------------------------

    @staticmethod
    def calculate_tokens(
        snapshots: List[UsageSnapshot], *, cumulative: bool = False
    ) -> List[Tuple[datetime, Dict[str, int]]]:
        """Convert snapshots → [(timestamp, token_dict)] with optional accumulation."""
        result: List[Tuple[datetime, Dict[str, int]]] = []
        totals = {"input": 0, "cache_creation": 0, "cache_read": 0, "output": 0}
        for snap in snapshots:
            if cumulative:
                totals["input"] += snap.input_tokens
                totals["cache_creation"] += snap.cache_creation_tokens
                totals["cache_read"] += snap.cache_read_tokens
                totals["output"] += snap.output_tokens
                d = dict(totals)
                d["total"] = sum(totals.values())
                result.append((snap.timestamp, d))
            else:
                result.append((snap.timestamp, snap.to_dict()))
        return result

    # ---- Collect all agents ------------------------------------------------

    def collect_all(
        self,
        agent_files: Dict[str, List[Path]],
        *,
        cumulative: bool = False,
        last_n: Optional[int] = None,
        max_minutes: Optional[int] = None,
    ) -> Dict[str, List[Tuple[datetime, Dict[str, int]]]]:
        """Load and process data for all agents."""
        self._is_cumulative = cumulative
        all_data: Dict[str, List[Tuple[datetime, Dict[str, int]]]] = {}
        effective_max = max_minutes or self.max_minutes
        for agent_id, files in agent_files.items():
            all_snaps: List[UsageSnapshot] = []
            for f in sorted(files):
                all_snaps.extend(
                    self.load_snapshots(f, agent_id, last_n=last_n, max_minutes=effective_max)
                )
            if all_snaps:
                all_snaps.sort(key=lambda s: s.timestamp)
                # If the parser reports cumulative values, convert to deltas
                # before applying our own cumulative aggregation.
                if self.parser.snapshots_are_cumulative:
                    all_snaps = LogParser.to_deltas(all_snaps)
                all_data[agent_id] = self.calculate_tokens(all_snaps, cumulative=cumulative)
        return all_data

    # ---- Quick status ------------------------------------------------------

    def print_quick_status(
        self,
        all_agent_data: Dict[str, List[Tuple[datetime, Dict[str, int]]]],
        target_agent: Optional[str] = None,
    ) -> None:
        """Print console status table."""
        print("\n" + "=" * 60)
        print(f"Context Usage Status - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 60)

        if target_agent:
            filtered = {
                k: v for k, v in all_agent_data.items()
                if target_agent.upper() in k.upper()
            }
        else:
            filtered = all_agent_data

        if not filtered:
            print(f"No data found" + (f" for '{target_agent}'" if target_agent else ""))
            return

        print(f"{'Agent':<12} {'Total':>10} {'%':>6} {'Status':<10} {'Est.Time':<10}")
        print("-" * 54)

        rows: List[Dict[str, Any]] = []
        for agent_id, token_data in filtered.items():
            if not token_data:
                continue
            _, latest = token_data[-1]
            total = latest["total"]
            pct = (total / self.config.auto_compact_tokens) * 100

            if total >= self.config.auto_compact_tokens * 0.95:
                status = "CRITICAL"
            elif total >= self.config.warning_tokens:
                status = "WARNING"
            else:
                status = "OK"

            est = "N/A"
            if len(token_data) >= 2:
                recent = token_data[-min(10, len(token_data)):]
                span_h = (recent[-1][0] - recent[0][0]).total_seconds() / 3600
                increase = recent[-1][1]["total"] - recent[0][1]["total"]
                if span_h > 0 and increase > 0:
                    remaining = self.config.auto_compact_tokens - total
                    if remaining > 0:
                        hours = remaining / (increase / span_h)
                        est = f"{int(hours * 60)}min" if hours < 1 else f"{hours:.1f}h"

            rows.append({"agent_id": agent_id, "total": total, "pct": pct,
                         "status": status, "est": est})

        rows.sort(key=lambda r: r["total"], reverse=True)
        for r in rows:
            print(
                f"{r['agent_id']:<12} {r['total']:>10,} {r['pct']:>5.1f}% "
                f"{r['status']:<10} {r['est']:<10}"
            )
        print("=" * 60)

    # ---- Threshold line helpers --------------------------------------------

    def _draw_threshold_lines(self, ax: Any) -> None:
        """Draw warning and auto-compact threshold lines on *ax*."""
        if self.config.auto_compact_line is not None:
            ax.axhline(
                y=self.config.auto_compact_line, color="red",
                linestyle="--", linewidth=2,
                label=f"Auto-compact ({self.config.auto_compact_line // 1000}K)",
            )
        if self.config.warning_line:
            ax.axhline(
                y=self.config.warning_line, color="orange",
                linestyle="--", linewidth=1,
                label=f"Warning ({self.config.warning_line // 1000}K)",
            )

    # ---- Visualization entry point -----------------------------------------

    def generate_all_graphs(
        self,
        all_agent_data: Dict[str, List[Tuple[datetime, Dict[str, int]]]],
        graph_type: str = "all",
        time_unit: str = "minutes",
    ) -> List[Path]:
        """Generate requested graph types. Returns list of output file paths."""
        outputs: List[Path] = []

        if graph_type in ("all", "overview"):
            outputs.extend(self._gen_overview(all_agent_data, time_unit))
        if graph_type in ("all", "stacked"):
            outputs.append(self._gen_stacked(all_agent_data, x_axis="count"))
            outputs.append(self._gen_stacked(all_agent_data, x_axis="time"))
        if graph_type in ("all", "timeline"):
            outputs.append(self._gen_timeline(all_agent_data))
        if graph_type in ("all", "individual"):
            for aid, data in all_agent_data.items():
                if data:
                    outputs.extend(self._gen_individual(aid, data, include_count=False))
        if graph_type == "count":
            for aid, data in all_agent_data.items():
                if data:
                    outputs.extend(self._gen_individual(aid, data, include_count=True))
        return [p for p in outputs if p is not None]

    # ---- Overview line graph -----------------------------------------------

    def _project_start(
        self, all_data: Dict[str, List[Tuple[datetime, Dict[str, int]]]]
    ) -> Optional[datetime]:
        start: Optional[datetime] = None
        for entries in all_data.values():
            if entries:
                t = entries[0][0]
                if start is None or t < start:
                    start = t
        return start

    def _gen_overview(
        self,
        all_data: Dict[str, List[Tuple[datetime, Dict[str, int]]]],
        time_unit: str,
    ) -> List[Path]:
        outputs: List[Path] = []
        if self.max_minutes:
            # Milestone snapshot: generate only the requested time window
            outputs.append(self._gen_single_overview(all_data, time_unit, self.max_minutes))
        else:
            # Regular run: autoscale overview + 200K fixed-ylim
            outputs.append(self._gen_single_overview(all_data, time_unit, None))
            outputs.append(self._gen_single_overview(
                all_data, time_unit, None,
                ylim_override=(0, 210_000),
                fname_override="overview_200k.png",
            ))
        return outputs

    def _gen_single_overview(
        self,
        all_data: Dict[str, List[Tuple[datetime, Dict[str, int]]]],
        time_unit: str,
        max_minutes: Optional[int],
        ylim_override: Optional[Tuple[float, float]] = None,
        fname_override: Optional[str] = None,
    ) -> Path:
        fig = plt.figure(figsize=(12, 8))
        fig.set_facecolor("white")
        ax = fig.gca()
        ax.set_facecolor("white")
        title_suffix = f" (First {max_minutes} minutes)" if max_minutes else ""
        start = self._project_start(all_data)

        filtered: Dict[str, List[Tuple[datetime, Dict[str, int]]]] = {}
        if start:
            for aid, entries in all_data.items():
                if max_minutes:
                    f = [
                        (t, tok) for t, tok in entries
                        if t >= start and (t - start).total_seconds() / 60 <= max_minutes
                    ]
                else:
                    f = [(t, tok) for t, tok in entries if t >= start]
                if f:
                    filtered[aid] = f
        else:
            filtered = all_data

        divisor = {"seconds": 1, "minutes": 60, "hours": 3600}[time_unit]
        for aid, entries in filtered.items():
            if not entries or start is None:
                continue
            times = [(t - start).total_seconds() / divisor for t, _ in entries]
            totals = [tok["total"] for _, tok in entries]
            plt.step(times, totals, where="post", marker="o", markersize=3,
                     label=aid, alpha=0.8)

        self._draw_threshold_lines(ax)

        unit_label = {"seconds": "Seconds", "minutes": "Minutes", "hours": "Hours"}[time_unit]
        plt.xlabel(f"{unit_label} from Start")
        if self._is_cumulative:
            plt.ylabel("Cumulative Token Usage")
            plt.title(f"Cumulative Token Usage Over Time{title_suffix}")
        else:
            plt.ylabel("Current Context Usage [tokens]")
            plt.title(f"Context Usage Monitor{title_suffix}")
        plt.legend(loc="upper left", bbox_to_anchor=(1.02, 1))
        plt.grid(True, alpha=0.3)
        plt.gca().yaxis.set_major_formatter(
            plt.FuncFormatter(lambda x, _: f"{int(x / 1000)}K")
        )
        if ylim_override:
            plt.ylim(*ylim_override)
        else:
            plt.ylim(0, self.config.context_limit * 1.05)
        if max_minutes:
            plt.xlim(0, max_minutes)
        plt.tight_layout()

        if fname_override:
            fname = fname_override
        elif max_minutes:
            fname = f"overview_{max_minutes}min.png"
        else:
            fname = "overview.png"
        ctx_dir = self.output_dir / "context"
        ctx_dir.mkdir(parents=True, exist_ok=True)
        out = ctx_dir / fname
        plt.savefig(out, dpi=120, bbox_inches="tight")
        plt.close()
        return out

    # ---- Stacked bar / area ------------------------------------------------

    def _gen_stacked(
        self,
        all_data: Dict[str, List[Tuple[datetime, Dict[str, int]]]],
        x_axis: str = "count",
    ) -> Path:
        fig, ax = plt.subplots(figsize=(16, 10))
        fig.set_facecolor("white")
        ax.set_facecolor("white")
        token_types = ["cache_read", "cache_creation", "input", "output"]
        colors = {
            "cache_read": "#f39c12",
            "cache_creation": "#2ecc71",
            "input": "#3498db",
            "output": "#e74c3c",
        }

        if x_axis == "count":
            for idx, (aid, entries) in enumerate(all_data.items()):
                if not entries:
                    continue
                _, latest = entries[-1]
                bottom = 0
                for tt in token_types:
                    v = latest[tt]
                    ax.bar(idx, v, 0.8, bottom=bottom, color=colors[tt],
                           label=tt if idx == 0 else "")
                    bottom += v
                total = latest["total"]
                pct = (total / self.config.auto_compact_tokens) * 100
                ax.text(idx, total + 2000, f"{total:,}\n({pct:.1f}%)",
                        ha="center", va="bottom", fontsize=9)
            ax.set_xticks(range(len(all_data)))
            ax.set_xticklabels(list(all_data.keys()))
            ax.set_xlabel("Agents")
        else:
            max_agent = max(all_data.items(),
                            key=lambda x: x[1][-1][1]["total"] if x[1] else 0)[0]
            if all_data[max_agent]:
                entries = all_data[max_agent]
                times = [t for t, _ in entries]
                vals = {tt: np.array([tok[tt] for _, tok in entries]) for tt in token_types}
                bottom = np.zeros(len(times))
                for tt in token_types:
                    ax.fill_between(times, bottom, bottom + vals[tt],
                                    color=colors[tt], label=tt, alpha=0.8)
                    bottom += vals[tt]
                ax.set_xlabel("Time")
                ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d %H:%M"))
                plt.xticks(rotation=45)
                ax.set_title(f"Token Usage Timeline - {max_agent}")

        self._draw_threshold_lines(ax)
        ax.set_ylabel("Tokens")
        if x_axis == "count":
            ax.set_title(f"Token Usage (X-axis: {x_axis})")
        ax.legend(loc="upper left", bbox_to_anchor=(1.02, 1))
        ax.grid(True, alpha=0.3, axis="y")
        ax.set_ylim(0, self.config.context_limit * 1.05)
        ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"{int(x / 1000)}K"))
        plt.tight_layout()

        details_dir = self.output_dir / "context" / "details"
        details_dir.mkdir(parents=True, exist_ok=True)
        out = details_dir / f"stacked_{x_axis}.png"
        plt.savefig(out, dpi=150, bbox_inches="tight")
        plt.close()
        return out

    # ---- Timeline with growth rate -----------------------------------------

    def _gen_timeline(
        self, all_data: Dict[str, List[Tuple[datetime, Dict[str, int]]]]
    ) -> Path:
        fig, (ax1, ax2) = plt.subplots(
            2, 1, figsize=(14, 10), gridspec_kw={"height_ratios": [2, 1]}
        )
        fig.set_facecolor("white")
        ax1.set_facecolor("white")
        ax2.set_facecolor("white")
        for aid, entries in all_data.items():
            if not entries:
                continue
            times = [t for t, _ in entries]
            totals = [tok["total"] for _, tok in entries]
            cur = totals[-1] if totals else 0
            if cur >= self.config.auto_compact_tokens * 0.95:
                color, alpha = "red", 1.0
            elif cur >= self.config.warning_tokens:
                color, alpha = "orange", 0.8
            else:
                color, alpha = "blue", 0.6
            ax1.step(times, totals, where="post", marker="o", markersize=3,
                     label=f"{aid} ({cur / 1000:.0f}K)", color=color, alpha=alpha)

        self._draw_threshold_lines(ax1)
        ax1.set_ylabel("Total Tokens")
        ax1.set_title("Context Usage Timeline & Auto-compact Prediction")
        ax1.legend(loc="upper left", bbox_to_anchor=(1.02, 1))
        ax1.grid(True, alpha=0.3)
        ax1.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"{int(x / 1000)}K"))

        # Growth rates
        for aid, entries in all_data.items():
            if len(entries) < 2:
                continue
            times = [t for t, _ in entries]
            totals = [tok["total"] for _, tok in entries]
            rates, rtimes = [], []
            for i in range(1, len(times)):
                dt_h = (times[i] - times[i - 1]).total_seconds() / 3600
                if dt_h > 0:
                    rates.append((totals[i] - totals[i - 1]) / dt_h)
                    rtimes.append(times[i])
            if rates:
                ax2.plot(rtimes, rates, marker="o", markersize=3, label=aid, alpha=0.7)

        ax2.set_xlabel("Time")
        ax2.set_ylabel("Growth Rate (tokens/hour)")
        ax2.set_title("Token Growth Rate Analysis")
        ax2.legend(loc="upper left", bbox_to_anchor=(1.02, 1))
        ax2.grid(True, alpha=0.3)
        ax2.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d %H:%M"))
        plt.setp(ax2.xaxis.get_majorticklabels(), rotation=45)

        plt.tight_layout()
        details_dir = self.output_dir / "context" / "details"
        details_dir.mkdir(parents=True, exist_ok=True)
        out = details_dir / "timeline.png"
        plt.savefig(out, dpi=150, bbox_inches="tight")
        plt.close()
        return out

    # ---- Individual agent detail -------------------------------------------

    def _gen_individual(
        self, agent_id: str, entries: List[Tuple[datetime, Dict[str, int]]],
        include_count: bool = True,
    ) -> List[Path]:
        outputs: List[Path] = []

        # 1. Stacked area + ratio
        fig, (ax1, ax2) = plt.subplots(
            2, 1, figsize=(14, 10), gridspec_kw={"height_ratios": [2, 1]}
        )
        fig.set_facecolor("white")
        ax1.set_facecolor("white")
        ax2.set_facecolor("white")
        times = [t for t, _ in entries]
        token_types = ["cache_read", "cache_creation", "input", "output"]
        tcolors = {
            "cache_read": "#f39c12", "cache_creation": "#2ecc71",
            "input": "#3498db", "output": "#e74c3c",
        }
        vals = {tt: np.array([tok[tt] for _, tok in entries]) for tt in token_types}
        bottom = np.zeros(len(times))
        for tt in token_types:
            ax1.fill_between(times, bottom, bottom + vals[tt],
                             color=tcolors[tt], label=tt, alpha=0.8)
            bottom += vals[tt]

        latest = entries[-1][1]
        total = latest["total"]
        pct = (total / self.config.auto_compact_tokens) * 100
        self._draw_threshold_lines(ax1)
        ax1.set_ylabel("Tokens")
        ax1.set_title(f"{agent_id} - Token Detail ({total:,} tokens, {pct:.1f}%)")
        ax1.legend(loc="upper left")
        ax1.grid(True, alpha=0.3)
        ax1.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"{int(x / 1000)}K"))
        ax1.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d %H:%M"))

        # Ratio subplot
        for tt in token_types:
            ratios = []
            for _, tok in entries:
                t = tok["total"]
                ratios.append(100 * tok[tt] / t if t > 0 else 0)
            ax2.plot(times, ratios, marker="o", markersize=3, label=f"{tt} %", alpha=0.7)
        ax2.set_xlabel("Time")
        ax2.set_ylabel("Token Type Ratio (%)")
        ax2.set_title("Token Type Distribution Over Time")
        ax2.legend(loc="upper left", bbox_to_anchor=(1.02, 1))
        ax2.grid(True, alpha=0.3)
        ax2.set_ylim(0, 100)
        ax2.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d %H:%M"))
        plt.setp(ax2.xaxis.get_majorticklabels(), rotation=45)
        plt.tight_layout()

        details_dir = self.output_dir / "context" / "details"
        details_dir.mkdir(parents=True, exist_ok=True)
        out = details_dir / f"{agent_id}_detail.png"
        plt.savefig(out, dpi=150, bbox_inches="tight")
        plt.close()
        outputs.append(out)

        if not include_count:
            return outputs

        # 2. Count-based graph (only with --graph-type all)
        fig, ax = plt.subplots(figsize=(12, 8))
        fig.set_facecolor("white")
        ax.set_facecolor("white")
        counts = list(range(1, len(entries) + 1))
        totals = [tok["total"] for _, tok in entries]
        colors = []
        for t in totals:
            if t >= self.config.auto_compact_tokens * 0.95:
                colors.append("red")
            elif t >= self.config.warning_tokens:
                colors.append("orange")
            else:
                colors.append("blue")
        ax.scatter(counts, totals, c=colors, s=50, alpha=0.7, edgecolors="black")
        ax.plot(counts, totals, "b-", alpha=0.3)
        self._draw_threshold_lines(ax)
        ax.set_xlabel("Log Entry Count")
        ax.set_ylabel("Total Tokens")
        ax.set_title(f"{agent_id} - Token Usage by Log Count")
        ax.legend()
        ax.grid(True, alpha=0.3)
        ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"{int(x / 1000)}K"))
        plt.tight_layout()
        out2 = details_dir / f"{agent_id}_count.png"
        plt.savefig(out2, dpi=120, bbox_inches="tight")
        plt.close()
        outputs.append(out2)

        return outputs

    # ---- Summary report ----------------------------------------------------

    def generate_summary_report(
        self, all_agent_data: Dict[str, List[Tuple[datetime, Dict[str, int]]]]
    ) -> Path:
        """Generate a Markdown summary report."""
        report_path = self.output_dir / "context_usage_report.md"
        with open(report_path, "w", encoding="utf-8") as f:
            if self._is_cumulative:
                f.write("# Cumulative Token Usage Report\n\n")
            else:
                f.write("# Context Usage Report\n\n")
            f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            f.write("## Summary\n\n")
            f.write(
                "| Agent | Total | Usage% | Cache Read | Cache Create "
                "| Input | Output | Est.Time |\n"
            )
            f.write(
                "|-------|-------|--------|------------|-------------|"
                "-------|--------|----------|\n"
            )

            summaries: List[Dict[str, Any]] = []
            for aid, entries in all_agent_data.items():
                if not entries:
                    continue
                _, latest = entries[-1]
                total = latest["total"]
                pct = (total / self.config.auto_compact_tokens) * 100
                est = "N/A"
                if len(entries) >= 2:
                    recent = entries[-min(10, len(entries)):]
                    span_h = (recent[-1][0] - recent[0][0]).total_seconds() / 3600
                    inc = recent[-1][1]["total"] - recent[0][1]["total"]
                    if span_h > 0 and inc > 0:
                        rem = self.config.auto_compact_tokens - total
                        if rem > 0:
                            est = f"{rem / (inc / span_h):.1f}h"
                summaries.append({"aid": aid, "total": total, "pct": pct,
                                  "tok": latest, "est": est})

            summaries.sort(key=lambda s: s["total"], reverse=True)
            for s in summaries:
                tok = s["tok"]
                f.write(
                    f"| {s['aid']} | {s['total']:,} | {s['pct']:.1f}% "
                    f"| {tok['cache_read']:,} | {tok['cache_creation']:,} "
                    f"| {tok['input']:,} | {tok['output']:,} | {s['est']} |\n"
                )
        return report_path


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _build_parser() -> "argparse.ArgumentParser":
    import argparse

    parser = argparse.ArgumentParser(
        description="Context usage monitor — parse CLI logs and generate token usage visualizations.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
parsers:
  claude   Parse Claude Code session JSONL (~/.claude/projects/<dir>/<session>.jsonl)
  codex    Parse Codex rollout JSONL (~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl)
  gemini   Parse Gemini telemetry JSONL (telemetry.outfile or ~/.gemini/tmp/telemetry.jsonl)
  opencode Parse OpenCode SQLite DB (.opencode/opencode.db)
  cline    Parse Cline CLI ui_messages.json (~/.cline/data/tasks/<task_id>/ui_messages.json)
  kimi     Parse Kimi CLI wire.jsonl (~/.kimi/sessions/<hash>/<uuid>/wire.jsonl)
  qwen     Parse Qwen Code chat JSONL (~/.qwen/projects/<dir>/chats/<session>.jsonl)
  all      Multi-CLI overview — reads registry, discovers all agents, unified output

examples:
  %(prog)s claude ~/.claude/projects/myproject/session.jsonl --status
  %(prog)s codex ~/.codex/sessions/2026/03/17/rollout-*.jsonl --visualize -o ./viz
  %(prog)s gemini /path/to/telemetry.jsonl --status --json
  %(prog)s claude /path/to/log.jsonl --visualize --context-limit 200000
  %(prog)s codex --find-latest --status
  %(prog)s cline ~/.cline/data/tasks/1774011856538/ui_messages.json --status
  %(prog)s kimi --find-latest --status
  %(prog)s qwen ~/.qwen/projects/-mnt-myproject/chats/abc123.jsonl --status
  %(prog)s all --registry Agent-shared/agent_and_pane_id_table.jsonl --status
  %(prog)s all --visualize -o User-shared/visualizations/
""",
    )
    parser.add_argument(
        "parser_type",
        choices=["claude", "codex", "gemini", "opencode", "cline", "kimi", "qwen", "all"],
        help="Log parser type ('all' for multi-CLI overview via registry)",
    )
    parser.add_argument(
        "log_file",
        nargs="?",
        help="Path to log file (or use --find-latest for auto-detection)",
    )
    parser.add_argument("--find-latest", action="store_true",
                        help="Auto-find the most recent log file for the parser type")
    parser.add_argument("--status", action="store_true",
                        help="Print quick status summary to console")
    parser.add_argument("--visualize", action="store_true",
                        help="Generate visualization PNGs (requires matplotlib)")
    parser.add_argument("-o", "--output-dir", default=".",
                        help="Output directory for visualizations (default: current dir)")
    parser.add_argument("--context-limit", type=int, default=1_000_000,
                        help="Context window size in tokens (default: 1000000)")
    parser.add_argument("--warning-line", type=int, default=200_000,
                        help="Warning threshold line in tokens (default: 200000)")
    parser.add_argument("--max-minutes", type=int, default=0,
                        help="Limit to first N minutes of data (0=unlimited)")
    parser.add_argument("--cumulative", action="store_true", default=False,
                        help="Show cumulative token usage (default: per-request snapshot)")
    parser.add_argument("--json", action="store_true",
                        help="Output status in JSON format")
    parser.add_argument("--agent-label", default=None,
                        help="Label for the agent in graphs (default: parser type)")
    parser.add_argument("--registry", default=None,
                        help="Path to registry JSONL (required for 'all' mode; auto-detects Agent-shared/agent_and_pane_id_table.jsonl)")
    parser.add_argument("--graph-type", default="all",
                        choices=["all", "overview", "stacked", "timeline", "individual", "count"],
                        help="Type of graphs to generate (default: all)")
    parser.add_argument("--time-unit", default="minutes",
                        choices=["seconds", "minutes", "hours"],
                        help="Time unit for X-axis (default: minutes)")
    return parser


def _resolve_registry_path(args_registry: Optional[str]) -> Optional[Path]:
    """Find the registry JSONL file.

    Search order:
    1. Explicit ``--registry`` path
    2. Walk upward from cwd looking for ``Agent-shared/agent_and_pane_id_table.jsonl``
    """
    if args_registry:
        p = Path(args_registry)
        if p.exists():
            return p
        return None

    # Auto-detect: walk upward from cwd
    cur = Path.cwd()
    for _ in range(10):
        candidate = cur / "Agent-shared" / "agent_and_pane_id_table.jsonl"
        if candidate.exists():
            return candidate
        parent = cur.parent
        if parent == cur:
            break
        cur = parent
    return None


def _resolve_log_for_agent(
    agent_id: str,
    cli_type: str,
    session_id: str,
    working_dir: str,
) -> Optional[Path]:
    """Resolve log file path for a single agent based on its CLI type."""
    if cli_type == "claude":
        if not session_id:
            return None
        return ClaudeCodeLogParser.session_log_path(working_dir, session_id)
    elif cli_type == "codex":
        if session_id:
            return CodexLogParser.find_session_file(session_id)
        return CodexLogParser.find_session_file()  # latest
    elif cli_type == "gemini":
        return GeminiLogParser.find_session_file(working_dir or None)
    elif cli_type == "opencode":
        return OpenCodeLogParser.db_path()
    elif cli_type == "cline":
        if session_id:
            # session_id is the task_id (timestamp) for Cline
            p = ClineLogParser.TASKS_DIR / session_id / "ui_messages.json"
            if p.exists():
                return p
        return ClineLogParser.find_latest_task()
    elif cli_type == "kimi":
        return KimiLogParser.find_latest_session(session_id or None)
    elif cli_type == "qwen":
        if session_id and working_dir:
            p = QwenLogParser.session_log_path(working_dir, session_id)
            if p.exists():
                return p
        return QwenLogParser.find_session_file(working_dir or None)
    elif cli_type == "vibe-local":
        # vibe-local has no persistent token log; runtime-only estimates
        return None
    return None


def _parser_for_cli_type(cli_type: str) -> Optional[LogParser]:
    """Return the appropriate LogParser for a CLI type."""
    parsers = {
        "claude": ClaudeCodeLogParser,
        "codex": CodexLogParser,
        "gemini": GeminiLogParser,
        "opencode": OpenCodeLogParser,
        "cline": ClineLogParser,
        "kimi": KimiLogParser,
        "qwen": QwenLogParser,
    }
    cls = parsers.get(cli_type)
    return cls() if cls else None


def _run_all_mode(args) -> None:
    """Execute 'all' mode: read registry, parse all agents, unified output."""
    import sys

    registry_path = _resolve_registry_path(args.registry)
    if registry_path is None:
        print("Error: registry not found. Use --registry or run from the project root.", file=sys.stderr)
        sys.exit(1)

    # Read registry entries
    agents = []
    with open(registry_path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            status = data.get("status", "")
            if status in ("dead", "stopped"):
                continue
            agents.append(data)

    if not agents:
        print("No active agents found in registry.", file=sys.stderr)
        sys.exit(1)

    # Collect data for all agents
    all_data: Dict[str, List[Tuple[datetime, Dict[str, int]]]] = {}
    all_status: List[Dict[str, Any]] = []

    for entry in agents:
        agent_id = entry.get("agent_id", "unknown")
        cli_type = entry.get("cli_type", "")
        session_id = entry.get("session_id", "") or ""
        raw_working_dir = entry.get("working_dir", "") or ""
        # Resolve relative working_dir against registry file's parent (project root)
        if raw_working_dir and not Path(raw_working_dir).is_absolute():
            registry_dir = Path(args.registry).resolve().parent.parent  # Agent-shared/../
            working_dir = str((registry_dir / raw_working_dir).resolve())
        else:
            working_dir = raw_working_dir

        log_path = _resolve_log_for_agent(agent_id, cli_type, session_id, working_dir)
        if log_path is None or not log_path.exists():
            if args.status and not args.json:
                print(f"  {agent_id} ({cli_type}): log not found", file=sys.stderr)
            continue

        parser_inst = _parser_for_cli_type(cli_type)
        if parser_inst is None:
            continue

        # OpenCode uses a global DB; filter by session_id if available
        if cli_type == "opencode" and session_id and isinstance(parser_inst, OpenCodeLogParser):
            snapshots = parser_inst.parse_session(log_path, session_id)
        else:
            snapshots = parser_inst.parse(log_path)
        if not snapshots:
            continue

        # If the parser already reports cumulative values (e.g. Codex),
        # convert to per-request deltas first to avoid double-counting.
        if parser_inst.snapshots_are_cumulative:
            delta_snaps = LogParser.to_deltas(snapshots)
        else:
            delta_snaps = snapshots

        if args.cumulative:
            # Cumulative mode: running total over time
            running_total = {"input": 0, "cache_creation": 0, "cache_read": 0, "output": 0, "total": 0}
            data_points: List[Tuple[datetime, Dict[str, int]]] = []
            for snap in delta_snaps:
                d = snap.to_dict()
                for k in running_total:
                    running_total[k] += d[k]
                data_points.append((snap.timestamp, dict(running_total)))
            last_total = running_total
        else:
            # Snapshot mode (default): each point is the per-request token count
            # (context window usage at that moment — drops after auto-compact)
            data_points = [(snap.timestamp, snap.to_dict()) for snap in delta_snaps]
            last_total = data_points[-1][1] if data_points else {"input": 0, "cache_creation": 0, "cache_read": 0, "output": 0, "total": 0}

        # For cumulative totals in status, always sum up the deltas
        cumulative_total = {"input": 0, "cache_creation": 0, "cache_read": 0, "output": 0, "total": 0}
        for snap in delta_snaps:
            d = snap.to_dict()
            for k in cumulative_total:
                cumulative_total[k] += d[k]

        label = f"{agent_id}({cli_type})"
        all_data[label] = data_points
        all_status.append({
            "agent": agent_id,
            "cli_type": cli_type,
            "label": label,
            "log_file": str(log_path),
            "snapshots": len(snapshots),
            "total_tokens": cumulative_total["total"],
            "cumulative_tokens": cumulative_total["total"],
            "input_tokens": cumulative_total["input"],
            "output_tokens": cumulative_total["output"],
            "cache_read_tokens": cumulative_total["cache_read"],
            "cache_creation_tokens": cumulative_total["cache_creation"],
        })

    if not all_data:
        print("No token usage data found for any agent.", file=sys.stderr)
        sys.exit(1)

    # Status output
    if args.status:
        if args.json:
            for s in all_status:
                s["context_limit"] = args.context_limit
                s["usage_pct"] = (s["total_tokens"] / args.context_limit * 100) if args.context_limit > 0 else 0
            print(json.dumps(all_status, indent=2, default=str))
        else:
            print(f"\n{'='*60}")
            print(f"Context Monitor — All Agents ({len(all_data)} active)")
            print(f"{'='*60}")
            print(f"{'Agent':<20} {'CLI':<10} {'Snapshots':>10} {'Total Tokens':>14} {'%':>7}")
            print("-" * 65)
            for s in all_status:
                pct = s["total_tokens"] / args.context_limit * 100 if args.context_limit > 0 else 0
                print(f"{s['agent']:<20} {s['cli_type']:<10} {s['snapshots']:>10} {s['total_tokens']:>14,} {pct:>6.1f}%")
            print("-" * 65)
            grand_total = sum(s["total_tokens"] for s in all_status)
            print(f"{'TOTAL':<20} {'':10} {sum(s['snapshots'] for s in all_status):>10} {grand_total:>14,}")

    # Visualization
    if args.visualize:
        output_dir = Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        config = ContextConfig(
            context_limit=args.context_limit,
            warning_line=args.warning_line,
        )
        # Use ClaudeCodeLogParser as a dummy — ContextMonitor only uses it for caching
        monitor = ContextMonitor(
            config=config,
            parser=ClaudeCodeLogParser(),
            output_dir=output_dir,
            max_minutes=args.max_minutes if args.max_minutes > 0 else None,
        )
        monitor._is_cumulative = args.cumulative

        paths = monitor.generate_all_graphs(
            all_data,
            graph_type=args.graph_type,
            time_unit=args.time_unit,
        )
        print(f"Generated {len(paths)} visualization(s):")
        for p in paths:
            print(f"  {p}")

    if not args.status and not args.visualize:
        # Default: compact summary
        for label, data_points in all_data.items():
            if data_points:
                _, latest = data_points[-1]
                pct = latest["total"] / args.context_limit * 100 if args.context_limit > 0 else 0
                print(f"{label}: {len(data_points)} snapshots, {latest['total']:,} tokens ({pct:.1f}%)")


def main():
    import argparse
    import sys

    parser = _build_parser()
    args = parser.parse_args()

    # All mode: multi-CLI overview via registry
    if args.parser_type == "all":
        _run_all_mode(args)
        return

    # Resolve parser
    log_parser = _parser_for_cli_type(args.parser_type)
    if log_parser is None:
        print(f"Error: unknown parser type: {args.parser_type}", file=sys.stderr)
        sys.exit(1)

    # Resolve log file
    log_file = None
    if args.log_file:
        log_file = Path(args.log_file)
    elif args.find_latest:
        if args.parser_type == "codex":
            log_file = CodexLogParser.find_session_file()
        elif args.parser_type == "gemini":
            log_file = GeminiLogParser.find_session_file()
        elif args.parser_type == "claude":
            # Find most recent session across all projects
            projects_dir = Path.home() / ".claude" / "projects"
            if projects_dir.exists():
                jsonl_files = sorted(
                    projects_dir.rglob("*.jsonl"),
                    key=lambda p: p.stat().st_mtime,
                    reverse=True,
                )
                if jsonl_files:
                    log_file = jsonl_files[0]
        elif args.parser_type == "cline":
            log_file = ClineLogParser.find_latest_task()
        elif args.parser_type == "kimi":
            log_file = KimiLogParser.find_latest_session()
        elif args.parser_type == "qwen":
            log_file = QwenLogParser.find_session_file()

    if log_file is None or not log_file.exists():
        print(f"Error: log file not found: {log_file}", file=sys.stderr)
        if not args.find_latest:
            print("Hint: use --find-latest to auto-detect the most recent log file", file=sys.stderr)
        sys.exit(1)

    agent_label = args.agent_label or args.parser_type.capitalize()

    # Parse
    snapshots = log_parser.parse(log_file)
    if not snapshots:
        print(f"No token usage data found in {log_file}", file=sys.stderr)
        sys.exit(1)

    # If the parser already reports cumulative values (e.g. Codex),
    # convert to per-request deltas first to avoid double-counting.
    if log_parser.snapshots_are_cumulative:
        delta_snaps = LogParser.to_deltas(snapshots)
    else:
        delta_snaps = snapshots

    if args.cumulative:
        # Cumulative mode: running total over time
        running_total = {"input": 0, "cache_creation": 0, "cache_read": 0, "output": 0, "total": 0}
        data_points = []
        for snap in delta_snaps:
            d = snap.to_dict()
            for k in running_total:
                running_total[k] += d[k]
            data_points.append((snap.timestamp, dict(running_total)))
        last_total = running_total
    else:
        # Snapshot mode (default): each point is the per-request token count
        # (context window usage at that moment — drops after auto-compact)
        data_points = [(snap.timestamp, snap.to_dict()) for snap in delta_snaps]
        last_total = data_points[-1][1] if data_points else {"input": 0, "cache_creation": 0, "cache_read": 0, "output": 0, "total": 0}

    all_data = {agent_label: data_points}

    if args.status:
        if args.json:
            import json as json_mod
            status = {
                "agent": agent_label,
                "log_file": str(log_file),
                "snapshots": len(snapshots),
                "total_tokens": last_total["total"],
                "input_tokens": last_total["input"],
                "output_tokens": last_total["output"],
                "cache_read_tokens": last_total["cache_read"],
                "cache_creation_tokens": last_total["cache_creation"],
                "context_limit": args.context_limit,
                "usage_pct": (last_total["total"] / args.context_limit * 100)
                if args.context_limit > 0 else 0,
            }
            print(json_mod.dumps(status, indent=2, default=str))
        else:
            pct = last_total["total"] / args.context_limit * 100 if args.context_limit > 0 else 0
            print(f"Context Monitor Status: {agent_label}")
            print(f"  Log file: {log_file}")
            print(f"  Snapshots: {len(snapshots)}")
            print(f"  Total tokens: {last_total['total']:,} ({pct:.1f}% of {args.context_limit:,})")
            print(f"  Input: {last_total['input']:,}")
            print(f"  Output: {last_total['output']:,}")
            print(f"  Cache read: {last_total['cache_read']:,}")
            print(f"  Cache creation: {last_total['cache_creation']:,}")

    if args.visualize:
        output_dir = Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        config = ContextConfig(
            context_limit=args.context_limit,
            warning_line=args.warning_line,
        )
        monitor = ContextMonitor(
            config=config,
            parser=log_parser,
            output_dir=output_dir,
            max_minutes=args.max_minutes if args.max_minutes > 0 else None,
        )
        monitor._is_cumulative = args.cumulative

        paths = monitor.generate_all_graphs(
            all_data,
            graph_type=args.graph_type,
            time_unit=args.time_unit,
        )
        print(f"Generated {len(paths)} visualization(s):")
        for p in paths:
            print(f"  {p}")

    if not args.status and not args.visualize:
        # Default: print status
        pct = running_total["total"] / args.context_limit * 100 if args.context_limit > 0 else 0
        print(f"{agent_label}: {len(snapshots)} snapshots, {running_total['total']:,} tokens ({pct:.1f}%)")


if __name__ == "__main__":
    main()
