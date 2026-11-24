# Review records

One folder per cross-family review, newest first. Each folder holds the reviewer's `summary.md` and a path-free
`receipt.md`. The reviewer's activity logs and wrapper state stay on the reviewing host (`GROUND_RULES.md` rule 3).
The route is set in `AGENTS.md`, "Cross-family review route".

## 2026-11-24: PR #1 HyperBench enrollment, round 3

- Record: [summary](patch-review-2026-11-24T07-56-50Z-hyperbench-enrollment-r3/summary.md),
  [receipt](patch-review-2026-11-24T07-56-50Z-hyperbench-enrollment-r3/receipt.md)
- The committed summary is the reviewer's text, unchanged (it holds no machine paths).
- Reviewed head `2ef4cf4`, tree `7b46e78`, the delta `1a852c0..2ef4cf4` that answers round 2. Reviewer
  `deepseek-v4.1-flash` via OpenCode Go at `high`, explicit selection, matrix 4.14.0.
- Verdict: PASS. The round 2 finding and both observations are closed; the redacted round 2 summary differs from
  the original by exactly the two stated lines; the licence fix matches upstream `LICENSE` at `c106531`. Two
  informational notes, no action taken:
  - The ignore rules match one folder level under `.hyperreview/`, which is where the launcher writes today.
  - The manifest's list of starter files does not name `STARTER_MANIFEST.json` itself; the list is descriptive.

## 2026-11-24: PR #1 HyperBench enrollment, round 2

- Record: [summary](patch-review-2026-11-24T07-44-22Z-hyperbench-enrollment-r2/summary.md),
  [receipt](patch-review-2026-11-24T07-44-22Z-hyperbench-enrollment-r2/receipt.md)
- The committed summary is the reviewer's text with two machine paths replaced by `<work-root>` and
  `<hub-clone>` (`GROUND_RULES.md` rule 3). Nothing else was changed.
- Reviewed head `1a852c0`, tree `fbaa906`, the delta `6d523f8..1a852c0` that answers round 1. Reviewer
  `deepseek-v4.1-flash` via OpenCode Go at `high`, explicit selection, matrix 4.14.0.
- Verdict: PASS-WITH-CONDITIONS. All four round 1 findings closed, and the committed round 1 summary is
  byte-identical to the original. New finding and dispositions:
  1. Medium (latent): the review wrapper writes `run_state.json`, `launcher.txt` and `launcher.out` into the review
     folder, none of them ignored, and `check_data_boundary.py` does not match machine paths. Fixed: `.gitignore`
     ignores the three files under `/.hyperreview/*/`; `activity.log` was already covered by `*.log`.
  - Observation: the manifest's list of starter files left out `GROUND_RULES.md`. Fixed.
  - Observation: the `ragesaq-001` node said "the commit after 6d523f8" without a hash. Fixed: it names `1a852c0`.
  - Found by the author, not the reviewer: `GROUND_RULES.md` rule 4 called the upstream licence GPL. Allegiance is
    MIT (Microsoft relicensed it in 2017). Fixed.

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
