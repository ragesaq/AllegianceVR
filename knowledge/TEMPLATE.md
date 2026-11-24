# <Subject — the thing this note is about>

<!-- Copy this file to knowledge/<subject-in-lower-case>.md, fill it in,
and add a row to knowledge/README.md in the same change. Delete a heading
that genuinely has nothing under it rather than writing "N/A". The rules
behind this shape are docs/KNOWLEDGE_NOTES.md in this repository, section
Normative. -->

**Owner:** <person> · **Started:** <YYYY-MM-DD> · **Last reviewed:**
<YYYY-MM-DD> · **Review by:** <YYYY-MM-DD>

**Status:** <in progress | in use | superseded by \<note\>>

## What this answers

*One short paragraph. The question a person arrives with — not a summary
of the product. "Whether and how we can turn on <thing> for <who>, and
what it costs us" is a question. "An overview of <thing>" is not.*

## Current state

*What is true now, in a few lines, each claim marked as below. Rewrite
this section whenever it changes; the history goes in the timeline. A
disputed value says so and points at its row under "Disagreements between
sources".*

## How it applies here

*The most valuable section, and the one that exists nowhere else. What is
true about **our** environment that changes how this product behaves.
Mark every claim:*

- *(read)* — from the vendor's documentation or a support case. **Link
  it.** True until they change it, with no warning when they do.
- *(observed YYYY-MM)* — we did it here, on that date, at a stated scale.
- *(derived)* — reasoned from the above. Say what it rests on. Every
  rationale and "why" cell below is a derived claim.
- *(decided YYYY-MM by <authority>)* — somebody chose this, and could
  have chosen otherwise. Evidence supports a choice; it does not make
  one, so a decision never wears the *(derived)* label.

*Example of the shape:*

> Policies apply per-location rather than per-group *(read —
> \<link to vendor doc\>)*. Our pilot group spans two locations
> *(observed 2026-08, pilot of ~40 accounts)*, so a single policy cannot
> cover it *(derived — from the two claims above)*. We run one policy per
> location rather than splitting the pilot group *(decided 2026-08 by
> \<owner\>)*.

*Four sentences, four provenance forms, and they do not overlap: what the
vendor says, what we saw, what follows, and what we chose. The fourth
could have gone the other way.*

## What we decided

*Each decision: what we chose, what we rejected, and what decided it. A
decision written alone reads as the only option there was, and the next
person re-derives the comparison.*

| Decision | Chosen | Rejected | Why *(derived — what it rests on)* | Decided by | Decided | Last reconciled |
|---|---|---|---|---|---|---|
| | | | | | | |

*The last three columns are not bookkeeping. Without "Decided by" and
"Decided" the "why" column reads as a proof that the choice was forced,
when a choice is something somebody with authority made and could have
made differently. "Last reconciled" is when the row was last checked
against its source; it is a different event from the decision.*

### What we cover, and why each thing is on the list

*When the subject is the same decision made many times over — per data
type, per policy, per environment — use this table rather than
paragraphs: prose hides an omission, a table shows it. Include rows for
what was deliberately **left out**, with the reason; those are often the
most valuable rows here, because they stop the same proposal being
re-litigated. Reconcile against the live system periodically and date the
row — the platform is authoritative for what is configured, this table is
authoritative for why.*

*Metadata about what we protect is the safe layer and the useful one: the
row goes here, the pattern or identifier itself never does.*

| What is covered | Why it is in scope *(derived)* | Where it applies | How we act on it | Decided by | Decided | Last reconciled |
|---|---|---|---|---|---|---|
| | | | | | | |
| *(not covered)* | *why we left it out* | | | | | |

*`Decided` and `Last reconciled` are different events and both are
required. A choice made a year ago and checked against the live system
this morning is current as configuration and a year old as a decision —
one column cannot say both, and merging them makes an old decision look
freshly made.*

### Changes to earlier decisions

*When a decision reverses, keep the old one here with its date and the
reason it changed. Someone will ask why the configuration looks like
this.*

## What we tried that did not work

*The section that saves the most time and gets written the least. What
looked reasonable, what actually happened, what it cost (time, runs, a
broken state) and — where you know it — why. "We do not know why" is a
legitimate and useful entry.*

## Traps

*Things that look right and are not. For each: what it looks like, what
is actually true, and the sign that tells them apart.*

| Looks like | Actually | How to tell |
|---|---|---|
| | | |

## Disagreements between sources

*When two sources give different figures or accounts for the same thing,
keep both here. Do not pick one because it is newer or rounder. A row is
settled only by a check that names its evidence; then fill in the last
column, add a timeline line, and keep the row.*

| What | Figure or account | Source *(provenance)* | Date | Settled by |
|---|---|---|---|---|
| | | | | *open* |

## Operational evidence, when relevant

*Keep this section only when the note will help a future operator diagnose
or perform the same kind of work. Preserve the provenance labels above.*

- **Symptom and scope:** affected behavior, applicable environment/version
  and tested scale, without sensitive identifiers or raw payloads.
- **Evidence:** the permitted observation and its source/revision/date.
- **Remedy or workaround:** distinguish what was actually tried from a
  suggestion; name limitations and exceptions.
- **Verification:** what was checked, the observed result, and what remains
  unconfirmed. An interrupted operation points to its existing work-item
  attempt rather than implying success or safe retry.

*This note provides context, not authorization to run a procedure. Recheck
the current environment and the operation's authority before acting.*

## Open questions

*What is genuinely unsettled, so the next session neither re-derives it
nor mistakes it for decided. Name who could answer it, if anyone can.*

## Timeline

*Dated lines, newest last, one event each: a measurement, a change, a
decision, a reversal. Never edit or remove a line; correct a wrong one
with a later line. "Current state" above must follow from these lines and
what they cite.*

- *YYYY-MM-DD — what happened (provenance; source)*

## Boundary

*What this note deliberately does not contain. Identifiers, patterns,
group names, tenant or policy ids, and document contents stay out —
a note about a data-protection configuration is a description of what
our sensitive data looks like, and this repository is fake-data-only.
Say where the real thing lives instead.*

## Sources

*Links out, not copies in. If a competent stranger could get a sentence
from the vendor's site in a minute, it belongs here as a link rather than
above as prose.*

-
