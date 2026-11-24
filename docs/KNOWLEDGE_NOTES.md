# Knowledge notes — what a session worked out, kept where the team can find it

<!-- ============================ NORMATIVE ============================
     This section is the contract. Everything below the INFORMATIVE
     marker explains it and binds nobody. -->

## Normative

**N1. When a note is written.** Draft a note when authorized work produces
understanding that took real effort, is not already in this repository,
and would otherwise be rebuilt by a colleague or by the same operator
later. Capture it **when the finding lands, not at session end**. Extend
the existing note on a subject rather than opening a second one. Routine
in-scope, permitted observation capture needs no separate permission
question. Publication and acceptance still follow the repository's change
and approval rules; capture does not grant new scope or canonical status.

**N2. Every claim carries its provenance.** Four forms, and each claim
takes exactly one:

| Form | Means | Carries |
|---|---|---|
| *(read)* | stated by the vendor's documentation, a support case, or equivalent | a link |
| *(observed YYYY-MM)* | done in this environment, at a stated scale | the date and the scale |
| *(derived)* | a conclusion reasoned from the other two | what it rests on |
| *(decided YYYY-MM by \<authority\>)* | a choice somebody with the authority made | who chose, and when |

A conclusion drawn from vendor facts plus local observation is
**derived** — it is neither read nor observed, and recording it as either
is a defect. Rationales, exclusions, and every "why" cell are derived
claims and say what they rest on.

**A decision is not a derivation.** Evidence can support a choice without
forcing it, and the two must not share a label: when they do, a
preference or a risk appetite gets presented as an inevitable deduction,
and a later reader cannot tell what the evidence established from what
somebody chose. A decision carries **who decided and when**; the
derivation that informed it is a separate, adjacent claim.

**N3. Do not restate the vendor's documentation.** Where a competent
stranger could obtain the sentence from the vendor in a minute, link it
instead of copying it.

**N4. Every decision records what it rejected.** Name the alternatives
weighed and what decided it. When a decision reverses, the prior decision
is kept with the date and the reason it changed; it is never silently
replaced. A decision recorded in a table carries both dates N5 requires,
when it was decided and when the row was last reconciled against its
source, whether or not the decision repeats.

**N5. Repeated decisions go in a table, not in prose.** Where the same
decision recurs — per data type, per policy, per environment — record it
with fixed columns: what is covered, why it is in scope, where it
applies, how it is acted on, **who decided and when they decided**, and
**when the row was last reconciled**. **Rows for what was deliberately
excluded are required**, with the reason.

**The two dates are different events and both are required.** A choice
made a year ago and checked against the live system this morning is
current *as configuration* and a year old *as a decision*; collapsing
them into one column makes an old decision look freshly made, which is
exactly the confusion N2 separates decisions from derivations to
prevent.

**N6. The platform is authoritative for configuration; the note is
authoritative for rationale.** Where a note and the live system disagree
about what is configured, the system wins and the row is corrected.
Nothing in the note may be treated as evidence of current configuration.

**N7. Every note names an owner and a review date.** Past that date the
note is **unconfirmed** and says so; it is not thereby wrong. This is a
convention a person keeps — no check in this repository enforces it.

**N8. Shapes and decisions only.** A note about a data-protection
configuration is a description of what the operator's sensitive data
looks like. Patterns, identifiers, group names, tenant or policy ids, and
document contents are never recorded; the shape and the decision are.
**Stop and ask** before recording any of them.

**N9. A note that is not in the index does not exist.** Add its row to
`knowledge/README.md` in the same change that adds the note. A memory
entry about a note is a pointer carrying its trust class, never a
summary that can drift from it.

**N10. Operational notes are context, not authority to execute.** Where
relevant, record the symptom, applicable environment and version, evidence,
remedy or workaround, how its outcome was verified, and known limits.
Include the owner and review date required by N7. Distinguish an observed
fix from an untested suggestion. An old procedure does not authorize a
new operation, prove the present configuration, or make a retry safe.
An unresolved prior attempt remains unresolved until its result is checked.

**N11. Publication state stays visible.** Publish the note, its index row
and affected work-item update together through the authorized workflow.
Local-only, pushed/unmerged, accepted and superseded are different states.
Do not claim a colleague received a note merely because it was saved.

**N12. Current state is rewritten; the timeline is only appended.** A note
whose subject changes over time keeps two sections. **Current state** says
what is true now, with its provenance, and is rewritten whenever that
changes. **Timeline** is dated lines, newest last, each one event: a
measurement, a change, a decision, a reversal. A timeline line is never
edited or removed; a wrong one gets a later line that corrects it. Current
state must be derivable from the timeline and the sources it cites. Where
the two disagree, the timeline and its sources win and current state is
rewritten. For what is configured, N6 still decides: a check of the live
system is recorded as a timeline line, and current state follows it.

**N13. A disagreement between sources is kept until a check settles it.**
When two sources give different figures or accounts for the same thing,
record each in the note's **Disagreements between sources** table: the
figure, its source and provenance form, and its date. Do not choose one
because it is newer, rounder or more convenient. A disagreement is settled
only by a check that names its evidence; record the result in the row and
as a timeline line, and keep the row. Until then, current state says the
value is disputed and names the row.

**N14. Failed attempts and traps are recorded with what they cost.** A
failed attempt says what was tried, what happened, what it cost (time,
runs, a broken state) and, if known, why. "We do not know why" is a valid
entry. A **trap** is something that looks right and is not: record what it
looks like, what is actually true, and the sign that tells them apart. An
open question names who could answer it, if anyone can.

<!-- =========================== INFORMATIVE =========================== -->

## Why this surface exists (informative)

The most expensive thing an assistant produces is usually not code. It is
understanding: how a complicated product actually maps onto *this*
environment, which configuration was settled on and why, and what was
tried that turned out not to work. That gets built over hours of
conversation and then, by default, it ends when the session does. The
next person asks the same questions and pays the same hours — and so does
the same person, months later, having forgotten.

## Where this sits among the other surfaces (informative)

| Surface | Holds | Read by |
|---|---|---|
| `memory/` | short typed observations, each with a trust class | the assistant, at session start |
| `GOAL.md` | what this project is for and how it is judged | everyone |
| `DAG.json` / `LEDGER.md` | work in flight / work finished | everyone |
| `archive/` | dated snapshots of documents that live elsewhere | everyone |
| **`knowledge/`** | **worked understanding of a subject** | **people, and assistants** |

Memory rule 7 sends long-form material out of memory — *"longer means it
is a document, not a memory"* — and `knowledge/` is the destination it
names. Memory is what the *assistant* must carry between sessions, kept
small enough to actually be read. A note is what a *person* needs in
order not to redo the work, and may be as long as the subject requires.

## Why provenance is marked (informative)

The read/observed/derived split (N2) exists because the three age
differently. A read claim is true until the vendor changes it, with no
notification when they do. An observed claim is the part that exists
nowhere else on earth, and it is why the note is worth keeping — but a
propagation time means nothing without the date and the scale of the
thing that propagated. A derived claim depends on both, so it can be
invalidated by a change to either, and the only way to see that is if it
says what it rests on.

When a vendor changes something, a marked note shows exactly which
sentences just became suspect. An unmarked one has to be re-derived
whole, which is the cost the note existed to avoid.

## Why repeated decisions go in a table (informative)

Most operational subjects are not one decision. They are the same
decision made many times over. Written as prose that shape has a specific
failure: **paragraphs hide an omission, a table shows it.** Five
paragraphs about five things never reveal that a sixth was never
considered by anyone; five rows with a visible gap do.

The exclusion rows (N5) are frequently the most valuable in the note.
*"We deliberately do not cover \<thing\>, because \<reason\>"* is the
sentence that stops the same proposal being re-litigated every few
months.

An inventory looks like it violates N3 and does not. The platform's own
console is authoritative for what is currently configured and completely
silent on *why* — no admin interface records the risk assessment, the
regulation, or the argument that made the scope stop where it stopped.
The table carries the half the platform cannot, which is also why N6
points the two claims in opposite directions.

## Why the boundary is tighter here (informative)

Ground rule 1 governs this repository: no restricted content, no
exceptions. Notes test it hardest, because their subject is frequently
the operator's own configuration.

There is a happy coincidence in N8 worth naming, because it is why this
surface can exist in a fake-data-only repository at all. Metadata *about*
what you protect is exactly the layer that is both safe to commit and the
layer that streamlines the next operation. *"We detect our internal
account-number format across mail and files, because of \<the contractual
driver\>, decided by \<owner\> in \<month\>"* is a decision record. The
pattern that matches those account numbers is the sensitive thing itself.
Write the row, never the rule.

## Why current state and a timeline (informative)

A note that is only edited in place loses its history: the reader sees the
latest figure and not that it replaced two others. A note that is only
appended becomes a log nobody can read quickly. N12 keeps one short,
rewritten summary for the reader in a hurry and one append-only record for
the reader who needs to know how it got there. The timeline is also what
makes a wrong current-state line correctable, because the line can be
rebuilt from what the timeline cites.

## Why disagreements are kept (informative)

Work spread over many sessions produces conflicting figures: a value
measured three times on three setups, a document that says one thing and a
run that shows another. Picking one silently is how a note becomes
confidently wrong. A late enrollment of one working repository found 22
such disagreements between its sources *(observed 2026-11, one backfill)*.
A kept disagreement costs one table row and tells the next reader exactly
what to check.

## Where the template lives (informative)

Copy the note template that ships beside the index and fill it in:

- in a **seeded or adopting repository**: `knowledge/TEMPLATE.md`
- in the **program hub**: `templates/repo-starter/knowledge/TEMPLATE.md`,
  which is the copy that gets seeded; the hub's own root `knowledge/`
  holds the hub's notes and its index.

Drop a heading when the subject genuinely has nothing under it, rather
than writing "N/A" under all of them.
