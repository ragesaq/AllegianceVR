---
id: mem-001
topic: hyperbench-scope
class: verified
observed: 2026-11-24
recorded-by: port
evidence: STARTER_MANIFEST.json
---

# HyperBench here is memory, decisions and orientation only

The operator asked for only the memory, decision and orientation parts of
HyperBench in this fork, not its wider rule set (operator direction in the
enrollment session, 2026-11-24). `STARTER_MANIFEST.json` records the result:
adopted `memory`, `work-map`, `knowledge` and `lifecycle-skill`; everything
else skipped. Decisions are recorded as `(decided ...)` rows in `knowledge/`
notes and as memory entries like this one.

Line endings were skipped for a separate reason: the hub checker wants every
tracked file LF, and this fork keeps upstream files byte-identical so
upstream merges stay clean. `check_map.py` warns that `data-boundary` and
`line-endings` are floor modules, and `check_memory.py` warns that a
`recorded-by` name has no `people/` folder (the `people` module is
skipped). Those warnings are expected here and do not fail the checks.
