#!/usr/bin/env python3
"""Refuse a work-map change that loses history the base still has.

    python3 tools/check_node_loss.py [base-ref] [--staged] [--allow-no-base]
    # default base: origin/master

Three losses, each compared against the base because none is visible in
the files alone (docs/STATE_MACHINES.md has the transition tables):

- a node the base has is gone here;
- a node 'done' at the base is not 'done' here ('done' is terminal);
- a LEDGER.md entry line at the base is missing or rewritten here (the
  ledger is append-only). Reopening a node and deleting its ledger line
  together leaves check_map nothing to object to, so only the base
  comparison sees it.

Exit codes: 0 = no loss - 1 = loss (or unreadable DAG) - 2 = cannot
compare (the base ref itself is unreachable). 2 is FAIL-CLOSED: an
unperformed comparison must never be distinguishable-only-by-reading-
the-text from a pass, or automation treats "could not check" as
"checked, fine". Pass --allow-no-base to accept that limit explicitly.

A base that IS reachable but has no DAG.json is a different thing
entirely and passes: it is the first commit to adopt a work map, and
there is nothing there to lose (HB9-006). Conflating the two made the
gate block the one workflow that cannot possibly drop a node.

There is NO flag that permits a drop. The first work-map rule in
AGENTS.md is that a node is never deleted — finished ones become
'done', abandoned ones 'parked'. A gate defending that rule must not
ship its own exception to it (HB9-007): if deleting a node ever becomes
legitimate, the rule changes first, by an operator decision, and this
check follows the rule rather than quietly outranking it.

`check_map.py` cannot catch this on its own. It notices a missing node
only when a `LEDGER.md` line points at the id, so it fires for a dropped
*done* node and stays silent for a dropped *open* one — and open nodes
are exactly what a long-lived branch carries a stale set of. Node counts
do not help either: one addition cancels one deletion and the total is
unchanged.

So this compares id sets against the base rather than inspecting the
file in isolation. A dropped node is always a failure: there is no flag,
argument, or record that makes one acceptable, because the repository's
own rule already defines what to do with a node instead of deleting it.

There is deliberately NO ledger-derived allowance. It let any line
mentioning an id in brackets — including ordinary prose, which
`check_ledger` itself ignores because it is not a canonical entry —
suppress the check for that node (HB9-005). Tightening it to the
canonical grammar would have been possible, but the allowance should
not exist at all: this repository's first work-map rule is that a node
is never deleted, finished ones become `done`. A ledger line records
that a node was FINISHED, which is precisely the case where it must
still be present. There is no way past this gate — not by flag, not by
record, not by wording a request differently; a dropped node is
repaired by restoring it, and if deletion is ever to become
legitimate, the work-map rule changes first, by operator decision.
"""
import json
import subprocess
import sys
from collections import Counter


MISSING = object()   # the ref has no DAG.json at all
INVALID = object()   # the ref HAS a DAG.json that does not parse


def statuses(text):
    """{node id: status} from DAG.json text; raises on a malformed map."""
    return {n["id"]: n.get("status") for n in json.loads(text)["nodes"]}


def nodes_at(ref, path="DAG.json"):
    """{node id: status} at a git ref, MISSING, or INVALID.

    Missing and malformed are opposite answers, not one None
    (HB9-006): a base that predates the work map has nothing to lose
    and passes as first adoption, while a base whose DAG.json exists
    but does not parse is a broken input — treating it as first
    adoption waves through exactly the state the CLI contract says
    must exit 1.
    """
    try:
        out = subprocess.run(["git", "show", "%s:%s" % (ref, path)],
                             capture_output=True, text=True,
                             encoding="utf-8", check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return MISSING
    try:
        return statuses(out.stdout)
    except (ValueError, KeyError, TypeError, AttributeError):
        return INVALID


def ledger_entries(text):
    """The ledger's entry lines ('- ...'), trailing whitespace dropped."""
    return [l.rstrip() for l in (text or "").splitlines()
            if l.startswith("- ")]


def ledger_at(ref, path="LEDGER.md"):
    """The base's ledger text, or None when the ref has no LEDGER.md."""
    try:
        return subprocess.run(["git", "show", "%s:%s" % (ref, path)],
                              capture_output=True, text=True,
                              encoding="utf-8", check=True).stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def ref_exists(ref):
    """Is the base ref itself reachable, whatever it contains?

    This is the difference between "I could not reach the base" and
    "the base has no work map yet", which are opposite situations: the
    first is a check that did not run, the second is a check with
    nothing to find.
    """
    try:
        return subprocess.run(["git", "rev-parse", "--verify", "%s^{commit}"
                               % ref], capture_output=True,
                              text=True, encoding="utf-8").returncode == 0
    except (OSError, FileNotFoundError):
        return False


def staged_text(path):
    """The INDEX's copy of a file — `:path`, not HEAD.

    HEAD is the last commit; the index is what the next commit will be.
    A deletion that is staged but uncommitted exists only in the index,
    so reading HEAD for --staged reports the past and misses exactly
    the change about to be recorded (HB9-003).
    """
    try:
        out = subprocess.run(["git", "show", ":%s" % path],
                             capture_output=True, text=True,
                             encoding="utf-8", check=True)
        return out.stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def main(argv):
    base = next((a for a in argv[1:] if not a.startswith("-")), "origin/master")
    for arg in argv[1:]:
        if arg.startswith("--allow-drop"):
            print("check_node_loss: --allow-drop is not supported. A node is "
                  "never deleted here (AGENTS.md work-map rule 1): finished "
                  "nodes become 'done', abandoned ones 'parked'. If a "
                  "deletion is genuinely right, change the rule first — this "
                  "check does not get to outrank it.")
            return 2
    before = nodes_at(base)
    if before is INVALID:
        print("check_node_loss: %s:DAG.json exists but cannot be parsed — "
              "a broken base is not a first adoption; fix or name a "
              "different base" % base)
        return 1
    if before is MISSING and ref_exists(base):
        # The base commit is right there; it simply predates the work
        # map. Nothing can be dropped relative to a set that does not
        # exist (HB9-006).
        print("check_node_loss: OK (%s is reachable and has no DAG.json — "
              "first adoption of a work map; nothing there to lose)" % base)
        return 0
    if before is MISSING:
        if "--allow-no-base" in argv:
            print("check_node_loss: SKIPPED by --allow-no-base (no readable "
                  "%s:DAG.json; the comparison was NOT performed)" % base)
            return 0
        print("check_node_loss: CANNOT COMPARE — no readable %s:DAG.json. "
              "An unperformed comparison is not a pass; fetch the base, name "
              "another with an argument, or accept the limit explicitly with "
              "--allow-no-base." % base)
        return 2
    if "--staged" in argv:
        text = staged_text("DAG.json")
        if text is None:
            print("check_node_loss: --staged but no DAG.json in the index")
            return 1
        try:
            after = statuses(text)
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            print("check_node_loss: staged DAG.json unreadable (%r)" % exc)
            return 1
        ledger_here = staged_text("LEDGER.md")
    else:
        try:
            with open("DAG.json", encoding="utf-8") as fh:
                after = statuses(fh.read())
        except (OSError, ValueError, KeyError, TypeError,
                AttributeError) as exc:
            print("check_node_loss: cannot read DAG.json (%r)" % exc)
            return 1
        try:
            with open("LEDGER.md", encoding="utf-8") as fh:
                ledger_here = fh.read()
        except OSError:
            ledger_here = None
    failed = False
    dropped = sorted(set(before) - set(after))
    if dropped:
        failed = True
        print("check_node_loss: %d node(s) present at %s and missing here:"
              % (len(dropped), base))
        for node in dropped:
            print("  - %s" % node)
        print("Merging this would delete them from the work map. If the "
              "branch is stale, merge the base and union both node sets. A "
              "node is never deleted here — finished ones become 'done', "
              "abandoned ones 'parked' — so restore it rather than looking "
              "for a way past this check.")
    # 'done' is terminal: a ledger line records that a node was finished
    # once, so a node done at the base and live here was reopened, which
    # check_map cannot see once the ledger line is gone too.
    reopened = sorted(i for i, s in before.items()
                      if s == "done" and i in after and after[i] != "done")
    if reopened:
        failed = True
        print("check_node_loss: %d node(s) done at %s and no longer done "
              "here:" % (len(reopened), base))
        for node in reopened:
            print("  - %s (now '%s')" % (node, after[node]))
        print("'done' is final: the ledger records the node as finished "
              "once. Restore the base's status; new work on it is a new "
              "node.")
    # LEDGER.md is append-only: every entry line at the base survives
    # here byte-for-byte (new lines may be added anywhere, since the
    # ledger sorts newest-first).
    remaining = Counter(ledger_entries(ledger_here))
    lost = []
    for line in ledger_entries(ledger_at(base)):
        if remaining[line]:
            remaining[line] -= 1
        else:
            lost.append(line)
    if lost:
        failed = True
        print("check_node_loss: %d LEDGER.md line(s) at %s are missing or "
              "rewritten here:" % (len(lost), base))
        for line in lost:
            print("  %s" % line)
        print("The ledger is append-only (AGENTS.md: never rewrite old "
              "lines). Restore the base's lines; a correction is a new "
              "line.")
    if failed:
        return 1
    print("check_node_loss: OK (no node, completion, or ledger line at %s "
          "is missing here)" % base)
    return 0


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8")
    sys.exit(main(sys.argv))
