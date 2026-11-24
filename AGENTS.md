# AGENTS.md: how agents keep track of work in AllegianceVR

AllegianceVR is the operator's fork of [FreeAllegiance/Allegiance](https://github.com/FreeAllegiance/Allegiance), the
open-source space combat game. The goal of the fork is a VR client built on OpenXR. The fork belongs to the
operator, **ragesaq**. Codex, Claude Code and any other agent read this file.

This repository uses only the memory, decision and orientation parts of HyperBench (hub: `PsiClawOps/hyperbench`,
taken at commit `e98c3185`, HyperBench 0.43.0). [`STARTER_MANIFEST.json`](STARTER_MANIFEST.json) records what was
adopted and what was skipped.

## Where things are kept

- **Work in flight:** [`DAG.json`](DAG.json), one node per piece of work, ids `<owner>-<number>`. Its `rules` block
  is the contract. Update a node's `status`, `next` and `updated` in the same PR as the work.
- **Finished work:** [`LEDGER.md`](LEDGER.md), one append-only line per node that reaches `done`. Node `ragesaq-000`
  stands for all history before adoption (2026-11-24).
- **Short facts to remember:** [`memory/`](memory/README.md), following
  [`docs/MEMORY_PROTOCOL.md`](docs/MEMORY_PROTOCOL.md). Each entry carries its trust class, and what the repository
  shows now beats a memory entry. Before saying "there is no record of X", find `MEMORY-CANARY-7F3A` by the same
  search.
- **Findings and decisions:** [`knowledge/`](knowledge/README.md), following
  [`docs/KNOWLEDGE_NOTES.md`](docs/KNOWLEDGE_NOTES.md). A decision is a `(decided YYYY-MM by <who>)` claim in a note,
  with the rejected options kept beside it.
- **Orientation:** the [hyperbench-lifecycle](.claude/skills/hyperbench-lifecycle/SKILL.md) skill, at task start,
  when something durable is learned, and at handoff.

## Three fork rules

1. **Public repository.** No secrets, personal data, host names or machine paths in files, commits or PRs. Never
   push branches named `next-release` or `antigravity` and never dispatch `.github/workflows/build-and-deploy.yml`:
   that is upstream's Steam deploy.
2. **Keep upstream mergeable.** Remote `upstream` is FreeAllegiance, fetch only. Do not reformat or renormalize
   upstream files. HyperBench files stay out of any PR to upstream.
3. **Changes land by pull request** against `master`, branch `<agent>/<topic>`. The operator merges.

## Checks

Before committing a change to `DAG.json`, `LEDGER.md` or `memory/`:

```powershell
python tools\check_map.py
python tools\check_memory.py
```

`check_map.py` warns that `data-boundary` and `line-endings` are floor modules, and `check_memory.py` warns that
`port` has no `people/` folder. Those warnings are expected: see `memory/mem-001`.
