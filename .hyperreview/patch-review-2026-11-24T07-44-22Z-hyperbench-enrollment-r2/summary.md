# Patch review r2 (light delta): HyperBench enrollment, AllegianceVR PR #1

- Repository: ragesaq/AllegianceVR, branch `port/hyperbench-enrollment`, PR #1
- Reviewed HEAD: `1a852c0a8708d39c3ebada46df3a31831b65aa57`
- Reviewed tree: `fbaa90616c44c43ca3b78fbf7ebab77561217919` (`git write-tree` matched the frozen value; the only untracked entry was this review folder)
- Delta range: `6d523f869e0574e85addb94074ae394f8069bbc2..1a852c0a8708d39c3ebada46df3a31831b65aa57` (9 files, +127/-8)
- Reviewer: DeepSeek family, `deepseek-v4.1-flash` through OpenCode Go, effort `high` (reviewer-parity matrix 4.14.0, sha256 `74618f22fd72f6a27ed86db1298fd387068118d3faab415a79604b60c8a63267`)
- Authoring family: Anthropic/Claude (Port), so this is a cross-family review
- Date: 2026-11-24

## Verdict: PASS-WITH-CONDITIONS

All four round 1 findings are closed, the committed round 1 summary is byte-identical to the original, and the four checkers pass. One new latent data-hygiene risk arrives with the new `.hyperreview/` convention (finding 1): the launcher artifacts that the README says stay on the host are not ignored, and the data-boundary tripwire would not catch them. That is a one-line guard, not a blocker.

## Round 1 dispositions

### 1. Manifest omitted `memory/README.md` from `localModifications`: CLOSED

`STARTER_MANIFEST.json:38` now lists `memory/README.md`, and `:39` lists `tools/check_node_loss.py`. I hashed the seven files the `about` says came from `templates/repo-starter/` at `e98c318` (`STARTER_MANIFEST.json:2`). Six differ from the starter and all six are listed: `AGENTS.md`, `DAG.json`, `LEDGER.md`, `memory/README.md`, `memory/CANARY.md`, `knowledge/README.md`. `knowledge/TEMPLATE.md` is blob-identical to the starter (`777f4a9a`) and is correctly absent. Every differing file is listed and the unchanged one is not. The provenance claim is supported: every local copy is much closer to the starter than to the hub root (changed lines vs starter / vs hub root: `AGENTS.md` 133/213 vs 134/599, `DAG.json` 41/8 vs 26/713, `LEDGER.md` 2/0 vs 2/37, `memory/README.md` 3/3 vs 15/29, `memory/CANARY.md` 2/2 vs 7/8, `knowledge/README.md` 4/6 vs 88/23). The starter `memory/README.md` differs from the local file only by the two index rows and the closing sentence, a seeded-then-filled shape. `GROUND_RULES.md`, also starter-sourced, differs (17/74) and is listed; `RECALL_GLOSSARY.json` differs from the hub root and is listed.

### 2. `DAG.json` rules block says "main": CLOSED by a justified decline

`tools/check_map.py:300` compares `dag.get("rules") != DAG_RULES` for exact list equality, so the rules text is enforced verbatim, not loosely. `DAG_RULES` (`tools/check_map.py:42-84`) is the hub text unchanged; the fork `check_map.py` differs from the hub copy only in the `origin/master` argument line. `DAG.json:15` therefore still says to take main's version, and `AGENTS.md:39-40` now says the rules block is the hub's canonical text and that `main` there means this fork's default branch, `master`. That note is accurate.

### 3. `tools/check_node_loss.py` defaulted to `origin/main`: CLOSED

The fork copy differs from the hub only in the docstring comment and the default at `tools/check_node_loss.py:147`, both now `origin/master`. Running the script from the worktree root prints `OK (origin/master is reachable and has no DAG.json ...)` and exits 0, so the direct invocation a maintainer is likely to make now works.

### 4. Knowledge-note line labels: CLOSED

Re-opened at `c106531`: `src/engine/device3d.cpp:530` is `SetTransform(D3DTS_PROJECTION, ...)` inside `GenerateProjectionTransform` (`:483`), and `:553` is `SetTransform(D3DTS_VIEW, ...)` inside `GenerateViewTransform` (`:533`). `src/engine/D3DDevice9.cpp:310` is `CreateDevice`, whose body closes at `:600`, so the new `:310-600` range is correct, and `:119` is still `Direct3DCreate9`.

### Committed round 1 summary: byte-identical

The original in the round 1 worktree and the committed copy both hash to SHA-256 `80D040587C0409D41C23780DB571C0B32386ED599E9A826ED677E1847BF90472`; `git hash-object` and `HEAD:.hyperreview/patch-review-2026-11-24T07-33-36Z-hyperbench-enrollment-r1/summary.md` are both blob `17ccab4e`. The claim holds.

## New findings

### 1. Medium (latent): `.hyperreview` launcher artifacts are not ignored, although the new README says they stay on the host

`.hyperreview/README.md:3-4` says the reviewer's activity logs and wrapper state stay on the reviewing host, and `GROUND_RULES.md:10-12` forbids machine paths in this public repo. Only `activity.log` is actually excluded, and only accidentally, by the upstream `*.log` rule at `.gitignore:67`. The launcher writes `run_state.json`, `launcher.txt` and `launcher.out` into the same review folder; `git check-ignore` returns no match for all three and exits 1, and the round 1 worktree already holds all four files untracked.

Failure scenario: a later session in a review worktree commits its record with `git add -A` or `git add .hyperreview`. `run_state.json` then carries absolute `<work-root>\...` paths and the full reviewer prompt, and `launcher.txt` carries the wrapper path, straight into the public repository. The tripwire does not stop it: `tools/check_data_boundary.py:26-33` matches key and SSN shapes only, not filesystem paths, so `check_data_boundary` would still print OK. The PR would be public before anyone noticed.

Fix: add the wrapper artifacts to `.gitignore`, for example `/.hyperreview/*/run_state.json`, `/.hyperreview/*/launcher.txt` and `/.hyperreview/*/launcher.out`. `activity.log` is already covered by `*.log`. A `.hyperreview/**/` block with two negations would also work. The README can state the rule, but the ignore file is what enforces it.

## Observations, not findings

- The `about` parenthetical list of seeded starter files omits `GROUND_RULES.md`, which is also in `templates/repo-starter/` and is listed under `localModifications`. The sentence does not claim to be exhaustive and reconciliation safety is unaffected, so this is a completeness nit.
- `DAG.json:47` says "the commit after 6d523f8" without pinning that commit's hash, while rule 2 asks a live node to pin exact state. The PR and branch are pinned, so the head is resolvable; no consequence found.
- The receipt values match the round 1 launcher record: route `codex:5aa43f19840ce08ad126b5b3`, binding `exact`, route lock on, return code 0, assurance `independent_cross_family`, tier `full`, start `07:33:36Z`, finish `07:41:18Z`. The file is path-free, and `GROUND_RULES.md` rule 3 is the right citation for keeping the logs out.

## Verified by execution

Target and content: `git rev-parse HEAD`, `git write-tree`, `git status --short` (only the r2 artifact directory untracked), `git show --stat`, `git diff --name-status 6d523f8 HEAD`, `git show c106531:<path>` at `device3d.cpp:478-557` and `D3DDevice9.cpp:112-600`.

Provenance: `git hash-object` against `git -C <hub-clone> rev-parse e98c318:templates/repo-starter/<path>` for the eight starter-derived files, `git diff --no-index --numstat` against both the starter copy and the hub root copy, and `Compare-Object` of `tools/check_map.py` and `tools/check_node_loss.py` against their hub versions.

Line endings and upstream reach: `git ls-files --eol` shows `i/lf` for all nine changed paths and `i/lf w/lf attr/text eol=lf` for the three committed `.hyperreview` files; `git check-attr` confirms `text: set, eol: lf`; `git ls-tree -r c106531` has no `.hyperreview` path, so the new pattern cannot touch upstream.

Checkers, exit 0 each, from the worktree root: `check_data_boundary.py` OK; `check_map.py` OK with the expected `line-endings` floor-module warning; `check_memory.py` OK with the two expected `recorded-by 'port' has no people/ folder` warnings; `check_node_loss.py` OK on its new default base.

Records and identity: `git ls-tree -r HEAD -- .hyperreview` shows exactly the three committed files; SHA-256 and blob comparison of the round 1 summary; `git show -s --format` confirms author and committer are `Port <323790917+psiclawops-port@users.noreply.github.com>`. A pattern scan of every added line found only that allowed noreply address.

## Verification limits

- No network or PR access: I could not confirm that the round 1 result was also posted as a PR comment, which `AGENTS.md` (review gates) requires, nor read the PR discussion.
- `tools/check_tracking.py` was not in the permitted verification set and was not run; `check_map.py`'s catalog-skipped check passed in its place.
- `tools/recall.py` was not run, as instructed, because it writes a cache into the worktree.
- The provenance judgement (seeded from `templates/repo-starter/`) rests on blob distance, not on a recorded seed log; it is consistent for all eight starter files compared.
- Line numbers apply to `c106531` only. This review does not build the game or test a headset.