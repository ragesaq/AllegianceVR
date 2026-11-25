---
id: mem-001
topic: hyperbench-scope
class: verified
observed: 2026-11-24
recorded-by: port
evidence: STARTER_MANIFEST.json
---

# HyperBench scope here, and the two-agent rules

The operator chose the scope in the enrollment session on 2026-11-24, in
three steps: only HyperBench's memory, decision and orientation system, not
its wider rule set; the memory system with vector recall included; and,
because Port and Socket will both work here, the same collaboration rules
the two agents use on the operator's other projects. `STARTER_MANIFEST.json`
records what was adopted and skipped, and `AGENTS.md` carries the rules.

Line endings were skipped for a separate reason: the hub checker wants every
tracked file LF, and this fork keeps upstream files byte-identical so
upstream merges stay clean. `check_map.py` warns that `line-endings` is a
floor module, and `check_memory.py` warns that a `recorded-by` name has no
`people/` folder (the `people` module is skipped). Those warnings are
expected here and do not fail the checks.
