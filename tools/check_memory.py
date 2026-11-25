#!/usr/bin/env python3
"""Standing consistency check for the memory store.

Run from the repo root: python3 tools/check_memory.py
Exits non-zero with a plain-English list of problems. AI assistants run this
before committing changes to memory/. Record it and
tools/test_check_memory.py explicitly in the PR; no CI is shipped here.

The rules this enforces live in docs/MEMORY_PROTOCOL.md. The canonical
vocabularies live HERE, not in the data files.

Failure posture, inherited from tools/check_map.py: inconsistency is
blocking; absence of an optional artifact is a warning at most, never
silently ignored. A missing input is never a silent pass.

The specific hazard this guards: a memory entry is an INPUT to the
assistant's reasoning, not a passive record. An over-trusted or stale entry
reframes the problem and the model rationalizes the evidence to fit it. So
class is mandatory, canonical is human-granted and expiring, and absence
claims must carry a positive control.
"""
import datetime
import os
import re
import stat
import subprocess
import sys
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent.parent
MEM = ROOT / "memory"

CLASSES = ["inferred", "witnessed", "verified", "canonical"]
# witnessed ranks with inferred: seen once without retained proof is a lead,
# not a check (operator-027 part A, decided 2026-11-03).
CLASS_RANK = {"inferred": 0, "witnessed": 0, "verified": 1, "canonical": 2}

ENTRY_ID = re.compile(r"^mem-\d{3}$")
FILE_NAME = re.compile(r"^(mem-\d{3})-[a-z0-9][a-z0-9-]*\.md$")
TOPIC = re.compile(r"^[a-z0-9][a-z0-9-]*$")
COMMIT_EVIDENCE = re.compile(r"^commit [0-9a-f]{7,40}$")
BUILDER_ONLY = (".hyperreview", ".hyperbuilder")
# The recall cache (tools/recall.py) is derived from the files and rebuilt
# at will. It sits inside the tree, so containment and existence alone
# would accept it as evidence (docs/RECALL.md, "A hit is a lead").
RECALL_CACHE = ".hyperbench-recall"
# The claim carrier is CLAIM_CONTRACT.md's (docs/implementation-briefs/
# compounding-memory/); only its heading, slug and fence info string are
# read here. The fence's contents belong to the claim checker
# (FOUNDATION_INTERFACE.md section 4).
CLAIM_ANCHOR = re.compile(r"^claim-([a-z0-9]+(?:-[a-z0-9]+)*)$")
CLAIM_FENCE_INFO = "hyperbench-claim-v1"
# The guest marker (FOUNDATION_INTERFACE.md section 2). Windows drops
# trailing dots and spaces when it opens a name, so lookalikes are compared
# after stripping them as well as after casefolding.
GUEST_MARKER = "GUEST.md"
HTML_COMMENT_OPEN = "<!--"
HTML_COMMENT_CLOSE = "-->"
# Pattern-matching a row is the wrong shape entirely. The renderer decides what
# is a row from block context: a header line, a delimiter line under it, then
# body rows until the block ends. A body row does not need a leading pipe at
# all ("mem-906 | x | ..." renders as a real row), and a row that matches any
# id-shaped guess is one the checker still has to bind to an entry. Every
# previous attempt here was a heuristic over line text, and each one left a row
# a human reads and CI does not: "| mem-004 |" (too few cells), "|mem-004 |"
# (no space), "  | mem-004 |" (indent), "memo-004" (near-miss id). The fix is
# to parse the table the way GFM parses it and check *every* body row, so
# there is no id shape left to be clever about.
#
# All of this was verified against the live GFM renderer, not assumed.
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
CODE_INDENT = re.compile(r"^ {4,}\S")
DELIMITER_CELL = re.compile(r"^:?-+:?$")
INDEX_HEADER = ["id", "topic", "class", "observed", "summary"]
# The v2 (typed-memory) index widens the SAME table by the three triple
# positions. This checker owns both headers so there is exactly one
# definition; the store's own format marker in memory/README.md picks the
# active one, and tools/check_tracking.py layers the v2 semantics on top
# (design rule: one code path per rule, the width included).
INDEX_HEADER_V2 = INDEX_HEADER + ["subject", "predicate", "object"]
STORE_FORMAT_LINE = re.compile(r"^Store format: memory/(v1|v2)$", re.MULTILINE)

# Reported, never skipped: a first cell that is close to an id but not one.
# This is no longer load-bearing (every body row is checked whatever its first
# cell looks like); it only sharpens the message for the common typo.
NEAR_ENTRY_ID = re.compile(r"^mem[-_ ]?\d+$", re.IGNORECASE)

# GFM lets a cell carry a literal pipe when it is escaped as \|, so splitting
# on every pipe would shred a legal summary into extra cells and reject it.
# Splitting on unescaped pipes only is what the renderer does, and the checker
# must read the row the same way the human does.
#
# Deliberately NOT backslash parity. cmark-gfm splits table cells before inline
# escape processing and treats a pipe preceded by any backslash as escaped, so
# "a \\| b" (two backslashes) is still ONE cell, not two. Probed against the
# live GFM API for one, two, and three backslashes: cell counts were 5, 5, 5.
# A parity-aware splitter would be more "correct" in theory and would disagree
# with the renderer in practice, which is the only thing that matters here.
UNESCAPED_PIPE = re.compile(r"(?<!\\)\|")

# memory/README.md is machine-read at session start, so it is a RESTRICTED
# SURFACE: container blocks the table scanner cannot model (blockquotes, raw
# HTML, list-embedded tables) are rejected outright rather than silently
# skipped. GitHub renders full markdown inside those containers; this checker
# deliberately does not, and a surface it cannot read is a surface it must
# refuse (round 5, render-verified). See check_index.
# Any indent, deliberately wider than CommonMark's top-level 3-space rule:
# at 4+ spaces these are code blocks at TOP level, but the same bytes inside
# a list item sit at content indent and render as real containers (verified
# live: a 4-space raw-HTML table inside a list item renders its cells).
# The scanner cannot know which context it is in, so on this surface the
# ambiguity is rejected at every indent.
BLOCKQUOTE = re.compile(r"^ *>")
HTML_BLOCK = re.compile(r"^ *<[!/a-zA-Z]")


def split_index_cells(line):
    """Split a GFM table row into its cells, honouring escaped pipes."""
    parts = UNESCAPED_PIPE.split(line.strip())
    if parts and not parts[0].strip():
        parts = parts[1:]
    if parts and not parts[-1].strip():
        parts = parts[:-1]
    return [p.strip() for p in parts]


def strip_fenced(text):
    """Return ([(lineno, line)] prose lines, open_fence_line or None).

    Fenced blocks are dropped. A row inside a fence renders as code, so it
    carries no trust claim and must not be flagged; the previous parser had no
    fence awareness and would reject a documentation example. An unclosed
    fence is reported by line number so the caller can fail it explicitly:
    a file whose fences do not balance does not render the way its author
    thinks it does, and silently swallowing the tail hid a rendered table
    once already (round 5).

    Fences are read the way CommonMark reads them: the info string of a
    BACKTICK fence may not contain a backtick, so a line like ``` ```
    is prose, not a fence opener — GitHub renders the table that follows it.
    Tilde fences may carry any info string. Both verified against the live
    GFM renderer, not assumed.
    """
    live = []
    fence_char = None
    fence_len = 0
    open_line = None
    for lineno, line in enumerate(text.splitlines(), 1):
        m = FENCE.match(line)
        if fence_char is not None:
            if (m and m.group(1)[0] == fence_char
                    and len(m.group(1)) >= fence_len and not m.group(2).strip()):
                fence_char = None
                open_line = None
            continue
        if m and not (m.group(1)[0] == "`" and "`" in m.group(2)):
            fence_char = m.group(1)[0]
            fence_len = len(m.group(1))
            open_line = lineno
            continue
        live.append((lineno, line))
    return live, open_line


def is_delimiter_row(cells):
    return bool(cells) and all(DELIMITER_CELL.match(c) for c in cells)


def scan_tables(live):
    """Find GFM tables the way the renderer does.

    A table is a header line, a delimiter line on the very next line, then body
    rows until a blank line, an indented code block, or a line gap. Body rows
    are taken verbatim: no id-shaped filter, because the caller must see every
    row a reader sees, including the ones whose first cell is not an id.

    Returns (tables, consumed); consumed is the set of line numbers belonging
    to a table, so the caller can tell which remaining lines are stray pipe
    lines that render as paragraphs rather than rows.
    """
    tables = []
    consumed = set()
    k = 0
    while k < len(live) - 1:
        (ln1, l1), (ln2, l2) = live[k], live[k + 1]
        if ln2 != ln1 + 1 or CODE_INDENT.match(l1) or "|" not in l1:
            k += 1
            continue
        header = split_index_cells(l1)
        delim = split_index_cells(l2)
        if not header or len(delim) != len(header) or not is_delimiter_row(delim):
            k += 1
            continue
        body = []
        prev = ln2
        j = k + 2
        while j < len(live):
            lnj, lj = live[j]
            if lnj != prev + 1 or not lj.strip() or CODE_INDENT.match(lj):
                break
            body.append((lnj, lj))
            prev = lnj
            j += 1
        consumed.update([ln1, ln2] + [b[0] for b in body])
        tables.append({"line": ln1, "header": header, "body": body})
        k = j
    return tables, consumed

# Rule 7: an entry the assistant cannot read is worse than no entry, because
# everyone believes it is there. These are byte caps, matching the protocol.
MAX_ENTRY_BYTES = 8_000
MAX_INDEX_BYTES = 20_000

# Rule 3: human-granted canonical claims expire; live evidence still wins.
MAX_CANONICAL_REVIEW_DAYS = 400

# When set, a commit reference this checkout cannot resolve is a failure, not a
# warning. CI sets it, because a green CI run is what people trust; an exported
# tree with no .git does not, because there the missing history is the declared
# condition rather than a hole. The variable makes the gate policy visible in
# the workflow file instead of hiding it in the checker's default.
STRICT_EVIDENCE = os.environ.get("MEMORY_STRICT_EVIDENCE") == "1"

problems = []
warnings = []


TRACKING_OWNED = ("reconciliation", "agent-store-snapshot.json")


def problem(msg):
    problems.append(msg)


def warn(msg):
    warnings.append(msg)


def parse_date(s):
    try:
        return datetime.date.fromisoformat(s)
    except (TypeError, ValueError):
        return None


def _is_link(st):
    """A symbolic link, a Windows junction, or any other reparse point."""
    if stat.S_ISLNK(st.st_mode):
        return True
    attrs = getattr(st, "st_file_attributes", 0)
    return bool(attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def guest_status(slug):
    """'member', 'guest', 'ambiguous' or 'absent' for people/<slug>.

    The folder is listed, never probed by name, so a case-insensitive
    filesystem cannot make 'guest.md' answer for 'GUEST.md'. Anything the
    rule cannot classify cleanly is 'ambiguous', and an ambiguous identity
    is never owner authority (FOUNDATION_INTERFACE.md section 2). A people/
    folder that is itself a link names nobody in this repository.
    """
    try:
        pst = os.lstat(ROOT / "people")
    except FileNotFoundError:
        return "absent"
    except OSError:
        return "ambiguous"
    if _is_link(pst) or not stat.S_ISDIR(pst.st_mode):
        return "ambiguous"
    person = ROOT / "people" / slug
    try:
        st = os.lstat(person)
    except FileNotFoundError:
        return "absent"
    except OSError:
        return "ambiguous"
    if _is_link(st) or not stat.S_ISDIR(st.st_mode):
        return "ambiguous"
    try:
        names = os.listdir(person)
    except OSError:
        return "ambiguous"
    marks = [n for n in names if n.rstrip(". ").casefold() == GUEST_MARKER.casefold()]
    if not marks:
        return "member"
    if marks != [GUEST_MARKER]:
        return "ambiguous"
    try:
        mst = os.lstat(person / GUEST_MARKER)
    except OSError:
        return "ambiguous"
    if stat.S_ISREG(mst.st_mode) and not _is_link(mst):
        return "guest"
    return "ambiguous"


def _comment_left_open(rest):
    """True when rest opens an HTML comment it does not close."""
    while (start := rest.find(HTML_COMMENT_OPEN)) >= 0:
        close = rest.find(HTML_COMMENT_CLOSE, start + len(HTML_COMMENT_OPEN))
        if close < 0:
            return True
        rest = rest[close + len(HTML_COMMENT_CLOSE):]
    return False


def _claim_prose(text):
    """Classify a note's lines for the claim locator in one pass.

    Returns ([(lineno, line)] plain prose lines, open_line or None). Fence
    and comment state are tracked together: inside a code fence a comment
    marker is literal text, and inside an HTML comment a fence marker opens
    nothing. A line that opens, closes or lies inside a comment is never
    returned, so a heading is matched against its own source line and text
    on either side of a comment cannot join into one. open_line is the line
    of a fence or comment still open at the end of the note
    (FOUNDATION_INTERFACE.md section 4). Fences are recognized as
    strip_fenced recognizes them.
    """
    prose = []
    fence_char = None
    fence_len = 0
    fence_line = None
    comment_line = None
    for lineno, line in enumerate(text.splitlines(), 1):
        if comment_line is not None:
            end = line.find(HTML_COMMENT_CLOSE)
            if end >= 0:
                rest = line[end + len(HTML_COMMENT_CLOSE):]
                comment_line = lineno if _comment_left_open(rest) else None
            continue
        m = FENCE.match(line)
        if fence_char is not None:
            if (m and m.group(1)[0] == fence_char
                    and len(m.group(1)) >= fence_len and not m.group(2).strip()):
                fence_char = None
                fence_line = None
            continue
        if m and not (m.group(1)[0] == "`" and "`" in m.group(2)):
            fence_char = m.group(1)[0]
            fence_len = len(m.group(1))
            fence_line = lineno
            continue
        if HTML_COMMENT_OPEN in line:
            if _comment_left_open(line):
                comment_line = lineno
            continue
        prose.append((lineno, line))
    return prose, fence_line if fence_char is not None else comment_line


def locate_claim(rel_path, slug):
    """Find '### claim-<slug>' and its claim fence in a repository note.

    Returns (status, line). status is one of ok, outside, no-file,
    not-markdown, unbalanced, missing, no-fence or duplicate; line is the
    heading's 1-based line for ok, else the line that explains the status or
    None. The single locator for memory citations and for the claim
    checker's claim references (FOUNDATION_INTERFACE.md section 4). It reads
    the carrier only, never the fence's contents.
    """
    if PurePosixPath(rel_path).is_absolute() or (len(rel_path) > 1 and rel_path[1] == ":"):
        return "outside", None
    try:
        resolved = (ROOT / rel_path).resolve()
        resolved.relative_to(ROOT.resolve())
    except (ValueError, OSError):
        return "outside", None
    if not resolved.is_file():
        return "no-file", None
    if resolved.suffix != ".md":
        return "not-markdown", None
    try:
        text = resolved.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return "no-file", None
    prose, open_line = _claim_prose(text)
    if open_line is not None:
        return "unbalanced", open_line
    heading = f"### claim-{slug}"
    hits = [lineno for lineno, line in prose if line.rstrip() == heading]
    if not hits:
        return "missing", None
    if len(hits) > 1:
        return "duplicate", hits[1]
    lines = text.splitlines()
    nxt = hits[0]  # 0-based index of the line after the heading
    while nxt < len(lines) and not lines[nxt].strip():
        nxt += 1
    m = FENCE.match(lines[nxt]) if nxt < len(lines) else None
    if not m or m.group(2).strip() != CLAIM_FENCE_INFO:
        return "no-fence", hits[0]
    return "ok", hits[0]


def today():
    return datetime.date.today()


def latest_date_anywhere():
    """The latest calendar date in force anywhere right now (UTC+14): the
    bound for 'in the future', which the host's local date is not for a
    writer one timezone ahead (docs/STATE_MACHINES.md, SM-2)."""
    return (datetime.datetime.now(datetime.timezone.utc)
            + datetime.timedelta(hours=14)).date()


def earliest_date_anywhere():
    """The earliest calendar date in force anywhere right now (UTC-12): a
    date before this has passed for every reader, so expiry judged against
    it gives the same verdict on every host (docs/STATE_MACHINES.md, SM-2)."""
    return (datetime.datetime.now(datetime.timezone.utc)
            - datetime.timedelta(hours=12)).date()


def split_front_matter(text, where):
    """Return (fields, body) or (None, None) with a recorded problem."""
    if not text.startswith("---\n"):
        problem(f"{where}: must start with a '---' front-matter block (see docs/MEMORY_PROTOCOL.md)")
        return None, None
    end = text.find("\n---\n", 4)
    if end == -1:
        problem(f"{where}: front-matter block is never closed with '---'")
        return None, None
    raw = text[4:end]
    body = text[end + 5:]
    fields = {}
    for i, line in enumerate(raw.splitlines(), 2):
        if not line.strip():
            continue
        if ":" not in line:
            problem(f"{where} line {i}: front-matter line must be 'field: value'")
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if not key:
            problem(f"{where} line {i}: front-matter field name must not be blank")
            continue
        if key in fields:
            problem(f"{where} line {i}: field '{key}' appears twice")
            continue
        fields[key] = value
    return fields, body


def _git(*args):
    """Run git in the repo. Returns (rc, stdout) or None if git is unusable."""
    if (Path(__file__).resolve().parent / '.distribution-marker').exists():
        return None  # distribution tree: coordinates resolve in the development repository, not here
    try:
        proc = subprocess.run(
            ["git", "-C", str(ROOT), *args],
            capture_output=True, text=True, encoding="utf-8", timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.returncode, proc.stdout.strip()


def baseline_ref():
    """The ref history checks compare against: the merge base with the
    remote default branch when derivable (origin/HEAD resolves it on any
    default-branch name), else common default names; None when git cannot
    answer."""
    candidates = []
    r = _git("symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    if r is not None and r[0] == 0 and r[1]:
        candidates.append(r[1])
    # remote-tracking names first, and of two that both exist the one
    # further ahead: a stale ref would make an old store the baseline, and
    # deletions since then would pass (SM-4)
    def newer_first(a, b):
        r = _git("merge-base", "--is-ancestor", a, b)
        back = _git("merge-base", "--is-ancestor", b, a)
        if r is not None and r[0] == 0 and not (back and back[0] == 0):
            return [b, a]  # a is strictly behind b
        return [a, b]
    candidates += (newer_first("origin/main", "origin/master")
                   + newer_first("main", "master"))
    for candidate in candidates:
        r = _git("merge-base", "HEAD", candidate)
        if r is not None and r[0] == 0 and r[1]:
            return r[1]
    return None


def check_entries_not_deleted(entries_raw):
    """Rule 5: an entry is superseded, never deleted. A snapshot check
    cannot see a deletion (the index row goes with the file and every
    count still agrees), so compare the entry ids at the merge base with
    the ids here (docs/STATE_MACHINES.md SM-4)."""
    if not (ROOT / ".git").exists():
        return
    base = baseline_ref()
    if base is None:
        warn("memory/: entry-deletion check cannot run (no git baseline "
             "reachable) — the limit is reported, not passed")
        return
    r = _git("ls-tree", "--name-only", base, "memory/")
    if r is None or r[0] != 0:
        return
    for rel in r[1].splitlines():
        m = FILE_NAME.match(rel.split("/")[-1])
        if m and m.group(1) not in entries_raw:
            problem(f"{rel}: entry {m.group(1)} existed at the merge base "
                    f"and is gone — supersede an entry, never delete it "
                    f"(docs/MEMORY_PROTOCOL.md rule 5)")


def commit_exists(sha):
    """Ask git whether the sha is a real commit in THIS repository.

    Returns True, False, or None when the question cannot be answered.
    None is NOT a pass and NOT a failure: the caller reports the limit.

    Why None has to exist: a shallow clone (CI checkout defaults to
    fetch-depth 1) legitimately lacks most history, so 'not found' there
    means 'not fetched', not 'not real'. Treating that as a failure would
    fail valid entries on every CI run; treating it as a pass would let a
    fabricated sha through whenever the check is cheap to dodge. Reporting
    the limit is the only honest third answer, and it is the same rule the
    protocol imposes on entries: never report absence from a surface that
    cannot hold the record.
    """
    if not (ROOT / ".git").exists():
        return None
    found = _git("cat-file", "-e", sha + "^{commit}")
    if found is None:
        return None
    if found[0] == 0:
        return True
    shallow = _git("rev-parse", "--is-shallow-repository")
    if shallow is not None and shallow[0] == 0 and shallow[1] == "true":
        return None
    return False


def check_evidence(value, where):
    """A verified claim names something that actually exists, in THIS repo.

    Three accepted forms, each verified rather than pattern-matched:
      https:// URL   - shape only; we do not fetch the network (stated limit)
      commit <sha>   - resolved against this repository's history
      <path>         - must resolve INSIDE the repo and exist

    http:// is rejected: evidence that can be rewritten in transit is not
    evidence, and docs/MEMORY_PROTOCOL.md says https.
    """
    if value.startswith("http://"):
        problem(
            f"{where}: evidence '{value}' uses http:// — use https:// so the "
            f"artifact cannot be rewritten in transit "
            f"(docs/MEMORY_PROTOCOL.md rule 2)"
        )
        return
    if value.startswith("https://"):
        return
    if value.startswith("commit "):
        if not COMMIT_EVIDENCE.match(value):
            problem(f"{where}: evidence '{value}' is not a well-formed "
                    f"'commit <sha>' (7-40 lowercase hex characters)")
            return
        sha = value.split(" ", 1)[1]
        state = commit_exists(sha)
        if state is False:
            problem(f"{where}: evidence names commit {sha}, which does not exist "
                    f"in this repository — a verified entry must point at real "
                    f"history, not a plausible-looking sha")
        elif state is None:
            # UNVERIFIED is honest, but honesty is not a gate. Where this run is
            # meant to be authoritative (CI), an unanswerable commit reference
            # must block: otherwise the cheapest place to smuggle a fabricated
            # sha is the exact place the checker prints OK. Where the missing
            # history is deliberate (an exported tree with no .git), the same
            # state is a stated limit and stays a warning.
            message = (f"{where}: evidence names commit {sha}, but this checkout "
                       f"cannot answer whether it exists (no git history, or a "
                       f"shallow clone), so the reference is UNVERIFIED here "
                       f"rather than confirmed")
            if STRICT_EVIDENCE:
                problem(message + " — this run is configured to gate on evidence "
                        "(MEMORY_STRICT_EVIDENCE=1), so an unresolvable "
                        "reference fails rather than passing with a warning; "
                        "fetch full history (actions/checkout fetch-depth: 0)")
            else:
                warn(message + " — re-run in a full clone before relying on it")
        return

    # '#' in path evidence is reserved for a claim anchor
    # (FOUNDATION_INTERFACE.md section 4): <note>.md#claim-<slug>.
    if "#" in value:
        check_claim_evidence(value, where)
        return

    # Path evidence: must stay inside the repo.
    if PurePosixPath(value).is_absolute() or (len(value) > 1 and value[1] == ":"):
        problem(f"{where}: evidence '{value}' is an absolute path — evidence must "
                f"be a repo-relative path, so it travels with the repo and means "
                f"the same thing on every machine")
        return
    try:
        resolved = (ROOT / value).resolve()
        resolved.relative_to(ROOT.resolve())
    except (ValueError, OSError):
        problem(f"{where}: evidence '{value}' resolves outside the repository — "
                f"evidence a reader cannot open from this checkout is not evidence")
        return
    if in_recall_cache(value):
        recall_cache_problem(value, where)
        return
    if resolved.exists():
        return
    if (PurePosixPath(value).parts[0] in BUILDER_ONLY
            and (Path(__file__).resolve().parent
                 / ".distribution-marker").exists()):
        # The export removes builder-only artifacts by design
        # (tools/check_transfer.py FORBIDDEN), so here the path is a
        # stated limit, like a commit that resolves only in the
        # development repository (docs/STATE_MACHINES.md SM-8).
        warn(f"{where}: evidence '{value}' is a builder-only artifact that "
             f"stays in the development repository, so it is UNVERIFIED in "
             f"this distribution tree")
        return
    problem(
        f"{where}: evidence '{value}' does not exist in the repo — a verified "
        f"entry must name a real repo-relative file, an https:// URL, or "
        f"'commit <sha>' (demote it to 'inferred' if you cannot show the artifact)"
    )


CLAIM_STATUS_MESSAGES = {
    "outside": "is absolute or resolves outside the repository — evidence a "
               "reader cannot open from this checkout is not evidence",
    "no-file": "names a note that does not exist in the repo",
    "not-markdown": "names a file that is not a Markdown note; claims live in "
                    "Markdown notes",
    "unbalanced": "names a note with an unclosed code fence or HTML comment at "
                  "line {line}, so it does not render the way it reads",
    "missing": "names a claim the note does not have — no live "
               "'### claim-{slug}' heading",
    "duplicate": "names a claim whose heading '### claim-{slug}' appears more "
                 "than once (again at line {line}); a claim id is unique in its note",
    "no-fence": "names a heading at line {line} that is not followed by a "
                "'" + CLAIM_FENCE_INFO + "' fence, so it is not a claim",
}


_DEVICE_NAMES = frozenset(
    ["CON", "PRN", "AUX", "NUL"]
    + [f"{d}{n}" for d in ("COM", "LPT") for n in "123456789¹²³"])


def _plain_part(part):
    """True when Windows would open this path part as exactly this name."""
    if part in ("", ".", "..") or part != part.rstrip(". "):
        return False
    if any(ord(c) < 32 or c in '\\:<>"|?*' for c in part):
        return False
    try:
        units = len(part.encode("utf-16-le")) // 2
    except UnicodeEncodeError:
        return False
    # Only the bare name is a device: since Windows 11 a name such as CON.md
    # is an ordinary file that an export can omit (round 6).
    return units <= 255 and part.upper() not in _DEVICE_NAMES


def _plainly_absent(rel_path):
    """True when rel_path is written plainly and part of it is missing, with
    no link or reparse point before the missing part: the shape an export
    leaves when it removes a builder-only artifact.

    Absence is shown by walking the path, not inferred from lookups of its
    two ends: a '..' spelling or a dangling link can make both ends look
    absent while something is there (patch review rounds 2 and 3). A path
    is not plain when a part is empty, '.' or '..', holds a control
    character or one of \\ : < > " | ? *, ends in a dot or space, is
    exactly a device name such as CON or COM1, is longer than 255 UTF-16
    units, or cannot be encoded, since Windows may open it as a different
    name or refuse it outright (rounds 4 to 6). A missing earlier part must
    not hide such a later one.
    """
    parts = rel_path.split("/")
    if not all(_plain_part(p) for p in parts):
        return False
    current = ROOT
    for part in parts:
        current = current / part
        try:
            st = os.lstat(current)
        except FileNotFoundError:
            return True
        except (OSError, ValueError):
            return False
        if _is_link(st):
            return False
    return False


def in_recall_cache(value):
    """True when a repo-relative evidence path resolves to the recall cache
    folder or anything under it, whatever its spelling: case, '..', '.',
    a backslash or a link into it. A path spelled through the cache folder
    is refused too, wherever a link there leads: it depends on the cache.
    So is a path through any folder that is the cache under another name."""
    # Walk the spelling one component at a time, before '..' is collapsed:
    # a path that visits the cache folder and backs out of it still
    # depends on that folder.
    stack = []
    for part in value.replace("\\", "/").split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            if stack:
                stack.pop()
            continue
        stack.append(part.rstrip(". ").casefold())
        if stack == [RECALL_CACHE.casefold()]:
            return True
    cache = os.path.normcase(os.path.realpath(ROOT / RECALL_CACHE))
    here = ROOT
    for part in value.replace("\\", "/").split("/"):
        if part in ("", "."):
            continue
        here = here / part
        try:
            seen = os.path.normcase(os.path.realpath(here))
        except (OSError, ValueError):
            continue
        if seen == cache or seen.startswith(cache.rstrip(os.sep) + os.sep):
            return True
    for candidate in (value, value.replace("\\", "/")):
        try:
            target = os.path.normcase(os.path.realpath(ROOT / candidate))
        except (OSError, ValueError):
            continue
        if target == cache or target.startswith(cache.rstrip(os.sep) + os.sep):
            return True
    return False


def recall_cache_problem(value, where):
    problem(f"{where}: evidence '{value}' is in the recall cache "
            f"({RECALL_CACHE}/), a derived index rebuilt from the files — a "
            f"search hit is a lead, not evidence; cite the file it points to "
            f"(docs/RECALL.md)")


def check_claim_evidence(value, where):
    """Evidence citing a claim: <note>.md#claim-<slug>, catalog-free.

    Only the carrier is checked here; the claim checker validates the fence
    for every such citation, and a citation holds when both pass.
    """
    path_part, _, anchor = value.partition("#")
    if in_recall_cache(path_part):
        recall_cache_problem(value, where)
        return
    m = CLAIM_ANCHOR.match(anchor)
    if not m:
        problem(f"{where}: evidence '{value}' has an anchor that is not a claim "
                f"anchor — in path evidence '#' may only introduce "
                f"'#claim-<slug>' (docs/MEMORY_PROTOCOL.md rule 2)")
        return
    status, line = locate_claim(path_part, m.group(1))
    if status == "ok":
        return
    # no-file covers an absent path and one that is there but is not a
    # readable UTF-8 file. Only a path shown to be absent is the
    # distribution tree's limit, or reads as a missing note; anything else
    # the locator could not read stays a problem.
    absent = status == "no-file" and _plainly_absent(path_part)
    if (absent and PurePosixPath(path_part).parts[0] in BUILDER_ONLY
            and (Path(__file__).resolve().parent
                 / ".distribution-marker").exists()):
        warn(f"{where}: evidence '{value}' is in a builder-only artifact that "
             f"stays in the development repository, so it is UNVERIFIED in "
             f"this distribution tree")
        return
    if status == "no-file" and not absent:
        target = ROOT / path_part
        try:
            exists = os.path.lexists(target) or os.path.lexists(target.resolve())
        except (OSError, ValueError):
            exists = False
        if exists:
            detail = ("names a path that exists but is not a file readable as "
                      "UTF-8 text, so the claim cannot be located")
        else:
            detail = ("names a path that cannot be shown to be absent — it is "
                      "not written plainly or passes through a link — and the "
                      "claim cannot be located; cite the note's plain path")
        problem(f"{where}: evidence '{value}' {detail} (docs/MEMORY_PROTOCOL.md rule 2)")
        return
    detail = CLAIM_STATUS_MESSAGES[status].format(line=line, slug=m.group(1))
    problem(f"{where}: evidence '{value}' {detail} (docs/MEMORY_PROTOCOL.md rule 2)")


def read_entries():
    """Load entries, keyed by id. A missing store is a blocking problem.

    Deleting memory/ used to exit 0. That is the worst possible failure for
    this tool: the one mutation that destroys every entry, the canary, and
    the index at once was the one mutation it approved, so a later session
    would read an absent store as an empty-but-searchable store and trust
    its own absence claims. The seed template ships memory/ with README.md
    and CANARY.md, so there is no legitimate state where it is missing.
    """
    entries = {}
    if MEM.exists() and not MEM.is_dir():
        problem("memory/ exists but is not a directory — the memory store must be "
                "a directory holding the index, the canary, and the entries")
        return entries
    if not MEM.is_dir():
        problem("memory/ is missing — the store, its index, and the retrieval "
                "canary are all absent, so no absence claim from this repo can be "
                "trusted; restore it from templates/repo-starter/memory/ "
                "(docs/MEMORY_PROTOCOL.md rules 7 and 8)")
        return entries
    seen_ids = {}
    for path in sorted(MEM.iterdir()):
        # check_tracking owns these two paths (reconciliation records and
        # the conventional agent-store snapshot); rejecting them here made
        # its documented states unreachable (SM-6)
        if path.name in TRACKING_OWNED:
            continue
        if not path.is_file():
            problem(f"memory/{path.name}: memory/ holds entry files only, no subfolders")
            continue
        if path.name in ("README.md", "CANARY.md"):
            continue
        if not path.name.endswith(".md"):
            problem(f"memory/{path.name}: memory entries are markdown files ending in .md")
            continue
        m = FILE_NAME.match(path.name)
        if not m:
            problem(f"memory/{path.name}: filename must be '<mem-NNN>-<short-topic>.md', "
                    f"lowercase, e.g. mem-001-standing-checks.md")
            continue
        text = path.read_text(encoding="utf-8")
        entry_id = m.group(1)
        if entry_id in seen_ids:
            problem(f"memory/{path.name}: id '{entry_id}' is already used by "
                    f"memory/{seen_ids[entry_id]} — two files sharing an id means "
                    f"one of them is invisible to the index and to every check, "
                    f"including its own validation")
            continue
        seen_ids[entry_id] = path.name
        entries[entry_id] = (path, text)
    return entries


def check_canonical_grant(fields, where, recorded_by=None):
    """The one canonical-grant rule, for memory entries and opted-in claims.

    fields maps granted-by, granted-on, granted-where and review-by to
    strings; problems and warnings go to this module's lists, so a caller
    shares one problem list and one exit answer (FOUNDATION_INTERFACE.md
    section 3).
    """
    # Rule 3: an assistant may never grant canonical status to its own memory.
    for required in ("granted-by", "granted-on", "granted-where", "review-by"):
        if required not in fields:
            problem(f"{where}: class 'canonical' requires '{required}' — canonical "
                    f"means a person decided, and the entry must name that decision "
                    f"(docs/MEMORY_PROTOCOL.md rule 3)")
        elif not fields[required].strip():
            problem(f"{where}: '{required}' is blank — an empty grant field names "
                    f"no decision, and a missing identity is not owner authority "
                    f"(docs/MEMORY_PROTOCOL.md rule 3)")
    granter = fields.get("granted-by", "")
    if granter:
        if not TOPIC.match(granter):
            problem(f"{where}: granted-by '{granter}' is not a plain person name "
                    f"(a lowercase slug like 'maria') — the people/ check "
                    f"resolves paths, so a path-shaped value can name a "
                    f"directory that is not a person and pass a membership "
                    f"check it should fail")
        elif (status := guest_status(granter)) == "absent":
            problem(f"{where}: granted-by '{granter}' is not a person in people/ — "
                    f"an assistant cannot grant canonical status, only a program "
                    f"member can")
        elif status == "guest":
            problem(f"{where}: granted-by '{granter}' is a guest (people/{granter}/"
                    f"{GUEST_MARKER}) — canonical is granted only by the repository "
                    f"owner's side, never by a guest (docs/MEMORY_PROTOCOL.md rule 3)")
        elif status == "ambiguous":
            problem(f"{where}: granted-by '{granter}' cannot be classified as a "
                    f"member: people/{granter} is a link or not a folder, or holds a "
                    f"name like {GUEST_MARKER} that is not exactly that one file — an "
                    f"ambiguous identity is not owner authority "
                    f"(docs/MEMORY_PROTOCOL.md rule 3)")
        elif granter == recorded_by:
            warn(f"{where}: granted-by and recorded-by are both '{granter}' — "
                 f"check that a real grant happened and was not self-assigned "
                 f"while filing; labelling it 'self-granted' does not quiet "
                 f"this warning, because a self-grant is exactly what it "
                 f"exists to flag")
    granted_on = fields.get("granted-on")
    g_on = parse_date(granted_on) if granted_on is not None else None
    if granted_on is not None and g_on is None:
        problem(f"{where}: granted-on '{granted_on}' is not a real date")
    elif g_on is not None and g_on > latest_date_anywhere():
        problem(f"{where}: granted-on '{granted_on}' is in the future — a grant "
                f"records a decision that already happened, and future-dating "
                f"it defers expiry, which is the exact failure rule 3's expiry "
                f"exists to prevent (docs/MEMORY_PROTOCOL.md rule 3)")
    review_by = fields.get("review-by")
    if review_by is not None:
        rb = parse_date(review_by)
        if rb is None:
            problem(f"{where}: review-by '{review_by}' is not a real date")
        elif rb < earliest_date_anywhere():
            problem(f"{where}: canonical entry expired on {review_by} — a person must "
                    f"re-grant it or it must be demoted; do not bump the date to make "
                    f"this check pass (docs/MEMORY_PROTOCOL.md rule 3)")
        else:
            # Two anchors, both binding. The granted-on window catches a
            # stretched grant; the run-date window catches a future-dated
            # one independently, because an expiry bounded only by a
            # self-declared date is not a bound (round 5, R5-3).
            if g_on is not None and (rb - g_on).days > MAX_CANONICAL_REVIEW_DAYS:
                problem(f"{where}: review-by is more than {MAX_CANONICAL_REVIEW_DAYS} days "
                        f"after granted-on — a canonical claim that never really expires is "
                        f"the failure mode this rule exists to prevent")
            if (rb - today()).days > MAX_CANONICAL_REVIEW_DAYS:
                problem(f"{where}: review-by '{review_by}' is more than "
                        f"{MAX_CANONICAL_REVIEW_DAYS} days from today — the expiry "
                        f"window is anchored to the run date, not to the declared "
                        f"granted-on, so a future-dated grant cannot stretch it")


def check_entry(entry_id, path, text):
    where = f"memory/{path.name}"
    size = len(text.encode("utf-8"))
    if size > MAX_ENTRY_BYTES:
        problem(f"{where}: entry is {size} bytes, over the {MAX_ENTRY_BYTES}-byte cap — "
                f"that is a document, not a memory: move it to docs/ and have the "
                f"entry point at it (docs/MEMORY_PROTOCOL.md rule 7)")

    fields, body = split_front_matter(text, where)
    if fields is None:
        return None
    if not body.strip():
        problem(f"{where}: entry has front matter but no body — say what was observed")

    for required in ("id", "topic", "class", "observed", "recorded-by"):
        if required not in fields:
            problem(f"{where}: missing required field '{required}'")

    fid = fields.get("id", "")
    if fid and not ENTRY_ID.match(fid):
        problem(f"{where}: id '{fid}' must look like 'mem-001'")
    elif fid and fid != entry_id:
        problem(f"{where}: id '{fid}' does not match the filename id '{entry_id}'")

    topic = fields.get("topic", "")
    if topic and not TOPIC.match(topic):
        problem(f"{where}: topic '{topic}' must be a lowercase slug, e.g. standing-checks")

    observed = fields.get("observed")
    obs_date = parse_date(observed) if observed is not None else None
    if observed is not None and obs_date is None:
        problem(f"{where}: observed '{observed}' is not a real date (use YYYY-MM-DD)")
    elif obs_date and obs_date > latest_date_anywhere():
        problem(f"{where}: observed '{observed}' is in the future — an entry records "
                f"something already seen")

    recorded_by = fields.get("recorded-by", "")
    if recorded_by and not TOPIC.match(recorded_by):
        problem(f"{where}: recorded-by '{recorded_by}' is not a plain person name "
                f"(a lowercase slug like 'maria') — a path or symbol here is not "
                f"an identity, and a path shape can resolve to a directory that "
                f"was never a person")
    elif recorded_by:
        # The grant rule's own lookup: links are not followed.
        found = guest_status(recorded_by)
        if found == "absent":
            warn(f"{where}: recorded-by '{recorded_by}' has no folder in people/ "
                 f"(add them, or fix the name)")
        elif found == "ambiguous":
            warn(f"{where}: recorded-by '{recorded_by}' cannot be classified: "
                 f"people/ or their folder is a link or not a folder")

    cls = fields.get("class")
    if cls is not None and cls not in CLASSES:
        problem(f"{where}: class '{cls}' must be one of {CLASSES} "
                f"(canonical list lives in tools/check_memory.py)")
        cls = None

    # Rule 2/3: each class carries its own burden of proof.
    if cls == "verified":
        if "evidence" not in fields:
            problem(f"{where}: class 'verified' requires an 'evidence:' field naming "
                    f"the artifact that was checked")
        else:
            check_evidence(fields["evidence"], where)
    if cls == "inferred" and "inferred-from" not in fields:
        problem(f"{where}: class 'inferred' requires an 'inferred-from:' field naming "
                f"what the reasoning rests on")
    if cls == "witnessed":
        if not fields.get("seen-in", "").strip():
            problem(f"{where}: class 'witnessed' requires a 'seen-in:' field naming the "
                    f"action or command, the environment and its versions — a first-hand "
                    f"observation without its setup cannot be seen again or checked")
        if "sources" in fields:
            problem(f"{where}: class 'witnessed' cannot declare 'sources' — an entry "
                    f"built from other entries is reasoning, so it is 'inferred' or "
                    f"stronger, never first-hand (docs/MEMORY_PROTOCOL.md rule 2)")
    if cls == "canonical":
        check_canonical_grant(fields, where, recorded_by)

    # Rule 6: an absence claim needs a scope and a positive control.
    has_surface = "surface" in fields
    has_control = "control" in fields
    if has_surface != has_control:
        missing = "control" if has_surface else "surface"
        problem(f"{where}: an absence claim needs both 'surface:' and 'control:'; "
                f"'{missing}' is missing (docs/MEMORY_PROTOCOL.md rule 6)")

    return {
        "id": entry_id,
        "path": path,
        "class": cls,
        "fields": fields,
        "observed": obs_date,
    }


def check_relationships(entries):
    """Supersession chains terminate; summaries never outrank their sources."""
    ids = set(entries)
    warned_pairs = set()
    for entry_id, e in sorted(entries.items()):
        where = f"memory/{e['path'].name}"
        fields = e["fields"]

        target = fields.get("superseded-by")
        if target is not None:
            if not ENTRY_ID.match(target):
                problem(f"{where}: superseded-by '{target}' must be an entry id like 'mem-002'")
            elif target not in ids:
                problem(f"{where}: superseded-by '{target}' is not an entry in memory/ — "
                        f"supersede with a real replacement, never a dangling pointer")
            elif target == entry_id:
                problem(f"{where}: superseded-by points at itself")

        back = fields.get("supersedes")
        if back is not None:
            if not ENTRY_ID.match(back):
                problem(f"{where}: supersedes '{back}' must be an entry id like 'mem-002'")
            elif back not in ids or back == entry_id:
                problem(f"{where}: supersedes '{back}' is not another entry in memory/")
            elif entries[back]["fields"].get("superseded-by") != entry_id:
                problem(f"{where}: supersedes '{back}', but {back} is not marked "
                        f"'superseded-by: {entry_id}' — the old entry carries the "
                        f"pointer that retires it (docs/MEMORY_PROTOCOL.md rule 5)")

        sources = fields.get("sources")
        if sources is not None:
            src_ids = [s.strip() for s in sources.split(",") if s.strip()]
            if not src_ids:
                problem(f"{where}: sources is present but empty")
            weakest = None
            for sid in src_ids:
                if not ENTRY_ID.match(sid):
                    problem(f"{where}: sources entry '{sid}' must be an id like 'mem-001'")
                    continue
                if sid not in ids:
                    problem(f"{where}: sources entry '{sid}' is not an entry in memory/")
                    continue
                s_cls = entries[sid]["class"]
                if s_cls is None:
                    continue
                if weakest is None or CLASS_RANK[s_cls] < CLASS_RANK[weakest]:
                    weakest = s_cls
            if weakest is not None and e["class"] is not None:
                if CLASS_RANK[e["class"]] > CLASS_RANK[weakest]:
                    problem(f"{where}: class '{e['class']}' is stronger than its weakest "
                            f"source ('{weakest}') — a summary is never more trustworthy "
                            f"than what it summarizes (docs/MEMORY_PROTOCOL.md)")

        contradicts = fields.get("contradicts")
        if contradicts is not None:
            items = [t.strip() for t in contradicts.split(",")]
            targets = [t for t in items if t]
            if not targets:
                problem(f"{where}: contradicts is present but empty")
            elif len(targets) != len(items):
                problem(f"{where}: contradicts has an empty item — list entry ids "
                        f"separated by single commas")
            for dup in sorted({t for t in targets if targets.count(t) > 1}):
                problem(f"{where}: contradicts lists '{dup}' more than once — one "
                        f"disagreement is one link")
            for target in dict.fromkeys(targets):
                if not ENTRY_ID.match(target):
                    problem(f"{where}: contradicts entry '{target}' must be an id like "
                            f"'mem-002'")
                elif target not in ids:
                    problem(f"{where}: contradicts '{target}', which is not an entry in "
                            f"memory/ — a contradiction keeps both entries")
                elif target == entry_id:
                    problem(f"{where}: contradicts itself")
                elif (target in (fields.get("supersedes"), fields.get("superseded-by"))
                      or entry_id in (entries[target]["fields"].get("supersedes"),
                                      entries[target]["fields"].get("superseded-by"))):
                    problem(f"{where}: contradicts '{target}', which it also supersedes "
                            f"or is superseded by — a replaced entry is not a standing "
                            f"disagreement; keep only the supersession")
                elif ("superseded-by" not in fields
                      and "superseded-by" not in entries[target]["fields"]
                      and frozenset((entry_id, target)) not in warned_pairs):
                    warned_pairs.add(frozenset((entry_id, target)))
                    # Reported every run so an unsettled disagreement stays visible
                    # until a check settles it and one side is superseded.
                    warn(f"{where}: open contradiction with {target} — neither entry is "
                         f"superseded and neither is settled; when a check decides it, "
                         f"supersede the side it disproves (docs/MEMORY_PROTOCOL.md rule 5)")

    # A cycle means retrieval can loop forever looking for the current entry.
    for entry_id in sorted(entries):
        seen = []
        cur = entry_id
        while cur in entries:
            nxt = entries[cur]["fields"].get("superseded-by")
            if nxt is None or not ENTRY_ID.match(nxt or "") or nxt not in entries:
                break
            if nxt in seen or nxt == entry_id:
                problem(f"memory/{entries[entry_id]['path'].name}: supersession chain "
                        f"loops back on itself — chains must terminate at a current entry")
                break
            seen.append(nxt)
            cur = nxt


def check_canary():
    """Rule 8: the store carries a known-present fact so retrieval can be proven."""
    canary = MEM / "CANARY.md"
    if not canary.is_file():
        problem("memory/CANARY.md is missing — without a known-present entry, no "
                "absence claim from this store can be trusted "
                "(docs/MEMORY_PROTOCOL.md rule 8)")
        return
    text = canary.read_text(encoding="utf-8")
    fields, _ = split_front_matter(text, "memory/CANARY.md")
    if fields is None:
        return
    if fields.get("id") != "mem-canary":
        problem("memory/CANARY.md: id must be 'mem-canary'")
    token = fields.get("token")
    if not token:
        problem("memory/CANARY.md: needs a 'token:' field — the fixed string a "
                "retrieval test searches for")
    elif token not in text[text.find("\n---\n") + 5:]:
        problem("memory/CANARY.md: the token does not appear in the body, so a body "
                "search for it would fail and every absence claim would be voided")


def check_index(entries, entries_raw=None):
    """Rule 7: the index is what actually gets read; it must be small and true.

    "True" means more than "lists the right ids". The index is the only part
    of the store guaranteed to be read at session start, so its class column
    is the trust signal an assistant acts on. An index row claiming
    'canonical' for an entry filed 'inferred' silently promotes a guess to a
    program decision, and nothing downstream re-reads the entry to catch it.
    So the row is checked against the entry it points at, field by field.
    """
    index = MEM / "README.md"
    if not index.is_file():
        # Required even when the store is empty: the index is what an assistant
        # reads at session start, and a repo with no index teaches every future
        # session that there is nothing to read.
        problem("memory/README.md is missing — the index is the part an assistant "
                "reads at session start; an empty store still needs one")
        return
    raw = index.read_bytes()
    if len(raw) > MAX_INDEX_BYTES:
        problem(f"memory/README.md is {len(raw)} bytes, over the {MAX_INDEX_BYTES}-byte "
                f"reading budget — past this the tail is silently dropped and the "
                f"assistant behaves as if it were never written; split it by topic "
                f"(docs/MEMORY_PROTOCOL.md rule 7)")
    text = raw.decode("utf-8").replace("\r\n", "\n")
    fmt = STORE_FORMAT_LINE.search(text)
    active_header = INDEX_HEADER_V2 if (fmt and fmt.group(1) == "v2") else INDEX_HEADER
    listed = set()
    rows = {}
    live, open_fence = strip_fenced(text)
    if open_fence is not None:
        problem(f"memory/README.md line {open_fence}: this code fence is never "
                f"closed — the check treats everything after it as code while "
                f"GitHub may still render some of it, so the file does not render "
                f"the way it reads; close the fence")
    tables, consumed = scan_tables(live)

    # Restricted surface (round 5): the scanner models exactly one block
    # context, top-level GFM tables. GitHub renders trust-claim tables in
    # places the scanner never looks — inside blockquotes, inside list items,
    # as raw HTML — and a forged canonical row rendered there is read by every
    # human and checked by nothing. A container model would have to be a real
    # markdown parser to stay honest; rejecting what cannot be modelled is
    # smaller, and it turns this whole class of blind spot into a loud
    # failure instead of a silent pass.
    for lineno, line in live:
        if BLOCKQUOTE.match(line):
            problem(f"memory/README.md line {lineno}: blockquote markers are not "
                    f"allowed in this file — GitHub renders full markdown, tables "
                    f"included, inside a blockquote, and this check cannot see into "
                    f"container blocks; quoted material belongs in an entry file or "
                    f"a fenced example")
            continue
        if HTML_BLOCK.match(line):
            problem(f"memory/README.md line {lineno}: raw HTML is not allowed in "
                    f"this file — an HTML table renders a trust claim this check "
                    f"cannot read; write markdown the checker and the reader parse "
                    f"the same way (links as [text](url), not autolinks)")
            continue
        if lineno in consumed:
            continue
        if UNESCAPED_PIPE.search(line):
            problem(f"memory/README.md line {lineno}: pipe line is not part of the "
                    f"index table — depending on surrounding container context "
                    f"GitHub renders a line like this as a table row, as code, or "
                    f"as plain text, and this check cannot tell which; outside the "
                    f"index table, pipe characters belong only inside a closed "
                    f"code fence")

    # Exactly one table may speak in the index's voice. A header that uses the
    # five index column names without being the exact index header renders as
    # an index-shaped table a reader will trust while its rows bind to no row
    # contract; an entry id appearing as a cell of any other table is a trust
    # claim wherever it renders. Both are rejected, not skipped.
    index_tables = []
    for t in tables:
        low = [c.lower() for c in t["header"]]
        named = [c for c in low if c]
        if low == active_header:
            index_tables.append(t)
            continue
        # A table speaking in EITHER format's index voice is a trust claim:
        # a five-column index-shaped table inside a v2 store is still a
        # table a reader will trust and this check cannot bind.
        if any(named == h or sorted(named) == sorted(h)
               for h in (INDEX_HEADER, INDEX_HEADER_V2)):
            problem(f"memory/README.md line {t['line']}: this table's header uses "
                    f"the index column names but is not the exact index header — "
                    f"it renders as a second index-shaped table a reader will "
                    f"trust, while its rows cannot be bound to the row contract; "
                    f"the only table allowed to use these names is the index "
                    f"table, with the header exactly "
                    f"'| " + " | ".join(active_header) + " |'")
        for lineno, bline in t["body"]:
            for cell in split_index_cells(bline):
                if ENTRY_ID.match(cell) or NEAR_ENTRY_ID.match(cell):
                    problem(f"memory/README.md line {lineno}: '{cell}' appears as "
                            f"a cell of a table that is not the index — a reader "
                            f"takes an id-keyed row as a trust claim about that "
                            f"entry, and only index-table rows are checked "
                            f"against the store")
                    break
    if not index_tables:
        problem("memory/README.md: no index table found — it must contain a table "
                "with the header '| id | topic | class | observed | summary |' "
                "(docs/MEMORY_PROTOCOL.md); without it nothing an assistant reads "
                "at session start is checked against the store")
        return
    if len(index_tables) > 1:
        problem(f"memory/README.md: {len(index_tables)} index tables found (lines "
                f"{', '.join(str(t['line']) for t in index_tables)}) — a reader "
                f"scans the first and may never reach the second, so two tables can "
                f"disagree while every row in each is individually valid")

    body_rows = [(lineno, line) for t in index_tables for lineno, line in t["body"]]
    for lineno, line in body_rows:
        cells = split_index_cells(line)
        if not cells:
            problem(f"memory/README.md line {lineno}: index table row is empty")
            continue
        first = cells[0]
        # Every body row of the index table is checked. There is no id-shaped
        # escape hatch: the renderer puts this row in the table a reader acts
        # on, so an id it cannot bind to an entry is an unverifiable trust
        # claim regardless of how far the string is from "mem-NNN".
        if not ENTRY_ID.match(first):
            near = " (close to an entry id — ids are exactly 'mem-NNN')" if \
                NEAR_ENTRY_ID.match(first) else ""
            problem(f"memory/README.md line {lineno}: index row id '{first}' is not "
                    f"a valid entry id{near} — it renders inside the index table, so "
                    f"a reader sees a trust claim that matches no entry file and "
                    f"nothing can check")
            continue
        entry_id = first
        listed.add(entry_id)
        # | id | topic | class | observed | summary |
        #
        # Every cell is required and non-empty, summary included. The contract
        # is declared in docs/MEMORY_PROTOCOL.md and the checker has to enforce
        # exactly what is declared: a row whose summary is blank is the row a
        # reader scans and learns nothing from, and a row with extra cells means
        # the parse disagrees with the render, so the field the checker compared
        # is not the field the human read. Both are unreadable claims, and an
        # unreadable claim must not be scored as agreement.
        # Width and required cells derive from INDEX_HEADER so the v2
        # checker (tools/check_tracking.py) can widen the index through the
        # same code path instead of growing a second row contract — the
        # first five positions stay the trust claim either way.
        if (len(cells) != len(active_header)
                or not all(cells[i] for i in (1, 2, 3, 4))):
            problem(f"memory/README.md: index row for '{entry_id}' is malformed — "
                    f"a row must be exactly '| " + " | ".join(active_header)
                    + f" |' with every cell of the first five non-empty (write "
                    f"a literal pipe in a cell as \\|); got {len(cells)} "
                    f"cell(s). A row missing its trust fields reads as "
                    f"'indexed' while telling a reader nothing about how far "
                    f"to trust the entry")
            continue
        if cells[2] not in CLASSES:
            problem(f"memory/README.md: index row '{entry_id}' has class "
                    f"'{cells[2]}', which is not one of {', '.join(CLASSES)} — "
                    f"the class column is read as a trust budget, so an "
                    f"unrecognised value is not a weaker claim, it is an "
                    f"uninterpretable one")
            continue
        # Duplicate rows are rejected regardless of order. Last-write-wins let a
        # forged row hide behind a valid one placed after it: the forged row is
        # what a human reads, the valid row is what the checker compared. Both
        # orders are the same defect, so neither is permitted to survive.
        if entry_id in rows:
            problem(f"memory/README.md: '{entry_id}' appears in the index more "
                    f"than once — a reader acts on the first row they see and "
                    f"the checker on the last, so duplicate rows can disagree "
                    f"with each other while the store still reports consistent")
            continue
        rows[entry_id] = {
            "topic": cells[1],
            "class": cells[2],
            "observed": cells[3],
        }
    for entry_id in sorted(entries):
        if entry_id not in listed:
            problem(f"memory/README.md: entry '{entry_id}' is in memory/ but not in the "
                    f"index — the index and the store must be updated together")
    for entry_id in sorted(listed):
        if entry_id not in entries:
            problem(f"memory/README.md: index lists '{entry_id}' but no such entry exists "
                    f"in memory/ — an index that points at nothing is worse than no index")

    # The row must agree with the entry, not merely name it.
    for entry_id, row in sorted(rows.items()):
        e = entries.get(entry_id)
        if e is None:
            continue
        fields = e["fields"]
        row_class = row.get("class")
        entry_class = fields.get("class")
        if row_class and entry_class and row_class != entry_class:
            problem(f"memory/README.md: index row '{entry_id}' says class "
                    f"'{row_class}' but the entry says '{entry_class}' — the index "
                    f"is what gets read, so a disagreeing row changes how far a "
                    f"reader trusts the entry without changing the entry")
        row_obs = row.get("observed")
        entry_obs = fields.get("observed")
        if row_obs and entry_obs and row_obs != entry_obs:
            problem(f"memory/README.md: index row '{entry_id}' says observed "
                    f"'{row_obs}' but the entry says '{entry_obs}' — a reader "
                    f"budgets trust by age, and the index is the age they see")
        row_topic = row.get("topic")
        entry_topic = fields.get("topic")
        if row_topic and entry_topic and row_topic != entry_topic:
            problem(f"memory/README.md: index row '{entry_id}' says topic "
                    f"'{row_topic}' but the entry says '{entry_topic}'")


def main():
    entries_raw = read_entries()
    parsed = {}
    for entry_id, (path, text) in sorted(entries_raw.items()):
        result = check_entry(entry_id, path, text)
        if result is not None:
            parsed[entry_id] = result
    check_relationships(parsed)
    if MEM.is_dir():
        check_entries_not_deleted(entries_raw)
    if MEM.is_dir():
        check_canary()
        check_index(parsed, entries_raw)

    for w in warnings:
        print("  warning:", w)
    if problems:
        print("check_memory: %d problem(s) found" % len(problems))
        for p in problems:
            print("  -", p)
        return 1
    print("check_memory: OK (%d entr%s consistent, classed, and indexed)"
          % (len(parsed), "y" if len(parsed) == 1 else "ies"))
    return 0


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8")
    sys.exit(main())
