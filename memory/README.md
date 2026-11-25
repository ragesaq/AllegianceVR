# Memory index — read this at session start

This is the index of what this project remembers between sessions. It is
deliberately short: an assistant only truly has the memory that fits in
its reading budget, so this index stays under 20,000 bytes and the detail
lives in the entries beside it.

The rules for writing and trusting these entries are the program's memory
protocol (`docs/MEMORY_PROTOCOL.md` in the hub, copied in beside this file
when this repo was seeded). The short version: an entry records what was
*observed*, every entry says how far it can be trusted, and only a person
can mark something `canonical`.

## How to read the class column

- `inferred` — an assistant worked it out. Treat as a lead, not a fact.
- `witnessed` — seen first-hand, but the proof was not kept. Also a lead.
- `verified` — checked against a named artifact on the date shown.
- `canonical` — the program decided it. A person granted it, and it expires.

If any entry disagrees with what you can see in the repo right now, the
repo wins. Report the disagreement and supersede the entry.

## Entries

| id | topic | class | observed | summary |
|---|---|---|---|---|
| mem-001 | hyperbench-scope | verified | 2026-11-24 | Adopted scope (memory, map, knowledge, recall with vectors) and the two-agent rules, at operator direction |
| mem-002 | renderer-d3d9-win32 | verified | 2026-11-24 | Fixed-function D3D9, Win32-only build; OpenXR needs interop; see the survey note |

Add a row here in the same pull request that adds the entry file; `tools/check_memory.py` fails if the index and the store drift apart.

## Before you say "there is no record of that"

Search for `MEMORY-CANARY-7F3A` first. It lives in
[`CANARY.md`](CANARY.md) and it is always there. If your search cannot
find the canary, your search is broken and any empty result you got proves
nothing.
