#!/usr/bin/env python3
"""Check the repository's fake-data boundary and obvious credential patterns.

This is a narrow tripwire, not a org-restricted data detector. It catches missing boundary
declarations and high-signal secret or identifier shapes so an assistant gets
a blocking failure before committing. Human review remains required for
names, context, and data that does not match a fixed pattern.

Run from the repository root: python3 tools/check_data_boundary.py
"""
import argparse
import re
import sys
from pathlib import Path


DEFAULT_ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {".git", ".hyperreview", "__pycache__", "node_modules", "dist", "build"}
MAX_SCAN_BYTES = 2_000_000

BOUNDARY_MARKERS = {
    "AGENTS.md": "No org-restricted data (as defined by your org policy) in the repo or the coding session",
    "GROUND_RULES.md": "No org-restricted data (as defined by your org policy) or client data",
}

PATTERNS = (
    ("private-key block", re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")),
    ("GitHub token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}\b")),
    ("GitHub fine-grained token", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b")),
    ("OpenAI-style key", re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")),
    ("AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("Slack token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b")),
    ("SSN-shaped identifier", re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)")),
)


def iter_text_files(root):
    for path in root.rglob("*"):
        if not path.is_file() or any(part in SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        try:
            if path.stat().st_size > MAX_SCAN_BYTES:
                continue
            raw = path.read_bytes()
        except OSError:
            continue
        if b"\x00" in raw:
            continue
        try:
            yield path, raw.decode("utf-8")
        except UnicodeDecodeError:
            continue


def check(root):
    problems = []
    for rel, marker in BOUNDARY_MARKERS.items():
        path = root / rel
        if not path.exists():
            problems.append(f"missing required boundary document: {rel}")
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            problems.append(f"cannot read boundary document {rel}: {exc}")
            continue
        if marker not in text:
            problems.append(f"{rel}: missing required fake-data boundary marker")

    for path, text in iter_text_files(root):
        rel = path.relative_to(root).as_posix()
        for label, pattern in PATTERNS:
            if pattern.search(text):
                problems.append(f"{rel}: possible {label}; inspect and remove before commit")
    return problems


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT,
                        help="repository root to inspect (default: this repo)")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    if not root.is_dir():
        print(f"check_data_boundary: root does not exist: {root}")
        return 2
    problems = check(root)
    if problems:
        print(f"check_data_boundary: {len(problems)} problem(s) found")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("check_data_boundary: OK (boundary declarations present; no high-signal patterns found)")
    return 0


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8")
    sys.exit(main())
