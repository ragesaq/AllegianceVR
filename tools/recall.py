#!/usr/bin/env python3
"""Word search over this repository's notes, with match labels.

    python3 tools/recall.py search "how do I prove a search works"
    python3 tools/recall.py search --json "who may approve a canonical entry"
    python3 tools/recall.py index            # build or update the cache, report coverage
    python3 tools/recall.py check-glossary   # every glossary target must be real
    python3 tools/recall.py enable-vectors --model-from DIR   # optional; see below
    python3 tools/recall.py check-vectors    # the paraphrase canary

A hit is a lead, never evidence: open the file and work from the file. An
empty list means no word matched; it never means the answer is absent
(docs/MEMORY_PROTOCOL.md rule 6 still needs a search with its control).
A memory-entry hit shows the class its front matter declares, nothing
more: whether the entry is current, expired, superseded or contradicted
is tools/check_memory.py's answer, not this tool's.
Full contract: docs/RECALL.md. Design record:
docs/proposals/2026-11-22-recall-and-memory-direction.md.

Standard library only. The cache is a derived, contentless SQLite FTS5
index in .hyperbench-recall/ at the working-tree root: never committed,
never exported, rebuilt from the files at will. Where the interpreter's
SQLite lacks the exact FTS5 table this needs, a plain scan runs instead.
Vectors are an optional part, switched on per worktree by enable-vectors
(tools/recall_vectors.py); they need numpy, model2vec and a pinned model.
"""
import argparse
import errno
import hashlib
import json
import os
import re
import sqlite3
import stat
import subprocess
import sys
import time
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_memory as cm  # noqa: E402
import check_tracking as ct  # noqa: E402
import recall_vectors as rv  # noqa: E402  (standard library at import)

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ".hyperbench-recall"
DB_NAME = "index.sqlite"
GLOSSARY = "RECALL_GLOSSARY.json"
GLOSSARY_SCHEMA = "hyperbench.recall-glossary/v1"
DECLARED = ("AGENTS.md", "memory", "knowledge", "docs")
SCHEMA = "3"
CHUNKER = "1"
CHUNK_CAP = 2000
MAX_WALKS = 3
TOKENIZER = "porter unicode61"
# 'meta' holds the path and heading trail, 'body' the passage, so a label
# can say when a match is only in the path or a heading.
DDL_WORDS = ("CREATE VIRTUAL TABLE {name} USING fts5(meta, body, content='', "
             "contentless_delete=1, tokenize='" + TOKENIZER + "')")
CACHE_CHILDREN = (DB_NAME, DB_NAME + "-wal", DB_NAME + "-shm", DB_NAME + "-journal",
                  ".gitignore")
# Read only where vectors are wanted: --no-vectors touches none of them.
VECTOR_CHILDREN = (rv.RECORD,)
VECTOR_FOLDERS = (rv.MODEL_DIR,)
CANDIDATE_LIMIT = 500
BUSY_TIMEOUT = 10  # seconds a writer waits for another writer

# Display caps (docs/RECALL.md, "Bounded output"). Development settings;
# the calibration run in an applied project may change them.
MAX_PRIMARY = 10
MAX_RELATED = 5
PER_FILE = 2
SNIPPET_LINES = 8
SNIPPET_CHARS = 480
TOKEN_CAP = 2500
FOOTER_RESERVE = 120
QUERY_ECHO = 200
PATH_ECHO = 160
NOTE_ECHO = 240
MAX_NOTES = 5
MAX_COLLISIONS = 3
MAX_LINKS_SHOWN = 3

PRIMARY_LABELS = ("exact", "alias", "words")
RELATED_LABELS = ("meaning", "linked")
LABEL_RANK = {label: n for n, label in enumerate(PRIMARY_LABELS + RELATED_LABELS)}
IN_META = "path or heading only"
ROUTE = {"exact": "identifier", "alias": "glossary", "words": "words",
         "meaning": "vectors", "linked": "link"}
NOT_ENABLED = "not enabled in this worktree (python3 tools/recall.py enable-vectors)"
UNCHANGED_RECORD = ("a vector record this worktree already had is unchanged; the next "
                    "search says whether vectors are on")

HEADING = re.compile(r"^ {0,3}(#{1,6})[ \t]+(.*?)[ \t]*#*[ \t]*$")
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
TOKEN = re.compile(r"[^\W_]+")
ENTRY_FILE = re.compile(r"^memory/(mem-\d{3})-[a-z0-9][a-z0-9-]*\.md$")
STOPWORDS = frozenset("""
a about after all also an and any are as at be been before being but by can
could did do does doing for from had has have how i if in into is it its me
my no not of on or our should so than that the their them then there these
they this those to under up was we were what when where which who whom why
will with would you your
""".split())
MISSING = "tracked but missing from the working tree"
LINKED = "a symlink or junction; links are not followed"
NOT_FILE = "not a regular file"
NOT_UTF8 = "not valid UTF-8"


class RecallError(Exception):
    pass


class CacheUnavailable(RecallError):
    """The cache cannot be used here (unreadable, unwritable, not ignored by
    Git). A search answers by a plain scan instead and says why; nothing in
    the cache is deleted."""


class Unsafe(Exception):
    """A path that is not a plain regular file inside the tree."""


# ---------------------------------------------------------------- tokens

def fold(text):
    """Lower-case and drop diacritics, close to what unicode61 does by
    default. Exact matches never depend on it: they are found literally."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def tokens(text):
    return TOKEN.findall(fold(text))


def light_stem(word):
    """Suffix stripping for the plain scan only; FTS5 uses Porter. The
    capability line says which one ran."""
    for suffix, keep in (("ies", "y"), ("sses", "ss"), ("ing", ""), ("ed", ""),
                         ("es", ""), ("s", ""), ("ly", "")):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[: len(word) - len(suffix)] + keep
    return word


def content_terms(text):
    return [t for t in tokens(text) if t not in STOPWORDS]


def fts_quote(token):
    return '"' + token.replace('"', '""') + '"'


def clip(text, n):
    return text if len(text) <= n else text[: n - 1] + "…"


# ---------------------------------------------------------------- confined reads

def _is_link_stat(info):
    return (stat.S_ISLNK(info.st_mode)
            or bool(getattr(info, "st_file_attributes", 0)
                    & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)))


def _linked(path):
    try:
        info = os.lstat(path)
    except OSError:
        return True
    return _is_link_stat(info)


# A read never follows a link that is in the tree when it looks. Where the
# platform can open a path one folder at a time without following a link
# (POSIX), every read does; elsewhere (Windows) each folder and the file are
# checked before the open. The working tree's own writers are trusted: a
# link swapped in while a read runs is outside what this guards
# (docs/RECALL.md, "What it searches").
_DIR_FD = (hasattr(os, "O_NOFOLLOW") and hasattr(os, "O_DIRECTORY")
           and os.open in os.supports_dir_fd)
_LINK_ERRNOS = {errno.ELOOP, errno.ENOTDIR, getattr(errno, "EMLINK", errno.ELOOP)}


def _plain_parents(root, parts):
    for i in range(1, len(parts)):
        d = Path(root).joinpath(*parts[:i])
        info = os.lstat(d)
        if _is_link_stat(info) or not stat.S_ISDIR(info.st_mode):
            raise Unsafe(f"inside a linked folder ({'/'.join(parts[:i])})")


def _open_confined(root, rel):
    parts = rel.split("/")
    if any(p in ("", ".", "..") for p in parts) or "\\" in rel:
        raise Unsafe("not a plain relative path")
    if _DIR_FD:
        nofollow = os.O_RDONLY | os.O_NOFOLLOW
        fd = os.open(str(root), os.O_RDONLY | os.O_DIRECTORY)
        try:
            for i, part in enumerate(parts[:-1]):
                try:
                    nfd = os.open(part, nofollow | os.O_DIRECTORY, dir_fd=fd)
                except FileNotFoundError:
                    raise
                except OSError as exc:
                    if exc.errno in _LINK_ERRNOS:
                        raise Unsafe(f"inside a linked folder ({'/'.join(parts[:i + 1])})")
                    raise
                os.close(fd)
                fd = nfd
            try:
                return os.open(parts[-1], nofollow | getattr(os, "O_NONBLOCK", 0), dir_fd=fd)
            except OSError as exc:
                if exc.errno in _LINK_ERRNOS:
                    raise Unsafe(LINKED)
                raise
        finally:
            os.close(fd)
    _plain_parents(root, parts)
    path = Path(root).joinpath(*parts)
    before = os.lstat(path)
    if _is_link_stat(before):
        raise Unsafe(LINKED)
    if not stat.S_ISREG(before.st_mode):
        raise Unsafe(NOT_FILE)
    return os.open(str(path), os.O_RDONLY | getattr(os, "O_BINARY", 0))


def read_confined(root, rel):
    """(bytes, stat) of root/rel, a regular file reached through no link.
    Raises Unsafe, FileNotFoundError or another OSError."""
    fd = _open_confined(root, rel)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise Unsafe(NOT_FILE)
        out = []
        while True:
            block = os.read(fd, 1 << 20)
            if not block:
                break
            out.append(block)
        return b"".join(out), info
    finally:
        os.close(fd)


def read_json(root, rel):
    """Parsed JSON of a tracked file at root/rel, or None when it is absent,
    linked or unreadable."""
    try:
        raw, _ = read_confined(root, rel)
        return json.loads(raw.decode("utf-8"))
    except (Unsafe, OSError, ValueError):
        return None


# ---------------------------------------------------------------- walk

class Snapshot:
    """One walk: the bytes observed for each declared, tracked file."""

    def __init__(self):
        self.files = {}        # path -> dict(sha256, size, mtime_ns, text|None)
        self.skipped = []      # (path, reason)
        self.skipped_sha = {}  # path -> sha256, for files read but not decoded
        self.collisions = []   # [paths]


def git_tracked(root, paths=None):
    cmd = ["git", "-C", str(root), "ls-files", "-z"]
    if paths:
        cmd += ["--", *paths]
    try:
        proc = subprocess.run(cmd, capture_output=True)
    except OSError as exc:
        raise RecallError(f"git is not available: {exc}")
    if proc.returncode != 0:
        raise RecallError("git ls-files failed: "
                          + proc.stderr.decode("utf-8", "replace").strip())
    return [n for n in proc.stdout.decode("utf-8", "replace").split("\0") if n]


def git_toplevel(root):
    """Refuse anything but the top of a Git working tree, before any write."""
    try:
        proc = subprocess.run(["git", "-C", str(root), "rev-parse", "--show-toplevel"],
                              capture_output=True)
    except OSError as exc:
        raise RecallError(f"git is not available: {exc}")
    if proc.returncode != 0:
        raise RecallError("not a Git working tree (git rev-parse failed): "
                          + proc.stderr.decode("utf-8", "replace").strip())
    top = proc.stdout.decode("utf-8", "replace").strip()
    if (os.path.normcase(os.path.realpath(top))
            != os.path.normcase(os.path.realpath(str(root)))):
        raise RecallError(f"not the top of its Git working tree (that is {top}); "
                          f"run the search from the working-tree root")


def declared_files(root, declared):
    names = []
    for name in git_tracked(root, list(declared)):
        if not name.lower().endswith(".md") or name == GLOSSARY:
            continue
        if name.split("/", 1)[0] == CACHE_DIR:
            continue
        names.append(name)
    return sorted(set(names))


def stat_file(root, rel, checked_dirs):
    """(size, mtime_ns) for a regular file inside the tree, or a reason.
    A cheap first look that names the reason; read_confined enforces it."""
    path = root / rel
    parts = rel.split("/")
    for i in range(1, len(parts)):
        d = "/".join(parts[:i])
        if d not in checked_dirs:
            checked_dirs[d] = _linked(root / d)
        if checked_dirs[d]:
            return None, f"inside a linked folder ({d})"
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return None, MISSING
    except OSError as exc:
        return None, f"cannot be read ({exc.strerror})"
    if _is_link_stat(info):
        return None, LINKED
    if not stat.S_ISREG(info.st_mode):
        return None, NOT_FILE
    return (info.st_size, info.st_mtime_ns), None


def observe(root, rel, checked_dirs):
    """('file', bytes, size, mtime_ns) or ('skip', reason)."""
    _, reason = stat_file(root, rel, checked_dirs)
    if reason:
        return ("skip", reason)
    try:
        raw, info = read_confined(root, rel)
    except Unsafe as exc:
        return ("skip", str(exc))
    except FileNotFoundError:
        return ("skip", MISSING)
    except OSError as exc:
        return ("skip", f"cannot be read ({exc.strerror})")
    return ("file", raw, info.st_size, info.st_mtime_ns)


def walk(root, declared):
    """Read the declared files once."""
    snap = Snapshot()
    checked = {}
    names = declared_files(root, declared)
    groups = {}
    for rel in names:
        groups.setdefault(unicodedata.normalize("NFC", rel).casefold(), []).append(rel)
    snap.collisions = [sorted(g) for g in groups.values() if len(g) > 1]
    for rel in names:
        seen = observe(root, rel, checked)
        if seen[0] == "skip":
            snap.skipped.append((rel, seen[1]))
            continue
        _, raw, size, mtime = seen
        sha = hashlib.sha256(raw).hexdigest()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            snap.skipped.append((rel, NOT_UTF8))
            snap.skipped_sha[rel] = sha
            continue
        snap.files[rel] = {"sha256": sha, "size": size, "mtime_ns": mtime, "text": text}
    return snap


def recheck(root, declared, snap):
    """List and hash again; return the paths that moved, including a
    skipped file that has since become readable."""
    changed = set()
    names = set(declared_files(root, declared))
    seen = set(snap.files) | {p for p, _ in snap.skipped}
    changed |= names ^ seen
    checked = {}
    for rel, obs in snap.files.items():
        if rel not in names:
            continue
        now = observe(root, rel, checked)
        if now[0] == "skip" or hashlib.sha256(now[1]).hexdigest() != obs["sha256"]:
            changed.add(rel)
    for rel, reason in snap.skipped:
        if rel not in names:
            continue
        now = observe(root, rel, checked)
        if now[0] == "skip":
            if now[1] != reason:
                changed.add(rel)
        elif hashlib.sha256(now[1]).hexdigest() != snap.skipped_sha.get(rel):
            changed.add(rel)
    return sorted(changed)


# ---------------------------------------------------------------- chunks

def chunk(text):
    """Heading sections, split at CHUNK_CAP characters on line boundaries.
    A single line longer than the cap is a passage of its own, kept whole,
    so a locator is always a line span. Returns [(start_line, end_line,
    trail, text, sha256)], lines 1-based and inclusive, sha256 over the
    chunk's exact bytes."""
    lines = text.splitlines(keepends=True)
    sections = []
    trail = []
    start = 0
    current = ()
    fence = None
    for i, line in enumerate(lines):
        bare = line.rstrip("\r\n")
        m = FENCE.match(bare)
        if m:
            mark = m.group(1)
            if fence is None:
                fence = (mark[0], len(mark))
            elif mark[0] == fence[0] and len(mark) >= fence[1] and not m.group(2).strip():
                fence = None
            continue
        if fence is not None:
            continue
        h = HEADING.match(bare)
        if not h:
            continue
        if i > start:
            sections.append((start, i, current))
        level = len(h.group(1))
        while trail and trail[-1][0] >= level:
            trail.pop()
        trail.append((level, h.group(2).strip()))
        current = tuple(t for _, t in trail)
        start = i
    sections.append((start, len(lines), current))

    out = []
    for begin, end, heads in sections:
        piece = []
        size = 0
        piece_start = begin
        for i in range(begin, end):
            if piece and size + len(lines[i]) > CHUNK_CAP:
                out.append(_chunk_row(lines, piece_start, i, heads))
                piece, size, piece_start = [], 0, i
            piece.append(lines[i])
            size += len(lines[i])
        if piece:
            out.append(_chunk_row(lines, piece_start, end, heads))
    return [c for c in out if c[3].strip()]


def _chunk_row(lines, begin, end, heads):
    body = "".join(lines[begin:end])
    return (begin + 1, end, heads, body,
            hashlib.sha256(body.encode("utf-8")).hexdigest())


def meta_text(path, heads):
    return path + "\n" + " > ".join(heads)


# ---------------------------------------------------------------- index

def probe_fts5():
    """The exact table definition, not a generic FTS5 check: builds without
    contentless_delete pass a generic probe and fail here."""
    try:
        conn = sqlite3.connect(":memory:")
        conn.execute(DDL_WORDS.format(name="probe"))
        conn.execute("INSERT INTO probe(rowid, meta, body) VALUES (1, 'p', 'quiet foxes ran')")
        hit = conn.execute("SELECT rowid FROM probe WHERE probe MATCH 'body : fox'").fetchall()
        conn.execute("DELETE FROM probe WHERE rowid = 1")
        gone = conn.execute("SELECT rowid FROM probe WHERE probe MATCH 'fox'").fetchall()
        conn.close()
    except sqlite3.Error as exc:
        return False, f"SQLite {sqlite3.sqlite_version}: {exc}"
    if hit != [(1,)] or gone:
        return False, f"SQLite {sqlite3.sqlite_version}: contentless delete did not behave"
    return True, f"SQLite {sqlite3.sqlite_version} FTS5, Porter stemming"


def manifest(declared):
    return {"schema": SCHEMA, "chunker": CHUNKER, "cap": str(CHUNK_CAP),
            "tokenizer": TOKENIZER, "paths": json.dumps(list(declared))}


def cache_path(root):
    return root / CACHE_DIR / DB_NAME


IGNORE_BYTES = b"*\n"


def _ensure_folder(folder):
    for attempt in (1, 2):
        try:
            info = os.lstat(folder)
        except FileNotFoundError:
            if attempt == 2:
                raise CacheUnavailable(f"{CACHE_DIR}/ could not be created")
            try:
                os.mkdir(folder)
            except FileExistsError:
                pass
            continue
        if _is_link_stat(info) or not stat.S_ISDIR(info.st_mode):
            raise RecallError(f"{CACHE_DIR} is a link or not a folder; refusing to write through it")
        return


def _ensure_inner_ignore(folder):
    """The folder's own '.gitignore' holds exactly '*'. Created exclusively;
    an existing file is never rewritten. An empty one may be another first
    search still writing it, so it is read again for a moment; anything
    else, or an empty file that stays empty (an interrupted first run), is
    refused."""
    path = folder / ".gitignore"
    try:
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL
                     | getattr(os, "O_BINARY", 0), 0o644)
    except FileExistsError:
        fd = None
    if fd is not None:
        try:
            os.write(fd, IGNORE_BYTES)
        finally:
            os.close(fd)
        return
    deadline = time.monotonic() + 2
    while True:
        raw = path.read_bytes()
        if raw == IGNORE_BYTES:
            return
        if raw or time.monotonic() > deadline:
            raise CacheUnavailable(f"{CACHE_DIR}/.gitignore does not hold exactly '*'; "
                                   f"remove {CACHE_DIR}/ and search again")
        time.sleep(0.05)


def git_ignores_cache(root):
    proc = subprocess.run(["git", "-C", str(root), "check-ignore", "-q", "--no-index",
                           f"{CACHE_DIR}/{DB_NAME}"], capture_output=True)
    return proc.returncode == 0


def ensure_cache_dir(root, vectors=True):
    """The cache folder and its files, each a plain folder or file, and Git
    ignoring the database, all before SQLite opens anything there. The
    vector record and model folder are checked only when vectors are
    wanted (vectors=False is --no-vectors, which reads neither)."""
    folder = root / CACHE_DIR
    try:
        _ensure_folder(folder)
        for name in CACHE_CHILDREN + (VECTOR_CHILDREN if vectors else ()):
            try:
                info = os.lstat(folder / name)
            except FileNotFoundError:
                continue
            if _is_link_stat(info) or not stat.S_ISREG(info.st_mode):
                raise RecallError(f"{CACHE_DIR}/{name} is a link or not a file; refusing to "
                                  f"write through it. Remove {CACHE_DIR}/ and search again")
        for name in VECTOR_FOLDERS if vectors else ():
            try:
                info = os.lstat(folder / name)
            except FileNotFoundError:
                continue
            if _is_link_stat(info) or not stat.S_ISDIR(info.st_mode):
                raise RecallError(f"{CACHE_DIR}/{name} is a link or not a folder; refusing "
                                  f"to use it. Remove {CACHE_DIR}/ and search again")
        _ensure_inner_ignore(folder)
    except OSError as exc:
        raise CacheUnavailable(f"{CACHE_DIR}/ cannot be created or written here "
                               f"({exc.strerror or exc})")
    if not git_ignores_cache(root):
        raise CacheUnavailable(f"Git does not ignore {CACHE_DIR}/{DB_NAME} here")


def _squash(sql):
    return " ".join((sql or "").split())


def _create_schema(conn, want):
    conn.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.execute("CREATE TABLE files(path TEXT PRIMARY KEY, sha256 TEXT NOT NULL, "
                 "size INTEGER NOT NULL, mtime_ns INTEGER NOT NULL)")
    conn.execute("CREATE TABLE chunks(id INTEGER PRIMARY KEY AUTOINCREMENT, "
                 "path TEXT NOT NULL, start_line INTEGER NOT NULL, "
                 "end_line INTEGER NOT NULL, sha256 TEXT NOT NULL)")
    conn.execute("CREATE INDEX chunks_path ON chunks(path)")
    conn.execute(DDL_WORDS.format(name="words"))
    # Vectors are keyed by their computation key (recall_vectors.py), never
    # by a locator: two identical passages may share one, never a path.
    conn.execute("CREATE TABLE vectors(key TEXT PRIMARY KEY, data BLOB NOT NULL)")
    conn.executemany("INSERT INTO meta VALUES (?, ?)",
                     list(want.items()) + [("generation", "0")])


def _objects(conn):
    """(type, name) -> squashed SQL for every schema object SQLite did not
    create for itself (the reserved prefix, matched literally: in LIKE an
    underscore is a wildcard)."""
    return {(t, n): _squash(s) for t, n, s in conn.execute(
        "SELECT type, name, sql FROM sqlite_master WHERE substr(name, 1, 7) != 'sqlite_'")}


_EXPECTED = None


def expected_objects():
    """The object inventory of a fresh cache, built by this SQLite. Every
    definition is compared, the word table's shadow tables included; a
    cache another SQLite version built differently is rebuilt in place."""
    global _EXPECTED
    if _EXPECTED is None:
        conn = sqlite3.connect(":memory:")
        _create_schema(conn, {})
        _EXPECTED = _objects(conn)
        conn.close()
    return _EXPECTED


def schema_problem(conn, want):
    """None when the cache holds exactly this release's schema objects and
    manifest; 'empty' for a new file; otherwise what differs."""
    have = _objects(conn)
    if not have:
        return "empty"
    expected = expected_objects()
    for key, sql in expected.items():
        if key not in have:
            return f"missing its {key[1]} {key[0]}"
        if have[key] != sql:
            return f"holding a {key[1]} {key[0]} defined another way"
    extra = sorted(n for _, n in set(have) - set(expected))
    if extra:
        return "holding objects this tool did not create (" + ", ".join(extra[:3]) + ")"
    meta = dict(conn.execute("SELECT key, value FROM meta"))
    stale = [k for k in want if meta.get(k) != want[k]]
    if stale:
        return "built with a different " + ", ".join(stale)
    if not str(meta.get("generation", "")).isdigit():
        return "missing its generation"
    return None


def _rebuild_schema(conn, want, fresh):
    """Inside the caller's write transaction: drop every object, then create
    this release's schema."""
    if not fresh:
        if ("table", "words") in _objects(conn):
            conn.execute("DROP TABLE words")
        kinds = {"trigger": 0, "view": 1, "index": 2, "table": 3}
        for kind, name in sorted(_objects(conn), key=lambda k: kinds.get(k[0], 4)):
            if kind in kinds and (kind, name) in _objects(conn):
                conn.execute(f"DROP {kind.upper()} IF EXISTS \"{name.replace(chr(34), chr(34) * 2)}\"")
    _create_schema(conn, want)


def _busy(exc):
    text = str(exc)
    return "locked" in text or "busy" in text


def open_index(root, declared, notes, vectors=True):
    """An open connection with the current schema. A cache of another
    schema, chunker or path list, or holding any object this tool would not
    create, is rebuilt in place inside one write transaction, so a reader
    holding the old generation keeps it. A cache that cannot be read or
    written is CacheUnavailable and is never deleted. Some SQLite paths
    (switching to WAL while another first search sets up the file) return
    busy without waiting, so a busy open is retried until BUSY_TIMEOUT,
    then reported."""
    deadline = time.monotonic() + BUSY_TIMEOUT
    while True:
        try:
            return _open_index(root, declared, notes, vectors)
        except RecallError as exc:
            if not str(exc).startswith("cache is busy") or time.monotonic() > deadline:
                raise
            time.sleep(0.05)


def _open_index(root, declared, notes, vectors=True):
    ensure_cache_dir(root, vectors)
    want = manifest(declared)
    conn = None
    try:
        conn = sqlite3.connect(str(cache_path(root)), timeout=BUSY_TIMEOUT,
                               isolation_level=None)
        conn.execute("PRAGMA journal_mode=WAL")
        if schema_problem(conn, want) is not None:
            conn.execute("BEGIN IMMEDIATE")
            problem = schema_problem(conn, want)
            if problem is not None:
                _rebuild_schema(conn, want, fresh=(problem == "empty"))
                if problem != "empty":
                    notes.append(f"cache was {problem}; rebuilt")
            conn.execute("COMMIT")
        conn.execute("SELECT count(*) FROM words WHERE words MATCH 'probe'").fetchall()
        return conn
    except sqlite3.Error as exc:
        if conn is not None:
            conn.close()
        if isinstance(exc, sqlite3.OperationalError) and _busy(exc):
            raise RecallError(f"cache is busy ({exc}); try again")
        if isinstance(exc, sqlite3.OperationalError):
            raise CacheUnavailable(f"cache cannot be opened or written ({exc}); "
                                   f"check the permissions of {CACHE_DIR}/")
        raise CacheUnavailable(f"cache cannot be read as this tool's database ({exc}); "
                               f"delete {CACHE_DIR}/ to rebuild it")


def known_files(conn):
    return {p: (sha, size, mtime) for p, sha, size, mtime in
            conn.execute("SELECT path, sha256, size, mtime_ns FROM files")}


def sync(conn, snap):
    """Reconcile the index with one walk, in one write transaction, so a
    reader sees one whole generation. Returns (added_or_changed, removed)."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        have = known_files(conn)
        changed = [p for p, obs in snap.files.items()
                   if obs["text"] is not None and (p not in have or have[p][0] != obs["sha256"])]
        removed = [p for p in have if p not in snap.files]
        for p in changed + removed:
            ids = [r[0] for r in conn.execute("SELECT id FROM chunks WHERE path = ?", (p,))]
            conn.executemany("DELETE FROM words WHERE rowid = ?", [(i,) for i in ids])
            conn.execute("DELETE FROM chunks WHERE path = ?", (p,))
            conn.execute("DELETE FROM files WHERE path = ?", (p,))
        for p in changed:
            obs = snap.files[p]
            for start, end, heads, body, sha in chunk(obs["text"]):
                cur = conn.execute("INSERT INTO chunks(path, start_line, end_line, sha256) "
                                   "VALUES (?, ?, ?, ?)", (p, start, end, sha))
                conn.execute("INSERT INTO words(rowid, meta, body) VALUES (?, ?, ?)",
                             (cur.lastrowid, meta_text(p, heads), body))
            conn.execute("INSERT INTO files VALUES (?, ?, ?, ?)",
                         (p, obs["sha256"], obs["size"], obs["mtime_ns"]))
        for p, obs in snap.files.items():
            if p in have and p not in changed and have[p][1:] != (obs["size"], obs["mtime_ns"]):
                conn.execute("UPDATE files SET size = ?, mtime_ns = ? WHERE path = ?",
                             (obs["size"], obs["mtime_ns"], p))
        if changed or removed:
            conn.execute("UPDATE meta SET value = CAST(value AS INTEGER) + 1 "
                         "WHERE key = 'generation'")
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return changed, removed


# ---------------------------------------------------------------- corpus

class Corpus:
    """What a query reads: the walk, the chunks, and either the index or
    the plain scan."""

    def __init__(self, root, declared=DECLARED, scan=False, need_index=False,
                 vectors=True, embed_budget=rv.EMBED_BUDGET, encoder=None):
        self.root = Path(root)
        self.declared = tuple(declared)
        self.need_index = need_index
        self.notes = []
        # vectors=False (--no-vectors) reads no record and no model. An
        # encoder given here (tests) stands in for the pinned model.
        self.want_vectors = vectors
        self.embed_budget = embed_budget
        self.encoder = encoder
        self.vec_on = False
        self.vec_why = "switched off for this search (--no-vectors)" if not vectors else None
        self.vec_keys = []
        self.vec_have = {}
        self.vec_encoded = 0
        ok, detail = probe_fts5()
        self.fts = ok and not scan
        if scan:
            self.capability = "plain scan (requested with --scan), light suffix stemming"
        elif ok:
            self.capability = f"word index ({detail})"
        else:
            self.capability = f"plain scan, light suffix stemming (FTS5 unavailable: {detail})"
        self.conn = None
        self.reading = False
        self.walks = 0
        self.recheck_changes = []
        self.changed = []
        self.removed = []
        self._chunks = {}
        try:
            self._load()
        except BaseException:
            self.close()
            raise

    def close(self):
        if self.conn is not None:
            self.conn.close()
            self.conn = None
        self.reading = False

    def _fallback(self, exc):
        """Answer by a plain scan, saying why; the index command fails."""
        if self.need_index:
            raise exc
        self.close()
        self.fts = False
        self.capability = ("plain scan, light suffix stemming (the cache cannot be used; "
                           "see the note)")
        self.notes.append(f"{exc}; answered by a plain scan")
        self._vectors_off("they are stored in the cache, which this search cannot use")

    def _vectors_off(self, why):
        if self.vec_on or (self.want_vectors and self.vec_why is None):
            self.vec_why = why
        self.vec_on = False
        self.vec_have = {}

    def _setup_vectors(self):
        """Vectors run only when this worktree enabled them, the word index
        is in use, and the pinned model loads. A record that is absent
        means nothing more is read."""
        if not self.want_vectors:
            return
        if self.encoder is None and not rv.enabled(self.root, CACHE_DIR):
            self.vec_why = NOT_ENABLED
            return
        if self.conn is None:
            self.vec_why = ("off with the plain scan: vectors are stored in the word "
                            "index, which this search does not use")
            return
        if self.encoder is None:
            self.encoder, self.vec_why = rv.load(self.root, CACHE_DIR)
            if self.encoder is None:
                return
        self.vec_on = True
        self.vec_why = None
        self.vec_spent = 0.0

    def _vector_items(self):
        out = []
        for path, c in self.all_chunks():
            text = rv.passage_text(meta_text(path, c[2]), c[3])
            out.append((rv.computation_key(self.encoder.identity, CHUNKER, CHUNK_CAP, text),
                        text, path, c))
        return out

    def _sync_vectors(self, collect=True):
        """Inside the walk, after the word sync and before the read: embed
        what this walk's passages lack, within the budget. Unused vectors
        are dropped only when collect is true, that is when the walk's own
        word sync changed nothing. Vectors are a cache: one dropped while
        another search's newer files need it is embedded again by a later
        search that reads them and has budget left."""
        items = self._vector_items()
        budget = None
        if self.embed_budget is not None:
            budget = max(0.0, self.embed_budget - self.vec_spent)
        began = time.monotonic()
        def fresh():
            # Inside the vector write: the word index still holds this walk's
            # files, so the vectors written and kept match what it holds.
            return ({p: v[0] for p, v in known_files(self.conn).items()}
                    == {p: o["sha256"] for p, o in self.snap.files.items()})

        try:
            self.vec_encoded += rv.sync(self.conn, self.encoder,
                                        [(k, t) for k, t, _, _ in items], budget, fresh=fresh,
                                        collect=collect)
        except rv.Stale:
            self.notes.append("another search changed the index before the vectors were "
                              "written; this walk wrote none")
        except sqlite3.Error:
            raise
        except Exception as exc:
            self._vectors_off(f"the model failed while embedding ({type(exc).__name__}: {exc})")
        self.vec_spent += time.monotonic() - began
        self._vec_items = items

    def _begin_read(self):
        # One read transaction for the rest of the query: every lookup sees
        # the generation that was compared with this walk.
        self.conn.execute("BEGIN")
        self.conn.execute("SELECT count(*) FROM files").fetchone()
        self.reading = True

    def _end_read(self):
        if self.reading:
            self.conn.execute("ROLLBACK")
            self.reading = False

    def _load(self):
        """Walk and sync; damage SQLite finds only after the open (a bad data
        page, say) answers by a plain scan like damage found at the open."""
        try:
            self._load_once()
        except sqlite3.DatabaseError as exc:
            if self.conn is None or _busy(exc):
                raise
            self._fallback(CacheUnavailable(f"cache cannot be read ({exc})"))
            self._load_once()

    def _load_once(self):
        git_toplevel(self.root)
        if self.fts:
            if git_tracked(self.root, [CACHE_DIR]):
                raise RecallError(f"{CACHE_DIR}/ is tracked by Git here, and the cache is "
                                  f"never committed; untrack it (git rm -r --cached "
                                  f"{CACHE_DIR}) and search again")
            try:
                self.conn = open_index(self.root, self.declared, self.notes,
                                       self.want_vectors)
            except CacheUnavailable as exc:
                self._fallback(exc)
        self._setup_vectors()
        moved = False
        for _ in range(MAX_WALKS):
            self.walks += 1
            self.snap = walk(self.root, self.declared)
            self._chunks = {}
            moved = False
            if self.conn is not None:
                self._end_read()
                try:
                    changed, removed = sync(self.conn, self.snap)
                except sqlite3.OperationalError as exc:
                    if _busy(exc):
                        raise
                    self._fallback(CacheUnavailable(f"cache cannot be written ({exc})"))
            if self.conn is not None and self.vec_on:
                try:
                    self._sync_vectors(collect=not changed and not removed)
                except sqlite3.OperationalError as exc:
                    if _busy(exc):
                        raise
                    self._fallback(CacheUnavailable(f"cache cannot be written ({exc})"))
            if self.conn is not None:
                self.changed += changed
                self.removed += removed
                self._begin_read()
                known = known_files(self.conn)
                moved = ({p: v[0] for p, v in known.items()}
                         != {p: o["sha256"] for p, o in self.snap.files.items()})
            self.recheck_changes = recheck(self.root, self.declared, self.snap)
            if not self.recheck_changes and not moved:
                break
        if moved:
            # Another search kept rewriting the index: answer from the bytes
            # this search read, never from a generation it did not check.
            self._end_read()
            self.fts = False
            self.capability = ("plain scan of the files this search read, light suffix "
                               "stemming (the index changed under this search)")
            self.notes.append("another search changed the index while this one read it; "
                              "answered by a plain scan")
            self._vectors_off("the index changed under this search")
        if self.fts:
            self.chunk_count = self.conn.execute("SELECT count(*) FROM chunks").fetchone()[0]
        else:
            self.chunk_count = sum(1 for _ in self.all_chunks())
        if self.vec_on:
            # Read inside the same read transaction as the word lookups.
            self.vec_keys = [k for k, _, _, _ in self._vec_items]
            self.vec_have = rv.stored(self.conn, self.vec_keys, self.encoder)

    def vectors_capability(self):
        if self.vec_on:
            return (f"on ({self.encoder.name}; {self.vec_embedded()} of "
                    f"{len(self.vec_keys)} passages embedded)")
        return f"off ({self.vec_why})"

    def vec_embedded(self):
        return sum(1 for k in self.vec_keys if k in self.vec_have)

    def vector_ranked(self, query):
        """[(path, chunk)] nearest first, among the embedded passages."""
        if not self.vec_on:
            return []
        try:
            idx = rv.ranked(self.encoder, self.vec_keys, self.vec_have, query)
        except sqlite3.Error:
            raise
        except Exception as exc:
            # A vector failure never costs the word answer.
            self._vectors_off(f"the vectors failed for this query ({type(exc).__name__}: {exc})")
            self.notes.append("the vectors failed for this query; answered by words alone")
            return []
        return [(self._vec_items[i][2], self._vec_items[i][3]) for i in idx]

    def text(self, path):
        obs = self.snap.files.get(path)
        return None if obs is None else obs["text"]

    def chunks(self, path):
        if path not in self._chunks:
            text = self.text(path)
            self._chunks[path] = chunk(text) if text else []
        return self._chunks[path]

    def all_chunks(self):
        for path in sorted(self.snap.files):
            for c in self.chunks(path):
                yield path, c

    def coverage(self):
        files = len(self.snap.files)
        if self.recheck_changes:
            named = ", ".join(clip(p, PATH_ECHO) for p in self.recheck_changes[:5])
            more = len(self.recheck_changes) - 5
            seen = ("changes seen on recheck after %d walks: %s%s"
                    % (self.walks, named, f"; and {more} more" if more > 0 else ""))
        else:
            seen = "no change detected on recheck"
        return {"files": files, "chunks": self.chunk_count,
                "declaredPaths": list(self.declared),
                "skipped": [{"path": p, "reason": r} for p, r in self.snap.skipped],
                "collisions": self.snap.collisions,
                "walks": self.walks,
                "recheck": seen,
                "recheckChanged": list(self.recheck_changes),
                "updated": len(self.changed), "removed": len(self.removed),
                "vectors": {"on": self.vec_on,
                            "model": self.encoder.name if self.vec_on else None,
                            "embedded": self.vec_embedded() if self.vec_on else 0,
                            "passages": len(self.vec_keys) if self.vec_on else 0,
                            "encodedNow": self.vec_encoded,
                            "why": None if self.vec_on else self.vec_why},
                "notes": list(self.notes)}

    # -- lookup by rowid, verified against the observed bytes
    def locate(self, rowid):
        row = self.conn.execute("SELECT path, start_line, end_line, sha256 FROM chunks "
                                "WHERE id = ?", (rowid,)).fetchone()
        if row is None:
            return None
        path, start, end, sha = row
        for c in self.chunks(path):
            if c[0] == start and c[1] == end and c[4] == sha:
                return path, c
        self.notes.append(f"{path}:{start}-{end}: the index entry does not match the "
                          f"bytes this search read; left out")
        return None

    def chunk_rowid(self, path, c):
        """The index row of one passage, or None."""
        row = self.conn.execute("SELECT id FROM chunks WHERE path = ? AND start_line = ? "
                                "AND end_line = ? AND sha256 = ?",
                                (path, c[0], c[1], c[4])).fetchone()
        return None if row is None else row[0]

    def row_matches(self, rowid, query, body_query):
        """(matches, in_body) for one indexed passage, by the same matcher
        and tokenizer as fts_ranked, whatever its rank."""
        hit = self.conn.execute("SELECT 1 FROM words WHERE words MATCH ? AND rowid = ?",
                                (query, rowid)).fetchone()
        if hit is None:
            return False, False
        body = self.conn.execute("SELECT 1 FROM words WHERE words MATCH ? AND rowid = ?",
                                 (body_query, rowid)).fetchone()
        return True, body is not None

    def fts_count(self, query):
        return self.conn.execute("SELECT count(*) FROM words WHERE words MATCH ?",
                                 (query,)).fetchone()[0]

    def fts_ranked(self, query, body_query, limit=None):
        """[(path, chunk, in_body)] in rank order, ties broken by path and
        line; at most limit, CANDIDATE_LIMIT by default."""
        rows = [r[0] for r in self.conn.execute(
            "SELECT words.rowid FROM words JOIN chunks ON chunks.id = words.rowid "
            "WHERE words MATCH ? ORDER BY bm25(words), chunks.path, chunks.start_line "
            "LIMIT ?", (query, CANDIDATE_LIMIT if limit is None else limit))]
        body = set()
        for i in range(0, len(rows), 400):
            part = rows[i:i + 400]
            body.update(r[0] for r in self.conn.execute(
                "SELECT rowid FROM words WHERE words MATCH ? AND rowid IN (%s)"
                % ",".join("?" * len(part)), (body_query, *part)))
        out = []
        for rowid in rows:
            hit = self.locate(rowid)
            if hit:
                out.append((hit[0], hit[1], rowid in body))
        return out


# ---------------------------------------------------------------- registry

def load_glossary(root):
    try:
        raw, _ = read_confined(Path(root), GLOSSARY)
    except FileNotFoundError:
        return [], None
    except (Unsafe, OSError) as exc:
        return [], f"{GLOSSARY} cannot be read: {exc}"
    try:
        data = json.loads(raw.decode("utf-8"))
    except ValueError as exc:
        return [], f"{GLOSSARY} cannot be read: {exc}"
    if not isinstance(data, dict):
        return [], f"{GLOSSARY} must hold one JSON object"
    problems = []
    if data.get("schemaVersion") != GLOSSARY_SCHEMA:
        problems.append(f"schemaVersion must be '{GLOSSARY_SCHEMA}'")
    raw_entries = data.get("entries", [])
    if not isinstance(raw_entries, list):
        problems.append("'entries' must be a list")
        raw_entries = []
    entries = []
    for i, e in enumerate(raw_entries):
        words = e.get("words") if isinstance(e, dict) else None
        terms = e.get("terms") if isinstance(e, dict) else None
        ok = (isinstance(words, list) and words and isinstance(terms, list) and terms
              and all(isinstance(w, str) and tokens(w) for w in words)
              and all(isinstance(t, str) and tokens(t) for t in terms))
        if not ok:
            problems.append(f"entries[{i}] needs non-empty 'words' and 'terms' lists of strings")
            continue
        entries.append({"words": words, "terms": terms})
    return entries, ("; ".join(problems) or None)


def front_matter_words():
    """One-word front-matter keys ('class', 'topic', 'evidence'): ordinary
    words too, so exact only when the query writes them as keys ('class:')."""
    return {k for k in ct.KNOWN_KEYS if "-" not in k and "_" not in k}


def registry(root, corpus):
    """Registered identifiers: entry ids, map node ids, tracked paths,
    compound front-matter keys, entity ids and aliases. A root path with
    no folder, extension or capital ('build') is an ordinary word, so it
    is left out; 'LICENSE' and 'Makefile' are in."""
    root = Path(root)
    ids = {k for k in ct.KNOWN_KEYS if "-" in k or "_" in k}
    try:
        ids.update(p for p in git_tracked(root) if "/" in p or "." in p or p != p.lower())
    except RecallError:
        pass
    for path in corpus.snap.files:
        m = ENTRY_FILE.match(path)
        if m:
            ids.add(m.group(1))
    dag = read_json(root, "DAG.json")
    if isinstance(dag, dict) and isinstance(dag.get("nodes"), list):
        ids.update(n["id"] for n in dag["nodes"]
                   if isinstance(n, dict) and isinstance(n.get("id"), str))
    ents = read_json(root, "catalog/ENTITIES.json")
    if isinstance(ents, dict) and isinstance(ents.get("entities"), dict):
        for eid, spec in ents["entities"].items():
            ids.add(eid)
            aliases = spec.get("aliases") if isinstance(spec, dict) else None
            if isinstance(aliases, list):
                ids.update(a for a in aliases if isinstance(a, str))
    return ids


def identifier_pattern(ident):
    if ident.endswith(":"):
        return re.compile(r"(?<![\w/.-])" + re.escape(ident))
    return re.compile(r"(?<![\w/.-])" + re.escape(ident) + r"(?![\w-]|\.\w)")


QUOTED = re.compile(r'"([^"]+)"|`([^`]+)`')
EDGE = ".,;!?()[]{}<>\"'`"


def query_identifiers(query, ids, keys=frozenset()):
    found = []
    # An identifier that holds a space (a tracked path such as
    # 'docs/two words.md') is recognized whole: the whole query, or a part
    # of it in double quotes or backticks. Other words are split on spaces.
    # The query and each word are tried as written before edge punctuation
    # is trimmed, and a match as written is never also read in its trimmed
    # form: '.github/one.md' names that path, not 'github/one.md'.
    whole = query.strip()
    if whole in ids:
        found.append(whole)
    else:
        whole = whole.strip(EDGE)
        if any(ch.isspace() for ch in whole) and whole in ids:
            found.append(whole)
    for part in [a or b for a, b in QUOTED.findall(query)]:
        part = part.strip()
        if any(ch.isspace() for ch in part) and part in ids and part not in found:
            found.append(part)
    for raw in query.split():
        if raw in ids:
            if raw not in found:
                found.append(raw)
            continue
        word = raw.strip(EDGE)
        if word.endswith(":") and word.rstrip(":") in keys:
            ident = word.rstrip(":") + ":"
            if ident not in found:
                found.append(ident)
            continue
        word = word.strip(":")
        if word in ids and word not in found:
            found.append(word)
    return found


def glossary_hits(query, glossary):
    """[(query words, alias word, terms)] for each glossary entry whose
    words occur in the query as a whole phrase."""
    qstems = [light_stem(t) for t in tokens(query)]
    out = []
    for entry in glossary:
        for word in entry["words"]:
            wstems = [light_stem(t) for t in tokens(word)]
            n = len(wstems)
            if any(qstems[i:i + n] == wstems for i in range(len(qstems) - n + 1)):
                out.append((word, entry["terms"]))
                break
    return out


# ---------------------------------------------------------------- search

def _has_phrase(toks, phrase):
    n = len(phrase)
    return any(toks[i:i + n] == phrase for i in range(len(toks) - n + 1))


def scan_match(corpus, stems_any=None, phrase=None):
    """Plain-scan ranking: chunks sharing a stem (most shared first), or
    holding a stemmed phrase; each with whether the body holds it."""
    scored = []
    for path, c in corpus.all_chunks():
        meta = [light_stem(t) for t in tokens(meta_text(path, c[2]))]
        body = [light_stem(t) for t in tokens(c[3])]
        if phrase:
            in_body = _has_phrase(body, phrase)
            if in_body or _has_phrase(meta, phrase):
                scored.append((0, path, c, in_body))
        elif stems_any:
            want = set(stems_any)
            shared = len(want & (set(meta) | set(body)))
            if shared:
                scored.append((-shared, path, c, bool(want & set(body))))
    scored.sort(key=lambda x: (x[0], x[1], x[2][0]))
    return [(p, c, b) for _, p, c, b in scored]


def phrase_hits(corpus, text, limit=None):
    toks = tokens(text)
    if not toks:
        return []
    if corpus.fts:
        phrase = '"' + " ".join(toks) + '"'
        return corpus.fts_ranked(phrase, "body : " + phrase, limit)
    return scan_match(corpus, phrase=[light_stem(t) for t in toks])


def passage_evidence(corpus, path, c, query, glossary=None):
    """(label, why, where) for the strongest alias or words evidence the
    query has in this one indexed passage, by the index's own matcher, or
    None. Alias beats words; within a label a body witness beats a
    metadata one. Exact evidence needs no test here: it is found by
    reading every file. Needs the word index (vectors on implies it)."""
    if not corpus.fts:
        raise RecallError("passage evidence needs the word index")
    rowid = corpus.chunk_rowid(path, c)
    if rowid is None:
        return None
    in_meta = None
    for word, terms in glossary_hits(query, glossary or []):
        for term in terms:
            if tokens(term):
                phrase = '"' + " ".join(tokens(term)) + '"'
                found, in_body = corpus.row_matches(rowid, phrase, "body : " + phrase)
                why = f'alias: "{word}" -> {term}'
                if found and in_body:
                    return "alias", why, "body"
                if found and in_meta is None:
                    in_meta = ("alias", f"{why} ({IN_META})", IN_META)
    if in_meta:
        return in_meta
    terms = list(dict.fromkeys(content_terms(query)))
    if terms:
        found, in_body = corpus.row_matches(
            rowid, " OR ".join(fts_quote(t) for t in terms),
            " OR ".join("body : " + fts_quote(t) for t in terms))
        if found:
            return ("words", "words" + ("" if in_body else f" ({IN_META})"),
                    "body" if in_body else IN_META)
    return None


def search(corpus, query, glossary=None, vectors=True):
    """Hits in label order, each {'path','start','end','label','why',...}.
    Damage SQLite finds while answering closes the index and answers the
    same query once more by a plain scan, saying why; a busy cache is
    reported, and the cache is never deleted. vectors=False answers by
    words alone on a corpus whose vectors are on (the canary's control)."""
    notes = list(corpus.notes)
    try:
        return _search(corpus, query, glossary, vectors)
    except sqlite3.DatabaseError as exc:
        if not corpus.fts or _busy(exc):
            raise
        corpus.notes[:] = notes
        corpus._fallback(CacheUnavailable(f"cache cannot be read ({exc})"))
        corpus.chunk_count = sum(1 for _ in corpus.all_chunks())
        return _search(corpus, query, glossary, vectors)


def _search(corpus, query, glossary=None, vectors=True):
    glossary = glossary or []
    ids = registry(corpus.root, corpus)
    hits = {}
    order = []
    # The 1-based rank each lexical list gave the hits it returned, kept
    # apart from the label: fusion uses the rank the returning list gave.
    lexrank = {ROUTE["alias"]: {}, ROUTE["words"]: {}}

    def returned(route, path, c):
        lexrank[route].setdefault((path, c[0]), len(lexrank[route]) + 1)

    def add(path, c, label, why, where):
        key = (path, c[0])
        if key in hits:
            h = hits[key]
            if h["label"] == label and h["where"] == IN_META and where == "body":
                h["why"], h["where"] = why, where
            if ROUTE[label] not in h["routes"]:
                h["routes"].append(ROUTE[label])
            return h
        hits[key] = {"path": path, "start": c[0], "end": c[1], "trail": list(c[2]),
                     "text": c[3], "label": label, "why": why, "where": where, "links": [],
                     "routes": [ROUTE[label]]}
        order.append(key)
        return hits[key]

    # exact: a registered identifier as a whole token in the passage body.
    # Found by reading every searched file literally, never through the
    # index, so no limit or tokenizer difference can hide an exact answer.
    for ident in query_identifiers(query, ids, front_matter_words()):
        pat = identifier_pattern(ident)
        needle = ident.rstrip(":")
        for path in sorted(corpus.snap.files):
            text = corpus.text(path)
            if not text or needle not in text:
                continue
            for c in corpus.chunks(path):
                if pat.search(c[3]):
                    add(path, c, "exact", f"exact: {ident}", "body")
        if ident in corpus.snap.files:
            first = corpus.chunks(ident)
            if first:
                add(ident, first[0], "exact", f"exact: path {ident}", "path")

    # alias: a glossary target term for a query word
    for word, terms in glossary_hits(query, glossary):
        for term in terms:
            if corpus.fts and tokens(term):
                total = corpus.fts_count('"' + " ".join(tokens(term)) + '"')
                if total > CANDIDATE_LIMIT:
                    corpus.notes.append(f"alias {term}: {total} passages matched; the "
                                        f"{CANDIDATE_LIMIT} best ranked were considered")
            for path, c, in_body in phrase_hits(corpus, term):
                why = f'alias: "{word}" -> {term}' + ("" if in_body else f" ({IN_META})")
                add(path, c, "alias", why, "body" if in_body else IN_META)
                returned(ROUTE["alias"], path, c)

    # words: at least one stemmed content term
    terms = list(dict.fromkeys(content_terms(query)))
    if terms:
        if corpus.fts:
            q = " OR ".join(fts_quote(t) for t in terms)
            total = corpus.fts_count(q)
            if total > CANDIDATE_LIMIT:
                corpus.notes.append(f"words: {total} passages matched; the "
                                    f"{CANDIDATE_LIMIT} best ranked were considered")
            ranked = corpus.fts_ranked(q, " OR ".join("body : " + fts_quote(t) for t in terms))
        else:
            ranked = scan_match(corpus, stems_any=[light_stem(t) for t in terms])
        for path, c, in_body in ranked:
            add(path, c, "words", "words" + ("" if in_body else f" ({IN_META})"),
                "body" if in_body else IN_META)
            returned(ROUTE["words"], path, c)

    # meaning: a passage the vectors returned that holds no evidence of its
    # own. One that does keeps its own label and records the route. Classed
    # before links, so a passage both the vectors and a link reached is
    # meaning, never linked.
    vrank = {}
    if vectors and corpus.vec_on:
        for i, (path, c) in enumerate(corpus.vector_ranked(query)):
            key = (path, c[0])
            vrank[key] = i + 1
            h = hits.get(key)
            if h is None or h["label"] != "exact":
                # Each word list holds only its best CANDIDATE_LIMIT matches:
                # evidence a list did not return still decides the label,
                # whatever its rank. It is evidence, not a route: no route or
                # word rank is added for it.
                ev = passage_evidence(corpus, path, c, query, glossary)
                if ev and (h is None or (LABEL_RANK[ev[0]], ev[2] != "body")
                           < (LABEL_RANK[h["label"]], h["where"] != "body")):
                    if h is None:
                        h = add(path, c, *ev)
                        h["routes"] = []
                    else:
                        h["label"], h["why"], h["where"] = ev
            add(path, c, "meaning", "meaning: no word in common; the vectors found it",
                "vectors")
        # Labels may have moved up a group: keep the groups in label order,
        # each in the order its hits were found.
        order.sort(key=lambda k: LABEL_RANK[hits[k]["label"]])

    # linked: every one-hop typed link from a memory-entry hit. A target
    # that is already a hit keeps its own label and gains the link; one
    # that is not becomes a linked lead.
    # An id two files share belongs to neither: it is unknown, and no
    # link reaches either file through it.
    # Occupancy counts every tracked entry file the walk met, read or
    # skipped: a skipped file still holds its id.
    by_id = {}
    for path in sorted(set(corpus.snap.files) | {p for p, _ in corpus.snap.skipped}):
        m = ENTRY_FILE.match(path)
        if m:
            by_id.setdefault(m.group(1), []).append(path)
    entry_path = {eid: ps[0] for eid, ps in by_id.items()
                  if len(ps) == 1 and ps[0] in corpus.snap.files}
    entries = {}
    for eid, path in entry_path.items():
        text = corpus.text(path)
        entries[eid] = entry_fields(text) if text is not None else None
    # Links start from hits with evidence of their own, never from a
    # vector neighbour.
    direct = [k for k in order if hits[k]["label"] in PRIMARY_LABELS]
    for key in direct:
        h = hits[key]
        m = ENTRY_FILE.match(h["path"])
        if not m or entries.get(m.group(1)) is None:
            continue
        src = m.group(1)
        f = entries[src]
        links = [("superseded-by", f.get("superseded-by")), ("supersedes", f.get("supersedes"))]
        links += [("contradicts", t) for t in _ids(f.get("contradicts"))]
        links += [("contradicted by", other) for other, of in entries.items()
                  if of and src in _ids(of.get("contradicts"))]
        for link, target in links:
            tpath = entry_path.get(target)
            if not tpath or tpath == h["path"]:
                continue
            edge = {"link": f"{src} {link} {target}",
                    "source": f"{h['path']}:{h['start']}-{h['end']}"}
            mine = [hits[k] for k in order if k[0] == tpath]
            if mine:
                t = mine[0]
            else:
                first = corpus.chunks(tpath)
                if not first:
                    continue
                t = add(tpath, first[0], "linked", f"linked: {edge['link']}", "link")
            if edge not in t["links"]:
                t["links"].append(edge)
            if "link" not in t["routes"]:
                t["routes"].append("link")

    out = []
    for key in order:
        h = hits[key]
        if h["label"] == "linked":
            h["source"] = h["links"][0]["source"]
        m = ENTRY_FILE.match(h["path"])
        h["entry"] = bool(m)
        h["class"] = None
        if m:
            h["class"] = entry_class(entries.get(m.group(1)))
        out.append(h)
    if vrank:
        # Fusion reorders within the alias and words groups only. An exact
        # hit keeps its place; no label changes. Each list credits only the
        # hits it returned, at the rank it gave them: a hit's word rank is
        # its rank in the group's own lexical list, or, for one its evidence
        # moved up from words, the rank the word list gave it. One labelled
        # by evidence alone has its vector rank and no word rank.
        for label in ("alias", "words"):
            slots = [i for i, h in enumerate(out) if h["label"] == label]
            group = [out[i] for i in slots]
            by_key = {(h["path"], h["start"]): h for h in group}
            first, other = ROUTE[label], ROUTE["words"]
            pos = {}
            for k in by_key:
                r = lexrank[first].get(k) or lexrank[other].get(k)
                if r:
                    pos[k] = r
            for i, k in zip(slots, rv.fused_order(list(by_key), pos, vrank)):
                out[i] = by_key[k]
    return out


def entry_class(fields):
    """The class an entry declares, as the repository reads it (an
    agent-store entry reads as inferred), or None when the entry declares
    no class check_memory.py knows: a missing, blank or unknown value is
    not shown as one."""
    if fields is None or fields.get("class") not in cm.CLASSES:
        return None
    return ct.effective_class(fields)


def entry_fields(text):
    """A memory entry's front-matter fields, read by check_memory.py's own
    parser, or None when that parser reports any problem with them (a
    duplicate field, say). Nothing it records is kept."""
    before = len(cm.problems)
    try:
        fields, _ = cm.split_front_matter(text.replace("\r\n", "\n"), "entry")
        bad = len(cm.problems) > before
    finally:
        del cm.problems[before:]
    return None if bad else fields


def _ids(value):
    return [t.strip() for t in value.split(",")] if value else []


# ---------------------------------------------------------------- render

def snippet(text):
    lines = text.splitlines()
    cut = len(lines) > SNIPPET_LINES
    body = "\n".join(lines[:SNIPPET_LINES])
    if len(body) > SNIPPET_CHARS:
        body, cut = body[:SNIPPET_CHARS], True
    return body + ("\n…" if cut else "")


def describe(h):
    if not h.get("entry"):
        return "unclassed"
    return f"class {h['class'] or 'unknown'}"


def render_hit(h):
    head = f"{h['path']}:{h['start']}-{h['end']}  [{h['why']}]  {describe(h)}"
    if h.get("source"):
        head += f"  (from {h['source']})"
    if len(h.get("routes", ())) > 1:
        head += "  (found by " + ", ".join(h["routes"]) + ")"
    out = [head]
    extra = h["links"][1:] if h["label"] == "linked" else h["links"]
    if extra:
        shown = "; ".join(f"{e['link']} (from {e['source']})" for e in extra[:MAX_LINKS_SHOWN])
        more = len(extra) - MAX_LINKS_SHOWN
        out.append("    links: " + shown + (f"; and {more} more" if more > 0 else ""))
    out += ["    " + line for line in snippet(h["text"]).splitlines()]
    return "\n".join(out)


def cost(text):
    return len(text) // 4 + 1


def fill(hits, budget=TOKEN_CAP - FOOTER_RESERVE):
    """The page, filled in one fixed order: by label; within a label files
    take turns in rank order, at most PER_FILE passages each; what a cap
    leaves out is counted per label, with up to five paths named."""
    shown, omitted = [], {}
    used = 0
    counts = {"primary": 0, "related": 0}
    omitted_paths = []
    for label in PRIMARY_LABELS + RELATED_LABELS:
        group = "primary" if label in PRIMARY_LABELS else "related"
        cap = MAX_PRIMARY if group == "primary" else MAX_RELATED
        by_file = {}
        for h in hits:
            if h["label"] == label:
                by_file.setdefault(h["path"], []).append(h)
        turn = 0
        queue = []
        while True:
            took = False
            for path, items in by_file.items():
                if turn < len(items) and turn < PER_FILE:
                    queue.append(items[turn])
                    took = True
            if not took:
                break
            turn += 1
        overflow = [h for items in by_file.values() for h in items[PER_FILE:]]
        for h in queue:
            text = render_hit(h)
            if counts[group] >= cap or used + cost(text) > budget:
                overflow.append(h)
                continue
            shown.append((h, text))
            counts[group] += 1
            used += cost(text)
        if overflow:
            omitted[label] = len(overflow)
            for h in overflow:
                if h["path"] not in omitted_paths and len(omitted_paths) < 5:
                    omitted_paths.append(h["path"])
    return shown, omitted, omitted_paths


def _header(query, corpus, cov):
    lines = [f'recall: "{clip(query, QUERY_ECHO)}"',
             f"capability: {corpus.capability}; vectors: "
             f"{clip(corpus.vectors_capability(), NOTE_ECHO)}",
             f"coverage: {cov['files']} files, {cov['chunks']} chunks under "
             f"{', '.join(cov['declaredPaths'])}; {cov['recheck']}"]
    if cov["skipped"]:
        lines.append("  skipped: " + "; ".join(
            f"{clip(s['path'], PATH_ECHO)} ({clip(s['reason'], PATH_ECHO)})"
            for s in cov["skipped"][:5])
            + (f"; and {len(cov['skipped']) - 5} more" if len(cov["skipped"]) > 5 else ""))
    for group in cov["collisions"][:MAX_COLLISIONS]:
        lines.append("  collision (case or Unicode form): "
                     + ", ".join(clip(p, PATH_ECHO) for p in group[:3])
                     + (f", and {len(group) - 3} more" if len(group) > 3 else ""))
    if len(cov["collisions"]) > MAX_COLLISIONS:
        lines.append(f"  and {len(cov['collisions']) - MAX_COLLISIONS} more collisions")
    for note in cov["notes"][:MAX_NOTES]:
        lines.append("  note: " + clip(note, NOTE_ECHO))
    if len(cov["notes"]) > MAX_NOTES:
        lines.append(f"  and {len(cov['notes']) - MAX_NOTES} more notes")
    return lines


def _assemble(head, hits, shown, omitted, omitted_paths):
    primary = sum(1 for h in hits if h["label"] in PRIMARY_LABELS)
    lines = list(head) + [f"results: {primary} primary, {len(hits) - primary} related"]
    current = None
    for h, text in shown:
        if h["label"] != current:
            title = h["label"] if h["label"] in PRIMARY_LABELS else f"related context ({h['label']})"
            lines.append(f"== {title} ==")
            current = h["label"]
        lines.append(text)
    if omitted:
        parts = [f"{k} {omitted[k]}" for k in PRIMARY_LABELS + RELATED_LABELS if k in omitted]
        lines.append("omitted: " + ", ".join(parts)
                     + (" (" + ", ".join(clip(p, PATH_ECHO) for p in omitted_paths) + ")"
                        if omitted_paths else ""))
    lines.append("A hit is a lead: open the file and work from it.")
    if any(h["label"] == "meaning" for h, _ in shown):
        lines.append("A meaning hit shares no word with the query: the vectors judged it "
                     "close. It is the weakest lead.")
    if any(h.get("entry") for h, _ in shown):
        lines.append("A memory entry's class is what it declares; whether it is current: "
                     "python3 tools/check_memory.py.")
    return "\n".join(lines)


def page(query, corpus, hits):
    """The whole page within TOKEN_CAP, header and footer included: what
    is shown in text is exactly what JSON returns."""
    cov = corpus.coverage()
    head = _header(query, corpus, cov)
    if not hits:
        text = "\n".join(head + [
            "results: none — no word matched. That is not evidence of absence; "
            "try other words and the repository's terms (docs/RECALL.md)."])
        return {"text": text, "shown": [], "omitted": {}, "omittedPaths": [], "coverage": cov}
    budget = TOKEN_CAP - cost("\n".join(head)) - FOOTER_RESERVE
    shown, omitted, omitted_paths = fill(hits, budget)
    while True:
        text = _assemble(head, hits, shown, omitted, omitted_paths)
        if cost(text) <= TOKEN_CAP or not shown:
            break
        h, _ = shown.pop()
        omitted[h["label"]] = omitted.get(h["label"], 0) + 1
        if h["path"] not in omitted_paths and len(omitted_paths) < 5:
            omitted_paths.append(h["path"])
    return {"text": text, "shown": [h for h, _ in shown], "omitted": omitted,
            "omittedPaths": omitted_paths, "coverage": cov}


def render(query, corpus, hits):
    return page(query, corpus, hits)["text"]


def as_json(query, corpus, hits):
    p = page(query, corpus, hits)
    results = []
    for h in p["shown"]:
        row = {k: h[k] for k in ("path", "start", "end", "label", "why", "where",
                                 "class", "trail", "links", "routes") if k in h}
        if h.get("source"):
            row["source"] = h["source"]
        results.append(row)
    return {"query": query,
            "capability": {"words": corpus.capability,
                           "vectors": corpus.vectors_capability()},
            "coverage": p["coverage"],
            "results": results,
            "omitted": {"byLabel": p["omitted"], "paths": p["omittedPaths"]},
            "note": "A hit is a lead: open the file and work from it. An empty "
                    "list means no word matched, not that no answer exists. A "
                    "memory entry's class is what its front matter declares; "
                    "whether it is current is tools/check_memory.py's answer."}


# ---------------------------------------------------------------- glossary check

def vocabulary_names(root):
    vocab = read_json(Path(root), "catalog/VOCABULARY.json")
    if not isinstance(vocab, dict):
        return set()
    types = vocab.get("types")
    preds = vocab.get("predicates")
    names = {t for t in types if isinstance(t, str)} if isinstance(types, list) else set()
    if isinstance(preds, dict):
        names.update(preds.keys())
    return names


def entity_ids(root):
    ents = read_json(Path(root), "catalog/ENTITIES.json")
    if isinstance(ents, dict) and isinstance(ents.get("entities"), dict):
        return set(ents["entities"].keys())
    return set()


def check_glossary(root, corpus):
    """Each target must be a vocabulary type or predicate, an entity id, or
    a whole search term in a searchable source file. The glossary itself
    is not indexed, so it cannot vouch for its own spelling."""
    if not os.path.lexists(Path(root) / GLOSSARY):
        return False, [f"FAIL {GLOSSARY} is missing"]
    entries, problem = load_glossary(root)
    report, failed = [], bool(problem)
    if problem:
        report.append(f"FAIL {GLOSSARY}: {problem}")
    vocab, ents = vocabulary_names(root), entity_ids(root)
    witness = None
    if corpus.fts:
        # A throwaway in-memory table over file text only, so a path or a
        # heading trail cannot be the witness; same tokenizer as the index.
        witness = sqlite3.connect(":memory:")
        witness.execute("CREATE VIRTUAL TABLE w USING fts5(path UNINDEXED, body, "
                        "tokenize='" + TOKENIZER + "')")
        witness.executemany("INSERT INTO w VALUES (?, ?)",
                            [(p, corpus.text(p) or "") for p in corpus.snap.files])
    for entry in entries:
        for term in entry["terms"]:
            if term in vocab:
                report.append(f"ok   {term}: catalog/VOCABULARY.json name")
                continue
            if term in ents:
                report.append(f"ok   {term}: catalog/ENTITIES.json id")
                continue
            toks = tokens(term)
            where = None
            if witness is not None:
                row = witness.execute("SELECT path FROM w WHERE w MATCH ? ORDER BY path LIMIT 1",
                                      ('"' + " ".join(toks) + '"',)).fetchone()
                where = row[0] if row else None
            else:
                stems = [light_stem(t) for t in toks]
                for p in sorted(corpus.snap.files):
                    if _has_phrase([light_stem(t) for t in tokens(corpus.text(p) or "")], stems):
                        where = p
                        break
            if where:
                report.append(f"ok   {term}: search term in {where}")
            else:
                failed = True
                report.append(f"FAIL {term}: not a vocabulary name, an entity id, or a "
                              f"search term in any searchable source file")
    if witness is not None:
        witness.close()
    return not failed, report


# ---------------------------------------------------------------- vector canary

def canary_passage(corpus):
    """(path, chunk) of the indexed canary fact, or None."""
    for c in corpus.chunks(rv.CANARY_FILE):
        if c[2] and c[2][-1] == rv.CANARY_HEADING and rv.CANARY_FACT in c[3]:
            return rv.CANARY_FILE, c
    return None


def check_vectors(root, corpus, glossary=None):
    """The paraphrase canary (design rule 6). The probe shares no content
    word with the fact, so it passes only by the vector path: words alone
    must miss it, the vectors must return it as meaning, and a related but
    wrong question must leave it in the related group, never primary. A
    non-empty result is not a pass: vectors always return neighbours."""
    report, failed = [], False

    def check(ok, good, bad):
        nonlocal failed
        report.append(("ok   " + good) if ok else ("FAIL " + bad))
        failed = failed or not ok

    if not corpus.vec_on:
        return False, [f"FAIL vectors are off ({corpus.vec_why}); the canary needs them on"]
    found = canary_passage(corpus)
    if found is None:
        return False, [f'FAIL the canary fact is missing: {rv.CANARY_FILE} needs a section '
                       f'"{rv.CANARY_HEADING}" holding "{rv.CANARY_FACT}"']
    path, c = found
    key = (path, c[0])
    where = f"{path}:{c[0]}-{c[1]}"

    def labels(hits):
        return {(h["path"], h["start"]): h["label"] for h in hits}

    def went_off():
        # A search that met damage answers by a plain scan and switches the
        # vectors off; the canary then fails with that reason.
        if corpus.vec_on:
            return []
        cause = f"; {corpus.notes[-1]}" if corpus.notes else ""
        return [f"FAIL vectors went off during the check ({corpus.vec_why}{cause})"]

    off = labels(search(corpus, rv.CANARY_PROBE, glossary, vectors=False))
    if went_off():
        return False, went_off()
    # Tested on the passage itself as well as by the search, which reads
    # only the best ranked word matches.
    shared = passage_evidence(corpus, path, c, rv.CANARY_PROBE, glossary)
    check(key not in off and shared is None, f"words alone miss the canary fact ({where})",
          f"words alone find the canary fact ({where}, {off.get(key) or (shared or ('',))[0]}): the "
          f"probe shares a word with it, so the canary cannot test the vectors")
    hits = search(corpus, rv.CANARY_PROBE, glossary)
    if went_off():
        return False, report + went_off()
    shown = labels(page(rv.CANARY_PROBE, corpus, hits)["shown"])
    check(shown.get(key) == "meaning", "the vectors return it, labelled meaning, on the page",
          f"the vectors did not put the canary fact on the page as meaning "
          f"(label {shown.get(key) or labels(hits).get(key) or 'not returned'})")
    hits = search(corpus, rv.CANARY_WRONG_PROBE, glossary)
    if went_off():
        return False, report + went_off()
    got = labels(hits)
    shown = labels(page(rv.CANARY_WRONG_PROBE, corpus, hits)["shown"])
    check(got.get(key) not in PRIMARY_LABELS and shown.get(key) in RELATED_LABELS,
          "a related but wrong question leaves it in the related group",
          f"for a related but wrong question the canary fact is "
          f"{got.get(key) or 'not returned'}"
          + ("" if key not in got or key in shown else ", and not on the page")
          + "; it must be shown as related context, never as a primary hit")
    return not failed, report


def enable_vectors(root, model_from=None, out=print):
    """Switch vectors on for this worktree: check the packages, place the
    pinned model, build the vectors and run the canary with it, and only
    when all of that passed write the record that switches them on. A
    failed run writes no record, so a worktree without one stays off and
    one enabled before keeps its record."""
    git_toplevel(root)
    why = rv.packages_problem()
    if why:
        raise RecallError(why)
    if git_tracked(root, [CACHE_DIR]):
        raise RecallError(f"{CACHE_DIR}/ is tracked by Git here, and the cache is never "
                          f"committed; untrack it (git rm -r --cached {CACHE_DIR}) first")
    try:
        ensure_cache_dir(root)
    except CacheUnavailable as exc:
        raise RecallError(f"vectors need the cache, and {exc}")
    try:
        how = rv.place_model(root, CACHE_DIR, model_from)
    except rv.VectorError as exc:
        raise RecallError(str(exc))
    out(f"model: {rv.MODEL_ID} at revision {rv.MODEL_REVISION}, {how}")
    encoder, why = rv.load_model(root, CACHE_DIR)
    if encoder is None:
        raise RecallError(f"{why}; no record written ({UNCHANGED_RECORD})")
    corpus = Corpus(root, need_index=True, embed_budget=None, encoder=encoder)
    try:
        cov = corpus.coverage()
        out(f"capability: {corpus.capability}; vectors: {corpus.vectors_capability()}")
        out(f"coverage: {cov['files']} files, {cov['chunks']} chunks; {cov['recheck']}")
        glossary, _ = load_glossary(root)
        ok, report = check_vectors(root, corpus, glossary)
        out("\n".join(report))
    finally:
        corpus.close()
    if not ok:
        out(f"no record written ({UNCHANGED_RECORD})")
        return False
    try:
        rv.write_record(root, CACHE_DIR)
    except (rv.VectorError, OSError) as exc:
        raise RecallError(f"the record {CACHE_DIR}/{rv.RECORD} cannot be written ({exc})")
    out(f"record: {CACHE_DIR}/{rv.RECORD} written; searches here use vectors")
    return True


# ---------------------------------------------------------------- main

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--root", default=str(ROOT), help=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("search", help="search the notes")
    s.add_argument("query")
    s.add_argument("--json", action="store_true", help="machine-readable output")
    s.add_argument("--scan", action="store_true", help="use the plain scan, not the index")
    s.add_argument("--no-vectors", action="store_true",
                   help="words only; reads no vector record or model")
    i = sub.add_parser("index", help="build or update the cache and report coverage")
    i.add_argument("--json", action="store_true")
    i.add_argument("--no-vectors", action="store_true")
    g = sub.add_parser("check-glossary", help="check every glossary target is real")
    g.add_argument("--scan", action="store_true")
    e = sub.add_parser("enable-vectors", help="switch vectors on for this worktree")
    e.add_argument("--model-from", metavar="DIR",
                   help="a folder holding the pinned model files (docs/RECALL.md, "
                        "\"Getting the model\"); this tool downloads nothing")
    sub.add_parser("check-vectors", help="run the paraphrase canary")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    corpus = None
    try:
        if args.cmd == "enable-vectors":
            return 0 if enable_vectors(root, args.model_from) else 1
        corpus = Corpus(root, scan=getattr(args, "scan", False),
                        need_index=(args.cmd == "index"),
                        vectors=not getattr(args, "no_vectors", False),
                        embed_budget=None if args.cmd == "index" else rv.EMBED_BUDGET)
        if args.cmd == "check-vectors":
            glossary, _ = load_glossary(root)
            ok, report = check_vectors(root, corpus, glossary)
            print("\n".join(report))
            return 0 if ok else 1
        if args.cmd == "index":
            cov = corpus.coverage()
            out = {"capability": corpus.capability, "written": corpus.conn is not None,
                   "coverage": cov}
            if args.json:
                print(json.dumps(out, indent=2, ensure_ascii=False))
                return 0
            lines = [] if out["written"] else [f"no index written: {corpus.capability}"]
            lines += [f"capability: {corpus.capability}; vectors: {corpus.vectors_capability()}",
                      f"coverage: {cov['files']} files, {cov['chunks']} chunks; "
                      f"{cov['updated']} updated, {cov['removed']} removed; {cov['recheck']}"]
            lines += [f"  skipped: {s['path']} ({s['reason']})" for s in cov["skipped"]]
            lines += [f"  note: {n}" for n in cov["notes"]]
            print("\n".join(lines))
            return 0
        if args.cmd == "check-glossary":
            ok, report = check_glossary(root, corpus)
            print("\n".join(report))
            return 0 if ok else 1
        glossary, problem = load_glossary(root)
        if problem:
            corpus.notes.append(f"glossary not used: {problem}")
            glossary = []
        hits = search(corpus, args.query, glossary)
        if args.json:
            print(json.dumps(as_json(args.query, corpus, hits), indent=2, ensure_ascii=False))
        else:
            print(render(args.query, corpus, hits))
        return 0
    except RecallError as exc:
        print(f"recall: {exc}", file=sys.stderr)
        return 2
    except sqlite3.OperationalError as exc:
        what = "busy; try again" if _busy(exc) else "not writable here"
        print(f"recall: the cache is {what} ({exc})", file=sys.stderr)
        return 2
    except sqlite3.DatabaseError as exc:
        print(f"recall: the cache is damaged ({exc}); delete {CACHE_DIR}/ and search "
              f"again to rebuild it", file=sys.stderr)
        return 2
    finally:
        if corpus is not None:
            corpus.close()


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
