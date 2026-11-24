"""The optional vector part of tools/recall.py.

    python3 tools/recall.py enable-vectors --model-from DIR   # an offline copy
    python3 tools/recall.py check-vectors                     # the paraphrase canary

This tool makes no network access. The person or their assistant fetches
the pinned model files once, outside it (docs/RECALL.md, "Getting the
model").

Vectors are switched on for one working tree by enable-vectors, never by
finding packages or a model already installed. The command checks the
packages, places the pinned model in the cache folder, builds the
vectors, runs the paraphrase canary and, only when it passes, writes the
record that switches them on. After that a search uses them without a
flag; `search --no-vectors` switches them off and then touches no vector
record or model. Full contract: docs/RECALL.md, "Vectors".

This module imports only the standard library. numpy and model2vec are
imported when vectors are loaded, and they need Python 3.10 or later; the
word floor in tools/recall.py does not.
"""
import hashlib
import importlib.util
import json
import os
import stat
import sys
import tempfile
import time
from fractions import Fraction
from pathlib import Path

MODEL_NAME = "potion-base-8M"
MODEL_ID = "minishlab/potion-base-8M"
MODEL_REVISION = "bf8b056651a2c21b8d2565580b8569da283cab23"
# name -> (size, sha256). Checked against the hub's own record for this
# revision: the LFS SHA-256 of the weights, the Git blob ids of the rest.
MODEL_FILES = {
    "config.json": (202, "2a6ac0e9aaa356a68a5688070db78fc3a464fefe85d2f06a1905ce3718687553"),
    "model.safetensors": (30236760,
                          "f65d0f325faadc1e121c319e2faa41170d3fa07d8c89abd48ca5358d9a223de2"),
    "tokenizer.json": (683666, "e67e803f624fb4d67dea1c730d06e1067e1b14d830e2c2202569e3ef0f70bb50"),
}
BACKEND = "model2vec"
PASSAGE_PREFIX = ""  # potion's model card names no prefixes
QUERY_PREFIX = ""
MODEL_DIR = "model"
RECORD = "vectors.json"
RECORD_SCHEMA = "hyperbench.recall-vectors/v1"
MIN_PYTHON = (3, 10)
PACKAGES = ("numpy", "model2vec")

# Ranking (docs/RECALL.md, "Vectors"). Development settings: the
# calibration run in an applied project sets them and freezes them.
VECTOR_TOP = 30
RRF_K = 60
WEIGHT_WORDS = 1.0
WEIGHT_VECTORS = 1.0
EMBED_BUDGET = 10.0  # seconds a search may spend embedding new passages
BATCH = 64

# The paraphrase canary (design rule 6). The fact is indexed: it lives in
# docs/RECALL.md, under the heading CANARY_HEADING. The probes live here,
# outside every indexed path, and share no content word with the fact.
CANARY_HEADING = "Paraphrase canary"
CANARY_FACT = "Strawberries and blueberries taste sweetest in early summer."
CANARY_PROBE = "Which season makes raspberries most delicious?"
CANARY_WRONG_PROBE = "How can fruit like pears mature quicker?"
CANARY_FILE = "docs/RECALL.md"


class VectorError(Exception):
    pass


def cache_folder(root, cache_dir):
    return Path(root) / cache_dir


def model_folder(root, cache_dir):
    return cache_folder(root, cache_dir) / MODEL_DIR


def packages_problem():
    """None when this interpreter can run the vectors, else what is missing.
    Looks the packages up without importing them."""
    if sys.version_info < MIN_PYTHON:
        return ("vectors need Python %d.%d or later; this is %d.%d"
                % (MIN_PYTHON + sys.version_info[:2]))
    missing = [p for p in PACKAGES if importlib.util.find_spec(p) is None]
    if missing:
        return ("vectors need the packages " + ", ".join(missing)
                + " in the Python that runs this tool; this tool installs nothing")
    return None


def _regular(path):
    """Raises VectorError unless path is a regular file reached through no
    link (the folder itself is checked by the caller)."""
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        raise VectorError(f"{path.name} is missing")
    if (stat.S_ISLNK(info.st_mode)
            or getattr(info, "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)):
        raise VectorError(f"{path.name} is a link; links are not followed")
    if not stat.S_ISREG(info.st_mode):
        raise VectorError(f"{path.name} is not a regular file")
    return info


def _plain_folder(path, what):
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        raise VectorError(f"{what} is missing")
    if (stat.S_ISLNK(info.st_mode)
            or getattr(info, "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
            or not stat.S_ISDIR(info.st_mode)):
        raise VectorError(f"{what} is a link or not a folder; refusing to read through it")


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _read_pinned(path, name, size, sha, what):
    """The bytes of one pinned file, read once through a descriptor that is
    the file lstat saw (no link, no swap), with the pinned size and hash."""
    try:
        info = _regular(path)
        if info.st_size != size:
            raise VectorError(f"{what}: {name} does not match the pinned {MODEL_ID} "
                              f"revision {MODEL_REVISION[:12]}")
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(path, flags)
        with os.fdopen(fd, "rb") as f:
            got = os.fstat(f.fileno())
            if (got.st_dev, got.st_ino) != (info.st_dev, info.st_ino):
                raise VectorError(f"{what}: {name} changed while it was opened")
            data = f.read(size + 1)
    except OSError as exc:
        raise VectorError(f"{what}: {name} cannot be read ({exc.strerror or exc})")
    if len(data) != size or hashlib.sha256(data).hexdigest() != sha:
        raise VectorError(f"{what}: {name} does not match the pinned {MODEL_ID} "
                          f"revision {MODEL_REVISION[:12]}")
    return data


def read_verified(folder, what):
    """{name: bytes} of the pinned files in folder, each a regular file with
    the pinned size and SHA-256. The model is built from these bytes, never
    by opening the files again. Raises VectorError naming the first that is
    not."""
    try:
        _plain_folder(folder, what)
    except OSError as exc:
        raise VectorError(f"{what} cannot be read ({exc.strerror or exc})")
    return {name: _read_pinned(folder / name, name, size, sha, what)
            for name, (size, sha) in sorted(MODEL_FILES.items())}


def verify_files(folder, what):
    """Raises VectorError unless folder holds the pinned files."""
    read_verified(folder, what)


def identity():
    """What a vector was computed with. Part of every computation key, so
    another model, revision, file, backend or prefix means new vectors."""
    return json.dumps({"model": MODEL_ID, "revision": MODEL_REVISION,
                       "files": {n: s for n, (_, s) in sorted(MODEL_FILES.items())},
                       "backend": BACKEND, "passagePrefix": PASSAGE_PREFIX,
                       "queryPrefix": QUERY_PREFIX}, sort_keys=True)


def wanted_record():
    return {"schemaVersion": RECORD_SCHEMA, "model": MODEL_ID, "revision": MODEL_REVISION,
            "files": {n: s for n, (_, s) in sorted(MODEL_FILES.items())}}


def read_record(root, cache_dir):
    """(record, None) for this release's record, else (None, why)."""
    path = cache_folder(root, cache_dir) / RECORD
    try:
        _regular(path)
        data = json.loads(path.read_bytes().decode("utf-8"))
    except VectorError as exc:
        return None, f"the record {cache_dir}/{RECORD}: {exc}"
    except (OSError, ValueError) as exc:
        return None, f"the record {cache_dir}/{RECORD} cannot be read ({exc})"
    if not isinstance(data, dict):
        return None, f"the record {cache_dir}/{RECORD} is not one JSON object"
    want = wanted_record()
    if any(data.get(k) != v for k, v in want.items()):
        return None, (f"{cache_dir}/{RECORD} records another model or revision than this "
                      f"release pins ({MODEL_ID} {MODEL_REVISION[:12]}); run enable-vectors again")
    return data, None


def enabled(root, cache_dir):
    """Whether the record exists, without reading it: a search that finds
    no record imports nothing more."""
    return os.path.lexists(cache_folder(root, cache_dir) / RECORD)


class Encoder:
    """The pinned static model, built from the verified bytes of its three
    files (read_verified): nothing is opened again by path, no optional
    file such as a model card is read, and nothing comes from the hub."""

    def __init__(self, files):
        os.environ["HF_HUB_OFFLINE"] = "1"
        import inspect
        import numpy  # imported here, never at module load
        from model2vec import StaticModel
        from safetensors.numpy import load as load_tensors
        from tokenizers import Tokenizer
        self.np = numpy
        self.identity = identity()
        self.name = MODEL_NAME
        self.encoded = 0
        tensors = load_tensors(files["model.safetensors"])
        config = json.loads(files["config.json"].decode("utf-8"))
        if "embeddings" not in tensors:
            raise VectorError("model.safetensors holds no embeddings tensor")
        args = {"vectors": tensors["embeddings"],
                "tokenizer": Tokenizer.from_str(files["tokenizer.json"].decode("utf-8")),
                "config": config, "normalize": bool(config.get("normalize", False)),
                "weights": tensors.get("weights"), "token_mapping": tensors.get("mapping")}
        if "max_length" in config:
            args["max_length"] = config["max_length"]
        accepted = inspect.signature(StaticModel.__init__).parameters
        dropped = [k for k, v in args.items() if k not in accepted and v is not None]
        if dropped:
            raise VectorError("this model2vec cannot build the pinned model "
                              f"(no {', '.join(dropped)})")
        self.model = StaticModel(**{k: v for k, v in args.items() if k in accepted})
        self.dim = int(tensors["embeddings"].shape[1])

    def _encode(self, texts):
        v = self.np.asarray(self.model.encode(list(texts)), dtype=self.np.float32)
        if v.ndim == 1:
            v = v.reshape(1, -1)
        norms = self.np.linalg.norm(v, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return v / norms

    def passages(self, texts):
        self.encoded += len(texts)
        return self._encode([PASSAGE_PREFIX + t for t in texts])

    def query(self, text):
        return self._encode([QUERY_PREFIX + text])[0]


def load_model(root, cache_dir):
    """(Encoder, None) from the pinned files in the cache, else (None, why).
    Checks the packages, then the files; reads no record (enable-vectors
    tests the model before it writes one)."""
    why = packages_problem()
    if why:
        return None, why
    try:
        files = read_verified(model_folder(root, cache_dir), f"{cache_dir}/{MODEL_DIR}")
    except VectorError as exc:
        return None, f"{exc}; run enable-vectors again"
    try:
        return Encoder(files), None
    except Exception as exc:  # a package that imports but cannot build the model
        return None, f"the model could not be loaded ({type(exc).__name__}: {exc})"


def load(root, cache_dir):
    """(Encoder, None) when vectors are on for this worktree, else (None,
    why). Checks, in order: the record, the packages, the pinned files."""
    record, why = read_record(root, cache_dir)
    if why:
        return None, why
    return load_model(root, cache_dir)


def passage_text(meta, body):
    """The exact text the encoder reads: the path and heading trail, then
    the passage (headings help vectors; design, "What a first measurement
    shows")."""
    return meta + "\n" + body


def computation_key(ident, chunker, cap, text):
    h = hashlib.sha256()
    for part in (ident, chunker, str(cap), text):
        b = part.encode("utf-8")
        h.update(str(len(b)).encode("ascii") + b":" + b)
    return h.hexdigest()


def pack(np, vec):
    return np.asarray(vec, dtype="<f2").tobytes()


def unpack(np, blob):
    return np.frombuffer(blob, dtype="<f2").astype(np.float32)


def decoded(encoder, blob):
    """The stored vector, or None when the blob is not one this model could
    have written (wrong length, or a value that is not finite)."""
    np = encoder.np
    if not isinstance(blob, (bytes, bytearray, memoryview)) or len(blob) != 2 * encoder.dim:
        return None
    vec = unpack(np, bytes(blob))
    return vec if bool(np.isfinite(vec).all()) else None


def stored(conn, keys, encoder):
    """key -> blob for the keys with a usable stored vector; a damaged one
    counts as missing, so the next write embeds that passage again."""
    have = {}
    keys = list(keys)
    for i in range(0, len(keys), 400):
        part = keys[i:i + 400]
        for key, blob in conn.execute("SELECT key, data FROM vectors WHERE key IN (%s)"
                                      % ",".join("?" * len(part)), part):
            if decoded(encoder, blob) is not None:
                have[key] = blob
    return have


class Stale(Exception):
    """The word index moved to another generation before the vectors were
    written; nothing was written, and the walk runs again."""


def sync(conn, encoder, items, budget=EMBED_BUDGET, clock=time.monotonic, fresh=None,
         collect=True):
    """Embed the passages with no usable stored vector, in batches of BATCH,
    until the budget (seconds; None for no limit) runs out; the budget is
    checked before each batch, so the last batch may end after it. Then, in
    one write transaction, store them and, when collect is true, drop
    vectors no passage uses. fresh(), called inside that transaction, says
    whether the word index still holds the generation these items came
    from; when it does not, nothing is written and Stale is raised.
    items: [(key, text)]. Returns the number encoded."""
    np = encoder.np
    want = dict(items)
    table = list(conn.execute("SELECT key, data FROM vectors"))
    have = {k for k, blob in table if decoded(encoder, blob) is not None}
    missing = [k for k in want if k not in have]
    rows = []
    start = clock()
    for i in range(0, len(missing), BATCH):
        if budget is not None and clock() - start >= budget:
            break
        part = missing[i:i + BATCH]
        vecs = encoder.passages([want[k] for k in part])
        rows += [(k, pack(np, v)) for k, v in zip(part, vecs)]
    if not rows and (not collect or all(k in want for k, _ in table)):
        return 0
    conn.execute("BEGIN IMMEDIATE")
    try:
        if fresh is not None and not fresh():
            raise Stale()
        unused = [] if not collect else [
            r[0] for r in conn.execute("SELECT key FROM vectors") if r[0] not in want]
        conn.executemany("INSERT OR REPLACE INTO vectors(key, data) VALUES (?, ?)", rows)
        conn.executemany("DELETE FROM vectors WHERE key = ?", [(k,) for k in unused])
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return len(rows)


def ranked(encoder, keys, have, query, top=None):
    """Indexes into keys, nearest first by cosine, among the passages with a
    usable stored vector (have: key -> blob); ties keep the keys' order
    (path, then line). At most VECTOR_TOP unless top says otherwise. A
    query or passage the model maps to the zero vector has no direction,
    so it ranks nothing and is never ranked."""
    np = encoder.np
    top = VECTOR_TOP if top is None else top
    q = np.asarray(encoder.query(query), dtype=np.float32)
    if q.shape != (encoder.dim,) or not bool(np.isfinite(q).all()) or not bool(q.any()):
        return []
    idx, rows = [], []
    for i, k in enumerate(keys):
        vec = decoded(encoder, have[k]) if k in have else None
        if vec is not None and bool(vec.any()):
            idx.append(i)
            rows.append(vec)
    if not idx:
        return []
    scores = np.stack(rows) @ q
    order = sorted(range(len(idx)), key=lambda j: (-float(scores[j]), j))
    return [idx[j] for j in order[:top]]


def fused_order(keys, word_positions, vector_rank):
    """Weighted reciprocal rank fusion: each list adds weight / (RRF_K +
    rank) to the hits it returned, and only to those. keys: the group's
    hits; word_positions: hit key -> 1-based rank in the group's word list;
    vector_rank: hit key -> 1-based rank in the vector list. Returns keys,
    best first; ties keep the word order, then the vector order. Scores
    are exact fractions, so a tie is a tie and not a rounding step."""
    none = float("inf")
    ww, wv = Fraction(WEIGHT_WORDS), Fraction(WEIGHT_VECTORS)

    def score(k):
        s = Fraction(0)
        if k in word_positions:
            s += ww / (RRF_K + word_positions[k])
        if k in vector_rank:
            s += wv / (RRF_K + vector_rank[k])
        return s
    return sorted(keys, key=lambda k: (-score(k), word_positions.get(k, none),
                                       vector_rank.get(k, none)))


# ---------------------------------------------------------------- enable

def _write_verified(files, dest_dir):
    """Write each pinned file's verified bytes into dest_dir through a
    temporary name, then replace; a file already there with the pinned
    bytes is kept."""
    for name, (size, sha) in sorted(MODEL_FILES.items()):
        target = dest_dir / name
        try:
            info = _regular(target)
            if info.st_size == size and sha256_file(target) == sha:
                continue
        except VectorError:
            pass
        fd, tmp = tempfile.mkstemp(prefix=name + ".", suffix=".part", dir=str(dest_dir))
        try:
            with os.fdopen(fd, "wb") as out:
                out.write(files[name])
            os.replace(tmp, target)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)


def _ensure_plain_dir(path, what):
    try:
        os.mkdir(path)
    except FileExistsError:
        pass
    _plain_folder(path, what)


def place_model(root, cache_dir, model_from=None):
    """Put the pinned files in the cache's model folder. Returns how, in
    words safe to copy into a pull request (no local path)."""
    folder = cache_folder(root, cache_dir)
    dest = folder / MODEL_DIR
    _ensure_plain_dir(dest, f"{cache_dir}/{MODEL_DIR}")
    if model_from is not None:
        src = Path(model_from)
        _write_verified(read_verified(src, "the offline copy given with --model-from"), dest)
        how = "copied from an offline copy (--model-from)"
    else:
        try:
            verify_files(dest, f"{cache_dir}/{MODEL_DIR}")
        except VectorError as exc:
            raise VectorError(f"{exc}. Give --model-from DIR, a folder holding the pinned "
                              f"files of {MODEL_ID} at revision {MODEL_REVISION} "
                              f"(docs/RECALL.md, \"Getting the model\")")
        return "already in place"
    verify_files(dest, f"{cache_dir}/{MODEL_DIR}")
    return how


def write_record(root, cache_dir):
    folder = cache_folder(root, cache_dir)
    path = folder / RECORD
    if os.path.lexists(path):
        _regular(path)
    data = dict(wanted_record())
    data["enabledAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    fd, tmp = tempfile.mkstemp(prefix=RECORD + ".", suffix=".part", dir=str(folder))
    try:
        with os.fdopen(fd, "wb") as out:
            out.write((json.dumps(data, indent=2, sort_keys=True) + "\n").encode("utf-8"))
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
