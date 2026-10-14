#!/usr/bin/env python3
"""VibeCodeHPC PreToolUse hook: refuse Read on images, PDFs and videos (Claude Code).

For agents backed by a text-only model server. Such a server rejects any
request that carries an image, and once an image block is in a conversation
every later request of that conversation fails too. periodic_monitor writes
PNG figures under User-shared/visualizations/, so agents do try to read them.

Blocks with exit code 2 and tells the agent what to read instead.
Malformed hook input is let through (exit 0).

Install with ``vibecodehpc/scripts/seed_claude_home.py --text-only`` or add
it by hand to the ``PreToolUse`` hooks with matcher ``Read``.
"""

import json
import sys

MEDIA_EXTENSIONS = (
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff",
    ".pdf",
    ".mp4", ".webm", ".mov", ".avi", ".mkv",
)

MESSAGE = (
    "The model server for this agent accepts text only, so images, PDFs and "
    "videos cannot be read. Read the data or the script that produced the "
    "file instead, or inspect it with a command-line tool "
    "(file sizes, ffprobe, pdftotext)."
)


def is_media(path: str) -> bool:
    """Return True if *path* has an image, PDF or video extension."""
    return path.lower().endswith(MEDIA_EXTENSIONS)


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)

    tool_input = data.get("tool_input") or {}
    path = str(tool_input.get("file_path", ""))
    if data.get("tool_name", "Read") == "Read" and is_media(path):
        print(MESSAGE, file=sys.stderr)
        sys.exit(2)
    sys.exit(0)


if __name__ == "__main__":
    main()
