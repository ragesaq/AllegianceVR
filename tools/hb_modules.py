#!/usr/bin/env python3
"""hb_modules — which optional HyperBench modules a repository has skipped.

The declaration is the existing STARTER_MANIFEST.json field
adoptionScope.skipped (docs/ADOPT_EXISTING_REPO.md). Only names in OPTIONAL
turn a check off, and only by explicit name. With no manifest (the hub) or an
unreadable one, nothing is skipped and every checker behaves as before.

The floor (FLOOR) cannot be skipped: memory and orientation are what keep
agents from duplicating work, so a repository that adopts HyperBench always
checks them. Naming a floor module in `skipped` draws a warning and changes
nothing. Other names (people, projects, ...) are recorded provenance that no
checker interprets, as before.
"""
import json
from pathlib import Path

FLOOR = ("work-map", "memory", "knowledge", "line-endings", "data-boundary")
OPTIONAL = ("catalog",)
MANIFEST = "STARTER_MANIFEST.json"


def skipped(root):
    """Return (set of skipped OPTIONAL modules, list of warning strings)."""
    path = Path(root) / MANIFEST
    if not path.is_file():
        return set(), []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        scope = data.get("adoptionScope", {})
        names = scope.get("skipped", [])
        if not isinstance(names, list):
            raise ValueError("adoptionScope.skipped is not a list")
    except (ValueError, AttributeError, OSError, RecursionError) as exc:
        return set(), [f"{MANIFEST}: cannot read adoptionScope.skipped "
                       f"({exc}); every module is checked"]
    out, warnings = set(), []
    for name in names:
        if name in OPTIONAL:
            out.add(name)
        elif name in FLOOR:
            warnings.append(f"{MANIFEST}: '{name}' is a floor module and "
                            f"cannot be skipped; it is still checked")
    return out, warnings
