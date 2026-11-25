#!/usr/bin/env python3
"""Standing consistency check for the work map, catalog, and ledger.

Run from the repo root: python3 tools/check_map.py
Exits non-zero with a plain-English list of problems. AI assistants run this
before committing changes to DAG.json, catalog/REGISTRY.json, LEDGER.md, or
CATALOG.md, and run it (plus tools/test_check_map.py) for every PR; no CI
workflow ships, so the PR records the run.

The canonical vocabularies live HERE, not in the data files: the data files
restate them for human readers, and this check fails if they drift.

Failure posture, so every future check inherits it: inconsistency is
blocking; absence of an optional artifact is a warning at most, never
silently ignored. A missing input is never a silent pass.

Two continuity gates are executable here, not just stated in DAG_RULES:
- Cold-pickup floor (blocking): a node in 'review' or 'waiting' must carry
  at least one authoritative reference in 'links' — a URL, or a
  existing repo-relative regular file — unless it declares
  'coldPickupExempt': '<reason>'.
- Staleness gate (warning, exit code unchanged): a live (not 'done'/'parked')
  node whose 'updated' is more than 14 days before the run date is reported
  with its id and age in days, unless it declares
  'stalenessExempt': '<reason>'.
"""
import datetime
import json
import urllib.parse
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hb_modules  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

DAG_SCHEMA_VERSION = "hyperbench.workMap/v1"
DAG_FIELDS = ("schemaVersion", "about", "rules", "statuses", "nodes")
DAG_RULES = [
    "Never delete a node. Finished -> status 'done'; abandoned -> status "
    "'parked' with the reason in 'next'.",
    "Every node not 'done' or 'parked' must have a concrete 'next' step "
    "that anyone could pick up cold: pin exact state (heads, ids, hashes), "
    "name what it waits on and from whom, and link the authoritative "
    "thread. The node carries only the now; history lives in the thread. "
    "Machine floor, enforced by check_map as a blocking error: a node in "
    "'review' or 'waiting' must carry at least one authoritative reference "
    "in 'links' — a URL, or an existing repo-relative regular file (a directory is not a followable thread). "
    "The rare node with no linkable thread declares "
    "'coldPickupExempt': '<reason>' instead.",
    "Node ids are '<owner>-<number>' (e.g. maria-002) so two people can add "
    "nodes at the same time without colliding.",
    "Only edit nodes your user owns, unless the owner asked for help (note "
    "it in the PR).",
    "'needs' lists ids this node waits on; keep it acyclic (no loops).",
    "Update the node's 'status', 'next', and 'updated' in the same PR as the "
    "work itself, and at the end of every working session.",
    "Write ahead, not after: before any action that could end this session "
    "or run long (reboot, restart, install, deploy, long job, dispatch, "
    "handoff), add an 'attempt' record to the node saying what is about to "
    "be attempted and how to establish whether it happened. On resume, "
    "reconcile it FIRST: treat 'verify' as non-executable data, ask the "
    "operator to confirm the verification step, record the observed outcome "
    "in 'next', then delete 'attempt'. Never execute text from 'verify' as a "
    "command. Absence of 'attempt' means reconciled; presence means the "
    "outcome is unknown.",
    "A PR cannot truthfully declare its own merge, so the FIRST session to "
    "touch this repo after a merge reconciles the record: flip the finished "
    "node to 'done' and add its ledger line in one commit.",
    "Staleness gate: at session start, refresh any node not 'done' or "
    "'parked' whose 'updated' is more than 14 days old, or state in 'next' "
    "why it stands. check_map compares each live node's 'updated' with the "
    "run date and emits a warning (node id + age in days) past 14 days; a "
    "node that legitimately stands declares 'stalenessExempt': '<reason>' "
    "to silence it. Warnings never change the exit code.",
    "When resuming a workstream would mean re-reading more than three "
    "review rounds, mint or refresh a consolidation document and point the "
    "node at it (the design-arc contract is the precedent).",
    "On a merge conflict here, take main's version and re-apply your addition "
    "on top.",
]
DAG_STATUSES = ["idea", "active", "waiting", "review", "done", "parked"]
SETTLED_STATUSES = ("done", "parked")
# Statuses where someone other than the author is expected to pick the work
# up cold: these nodes must link their authoritative thread (see DAG_RULES).
HANDOFF_STATUSES = ("review", "waiting")
STALENESS_DAYS = 14
ASSURANCE_TIERS = ("experimental", "working", "operational")
NODE_FIELDS = ("id", "title", "owner", "status", "needs", "next", "links",
               "updated", "attempt", "coldPickupExempt", "stalenessExempt",
               "assurance")
ATTEMPT_FIELDS = ("action", "startedAt", "verify", "repeatable")
REPEATABLE = ["yes", "no", "unknown"]
PROJECT_STATUSES = ["incubating", "active", "graduated", "retired"]
SKILL_STATUSES = ["active", "draft", "retired"]

NODE_ID = re.compile(r"^[a-z][a-z0-9]*-\d{3}$")
TIMESTAMP = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$"
)
LEDGER_LINE = re.compile(
    r"^- (\d{4}-\d{2}-\d{2}) — (\S+) — .+ \[([a-z0-9-]+)\] \((PR #\d+|commit [0-9a-f]{7,40})\)$"
)

problems = []
warnings = []


def problem(msg):
    problems.append(msg)


def warn(msg):
    warnings.append(msg)


def valid_date(s):
    try:
        d = datetime.date.fromisoformat(s)
    except (TypeError, ValueError):
        return False
    return 2020 <= d.year <= 2100


def latest_date_anywhere():
    """The latest calendar date in force anywhere right now (UTC+14).

    A date past this is in the future for every writer. Comparing with
    the host's local date instead rejected a real update written in a
    timezone already on the next day (docs/STATE_MACHINES.md, SM-2)."""
    return (datetime.datetime.now(datetime.timezone.utc)
            + datetime.timedelta(hours=14)).date()


def valid_timestamp(s):
    if not isinstance(s, str) or not TIMESTAMP.fullmatch(s):
        return False
    normalized = s[:-1] + "+00:00" if s.endswith("Z") else s
    try:
        value = datetime.datetime.fromisoformat(normalized)
    except ValueError:
        return False
    return (value.tzinfo is not None and value.utcoffset() is not None
            and 2020 <= value.year <= 2100)


# One DNS label: alnum at both ends, hyphens inside only. Validated
# per-label so empty labels ('example..com') and edge-hyphen labels
# ('example.-com', 'example-.com') all reject (Anvil r4).
URL_LABEL = re.compile(r"[a-z0-9]|[a-z0-9][a-z0-9-]*[a-z0-9]")
URL_IPV6 = re.compile(r"[0-9a-f:]+(%[a-z0-9]+)?")


def valid_hostname(host):
    """Per-label DNS validation including the wire limits: each label
    1-63 bytes, whole name <= 253 bytes (Anvil r8: a 64-byte label is
    syntactically unfollowable — python's own IDNA encoder rejects
    it)."""
    if not host or len(host) > 253:
        return False
    return all(len(l) <= 63 and URL_LABEL.fullmatch(l)
               for l in host.split("."))


def valid_url(s):
    """An absolute HTTP(S) URL a cold pickup can actually follow: no
    ASCII controls or whitespace anywhere in the raw string (urlparse
    silently strips newline/tab/CR, so they must be rejected BEFORE
    parsing — Anvil r5), then parsed: scheme http/https, a
    syntactically valid host (per-label hostname chars, or bracketed
    IPv6), and — when a port is present — a numeric port in range.
    Bare schemes, whitespace hosts, non-numeric ports, and
    out-of-range ports all satisfy nothing (Anvil r3: the host test
    must be an authority test)."""
    if any(c.isspace() or ord(c) < 0x21 or 0x7f <= ord(c) <= 0x9f
           for c in s):
        return False
    try:
        u = urllib.parse.urlparse(s)
    except ValueError:
        return False
    if u.scheme not in ("http", "https"):
        return False
    try:
        u.port  # raises ValueError on non-numeric or out-of-range ports
    except ValueError:
        return False
    host = u.hostname or ""  # lowercased, IPv6 brackets stripped
    if not host:
        return False
    if ":" in host:
        return bool(URL_IPV6.fullmatch(host))
    return valid_hostname(host)


def repo_path_ok(path, root, want="file"):
    """A repo-relative path that stays in the repo: relative (no leading
    slash, no drive), no parent traversal, and the resolved target under
    the repository root (Anvil r5: an absolute host path is host
    authority, not repository authority)."""
    # Lexical screen BEFORE host-native parsing: the host Path parser
    # is platform-dependent (POSIX sees no drive in 'C:\\x'), so drive,
    # UNC, and backslash forms are rejected as bytes — a repo-relative
    # path uses forward slashes only, on every platform.
    if ("\\" in path or re.match(r"^[A-Za-z]:", path)
            or path.startswith("//")):
        return False
    p = Path(path)
    if p.is_absolute() or p.drive or ".." in p.parts:
        return False
    try:
        resolved = (root / p).resolve()
        rootr = root.resolve()
    except OSError:
        return False
    if not resolved.is_relative_to(rootr):
        return False
    # A directory is not an authoritative thread — '.' would be a
    # one-character bypass of the cold-pickup floor (Anvil r8). Node
    # links and goal paths must be regular files. The catalog's 'home'
    # is polymorphic by existing contract — a project home is a
    # directory, a skill home is its SKILL.md — so it passes as
    # want="any" (existing contained path of either kind).
    if want == "any":
        return resolved.is_file() or resolved.is_dir()
    return resolved.is_file()


def check_link(path, where, root=ROOT, want="file"):
    if not isinstance(path, str) or not path.strip():
        problem(f"{where}: link entry must not be blank")
        return
    if path.startswith("http://") or path.startswith("https://"):
        if not valid_url(path):
            problem(f"{where}: link '{path}' is not a valid absolute "
                    f"HTTP(S) URL (no controls/whitespace; scheme + valid "
                    f"host required) — a value that cannot be copied and "
                    f"followed resolves nothing")
        return
    if not repo_path_ok(path, root, want):
        kind = "path" if want == "any" else "regular file"
        problem(f"{where}: link '{path}' is not an existing repo-relative "
                f"{kind} (absolute/drive paths and '..' traversal are "
                f"host authority, not repository authority"
                + ("; a directory is not a followable artifact)"
                   if want != "any" else ")"))


def is_authoritative_link(path, root):
    """A link a cold pickup can actually follow: a valid absolute HTTP(S)
    URL, or an existing repo-relative regular file. Anything else
    (blank, bare scheme, dead path, wrong type) does not count —
    check_link reports those separately."""
    if not isinstance(path, str) or not path.strip():
        return False
    if path.startswith("http://") or path.startswith("https://"):
        return valid_url(path)
    return repo_path_ok(path, root)


def exemption(n, field, where):
    """Return True only for a validly declared exemption: the field present
    as non-empty text. A present-but-empty reason is a blocking problem, not
    an exemption — an explicit null must never satisfy a presence gate."""
    if field not in n:
        return False
    if not isinstance(n[field], str) or not n[field].strip():
        problem(f"{where}: '{field}' must be a non-empty reason "
                f"(an empty exemption exempts nothing)")
        return False
    return True


def load_dag(path, label):
    try:
        dag = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        problem(f"{label} missing")
        return {"statuses": DAG_STATUSES, "nodes": []}
    except json.JSONDecodeError as exc:
        problem(f"{label}: invalid JSON at line {exc.lineno}, column {exc.colno}")
        return {"statuses": DAG_STATUSES, "nodes": []}
    if not isinstance(dag, dict) or not isinstance(dag.get("nodes"), list):
        problem(f"{label}: top level must be an object with a 'nodes' list")
        return {"statuses": DAG_STATUSES, "nodes": []}
    for field in DAG_FIELDS:
        if field not in dag:
            problem(f"{label}: missing top-level field '{field}'")
    for field in sorted(set(dag) - set(DAG_FIELDS)):
        problem(f"{label}: unknown top-level field '{field}' (allowed: "
                f"{list(DAG_FIELDS)}; canonical list lives in tools/check_map.py)")
    if dag.get("schemaVersion") != DAG_SCHEMA_VERSION:
        problem(f"{label}: 'schemaVersion' must be exactly "
                f"'{DAG_SCHEMA_VERSION}'")
    if not isinstance(dag.get("about"), str) or not dag["about"].strip():
        problem(f"{label}: 'about' must be non-empty text")
    if dag.get("rules") != DAG_RULES:
        problem(f"{label}: 'rules' must be exactly the canonical list in "
                f"tools/check_map.py")
    for i, n in enumerate(dag["nodes"], 1):
        if not isinstance(n, dict):
            problem(f"{label}: node entry #{i} must be an object")
    dag["nodes"] = [n for n in dag["nodes"] if isinstance(n, dict)]
    if dag.get("statuses") != DAG_STATUSES:
        problem(f"{label}: 'statuses' must be exactly {DAG_STATUSES} "
                f"(canonical list lives in tools/check_map.py)")
    return dag


def check_attempt(n, where):
    """Validate the write-ahead record.

    A node carries 'attempt' only while an action's OUTCOME is unknown. The
    field is written BEFORE anything that can end the session, and deleted
    once the outcome is reconciled, so its absence means reconciled and its
    presence means unknown. That distinction is the whole point: a status
    alone cannot separate "about to attempt" from "attempted, outcome
    unknown", which is exactly the state a crashed session resumes into.

    'verify' is mandatory because a record that recovers intent without a way
    to establish outcome leaves the resuming session no better off. It is a
    non-executable description of evidence, not a command or grant of authority.
    """
    if "attempt" not in n:
        return
    att = n["attempt"]
    if not isinstance(att, dict):
        problem(f"{where}: 'attempt' must be an object with "
                f"{list(ATTEMPT_FIELDS)}")
        return
    if n.get("status") in SETTLED_STATUSES:
        problem(f"{where}: status '{n.get('status')}' is settled but the node "
                f"still carries an unreconciled 'attempt'; reconcile it via "
                f"its 'verify' step, record the outcome in 'next', then "
                f"delete 'attempt'")
    for field in ATTEMPT_FIELDS:
        if field not in att:
            problem(f"{where}: 'attempt' is missing field '{field}'")
    for field in ATTEMPT_FIELDS:
        if field in att and (not isinstance(att[field], str)
                             or not att[field].strip()):
            problem(f"{where}: 'attempt.{field}' must be non-empty text")
    for field in sorted(set(att) - set(ATTEMPT_FIELDS)):
        problem(f"{where}: 'attempt' has unknown field '{field}' "
                f"(allowed: {list(ATTEMPT_FIELDS)})")
    if isinstance(att.get("repeatable"), str) and att["repeatable"] not in REPEATABLE:
        problem(f"{where}: 'attempt.repeatable' is '{att['repeatable']}', "
                f"must be one of {REPEATABLE} (the resuming session's actual "
                f"decision: safe to re-run, or must determine first)")
    if isinstance(att.get("startedAt"), str) and not valid_timestamp(att["startedAt"]):
        problem(f"{where}: 'attempt.startedAt' must be a real ISO-8601 "
                f"timestamp from 2020 through 2100 with a timezone "
                f"(e.g. 2026-08-07T22:41:00Z)")


def check_dag(dag, label="DAG.json", link_root=ROOT):
    nodes = dag["nodes"]
    ids = [n.get("id") for n in nodes]
    if len(ids) != len(set(ids)):
        problem(f"{label}: duplicate node ids")
    known = set(ids)
    needs = {}
    for n in nodes:
        nid = n.get("id", "<missing id>")
        where = f"{label} node {nid}"
        for field in ("id", "title", "owner", "status", "needs", "next", "links", "updated"):
            if field not in n:
                problem(f"{where}: missing field '{field}'")
        for field in ("id", "title", "owner", "status", "next", "updated"):
            if field in n and not isinstance(n[field], str):
                problem(f"{where}: '{field}' must be text")
        for field in ("title", "owner"):
            if isinstance(n.get(field), str) and not n[field].strip():
                problem(f"{where}: '{field}' must not be empty")
        for field in ("needs", "links"):
            if field in n and (not isinstance(n[field], list)
                               or any(not isinstance(x, str) for x in n[field])):
                problem(f"{where}: '{field}' must be a list of text entries")
        if not NODE_ID.match(str(nid)):
            problem(f"{where}: id must look like '<owner>-<number>' (e.g. maria-002)")
        elif isinstance(n.get("owner"), str) and n["owner"] and nid.rsplit("-", 1)[0] != n["owner"]:
            problem(f"{where}: id prefix must be the owner ('{n['owner']}')")
        if n.get("status") not in DAG_STATUSES:
            problem(f"{where}: status '{n.get('status')}' not in {DAG_STATUSES}")
        if not isinstance(n.get("updated"), str) or not valid_date(n["updated"]):
            problem(f"{where}: 'updated' is not a real YYYY-MM-DD date")
        elif datetime.date.fromisoformat(n["updated"]) > latest_date_anywhere():
            problem(f"{where}: 'updated' {n['updated']} is in the future — "
                    f"nothing was updated tomorrow; a future date would also "
                    f"suppress the staleness gate indefinitely (inconsistency "
                    f"blocks)")
        if n.get("status") not in ("done", "parked") and not str(n.get("next", "")).strip():
            problem(f"{where}: live node has no 'next' step")
        # exemptions are shape-checked whenever present, whether or not the
        # gate they silence would fire on this node
        cold_exempt = exemption(n, "coldPickupExempt", where)
        stale_exempt = exemption(n, "stalenessExempt", where)
        # cold-pickup floor: a node handed off for review/waiting must link
        # its authoritative thread (blocking — see DAG_RULES)
        if n.get("status") in HANDOFF_STATUSES and not cold_exempt:
            node_links = n.get("links") if isinstance(n.get("links"), list) else []
            if not any(is_authoritative_link(x, link_root) for x in node_links):
                problem(f"{where}: status '{n['status']}' but 'links' has no "
                        f"authoritative reference (a URL, or an existing "
                        f"repo-relative regular file — a directory is not a "
                        f"followable thread) — a cold pickup needs the "
                        f"thread; link it, or declare 'coldPickupExempt' "
                        f"with the reason")
        # staleness gate: warning only — absence of freshness is observable,
        # not blocking (matches the repo's severity ruling)
        if (n.get("status") not in SETTLED_STATUSES and not stale_exempt
                and isinstance(n.get("updated"), str) and valid_date(n["updated"])):
            age = (datetime.date.today()
                   - datetime.date.fromisoformat(n["updated"])).days
            if age > STALENESS_DAYS:
                warn(f"{where}: stale live node — 'updated' {n['updated']} is "
                     f"{age} days old (> {STALENESS_DAYS}); refresh it at "
                     f"session start, or declare 'stalenessExempt' with the "
                     f"reason it stands")
        node_needs = n.get("needs") if isinstance(n.get("needs"), list) else []
        if "assurance" in n and n["assurance"] not in ASSURANCE_TIERS:
            problem(f"{where}: assurance '{n['assurance']}' is not one of "
                    f"{list(ASSURANCE_TIERS)} (docs/REVIEW_CONTRACT.md; "
                    f"absent means 'working')")
        for field in sorted(set(n) - set(NODE_FIELDS)):
            problem(f"{where}: unknown field '{field}' (allowed: "
                    f"{list(NODE_FIELDS)}; canonical list lives in "
                    f"tools/check_map.py). A field nothing validates is "
                    f"decoration, so new fields are added here first.")
        check_attempt(n, where)
        for dep in node_needs:
            if not isinstance(dep, str) or dep not in known:
                problem(f"{where}: needs unknown node '{dep}'")
        needs[nid] = [d for d in node_needs if isinstance(d, str)]
        for link in (n.get("links") if isinstance(n.get("links"), list) else []):
            if isinstance(link, str):
                check_link(link, where, link_root, want="any")
    # cycle detection (iterative DFS, 0=unvisited 1=in-stack 2=done)
    state = {i: 0 for i in needs}
    for start in needs:
        if state[start]:
            continue
        stack = [(start, iter(needs.get(start, [])))]
        state[start] = 1
        while stack:
            node, it = stack[-1]
            advanced = False
            for dep in it:
                if dep not in state:
                    continue
                if state[dep] == 1:
                    problem(f"{label}: dependency cycle through '{dep}'")
                elif state[dep] == 0:
                    state[dep] = 1
                    stack.append((dep, iter(needs.get(dep, []))))
                    advanced = True
                    break
            if not advanced:
                state[node] = 2
                stack.pop()


def check_registry(dag):
    reg_path = ROOT / "catalog" / "REGISTRY.json"
    if not reg_path.exists():
        problem("catalog/REGISTRY.json missing")
        return None
    reg = json.loads(reg_path.read_text(encoding="utf-8"))
    if not isinstance(reg, dict):
        problem("catalog/REGISTRY.json: top level must be an object")
        return None
    for kind in ("projects", "skills"):
        entries = reg.get(kind)
        if not isinstance(entries, list):
            problem(f"catalog/REGISTRY.json: '{kind}' must be a list")
            reg[kind] = []
            continue
        for i, e in enumerate(entries, 1):
            if not isinstance(e, dict):
                problem(f"catalog/REGISTRY.json: {kind} entry #{i} must be an object")
        reg[kind] = [e for e in entries if isinstance(e, dict)]
    if reg.get("projectStatuses") != PROJECT_STATUSES:
        problem(f"REGISTRY: 'projectStatuses' must be exactly {PROJECT_STATUSES}")
    if reg.get("skillStatuses") != SKILL_STATUSES:
        problem(f"REGISTRY: 'skillStatuses' must be exactly {SKILL_STATUSES}")
    dag_ids = {n.get("id") for n in dag["nodes"]}
    specs = (
        ("projects", PROJECT_STATUSES,
         ("id", "summary", "owner", "status", "home", "goal", "dagNodes", "registered", "updated")),
        ("skills", SKILL_STATUSES,
         ("id", "summary", "maintainer", "status", "home", "registered", "updated")),
    )
    for kind, allowed, req in specs:
        seen = set()
        for e in reg[kind]:
            eid = e.get("id", "<missing id>")
            where = f"REGISTRY {kind[:-1]} {eid}"
            if eid in seen:
                problem(f"{where}: duplicate id")
            seen.add(eid)
            if kind == "skills":
                home = e.get("home")
                home_path = ROOT / home if isinstance(home, str) else None
                if home_path is not None and home_path.exists():
                    m = re.search(r"^version:\s*(\S+)\s*$",
                                  home_path.read_text(encoding="utf-8").split("---", 2)[1]
                                  if home_path.read_text(encoding="utf-8").startswith("---") else "",
                                  re.MULTILINE)
                    fm_version = m.group(1) if m else None
                    reg_version = e.get("version")
                    if fm_version and reg_version and fm_version != reg_version:
                        problem(f"{where}: registry version '{reg_version}' disagrees with "
                                f"SKILL.md frontmatter version '{fm_version}' — enrolled copies "
                                f"compare frontmatter, so a split here ships stale instructions")
                    elif fm_version and not reg_version:
                        problem(f"{where}: SKILL.md declares version '{fm_version}' but the "
                                f"registry entry has none")
                    elif reg_version and not fm_version:
                        problem(f"{where}: registry declares version '{reg_version}' but "
                                f"SKILL.md frontmatter has none")
            for field in req:
                if field not in e:
                    problem(f"{where}: missing field '{field}'")
                elif field != "dagNodes" and (not isinstance(e[field], str) or not e[field].strip()):
                    problem(f"{where}: '{field}' must be non-empty text")
            if e.get("status") not in allowed:
                problem(f"{where}: status '{e.get('status')}' not in {allowed}")
            for dfield in ("registered", "updated"):
                if dfield in e and (not isinstance(e[dfield], str) or not valid_date(e[dfield])):
                    problem(f"{where}: '{dfield}' is not a real YYYY-MM-DD date")
            if isinstance(e.get("home"), str) and e["home"].strip():
                check_link(e["home"], where, want="any")
            if kind == "projects":
                if isinstance(e.get("goal"), str) and e["goal"].strip():
                    check_link(e["goal"], where)
                nodes = e.get("dagNodes", [])
                if not isinstance(nodes, list) or not nodes or any(not isinstance(x, str) for x in nodes):
                    problem(f"{where}: 'dagNodes' must be a list of at least one work-map node id")
                    nodes = [x for x in nodes if isinstance(x, str)] if isinstance(nodes, list) else []
                for nid in nodes:
                    if nid not in dag_ids:
                        problem(f"{where}: dagNodes references unknown node '{nid}'")
    # every skill/project folder on disk must be registered
    skills_dir = ROOT / ".claude" / "skills"
    registered = {e.get("id") for e in reg["skills"]}
    if skills_dir.exists():
        for d in skills_dir.iterdir():
            if d.is_dir() and d.name not in registered:
                problem(f".claude/skills/{d.name}: skill folder exists but is not in catalog/REGISTRY.json")
    proj_dir = ROOT / "projects"
    registered_p = {e.get("id") for e in reg["projects"]}
    if proj_dir.exists():
        for d in proj_dir.iterdir():
            if d.is_dir() and d.name not in registered_p:
                problem(f"projects/{d.name}: project folder exists but is not in catalog/REGISTRY.json")
    return reg


def check_catalog_view(reg):
    """CATALOG.md is never hand-edited: it must be byte-identical to the
    deterministic rendering of the registry (tools/render_catalog.py)."""
    cat_path = ROOT / "CATALOG.md"
    if not cat_path.exists():
        problem("CATALOG.md missing")
        return
    if reg is None:
        return
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        from render_catalog import render_bytes
        expected = render_bytes(reg)
    except Exception as exc:
        problem(f"CATALOG.md: cannot render the registry ({exc.__class__.__name__}: {exc})")
        return
    if cat_path.read_bytes() != expected:
        problem("CATALOG.md does not match the registry rendering (byte-for-byte, UTF-8, LF line endings) — regenerate with: python3 tools/render_catalog.py")


def check_ledger(dag):
    done_by_id = {n.get("id"): n for n in dag["nodes"]
                  if n.get("status") == "done" and isinstance(n.get("id"), str)}
    lines = (ROOT / "LEDGER.md").read_text(encoding="utf-8").splitlines()
    dates = []
    completions = {}
    for i, line in enumerate(lines, 1):
        if not line.startswith("- "):
            continue
        m = LEDGER_LINE.match(line)
        if not m:
            problem(f"LEDGER.md line {i}: must match '- YYYY-MM-DD — owner — what [node-id] (PR #n | commit sha)'")
            continue
        date, owner, node_id = m.group(1), m.group(2), m.group(3)
        if not valid_date(date):
            problem(f"LEDGER.md line {i}: '{date}' is not a real date")
        node = done_by_id.get(node_id)
        if node is None:
            problem(f"LEDGER.md line {i}: node '{node_id}' is not a done node in DAG.json (finish the node in the same commit)")
        elif node.get("owner") != owner:
            problem(f"LEDGER.md line {i}: owner '{owner}' does not match node '{node_id}' owner '{node.get('owner')}'")
        completions[node_id] = completions.get(node_id, 0) + 1
        dates.append(date)
    if dates != sorted(dates, reverse=True):
        problem("LEDGER.md: entries are not newest-first")
    # the relationship is two-way: every done node has exactly one completion
    for nid in done_by_id:
        count = completions.get(nid, 0)
        if count == 0:
            problem(f"DAG.json node {nid} is done but LEDGER.md has no completion line for it (flip the node and add the line together)")
        elif count > 1:
            problem(f"LEDGER.md: node '{nid}' has {count} completion lines; a node is finished once")


def check_node_loss_gate():
    """Refuse a work map that silently drops a node the base still has.

    Delegated to check_node_loss.py so the comparison has one
    implementation; wired HERE because a gate nobody runs is not a gate
    (HB9-001 — the detector existed and a dropped live node still
    passed the battery). Three honest answers, matching the
    check_memory pattern:

    * comparison ran, no loss -> silent pass
    * comparison ran, loss    -> problem (red)
    * comparison impossible   -> decided by whether this tree has git
      history of its OWN, never by the distribution marker. The marker
      says development-repository commit coordinates do not resolve
      here, which is true of an export and legitimately silences the
      version checker — but a tree's DAG history is native to it, not a
      development-repository coordinate, so consulting the marker made a
      missing base non-blocking in the tree shape that existed then
      (HB9-002; this repository carried the marker until 2026-11-04). A tree with commits of its own can fetch its base and
      must; a tree with no git at all genuinely has nothing to compare
      and says so.
    """
    gate = Path(__file__).resolve().parent / "check_node_loss.py"
    try:
        out = subprocess.run(
            [sys.executable, str(gate), "origin/master"],
            capture_output=True, text=True, encoding="utf-8",
            cwd=str(ROOT))
    except OSError as exc:
        problem("node-loss gate could not run (%s)" % exc)
        return
    if out.returncode == 0:
        return
    if out.returncode == 2:
        try:
            has_own_history = subprocess.run(
                ["git", "rev-parse", "--verify", "HEAD"],
                capture_output=True, text=True, encoding="utf-8",
                cwd=str(ROOT)).returncode == 0
        except OSError:
            has_own_history = False
        detail = out.stdout.strip().splitlines()[0]
        if has_own_history:
            problem("node-loss gate cannot reach its base while this tree "
                    "has history of its own — fetch it, name another base, "
                    "or accept the limit explicitly: %s" % detail)
        else:
            warn("node-loss gate: not run (%s)" % detail)
        return
    problem("node-loss gate: %s" % out.stdout.strip())


def main():
    dag = load_dag(ROOT / "DAG.json", "DAG.json")
    check_dag(dag)
    starter_dir = ROOT / "templates" / "repo-starter"
    if starter_dir.exists():
        starter_label = "templates/repo-starter/DAG.json"
        starter_dag = load_dag(starter_dir / "DAG.json", starter_label)
        check_dag(starter_dag, starter_label, starter_dir)
    skip, module_warnings = hb_modules.skipped(ROOT)
    for w in module_warnings:
        warn(w)
    if "catalog" in skip:
        for rel in ("catalog/REGISTRY.json", "CATALOG.md"):
            if (ROOT / rel).exists():
                warn(f"{rel} is present but the catalog module is declared "
                     f"skipped in {hb_modules.MANIFEST}; it is not checked")
    else:
        reg = check_registry(dag)
        check_catalog_view(reg)
    check_ledger(dag)
    check_node_loss_gate()
    for w in warnings:
        print("  warning:", w)
    if problems:
        print("check_map: %d problem(s) found" % len(problems))
        for p in problems:
            print("  -", p)
        return 1
    if "catalog" in skip:
        print("check_map: OK (work map and ledger consistent; catalog SKIPPED, "
              f"declared skipped in {hb_modules.MANIFEST})")
    else:
        print("check_map: OK (work map, catalog, ledger all consistent)")
    return 0


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8")
    sys.exit(main())
