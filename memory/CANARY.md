---
id: mem-canary
topic: retrieval-canary
class: verified
observed: 2026-11-24
recorded-by: port
token: MEMORY-CANARY-7F3A
evidence: memory/README.md
---

# Retrieval canary — do not delete, do not make interesting

This entry exists to be found. Its only job is to prove that a search of
the memory store actually works before anyone trusts a search that came
back empty.

The fixed token is `MEMORY-CANARY-7F3A`.

How to use it: whenever you are about to say "there is no record of X",
first run the same search for `MEMORY-CANARY-7F3A`.

- Canary found: your method works. An empty result for X is a real absence
  of X **on the surface you searched**. Say which surface that was.
- Canary not found: your method is broken. You have learned nothing about
  X. Fix the search, and do not record an absence.

The fact recorded here is deliberately boring and permanent: this
repository keeps its durable notes in `memory/`, indexed by
`memory/README.md`.
