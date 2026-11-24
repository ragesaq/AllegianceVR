# Memory protocol — what an assistant may remember, and how strongly

Your AI assistant keeps notes between sessions. That is useful and it is
also the most dangerous thing it does, because a note is not a passive
record: it is an *input* to the assistant's reasoning. A wrong note does
not simply get ignored. It reframes the problem, and a competent model
will then work hard to make the evidence in front of it agree with the
note.

That failure has a name in our testing: the assistant is handed a claim it
treats as settled, and instead of checking the claim it rewrites reality
around it. The same shape shows up when a test is wrong and the code is
right — a model that treats the test as canonical "fixes" perfectly good
code. Memory is where our program manufactures that kind of settled claim,
so memory is where we control it.

Eight rules. They apply to this repo, every repo enrolled in the program,
and every assistant session. `tools/check_memory.py` enforces the
mechanical parts. Run it explicitly before committing memory changes and
record the result in the PR; this release ships no GitHub Actions workflow.
Filling a new store from a repository's past (its history, decision
records and agents' private notes) follows the same rules; the hub's
`docs/MEMORY_BACKFILL.md` is the procedure.

## 1. Memory records what was observed, not what is true

An entry says what was seen, where, and when. "`check_map.py` printed OK
on 2026-08-07 at commit 52277f7" is an observation. "The work map is
consistent" is a verdict, and it will still be sitting there long after
it stops being true.
**Your assistant will:** write entries in observation form, with the date
and the thing it actually looked at.

## 2. Every entry declares how far it can be trusted

Four classes, strongest last. `inferred` and `witnessed` rank together:

| Class | Means | Requires |
|---|---|---|
| `inferred` | The assistant worked it out | `inferred-from:` naming what it reasoned from |
| `witnessed` | A person or assistant saw it directly, and the evidence was not kept in a form a reader can resolve | `seen-in:` naming the action or command, the environment and its versions |
| `verified` | Someone checked it against a real artifact | `evidence:` naming a file, URL, or commit the checker can resolve |
| `canonical` | The program has decided this is how it is | A grant event: who granted it, when, and where |

Class attaches to the *claim*, not to the document. A single file may hold
one canonical decision and a dozen inferred notes; each entry carries its
own class.

`witnessed` is for an error in a terminal that was not saved, behavior seen
during a manual hardware test, a dialog that appeared, or a remote service's
answer. It is the memory form of a knowledge note's *(observed)* claim when
no resolvable evidence was kept; with kept evidence the entry is `verified`.
Its rules:

- `seen-in:` describes the machine by its role ("the VR test PC"), never by
  hostname, serial number or personal path. This is a rule for the writer.
  The checker requires the field and does not read what it says; what it
  says follows the data boundary, as every entry does.
- `reproduce:` is optional: how to see it again, as a description. It is
  never a command to run, and the same writing rule applies to it.
- A `witnessed` entry must carry `seen-in:`. Neither field is reserved to
  this class: an entry of another class may carry them too.
- The class and these fields need the checkers from release 0.39.0 or
  later. An older `check_memory.py` refuses the class and ignores
  `seen-in:`, `reproduce:` and `contradicts:`. An older `check_tracking.py`
  refuses the class and all three fields in a typed store.
- A `witnessed` entry never declares `sources:`. An entry built from other
  entries is reasoning, so it is `inferred` or stronger. Two `witnessed`
  entries do not add up to `verified`.
- When it is seen again with kept evidence (a saved log, a commit, a test),
  file a `verified` entry and supersede the `witnessed` one (rule 5).

**Your assistant will:** refuse to file an entry without a class, and
refuse to claim a class it cannot back.

## 3. Canonical status is granted by a person, never taken by an assistant

An assistant may write `verified`, `witnessed` and `inferred` entries on
its own. It may never mark its own memory `canonical`. Canonical means a
human with authority decided, and the entry must name that decision:
`granted-by` a person who has a folder in `people/`, `granted-on` a date,
`granted-where` the pull request, issue, or meeting where it happened.

Every canonical entry also carries `review-by:`. Past that date the check
fails until a person re-grants it or it is demoted. Canonical status records
an authorized decision about intended behavior; it never overrides evidence
of the actual system state. Its authority must be reviewed, and the expiry
must be one the entry cannot stretch for itself:
`granted-on` may not be in the future (a grant records a decision that
already happened), and `review-by` may sit at most 400 days past both
`granted-on` and the day the check runs, so a future-dated grant buys no
extra life. `granted-by` and `recorded-by` are plain lowercase names with
a folder in `people/`, never paths or symbols. When the same person
records and grants an entry, the check warns every time — labelling it
"self-granted" does not quiet the warning, because a self-grant is exactly
what the warning exists to flag.

Every grant field must have a value: a blank `granted-by`, `granted-on`,
`granted-where` or `review-by` names no decision, so the check fails it.

**Guests never grant.** A guest from another operator's side has a
`people/<name>/` folder holding a `GUEST.md` file, which the owner side adds
in the invitation pull request. A guest may record `inferred` and
`verified` entries like anyone else, proposed by pull request, but
`canonical` is granted only by the repository owner's side: a `granted-by`
naming a guest fails. So does one whose folder cannot be classified cleanly
(the folder is a link, or it holds a name like `GUEST.md` that is not
exactly that one file), because an unclear identity is not owner authority.
The collaboration decision gives a guest those two classes only, so a guest
does not file `witnessed`; the checker does not check which class a recorder
files, so review holds that line.
Opted-in knowledge claims follow this same rule through the same check.
**Your assistant will:** ask you to grant canonical status explicitly, and
tell you when a canonical entry is due for review.

## 4. When memory and reality disagree, reality wins

Always. Not "usually". If the repo, the file, or the command output
contradicts an entry's claim about actual state, including a canonical one,
that claim is wrong. Do not reinterpret the evidence to rescue the note.
If the entry records approved intended behavior, an observed deviation
does not silently repeal that decision. Report the intended/actual
disagreement, preserve the decision history, and obtain the decision needed
before changing policy or operating outside the existing authorization.
**Your assistant will:** stop, tell you the entry and the evidence
disagree, and offer to supersede the entry. It will not quietly pick the
note over the bytes.

## 5. Update by superseding, never by silent edit

Wrong memory is evidence about how the program went wrong. Do not edit it
away. Write a new entry and point the old one at it with
`superseded-by:`. The old entry stays, marked, and stops being retrieved
as current.
**Your assistant will:** supersede rather than overwrite, and never delete
an entry to make a check pass.

When two entries disagree and nothing yet shows which is right, neither is
superseded. One of them, usually the newer, names the other with
`contradicts:` (one or more entry ids, comma-separated), and its body says
where the two overlap. Neither is settled and both stay current; the
checker reports each pair once,
whichever side carries the link, as an open contradiction on every run. A
check that settles it files its result as an entry and supersedes the side
it disproves; the report then stops. An entry never `contradicts` an entry
that it supersedes or that supersedes it, whichever of the two records the
link: a replaced entry is not a standing disagreement. Each id appears
once, and the list has no empty items.

In a typed store, a functional predicate still allows one current object
per subject: two current facts that disagree fail the check even when one
names the other with `contradicts:`. Keep the current fact, record the
unsettled observation as a `predicate: notes` fact that names it with
`contradicts:`, and file the typed fact once a check settles it.

## 6. Saying "there is nothing" is a claim, and it needs proof

"There is no such file", "that never happened", "we have no record of it"
— these are the claims we get wrong most often, and they are acted on
hardest. An entry that asserts absence must name two things:

- `surface:` exactly what was searched (this repo's `docs/`, the catalog,
  a specific person's folder). An absence on one surface is not an absence
  everywhere.
- `control:` the same search run against something known to be present. If
  the method cannot find the thing that *is* there, the method is broken
  and the absence means nothing.

Say which places you did not search, rather than folding them into a clean
"nothing found".
**Your assistant will:** run the control before recording an absence, and
scope the claim to what it actually searched.

## 7. Memory stays small enough to be read

An assistant's memory is only real if it fits in the assistant's reading
budget. Past that, the tail is silently dropped and the assistant behaves
as if it never existed — worse than having no memory, because everyone
believes it is there.

- One entry: 8,000 bytes maximum. Longer means it is a document, not a
  memory; put the document in `knowledge/` (see `docs/KNOWLEDGE_NOTES.md`)
  and let the entry point at it. The entry keeps its class and its
  pointer; it never restates the document, because two copies drift and
  only one of them is right.
- The index `memory/README.md`: 20,000 bytes maximum, which is the
  default reading budget assistants are given. When it approaches the cap,
  split by topic — never let it grow past.

**Your assistant will:** refuse to append to an oversized index and split
it instead.

### What `verified` evidence has to survive

The checker resolves evidence rather than pattern-matching it, because a
reference that merely *looks* right is how a fabricated citation survives
review:

- **Repo path** must be repo-relative and must exist. Absolute paths and
  paths escaping the repository are rejected: evidence a reader cannot
  open from this checkout is not evidence, and it means something
  different on every machine.
- **A claim in a knowledge note** is cited as
  `knowledge/<note>.md#claim-<slug>`, with no catalog involved. The note
  must hold exactly one live `### claim-<slug>` heading (not inside a code
  block or an HTML comment) followed by its `hyperbench-claim-v1` fence;
  the claim checker validates the fence itself. In a path, `#` is reserved
  for this: anything after it that is not a claim anchor fails, so a file
  whose name contains `#` cannot be cited.
- **URL** must be `https://`. Plain `http://` is rejected, since
  evidence that can be rewritten in transit is not evidence. The checker
  does not fetch the network, so a URL is checked for shape only. That
  limit is real and stated rather than hidden.
- **`commit <sha>`** is resolved against this repository's history. A
  well-formed sha that names no commit fails. In a shallow clone the
  checker cannot tell "absent" from "not fetched", so it reports the
  reference UNVERIFIED instead of passing or failing it: the same rule
  rule 6 imposes on you, applied to the tool.

UNVERIFIED is an honest answer, not a passing one. Where a run is meant to
be authoritative, set `MEMORY_STRICT_EVIDENCE=1` and an unresolvable
reference fails instead of warning. Run with full Git history so the question
is answerable, and set the flag so an unanswerable one still blocks. An
adopted CI system should use the same pairing (`fetch-depth: 0` plus the
flag). This release's explicit local checks are not evidence that such CI
is installed. A green result without resolvable evidence cannot prove a
commit-backed claim.
The flag stays off where missing history is the declared condition, such
as an exported tree with no `.git`.

## 8. The canary proves retrieval works before you trust it

`memory/CANARY.md` holds one fixed, deliberately boring fact. Before an
assistant reports that it could not find something, it retrieves the
canary the same way it just searched. Canary found: the search worked, the
absence is real. Canary missing: the search is broken, and the absence
claim is void.
**Your assistant will:** check the canary before telling you something
isn't there.

---

## How an entry looks

One file per topic in `memory/`, named `<id>-<short-topic>.md` with an id
like `mem-001`:

    ---
    id: mem-001
    topic: standing-checks
    class: verified
    observed: 2026-08-07
    recorded-by: operator
    evidence: tools/check_map.py
    ---

    # Standing checks run from the repo root

    On 2026-08-07 `python3 tools/check_map.py` printed
    "check_map: OK (work map, catalog, ledger all consistent)" and exited 0.

Fields:

| Field | When | Meaning |
|---|---|---|
| `id` | always | `mem-` plus three digits, matching the filename |
| `topic` | always | short slug, what this entry is about |
| `class` | always | `inferred`, `witnessed`, `verified`, or `canonical` |
| `observed` | always | the date it was seen; not a future date |
| `recorded-by` | always | who filed it |
| `evidence` | `verified` | a repo-relative path that exists, an `https://` URL, or `commit <sha>` resolvable in this repo |
| `inferred-from` | `inferred` | what the reasoning rests on |
| `seen-in` | `witnessed`; optional on other classes | the action or command, the environment and versions, the machine by role |
| `reproduce` | optional | how to see it again; a description, never a command |
| `granted-by` / `granted-on` / `granted-where` / `review-by` | `canonical` | the grant event and its expiry |
| `surface` / `control` | absence claims | where you looked, and the proof the method works |
| `sources` | entries built from others | the entry ids this summarizes |
| `superseded-by` | retired entries | the entry that replaced this one |
| `contradicts` | standing disagreements | the entry ids this one disagrees with, both kept (rule 5) |

A summary built from other entries can never be stronger than its weakest
source. Two `inferred` notes do not add up to a `verified` conclusion.
The checker enforces this only for declared sources: an aggregate that
omits `sources` escapes the weakest-source check entirely, so the
declaration is what buys the protection, not optional bookkeeping.

## Keeping it healthy without being asked

The checker is the floor, not the practice. Every assistant working in
this repo:

- **At session start**, reads `memory/README.md` — that is the index, and
  it is short on purpose.
- **When it learns something durable**, files an entry in the same pull
  request as the work, the way `DAG.json` and `LEDGER.md` are updated
  together. Memory written "later" is memory not written.
- **When it finds an entry contradicted**, supersedes it in that same pull
  request. Leaving a known-wrong entry in place is the failure this whole
  protocol exists to prevent.
- **When it files an entry**, adds the id and one-line summary to
  `memory/README.md` so the index and the store stay in step. The index row
  must repeat the entry's own `topic`, `class`, and `observed` values. The
  checker fails if they drift, because the index is the part that actually
  gets read: a row claiming `canonical` for an `inferred` entry promotes a
  guess to a decision without touching the entry.
- **Writes complete index rows.** The row is exactly
  `| id | topic | class | observed | summary |` — five cells, all non-empty,
  with a class the reader recognises. A row stripped down to its id still
  counts as "indexed" to a careless check while telling a reader nothing
  about how far to trust the entry, so the checker rejects it rather than
  skipping it. A blank summary is the same defect: it is the line a reader
  scans and learns nothing from. Extra cells are rejected too, because when
  the parse and the render disagree, the field the checker compared is not
  the field the human read. To put a literal pipe in a summary, escape it as
  `\|`, which is what the renderer expects and what the checker parses.
- **Writes rows the checker can see.** Markdown starts a table row at up to
  three spaces of indent, with or without a space after the pipe, and a body
  row does not need a leading pipe at all. A row that renders to a human but
  slips past the tool is the worst of both: readable enough to be believed,
  invisible to the thing meant to verify it. So the checker reads the index
  the way the renderer does rather than pattern-matching lines.
- **Every body row of the index table is checked, with no id-shaped escape
  hatch.** The first cell must be exactly `mem-NNN` and must name an entry
  that exists. `memo-004` and `memory-004` render inside the table just as
  `mem-004` does, so a reader sees the same trust claim; a checker that
  skipped them because they were not "close enough" to an id would be
  scoring an unreadable claim as agreement. A near-miss id is reported, not
  passed over.
- **Treats `memory/README.md` as a restricted surface.** GitHub renders
  tables inside blockquotes and list items, and renders raw HTML tables —
  and the checker's scanner models none of those containers. Instead of
  guessing, it rejects them outright: no blockquote lines, no raw HTML,
  and no pipe lines outside the one index table, because a stray pipe line
  may render as a row, as code, or as prose depending on container context
  the checker cannot see. The file carries exactly one index table, with
  exactly the header `| id | topic | class | observed | summary |`; any
  other table that uses the index column names — reordered, padded with an
  empty cell, or otherwise varied — is rejected, and an entry id appearing
  as a cell of any other table is rejected too, because a reader takes an
  id-keyed row as a trust claim wherever it renders. Prose, headings,
  bullet lists, links written as `[text](url)`, and fenced examples are
  all fine.
- **Table examples belong in fenced code blocks.** Fenced rows are
  documentation, not claims, and the checker skips them. An unterminated
  fence now fails the check in its own right rather than silently
  swallowing the rest of the file. Fences are read the way CommonMark and
  GitHub read them: a backtick fence whose info string contains a backtick
  is not a fence at all — GitHub renders what follows — so the checker
  treats that line as prose too.
- **Never files two rows for one id**, in either order. A forged row placed
  above a valid one is what a human reads; placed below, it is what a
  naive checker compares. Both are the same defect, so both fail.
- **Never files two entries under one id.** The second would shadow the
  first, hiding it from the index and from every check including its own.
- **Before recording an absence**, runs the canary and fills in `surface:`
  and `control:`.
- **When `check_memory.py` reports a stale entry**, re-verifies it or
  supersedes it rather than bumping the date.

Run it yourself any time:

    python3 tools/check_memory.py

## When you disagree with your own memory

Tell the person. An assistant that finds a canonical entry contradicted by
the repo does not resolve that quietly in either direction: it reports the
entry, the evidence, and the disagreement, and asks. Rule 8 of
[`GROUND_RULES.md`](../GROUND_RULES.md) applies to memory too — there is no
prize for guessing.

## Typed memory (store format v2)

A store whose index declares `Store format: memory/v2` carries the typed
layer on the same entry shape (facts-store v2, merged design:
docs/proposals/2026-08-07-facts-store-v2-typed-memory.md). Everything
above still applies; v2 adds, enforced by `python3
tools/check_tracking.py`:

- **The triple**: `subject` / `predicate` / `object` in frontmatter,
  entity ids spelled `<type>:<kebab-slug>` exactly as registered in
  `catalog/ENTITIES.json`; predicates come only from
  `catalog/VOCABULARY.json` (closed — propose, don't mint). A fact with
  no triple shape uses `predicate: notes` with only a subject.
- **`store: repo|agent`**, and the ceiling: an agent store caps at
  `verified` — canonical never originates from an agent.
- **A closed key set**: unknown frontmatter keys fail; free text may not
  smuggle governed-field assertions (`class:`, `store:`, grants,
  triples) — those live only in frontmatter where they are validated.
- **The temporal stale test** (ask all three before writing):
  1. Does this describe steady state, or a moment that will pass?
  2. If it will pass, when does it stop being true — and did you write
     `valid_from`/`invalid_at` instead of a date buried in prose?
  3. Would a reader six months from now be misled by this entry as
     written?
  An entry whose body matches a temporal marker (`for now`, `pending`,
  `workaround`, … — the closed list lives in `catalog/VOCABULARY.json`)
  must carry the validity window; a plain date in prose is not a bypass.
- **Citations**: fact and decision addresses (live examples:
  fact:mem-001, decision:hyperbench-public-release) are the only
  citable address kinds; decisions resolve through
  `catalog/DECISIONS_INDEX.json`. Every citation in a tracked live file
  must resolve — a pointer that silently 404s is an incident, not a
  style issue.
- **Index**: three more columns (`subject | predicate | object`) so all
  three triple positions answer from the index alone, and a
  `Last verified` block (Date / Commit / Evidence) anchoring absence
  claims — absent block is a warning, inconsistent block is an error.
