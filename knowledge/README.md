# knowledge/ — what we worked out, so nobody works it out twice

This folder holds the understanding this project built up: how a
complicated subject actually maps onto our environment, what we decided
and why, and what we tried that did not work. It is written for **people**
— your assistant maintains it, you and your colleagues read it.

It exists because that understanding is otherwise expensive and invisible.
It gets built over hours of conversation with an assistant and then
disappears when the session ends, so the next person asks the same
questions and pays the same hours.

## What belongs here, and what does not

| If it is… | It goes in… |
|---|---|
| a short thing the assistant must remember between sessions | `memory/` |
| worked understanding of a subject, for humans | **here** |
| what we are building and why | `AGENTS.md` (opening section) |
| work in flight, or work finished | `DAG.json`, `LEDGER.md` |

A note here and a memory entry are not alternatives. The memory entry is
a one-line pointer carrying its trust class; the note is the content. The
pointer never restates the note, because two copies drift and only one of
them is right.

## The three rules that keep these useful

1. **Say where each claim came from.** *(read)* means the vendor's
   documentation said so — link it, and know it is true only until they
   change it. *(observed YYYY-MM)* means we did it here, on that date, at
   a stated scale; those exist nowhere else, and they are why the note is
   worth keeping. *(derived)* means we reasoned it out from the other two
   — every rationale and "why" cell is derived, and says what it rests
   on. A conclusion recorded as an observation is a defect: it will
   outlive the facts it was built from without anyone noticing. And
   *(decided YYYY-MM by \<authority\>)* is its own form, because a choice
   is not a deduction — evidence can support a decision without forcing
   it, and blurring them presents somebody's judgement as inevitable.
2. **Do not restate the manual.** If a stranger could get the sentence
   from the vendor's site in a minute, link it instead. A copied
   explanation goes stale silently and nothing here will contradict it.
3. **Record the option you rejected.** A decision written alone reads as
   the only possibility, and the next person re-derives the comparison
   you already did. Where the same decision recurs — per data type, per
   policy, per environment — put it in a table with a row for each,
   including the ones deliberately left out: paragraphs hide an omission,
   a table shows it. Each row records **when it was decided** and **when
   it was last reconciled** against the live system; those are different
   events, and one column cannot say both.

A note about something that changes also keeps a short **current state**,
rewritten as it changes, and an append-only **timeline** of what happened.
It keeps **disagreements between sources** side by side until a check
settles them, and records **failed attempts** with their cost and **traps**
with the sign that gives them away.

The full rules are `docs/KNOWLEDGE_NOTES.md` **in this repository** —
copied in beside this folder when the repo was seeded, and host-owned
from that point on. Its `## Normative` section is the contract; the rest
explains it. Later hub changes reach this copy only by an intentional
reconciliation, never automatically.

Use the repository's `hyperbench-lifecycle` skill when a useful finding
lands and when preparing a handoff. Draft permitted observations during
the work, then publish the note, its index row and affected work record
in the same PR. Local-only, pushed/unmerged and accepted are different
states. A runbook helps a future authorized operation; it never supplies
the authority to execute one. The optional operational section of
`TEMPLATE.md` captures environment, evidence, remedy and verification.

## Two things to be careful about

**These notes perish.** Nothing in this repository goes red when a vendor
changes a default, so each note carries an owner and a review date. Past
that date a note is not wrong, it is *unconfirmed* — and it should say so
rather than presenting last year's behaviour as current. This is a habit
a person keeps, not a check a tool runs.

**The data rule bites hardest here**, because these notes are often about
our own configuration — and a note about a data-protection setup is a
description of what our sensitive data looks like. Write shapes and
decisions, never the patterns, identifiers, group names, or document
contents themselves. Once those are committed they cannot truly be
removed.

## Notes

| Subject | What it answers | Owner | Last reviewed |
|---|---|---|---|

| [OpenXR port survey](openxr-port-survey.md) | Where VR attaches to the engine, which rendering path, risks, and what the VR-modding wizard workflow contributes | ragesaq | 2026-11-24 |

Copy [`TEMPLATE.md`](TEMPLATE.md) to `knowledge/<subject>.md` for a new subject, and add its row here in the same change.
