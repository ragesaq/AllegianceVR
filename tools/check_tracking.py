#!/usr/bin/env python3
"""check_tracking — the typed-memory reasoner (facts-store v2).

Run from the repo root: python3 tools/check_tracking.py [--report]

EXTENDS tools/check_memory.py, never duplicates it (contract D1: one fact
shape, one legality answer). Every PR #13 rule runs through check_memory's
own functions; this file adds only the v2 layers:

  vocabulary + entities (D2) · eight-column index (D3) · enforcement
  floor: store ceiling, key whitelist, governed-field denylist (D4) ·
  decision index + citation resolvers + resolvability accounting (D6/D7)
  · cross-store mechanisms (D9) · temporal-marker screen (D10) · index
  Last-Verified block (D11) · health metrics, reported never gated (D12)

Store format is declared in memory/README.md ("Store format: memory/v2");
a store with no marker is v1 and gets exactly check_memory's contract —
this checker adds nothing to a v1 store (F-CV-001: no store is ever
silently half-typed).

Failure posture inherited from check_map/check_memory: inconsistency is
blocking; absence of an optional artifact is a warning at most; a missing
input is never a silent pass.
"""
import datetime
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_memory as cm  # noqa: E402  (the extension point, by contract)
import hb_modules  # noqa: E402

ROOT = cm.ROOT
MEM = cm.MEM
CATALOG = ROOT / "catalog"
VOCAB_PATH = CATALOG / "VOCABULARY.json"
ENTITIES_PATH = CATALOG / "ENTITIES.json"
DECISIONS_PATH = CATALOG / "DECISIONS_INDEX.json"
RECONCILE_DIR = MEM / "reconciliation"

problem = cm.problem   # one problem list, one exit answer (D1)
warn = cm.warn

FORMAT_LINE = cm.STORE_FORMAT_LINE
INDEX_HEADER_V2 = cm.INDEX_HEADER_V2  # single definition, owned by check_memory
ENTITY_ID = re.compile(r"^[a-z][a-z0-9]*:[a-z0-9][a-z0-9-]*$")
SEMDATE = cm.parse_date
FULL_SHA = re.compile(r"^[0-9a-f]{40}$")

# The complete key whitelist (D4). v1 keys are every field check_memory
# reads or a live PR #13 entry carries; v2 adds the typed layer. An
# unknown key is a failure, not an extension point.
V1_KEYS = {"id", "topic", "class", "observed", "recorded-by", "evidence",
           "inferred-from", "granted-by", "granted-on", "granted-where",
           "review-by", "surface", "control", "sources", "supersedes",
           "superseded-by", "seen-in", "reproduce", "contradicts"}
V2_KEYS = {"subject", "predicate", "object", "store",
           "verified-repo", "verified-sha", "valid_from", "invalid_at"}
KNOWN_KEYS = V1_KEYS | V2_KEYS

STORES = ("repo", "agent")
CLASS_RANK = cm.CLASS_RANK

# Governed-field denylist (D4): free text may not smuggle an assertion
# that only frontmatter may make. Matches a line that *looks like* a
# governed field at line start (the laundering shape), inside any prose
# body — fenced examples are already stripped by cm.strip_fenced.
GOVERNED_SMUGGLE = re.compile(
    r"^\s*(?:(?:[-*+>]|\d+[.)]|\[[ xX]\])\s*)*"
    r"(class|store|granted-by|granted-on|subject|predicate|object)"
    r"\s*:\s*\S", re.IGNORECASE)

# Citation grammar (D7): closed kinds, nothing else resolves.
CITATION = re.compile(r"\b(fact|decision):([a-z0-9][a-z0-9-]*)\b")
# Loose detector: anything citation-SHAPED must then validate strictly —
# a malformed address (fact:Mem-001, decision:Foo_bar) is a defect, not
# invisible (F-PR27-005).
CITATION_LOOSE = re.compile(r"\b(fact|decision):([^\s\)\]\},;'\"`]+)")
# Near-kind variants (case/plural of the two closed kinds) are citation
# INTENT and must be visible, not silently not-a-citation. The kind set
# stays closed; this only catches its misspellings.
# ANY case/plural variant of the two closed stems carries citation
# intent; only the exact lowercase singular is the grammar. Kinds outside
# the two stems (ruling:, note:, https:) are NOT citations by contract —
# a closed grammar means exactly this — and are indistinguishable from
# prose and URI schemes, so they are out of scope by design, stated here
# rather than silently.
CITATION_NEARKIND = re.compile(
    r"\b(facts?|decisions?):([a-z0-9][a-z0-9-]*)", re.IGNORECASE)
FACT_ADDR = re.compile(r"^mem-\d{3}$")

# Tracked citation surfaces (D7): live, editable files where a citation is
# a promise. Frozen point-in-time records are excluded BY NAME, not
# silently: .hyperreview/ (review evidence), docs/proposals/ (reviewed
# historical records — editing one invalidates its review chain), tools/
# (code), .github/ (config).
TRACKED_DIRS = ("memory", "catalog", "templates", "docs")
TRACKED_EXCLUDE = ("docs/proposals/",)
TRACKED_ROOT_FILES = ("README.md", "START_HERE.md", "AGENTS.md",
                      "GROUND_RULES.md", "CATALOG.md", "LEDGER.md",
                      "DAG.json")


def load_json(path, label):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        problem(f"{label} is missing — the v2 store cannot be validated "
                f"without it")
    except json.JSONDecodeError as exc:
        problem(f"{label}: invalid JSON at line {exc.lineno}")
    return None


def store_format():
    index = MEM / "README.md"
    if not index.is_file():
        return "v1"  # cm.check_index reports the missing index itself
    m = FORMAT_LINE.search(index.read_text(encoding="utf-8"))
    return m.group(1) if m else "v1"


# ---------------------------------------------------------------- D2 --

def load_vocabulary():
    v = load_json(VOCAB_PATH, "catalog/VOCABULARY.json")
    if v is None:
        return None
    for field in ("schemaVersion", "tier", "types", "predicates",
                  "temporalMarkers"):
        if field not in v:
            problem(f"catalog/VOCABULARY.json: missing field '{field}'")
    _ABSENT = object()
    pp = v.get("proposedPredicates", _ABSENT)
    if pp is not _ABSENT and not isinstance(pp, dict):
        problem("catalog/VOCABULARY.json: proposedPredicates must be an "
                "object keyed by predicate name — a malformed proposal "
                "surface must not read as zero proposals")
    preds = v.get("predicates", {})
    types = set(v.get("types", []))
    for name, spec in sorted(preds.items()):
        if not re.match(r"^[a-z][a-z0-9-]*$", name):
            problem(f"catalog/VOCABULARY.json: predicate '{name}' is not a "
                    f"lowercase slug")
        dom = spec.get("domain")
        rng = spec.get("range")
        for side, val in (("domain", dom), ("range", rng)):
            if val is None:
                continue
            vals = val if isinstance(val, list) else [val]
            for t in vals:
                if t != "*" and t not in types:
                    problem(f"catalog/VOCABULARY.json: predicate '{name}' "
                            f"{side} '{t}' is not a declared type")
    return v


def load_entities(vocab):
    e = load_json(ENTITIES_PATH, "catalog/ENTITIES.json")
    if e is None:
        return None
    entities = e.get("entities")
    if not isinstance(entities, dict):
        problem("catalog/ENTITIES.json: 'entities' must be an object")
        return None
    types = set(vocab.get("types", [])) if vocab else set()
    alias_owner = {}
    for eid, spec in sorted(entities.items()):
        if not ENTITY_ID.match(eid):
            problem(f"catalog/ENTITIES.json: entity id '{eid}' is not "
                    f"normalized '<type>:<kebab-slug>'")
            continue
        etype = eid.split(":", 1)[0]
        if types and etype not in types:
            problem(f"catalog/ENTITIES.json: entity '{eid}' uses undeclared "
                    f"type '{etype}'")
        for alias in spec.get("aliases", []):
            if not ENTITY_ID.match(alias):
                problem(f"catalog/ENTITIES.json: alias '{alias}' of '{eid}' "
                        f"is not a normalized entity id")
                continue
            if alias in entities:
                problem(f"catalog/ENTITIES.json: alias '{alias}' is also an "
                        f"entity key — an id must resolve to exactly one "
                        f"canonical entry")
            if alias in alias_owner and alias_owner[alias] != eid:
                problem(f"catalog/ENTITIES.json: alias '{alias}' points at "
                        f"both '{alias_owner[alias]}' and '{eid}' — alias "
                        f"resolution must be injective")
            alias_owner[alias] = eid
    return entities


def resolve_entity(eid, entities):
    """Alias resolution runs BEFORE any comparison (F-CV-002)."""
    if entities is None:
        return eid
    if eid in entities:
        return eid
    for canonical, spec in entities.items():
        if eid in spec.get("aliases", []):
            return canonical
    return None


# ---------------------------------------------------------- D4 / D10 --

def check_v2_entry(entry_id, path, fields, body, vocab, entities):
    where = f"memory/{path.name}"

    for key in sorted(set(fields) - KNOWN_KEYS):
        problem(f"{where}: unknown field '{key}' — the key set is closed "
                f"(canonical whitelist lives in tools/check_tracking.py); "
                f"an unrecognised key is not a weaker claim, it is an "
                f"unchecked one")
    if fields.get("provisional"):
        problem(f"{where}: 'provisional' facts are workbench-local by "
                f"contract and never travel into a repo store as typed "
                f"facts")

    store = fields.get("store")
    if store is None:
        problem(f"{where}: v2 entry missing 'store' (repo|agent) — the "
                f"store caps the class (A1)")
    elif store not in STORES:
        problem(f"{where}: store '{store}' must be one of {list(STORES)}")
    cls = fields.get("class")
    if store == "agent" and cls == "canonical":
        problem(f"{where}: store 'agent' caps class at 'verified' — an "
                f"agent store cannot emit canonical facts (store ceiling, "
                f"D4); this is the C1 attack shape")

    # Governed-field smuggling in free text (D4): check prose only.
    live, _ = cm.strip_fenced(body)
    for lineno, line in live:
        if GOVERNED_SMUGGLE.match(line):
            problem(f"{where} body line {lineno}: free text may not carry a "
                    f"governed-field assertion ('{line.strip()[:40]}…') — "
                    f"class/store/grants/triples live only in frontmatter "
                    f"where they are validated (laundering defense, D4)")
            break

    # Triple validation (D2/D3 semantics).
    preds = (vocab or {}).get("predicates", {})
    subject = fields.get("subject")
    predicate = fields.get("predicate")
    obj = fields.get("object")
    if predicate is None:
        problem(f"{where}: v2 entry missing 'predicate' (use 'notes' for a "
                f"fact with no triple shape)")
        return
    if predicate not in preds:
        problem(f"{where}: predicate '{predicate}' is not declared in "
                f"catalog/VOCABULARY.json — the vocabulary is closed; "
                f"propose the predicate rather than minting it")
        return
    spec = preds[predicate]
    if subject is None:
        problem(f"{where}: v2 entry missing 'subject'")
        return
    for role, val in (("subject", subject), ("object", obj)):
        if val is None:
            continue
        if not ENTITY_ID.match(val):
            problem(f"{where}: {role} '{val}' is not a normalized entity id "
                    f"'<type>:<kebab-slug>'")
            return
        if resolve_entity(val, entities) is None:
            problem(f"{where}: {role} '{val}' is not in catalog/"
                    f"ENTITIES.json (as key or alias) — type nouns once, "
                    f"at the top")
    # Domain / range (a repo cannot 'prefers').
    def type_ok(val, allowed):
        if allowed is None or allowed == "*":
            return True
        allowed = allowed if isinstance(allowed, list) else [allowed]
        return "*" in allowed or val.split(":", 1)[0] in allowed
    if not type_ok(subject, spec.get("domain")):
        problem(f"{where}: subject '{subject}' violates domain "
                f"'{spec.get('domain')}' of predicate '{predicate}'")
    if spec.get("range") is None:
        pass  # notes-shaped: object optional, unchecked further
    elif obj is None:
        problem(f"{where}: predicate '{predicate}' requires an object of "
                f"range '{spec.get('range')}'")
    elif not type_ok(obj, spec.get("range")):
        problem(f"{where}: object '{obj}' violates range "
                f"'{spec.get('range')}' of predicate '{predicate}'")

    # Temporal-marker screen (D10): temporary state must carry validity.
    markers = (vocab or {}).get("temporalMarkers", [])
    text_l = body.lower()
    hit = next((m for m in markers
                if re.search(r"\b" + re.escape(m) + r"\b", text_l)), None)
    if hit and ("valid_from" not in fields or "invalid_at" not in fields):
        problem(f"{where}: body matches temporal marker '{hit}' but the "
                f"entry lacks 'valid_from'/'invalid_at' — temporary state "
                f"must carry its validity window or it hardens into "
                f"permanent fact (D10); a plain date in prose is not a "
                f"bypass")
    for k in ("valid_from", "invalid_at"):
        if k in fields and SEMDATE(fields[k]) is None:
            problem(f"{where}: {k} '{fields[k]}' is not a real date")
    # The window is a state, not decoration (SM-5): inverted, it describes
    # no moment at all; closed, the entry still reads as current fact.
    vf, ia = SEMDATE(fields.get("valid_from")), SEMDATE(fields.get("invalid_at"))
    if vf and ia and ia <= vf:
        problem(f"{where}: invalid_at {ia} is not after valid_from {vf} — "
                f"a validity window that closes before it opens describes "
                f"no moment at all")
    elif ia and ia <= cm.earliest_date_anywhere() \
            and "superseded-by" not in fields:
        warn(f"{where}: validity window closed on {ia} and the entry is not "
             f"superseded — it still reads as current; supersede it with "
             f"what is true now, or record why the window was extended "
             f"(docs/MEMORY_PROTOCOL.md temporal stale test)")
    if "verified-sha" in fields and not FULL_SHA.match(
            str(fields["verified-sha"])):
        problem(f"{where}: verified-sha must be a full 40-hex sha")


def check_functional(entries, vocab, entities):
    """Unify-or-defect inside one store (A2 mech 1): FAIL, never guess."""
    preds = (vocab or {}).get("predicates", {})
    seen = {}
    for entry_id, e in sorted(entries.items()):
        f = e["fields"]
        p = f.get("predicate")
        if not p or not preds.get(p, {}).get("functional"):
            continue
        if "superseded-by" in f:
            continue  # retired: it stops being read as current (rule 5, SM-6)
        subj = resolve_entity(f.get("subject", ""), entities)
        obj = resolve_entity(f.get("object", ""), entities)
        if subj is None or obj is None:
            continue
        key = (subj, p)
        if key in seen and seen[key][1] != obj:
            problem(f"memory/: functional predicate '{p}' has two objects "
                    f"for subject '{subj}' ({seen[key][0]}: '{seen[key][1]}' "
                    f"vs {entry_id}: '{obj}') — same-entity-two-names or "
                    f"real drift; the checker demands the decision, never "
                    f"guesses (unify-or-defect)")
        seen.setdefault(key, (entry_id, obj))


def cross_store_conflicts(repo_facts, agent_facts, vocab, entities):
    """Boundary reconciliation on read (A2 mech 2, D9): compare functional
    predicates on shared subjects across two stores. Returns conflict list;
    each conflict must produce exactly one blocking reconciliation record.
    Alias resolution runs first — that is the entire point (F-CV-002)."""
    preds = (vocab or {}).get("predicates", {})
    def norm(facts):
        out = {}
        for f in facts:
            p = f.get("predicate")
            if p and preds.get(p, {}).get("functional"):
                s = resolve_entity(f.get("subject", ""), entities)
                o = resolve_entity(f.get("object", ""), entities)
                if s and o:
                    out[(s, p)] = o
        return out
    a, b = norm(repo_facts), norm(agent_facts)
    return [{"subject": s, "predicate": p, "repo": a[(s, p)],
             "agent": b[(s, p)]}
            for (s, p) in sorted(set(a) & set(b)) if a[(s, p)] != b[(s, p)]]


def effective_class(entry_fields, reading_surface="repo"):
    """Demote-on-crossing (A2 mech 3, D9): an agent-store fact about a
    repo-owned subject reads as 'inferred' inside the repo — it can prompt
    a check, never win an argument."""
    cls = entry_fields.get("class", "inferred")
    if reading_surface == "repo" and entry_fields.get("store") == "agent":
        return "inferred"
    return cls


def check_cross_store(agent_store_path, parsed, vocab, entities):
    """Boundary reconciliation IN the pipeline (F-PR27-004 residual): given
    an agent-store snapshot (JSON list of {subject,predicate,object}),
    every functional conflict on a shared subject must have a matching
    reconciliation record in memory/reconciliation/ — a live conflict
    without its record is undetected drift, which is the failure A2
    exists to catch. The records themselves block until deleted, so a
    conflict always blocks: first for being unrecorded, then until
    resolved."""
    snap = Path(agent_store_path)
    if not snap.is_absolute():
        snap = ROOT / snap  # relative paths are repo-relative
    try:
        agent_facts = json.loads(snap.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        problem(f"--agent-store {agent_store_path}: unreadable or invalid "
                f"JSON ({exc}) — an unreadable snapshot is a failure, not "
                f"a skip")
        return
    if not isinstance(agent_facts, list) or any(
            not isinstance(f, dict) for f in agent_facts):
        problem(f"--agent-store {agent_store_path}: a snapshot is a JSON "
                f"list of {{subject, predicate, object}} objects")
        return
    repo_facts = [e["fields"] for e in parsed.values()
                  if "superseded-by" not in e["fields"]]
    conflicts = cross_store_conflicts(repo_facts, agent_facts, vocab,
                                      entities)
    recorded = set()
    if RECONCILE_DIR.is_dir():
        for rp in sorted(RECONCILE_DIR.glob("*.md")):
            f, _ = cm.split_front_matter(
                rp.read_text(encoding="utf-8"), rp.name)
            if f:
                recorded.add((f.get("subject"), f.get("predicate")))
    for c in conflicts:
        if (c["subject"], c["predicate"]) not in recorded:
            problem(f"cross-store conflict on '{c['subject']}' / "
                    f"'{c['predicate']}' (repo: '{c['repo']}' vs agent: "
                    f"'{c['agent']}') has NO reconciliation record — "
                    f"write memory/reconciliation/<slug>.md naming it; "
                    f"undetected drift is the A2 failure mode")


def check_reconciliation_records():
    """Presence means unresolved and BLOCKS (deletion-is-the-outcome,
    PR #15's mechanic applied to stores)."""
    if not RECONCILE_DIR.is_dir():
        return
    for p in sorted(RECONCILE_DIR.glob("*.md")):
        where = f"memory/reconciliation/{p.name}"
        fields, _ = cm.split_front_matter(p.read_text(encoding="utf-8"),
                                          where)
        if fields is None:
            continue
        for req in ("subject", "predicate", "stores", "startedAt"):
            if req not in fields:
                problem(f"{where}: reconciliation record missing '{req}'")
        problem(f"{where}: unresolved cross-store reconciliation for "
                f"'{fields.get('subject')}' / '{fields.get('predicate')}' — "
                f"resolve the drift (fix the entity or fix the facts), "
                f"record the outcome, then DELETE this file; presence "
                f"means unresolved (D9)")


# ---------------------------------------------------------- D6 / D7 --

def load_decisions():
    d = load_json(DECISIONS_PATH, "catalog/DECISIONS_INDEX.json")
    if d is None:
        return None
    # Duplicate-key detection must not depend on formatting: re-parse with
    # an object_pairs_hook so a duplicate at ANY level and ANY indentation
    # is caught (F-PR27-006) — plain json.loads silently keeps the last
    # duplicate, which is exactly how a forged second minting hides.
    def _dup_hook(pairs):
        seen = {}
        for k, v in pairs:
            if k in seen:
                problem(f"catalog/DECISIONS_INDEX.json: key '{k}' appears "
                        f"more than once in one object — for a decision-id "
                        f"that is a second minting of the permanent alias "
                        f"(D6)")
            seen[k] = v
        return seen
    try:
        json.loads(DECISIONS_PATH.read_text(encoding="utf-8"),
                   object_pairs_hook=_dup_hook)
    except json.JSONDecodeError:
        pass  # already reported by load_json
    rows = d.get("decisions")
    if not isinstance(rows, dict):
        problem("catalog/DECISIONS_INDEX.json: 'decisions' must be an "
                "object keyed by decision-id")
        return None
    for did, spec in sorted(rows.items()):
        if not isinstance(spec, dict):
            problem(f"catalog/DECISIONS_INDEX.json: '{did}' must be an "
                    f"object with 'location' and 'url'")
            continue
        if not re.match(r"^[a-z][a-z0-9-]{2,}$", did):
            problem(f"catalog/DECISIONS_INDEX.json: decision-id '{did}' is "
                    f"not a lowercase slug")
        if not spec.get("url") or not spec.get("location"):
            problem(f"catalog/DECISIONS_INDEX.json: '{did}' needs BOTH a "
                    f"'location' (the record) and a 'url' (the permanent "
                    f"alias) — the envelope is not optional (D6)")
        loc = spec.get("location", "")
        if loc and not loc.startswith("http") and " " not in loc[:1]:
            lp = ROOT / loc
            if lp.is_file():
                digest = hashlib.sha256(lp.read_bytes()).hexdigest()
                want = spec.get("contentSha256")
                if not want:
                    problem(f"catalog/DECISIONS_INDEX.json: '{did}' names a "
                            f"local record '{loc}' without contentSha256 — "
                            f"revision binding is required for local "
                            f"records (edit-without-index-touch is "
                            f"undetectable without it)")
                if want and digest != want:
                    problem(f"catalog/DECISIONS_INDEX.json: '{did}' record "
                            f"'{loc}' content sha256 {digest[:12]}… does "
                            f"not match the indexed {str(want)[:12]}… — the "
                            f"record was edited without touching the index "
                            f"(§6a edit-without-index-touch)")
            elif not loc.startswith("issue ") and not loc.startswith("PR "):
                problem(f"catalog/DECISIONS_INDEX.json: '{did}' record "
                        f"location '{loc}' does not exist in the repo and "
                        f"is not a named issue/PR location")
    return rows


def resolve_fact(fact_id, entries):
    """Per-kind resolver, v2.3 envelope shape. Zero-hit returns None."""
    if not FACT_ADDR.match(fact_id):
        return None
    e = entries.get(fact_id)
    if e is None:
        return None
    fields = e["fields"]
    env = {"kind": "fact", "id": fact_id,
           "location": f"memory/{e['path'].name}"
           if hasattr(e.get("path", None), "name") else "memory/",
           "class": effective_class(fields, "repo"),
           "observed": fields.get("observed")}
    # Demote-on-crossing is part of the ENVELOPE, not a side helper
    # (F-PR27-004): a consumer reading through this resolver inside the
    # repo sees the demoted class, with the raw claim carried honestly.
    if env["class"] != fields.get("class"):
        env["storedClass"] = fields.get("class")
        env["demotion"] = "agent-store fact read inside a repo (A2 mech 3)"
    return env


def resolve_decision(decision_id, decisions):
    if decisions is None or decision_id not in decisions:
        return None
    spec = decisions[decision_id]
    if not isinstance(spec, dict):
        return None  # load_decisions reported the malformed row
    env = {"kind": "decision", "id": decision_id,
           "location": spec.get("location"), "url": spec.get("url")}
    if spec.get("contentSha256"):
        env["contentSha256"] = spec["contentSha256"]  # revisions bind bytes
    return env


def tracked_files():
    out = []
    for name in TRACKED_ROOT_FILES:
        p = ROOT / name
        if p.is_file():
            out.append(p)
    for d in TRACKED_DIRS:
        base = ROOT / d
        if base.is_dir():
            for p in sorted(base.rglob("*")):
                rel = p.relative_to(ROOT).as_posix()
                if (p.is_file() and p.suffix in (".md", ".json")
                        and not any(rel.startswith(x)
                                    for x in TRACKED_EXCLUDE)):
                    out.append(p)
    return out


def check_citations(entries, decisions):
    """D7: exhaustive per-target accounting. Zero-hit is a failure;
    unreadable is a failure, not a skip; per-file OK | UNRESOLVABLE(n) |
    UNREADABLE."""
    report = []
    for p in tracked_files():
        rel = p.relative_to(ROOT).as_posix()
        try:
            text = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            report.append((rel, "UNREADABLE"))
            problem(f"{rel}: UNREADABLE while resolving citations ({exc}) — "
                    f"an unreadable tracked file is a failure, not a skip")
            continue
        bad = 0
        strict = {(k, a) for k, a in CITATION.findall(text)}
        for kind, addr in set(CITATION_LOOSE.findall(text)):
            # Sentence punctuation is not part of an address: strip
            # trailing non-slug characters before judging malformedness,
            # so 'fact:mem-001.' at a sentence end is the strict citation
            # it contains, not a defect.
            trimmed = re.sub(r"[^a-z0-9-]+$", "", addr)
            if (kind, trimmed) in strict:
                continue
            if (kind, addr) not in strict:
                bad += 1
                problem(f"{rel}: citation-shaped address '{kind}:{addr}' "
                        f"does not match the closed grammar "
                        f"(lowercase slug) — a malformed address must be "
                        f"visible, not silently not-a-citation")
        for kind, addr in set(CITATION_NEARKIND.findall(text)):
            if kind in ("fact", "decision"):
                continue  # exact grammar, validated below
            bad += 1
            problem(f"{rel}: '{kind}:{addr}' uses a near-miss of a closed "
                    f"citation kind — the kinds are exactly 'fact' and "
                    f"'decision', lowercase; intent to cite must not "
                    f"vanish on a spelling variant")
        for kind, addr in sorted(strict):
            env = (resolve_fact(addr, entries) if kind == "fact"
                   else resolve_decision(addr, decisions))
            if env is None:
                bad += 1
                problem(f"{rel}: citation '{kind}:{addr}' resolves to "
                        f"nothing — a pointer convention that silently 404s "
                        f"is the 2026-07-16 incident class; fix the address "
                        f"or register the target")
        report.append((rel, f"UNRESOLVABLE({bad})" if bad else "OK"))
    # The per-file accounting IS a required output (D7): one line per
    # tracked file, every run — OK included.
    print(f"  citations ({len(report)} tracked files):")
    for f, st in report:
        print(f"    {st:>15}  {f}")
    return report


# --------------------------------------------------------------- D3 --

def check_index_v2(entries):
    """The three extra columns must agree with the entries (same posture as
    cm.check_index's field-agreement checks; positions 5..7)."""
    index = MEM / "README.md"
    if not index.is_file():
        return
    live, _ = cm.strip_fenced(index.read_text(encoding="utf-8"))
    tables, _ = cm.scan_tables(live)
    for t in tables:
        if [c.lower() for c in t["header"]] != INDEX_HEADER_V2:
            continue
        for lineno, bline in t["body"]:
            cells = cm.split_index_cells(bline)
            if len(cells) != len(INDEX_HEADER_V2):
                continue  # width mismatch already failed via cm.check_index
            eid = cells[0]
            e = entries.get(eid)
            if e is None:
                continue
            f = e["fields"]
            for pos, field in ((5, "subject"), (6, "predicate"),
                               (7, "object")):
                entry_val = f.get(field) or "-"
                if cells[pos] != entry_val:
                    problem(f"memory/README.md line {lineno}: index row "
                            f"'{eid}' says {field} '{cells[pos]}' but the "
                            f"entry says '{entry_val}' — all three triple "
                            f"positions are index-answerable only if the "
                            f"index tells the truth (F-CV-004)")


# --------------------------------------------------------------- D11 --

LV_DATE = re.compile(r"^- Date: (\d{4}-\d{2}-\d{2})$", re.MULTILINE)
LV_COMMIT = re.compile(r"^- Commit: ([0-9a-f]{7,40})$", re.MULTILINE)
LV_EVIDENCE = re.compile(r"^- Evidence: (\S.*)$", re.MULTILINE)

# Wall-clock leg (memory-cadence addendum, issue #3 comment 5236971755,
# ratified 2026-08-17 in comment 5313041570): a Last-Verified block older
# than this many days warns — never blocks — so a neglected but
# internally consistent store becomes visible instead of rotting
# silently. Inconsistency (date older than the newest entry) stays a
# blocking error above this.
LAST_VERIFIED_MAX_AGE_DAYS = 14


def check_last_verified(entries):
    """Absence is observable (warning); inconsistency is blocking (error)."""
    index = MEM / "README.md"
    if not index.is_file():
        return
    text = index.read_text(encoding="utf-8")
    d, c, ev = (LV_DATE.search(text), LV_COMMIT.search(text),
                LV_EVIDENCE.search(text))
    if not (d or c or ev):
        warn("memory/README.md: no 'Last verified' block (- Date / - Commit "
             "/ - Evidence) — absence claims have no machine-checkable "
             "anchor; add the block the next time the store is verified "
             "(D11)")
        return
    if not (d and c and ev):
        problem("memory/README.md: 'Last verified' block is incomplete — "
                "it needs all three of Date, Commit, Evidence")
        return
    date = SEMDATE(d.group(1))
    if date is None:
        problem(f"memory/README.md: Last verified date '{d.group(1)}' is "
                f"not a real date")
        return
    newest = max((SEMDATE(e['fields'].get('observed', '')) or
                  datetime.date.min for e in entries.values()),
                 default=datetime.date.min)
    if date < newest:
        problem(f"memory/README.md: Last verified date {date} is older than "
                f"the newest entry's observed date {newest} — a "
                f"verification that predates the store contents anchors "
                f"nothing (D11: inconsistency blocks)")
    age = (datetime.date.today() - date).days
    if date > cm.latest_date_anywhere():
        problem(f"memory/README.md: Last verified date {date} is in the "
                f"future — nothing was verified tomorrow, and a future date "
                f"would park the wall-clock warning until it arrives "
                f"(inconsistency blocks)")
    if age > LAST_VERIFIED_MAX_AGE_DAYS:
        warn(f"memory/README.md: Last verified date {date} is {age} days "
             f"old (> {LAST_VERIFIED_MAX_AGE_DAYS}) — the store may be "
             f"aging unwatched; re-verify and refresh the block "
             f"(memory-cadence addendum: staleness warns, inconsistency "
             f"blocks)")
    sha = c.group(1)
    exists = cm.commit_exists(sha)
    if exists is False:
        problem(f"memory/README.md: Last verified commit {sha[:12]} does "
                f"not resolve in this repository")
    elif exists is None:
        warn(f"memory/README.md: Last verified commit {sha[:12]} cannot be "
             f"checked here (shallow or no git) — the limit is reported, "
             f"not passed")
    else:
        r = cm._git("merge-base", "--is-ancestor", sha, "HEAD")
        if r is not None and r[0] != 0:
            problem(f"memory/README.md: Last verified commit {sha[:12]} is "
                    f"not an ancestor of HEAD — it anchors a different "
                    f"history")


# ------------------------------------------- map three-tier split -----
# (map-scale decisions, the operator 2026-08-07, issue #3 comment 5210904001,
# restored into the slice 2026-08-14: index -> node -> journal.
# Act -> node; understand-history -> journal.)

NODE_NEXT_WARN = 1500   # bytes; narrative accretion starts here
NODE_NEXT_FAIL = 3000   # bytes; history belongs in nodes/<id>.md
JOURNAL_DIR = ROOT / "nodes"
JOURNAL_NAME = re.compile(r"^([a-z][a-z0-9]*-\d{3})\.md$")


def check_map_tiers():
    # Deletion is judged against the baseline, so it runs before anything
    # that depends on the current tree: a removed nodes/ folder or a
    # missing DAG.json used to skip it entirely (SM-4).
    check_journals_not_deleted()
    dag_path = ROOT / "DAG.json"
    if not dag_path.is_file():
        return
    try:
        dag = json.loads(dag_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return  # check_map owns reporting a broken DAG
    node_ids = {n.get("id") for n in dag.get("nodes", [])
                if isinstance(n, dict)}

    # Index parity: the committed index must be byte-identical to a fresh
    # render (same posture as CATALOG.md) — a hand-edited or stale index
    # is worse than none, because it is the one thing read every session.
    idx = ROOT / "WORK_MAP_INDEX.md"
    if idx.is_file():
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import render_map_index
        fresh = render_map_index.render()
        if idx.read_text(encoding="utf-8") != fresh:
            problem("WORK_MAP_INDEX.md is not byte-identical to a fresh "
                    "render — regenerate with 'python3 "
                    "tools/render_map_index.py' (the index is generated, "
                    "never hand-edited; a drifted index misdirects every "
                    "session start)")
    else:
        warn("WORK_MAP_INDEX.md is missing — generate it with 'python3 "
             "tools/render_map_index.py' (the hot tier of the map split; "
             "sessions read it first and load only the nodes they need)")

    # Journal correspondence: every journal names a real node. A node
    # without a journal is fine (young work); a journal without a node is
    # history hanging off nothing.
    if JOURNAL_DIR.is_dir():
        for p in sorted(JOURNAL_DIR.glob("*")):
            if p.name == "README.md":
                continue
            m = JOURNAL_NAME.match(p.name)
            if not m:
                problem(f"nodes/{p.name}: journal filename must be "
                        f"'<node-id>.md' (append-only history for exactly "
                        f"one node)")
                continue
            if m.group(1) not in node_ids:
                problem(f"nodes/{p.name}: no node '{m.group(1)}' in "
                        f"DAG.json — a journal must correspond to a real "
                        f"node")
                continue
            check_journal_append_only(p)

    # Node-size lint: 'next' carries the now, not the story. Past the cap
    # the history relocates to the node's journal.
    for n in dag.get("nodes", []):
        if not isinstance(n, dict):
            continue
        size = len(str(n.get("next", "")).encode("utf-8"))
        where = f"DAG.json node {n.get('id')}"
        if size > NODE_NEXT_FAIL:
            problem(f"{where}: 'next' is {size} bytes (cap "
                    f"{NODE_NEXT_FAIL}) — that is a narrative, not a next "
                    f"step; move the history to nodes/{n.get('id')}.md "
                    f"(append-only) and leave the now")
        elif size > NODE_NEXT_WARN:
            warn(f"{where}: 'next' is {size} bytes — approaching the "
                 f"{NODE_NEXT_FAIL}-byte cap; consider relocating history "
                 f"to nodes/{n.get('id')}.md")


def journal_baseline_ref():
    """The ref the append-only check compares against: the merge base with
    the remote default branch when derivable (origin/HEAD resolves it on
    any default-branch name), else common default names."""
    return cm.baseline_ref()


def check_journals_not_deleted():
    """A deleted journal is the strongest append-only violation of all
    (F-PR27-008 residual): enumerate the BASELINE's journals and require
    each to still exist."""
    base = journal_baseline_ref()
    if base is None:
        return  # per-journal check already reported the limit
    r = cm._git("ls-tree", "--name-only", base, "nodes/")
    if r is None or r[0] != 0:
        return
    for rel in r[1].splitlines():
        name = rel.split("/")[-1]
        if not JOURNAL_NAME.match(name):
            continue
        if not (ROOT / rel).is_file():
            problem(f"{rel}: journal existed at the merge base and is gone "
                    f"— deleting history is the strongest append-only "
                    f"violation; a journal is never removed, only grown")


def check_journal_append_only(path):
    """Append-only means the committed baseline's lines are a PREFIX of the
    current content's lines (F-PR27-008): prior digests are never edited,
    truncated, or deleted. New journals have no baseline and pass; when
    git cannot answer, the limit is reported, never silently passed."""
    base = journal_baseline_ref()
    rel = f"nodes/{path.name}"
    if base is None:
        warn(f"{rel}: append-only check cannot run (no git baseline "
             f"reachable) — the limit is reported, not passed")
        return
    r = cm._git("show", f"{base}:{rel}")
    if r is None:
        warn(f"{rel}: append-only check cannot run (git unusable)")
        return
    if r[0] != 0:
        return  # not in the baseline: a new journal, nothing to preserve
    # Compared line by line, so text glued onto the base's last line
    # edits that line ('5' becoming '57') while a first entry in an empty
    # journal, or one after a trailing-space hard break, is an append
    # (SM-4). Only the base's last line may differ in trailing whitespace,
    # because git output arrives stripped; earlier lines must match
    # exactly, since two trailing spaces are a Markdown hard break.
    old = r[1].strip().splitlines()
    new = path.read_text(encoding="utf-8").strip().splitlines()
    n = len(old)
    if n and (len(new) < n or new[:n - 1] != old[:n - 1]
              or new[n - 1].rstrip() != old[n - 1].rstrip()):
        problem(f"{rel}: journal is not append-only against the merge "
                f"base — prior history was edited, truncated, or deleted; "
                f"a journal only ever grows (corrections are new entries "
                f"that say what they correct)")


# --------------------------------------------------------------- D12 --

def health_report(entries, vocab):
    """Reported, never gated (D12): the audit seam, in the contract's own
    metric names — proposals-per-month, near-duplicate predicate RATE,
    notes ratio (F-PR27-009)."""
    notes = 0
    for e in entries.values():
        if e["fields"].get("predicate") == "notes":
            notes += 1
    total = len(entries)
    # Proposals per month: predicates carrying a proposal record. The
    # governance pipeline files proposals under vocabulary "proposed"
    # entries; until any exist the count is zero WITH ITS SOURCE NAMED —
    # zero from an empty surface, not from a surface that was not read.
    _ABSENT = object()
    proposals = (vocab or {}).get("proposedPredicates", _ABSENT)
    source_absent = proposals is _ABSENT
    source_invalid = (proposals is not _ABSENT
                      and not isinstance(proposals, dict))
    by_month = {}
    if isinstance(proposals, dict):
        for name, spec in proposals.items():
            m = str(spec.get("proposed", "") if isinstance(spec, dict)
                    else "")[:7]
            by_month[m] = by_month.get(m, 0) + 1
    declared = sorted((vocab or {}).get("predicates", {}))
    near = [(a, b) for i, a in enumerate(declared) for b in declared[i + 1:]
            if a != b and (a.replace("-", "") == b.replace("-", "")
                           or a.rstrip("s") == b.rstrip("s"))]
    pairs = len(declared) * (len(declared) - 1) // 2
    rate = (len(near) / pairs) if pairs else 0.0
    print("health report (informational, never gating):")
    if source_invalid:
        print("  proposals per month: SOURCE INVALID — proposedPredicates "
              "is not an object; see the blocking problem above")
    elif source_absent:
        print("  proposals per month: SOURCE ABSENT — "
              "catalog/VOCABULARY.json declares no proposedPredicates "
              "surface; absence of the surface is not zero proposals")
    else:
        print(f"  proposals per month: "
              + (", ".join(f"{m}={n}" for m, n in sorted(by_month.items()))
                 or "0 (source: proposedPredicates — declared and empty)"))
    print(f"  near-duplicate predicate rate: {rate:.3f} "
          f"({len(near)}/{pairs} declared pairs"
          + ("; " + ", ".join(f"{a}~{b}" for a, b in near) if near else "")
          + ")")
    print(f"  notes ratio: {notes}/{total} typed-escape facts"
          + (" — every notes fact is a predicate the vocabulary lacks"
             if notes else ""))


# --------------------------------------------------------------- main --

def run(report=False, agent_store=None):
    fmt = store_format()
    if fmt == "v1":
        # A v1 store gets check_memory's checks — but v2-only keys
        # present in a v1 store are a DOWNGRADE BYPASS, not a formatting
        # choice: removing the marker must not turn off the ceiling and
        # triple validation while the typed claims stay readable
        # (F-PR27-002).
        for entry_id, (path, text) in sorted(cm.read_entries().items()):
            fields, _ = cm.split_front_matter(text, f"memory/{path.name}")
            if fields is None:
                continue
            stray = sorted(set(fields) & V2_KEYS)
            if stray:
                problem(f"memory/{path.name}: v2 fields {stray} present in "
                        f"a store with no v2 format marker — declare "
                        f"'Store format: memory/v2' in memory/README.md or "
                        f"remove the typed fields; a marker downgrade must "
                        f"not silently disable their validation")
        rc = cm.main()
        if rc == 0:
            print("check_tracking: OK (store format memory/v1 — "
                  "check_memory.py's checks passed)")
        return rc

    # v2: the SAME cm pipeline runs first — check_memory reads the store's
    # own format marker and applies the wider index header through its own
    # hardened parser (one code path per rule, D1).
    entries_raw = cm.read_entries()
    parsed = {}
    for entry_id, (path, text) in sorted(entries_raw.items()):
        result = cm.check_entry(entry_id, path, text)
        if result is not None:
            result["path"] = path
            parsed[entry_id] = result
    cm.check_relationships(parsed)
    if MEM.is_dir():
        cm.check_entries_not_deleted(entries_raw)
        cm.check_canary()
        cm.check_index(parsed, entries_raw)

    # A typed store is catalog-bound by design: skipping the catalog never
    # turns the v2 layers off (F-CV-001: no store is silently half-typed).
    if "catalog" in hb_modules.skipped(ROOT)[0]:
        problem(f"memory/README.md declares 'Store format: memory/v2', which "
                f"needs the catalog (vocabulary, entities, decisions), but "
                f"{hb_modules.MANIFEST} declares the catalog module skipped — "
                f"adopt the catalog or use a memory/v1 store")
    vocab = load_vocabulary()
    entities = load_entities(vocab)
    for entry_id, (path, text) in sorted(entries_raw.items()):
        fields, body = cm.split_front_matter(text, f"memory/{path.name}")
        if fields is None:
            continue
        check_v2_entry(entry_id, path, fields, body or "", vocab, entities)
    check_functional(parsed, vocab, entities)
    check_reconciliation_records()
    decisions = load_decisions()
    check_citations(parsed, decisions)
    check_index_v2(parsed)
    check_last_verified(parsed)
    check_map_tiers()
    # Cross-store reconciliation is part of the NORMAL run, never a silent
    # skip: --agent-store wins; else the conventional snapshot location is
    # used; else the limit is reported (a missing input is never a silent
    # pass — this checker's own posture).
    default_snap = MEM / "agent-store-snapshot.json"
    if agent_store:
        check_cross_store(agent_store, parsed, vocab, entities)
    elif default_snap.is_file():
        check_cross_store(str(default_snap), parsed, vocab, entities)
    else:
        warn("cross-store reconciliation not run: no --agent-store given "
             "and no memory/agent-store-snapshot.json present — the "
             "boundary comparison (A2 mech 2) ran against nothing this "
             "run; export a workbench snapshot to enable it")

    if report:
        health_report(parsed, vocab)

    for w in cm.warnings:
        print("  warning:", w)
    if cm.problems:
        print(f"check_tracking: {len(cm.problems)} problem(s) found")
        for p in cm.problems:
            print("  -", p)
        return 1
    print(f"check_tracking: OK ({len(parsed)} v2 entr"
          f"{'y' if len(parsed) == 1 else 'ies'} typed, indexed, and "
          f"citation-resolvable)")
    return 0


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8")
    _args = sys.argv[1:]
    _store = None
    if "--agent-store" in _args:
        _i = _args.index("--agent-store")
        if _i + 1 >= len(_args) or _args[_i + 1].startswith("--"):
            print("check_tracking: --agent-store requires a snapshot path")
            sys.exit(2)
        _store = _args[_i + 1]
    sys.exit(run(report="--report" in _args, agent_store=_store))
