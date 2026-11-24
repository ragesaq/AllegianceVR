# Review records

One folder per cross-family review, newest first. Each folder holds the reviewer's `summary.md` and a path-free
`receipt.md`. The reviewer's activity logs and wrapper state stay on the reviewing host (`GROUND_RULES.md` rule 3).
The route is set in `AGENTS.md`, "Cross-family review route".

## 2026-11-24: PR #1 HyperBench enrollment, round 1

- Record: [summary](patch-review-2026-11-24T07-33-36Z-hyperbench-enrollment-r1/summary.md),
  [receipt](patch-review-2026-11-24T07-33-36Z-hyperbench-enrollment-r1/receipt.md)
- Reviewed head `6d523f8`, tree `c64ce5d`. Reviewer `deepseek-v4.1-flash` via OpenCode Go at `high`, explicit
  selection, matrix 4.14.0.
- Verdict: PASS-WITH-CONDITIONS. Findings and dispositions:
  1. Medium: `memory/README.md` diverged from its source but was missing from the manifest's `localModifications`.
     Fixed: listed, and the manifest now says the starter files came from the hub's `templates/repo-starter/` and the
     store is `memory/v1`. The finding's failure story compared against the hub's own v2 index rather than the
     starter template, but the missing entry was real.
  2. Low: the `DAG.json` rules block says "take main's version". Not changed in `DAG.json`, because `check_map.py`
     requires the hub's canonical rules text verbatim (the edit made it fail). `AGENTS.md` now says that `main` in
     the rules block means `master`.
  3. Low: `tools/check_node_loss.py` defaulted to `origin/main`. Fixed: defaults to `origin/master`, listed in
     `localModifications`.
  4. Low: survey note cited function entry lines for the `SetTransform` calls. Fixed: `:530` and `:553`, and the
     `CreateDevice` range is now `:310–600`.
