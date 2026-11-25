# Patch review: HyperBench enrollment, AllegianceVR PR #1

- Repository: ragesaq/AllegianceVR, branch `port/hyperbench-enrollment`, PR #1
- Reviewed HEAD: `6d523f869e0574e85addb94074ae394f8069bbc2`
- Reviewed tree: `c64ce5d93ef4246f6eec06feded6461067cdb2fb` (`git write-tree` matched the frozen value; the only untracked entry was `.hyperreview/`)
- Change range: `c1065318bfd6459173fbd2434661c2231d67106e..6d523f86` (4 commits, 27 files, +8194/-1)
- Reviewer: DeepSeek family, `deepseek-v4.1-flash` through OpenCode Go, reasoning effort `high` (reviewer-parity matrix 4.14.0, sha256 `74618f22fd72f6a27ed86db1298fd387068118d3faab415a79604b60c8a63267`)
- Authoring family: Anthropic/Claude (Port), so this is a cross-family review
- Date: 2026-11-24

## Verdict: PASS-WITH-CONDITIONS

The enrollment is accurate about its own departures and safe for upstream. One provenance defect should be fixed before merge (finding 1). Three low-severity wording/default/citation defects are worth a small repair commit but do not change behavior.

## Findings, by severity

### 1. Medium: `STARTER_MANIFEST.json` omits `memory/README.md` from `localModifications`, although that file diverges from the hub copy in a load-bearing way

`STARTER_MANIFEST.json:27-38` lists ten locally changed files. `memory/README.md` is not among them, but its blob differs from `e98c318:memory/README.md` (`f0925f3b` local vs `f7b36c55` hub). The local file drops the hub's `Store format: memory/v2` marker and its eight-column v2 index header (`subject|predicate|object`), and substitutes the v1 five-column header with the two fork rows (`memory/README.md:1-3`, `:28-33`).

The omission matters because `docs/ADOPT_EXISTING_REPO.md` step 3 says `localModifications` "is what makes a later reconciliation safe", and `STARTER_MANIFEST.json`'s own `about` promises that later hub changes arrive "only by an intentional reconciliation PR". 

Failure scenario: a later reconciliation reads the manifest, treats `memory/README.md` as a pristine hub copy, and restores the hub version. The store is then declared `memory/v2` while `adoptionScope.skipped` still names `catalog`, which `tools/check_tracking.py:973-977` treats as a hard failure ("declares 'Store format: memory/v2', which needs the catalog ... adopt the catalog or use a memory/v1 store"). The fork's two index rows are also overwritten, so `check_memory` loses the index and `check_map`/`check_memory` diverge. A reader auditing the manifest also cannot see that the v1 downgrade was deliberate.

Fix: add `"memory/README.md"` to `localModifications`, and optionally say in `about` why the store is v1 (catalog skipped). The same file is correctly absent from `adoptionScope.adopted`, so only the list needs the entry.

### 2. Low: `DAG.json` rule 10 tells an agent to take "main's" version, but this fork's default branch is `master`

`DAG.json:15`: "On a merge conflict here, take main's version and re-apply your addition on top." Every other surface in the change (AGENTS.md, `DAG.json` node text, `.gitattributes` comment, the manifest `about`) says `master`, and `tools/check_map.py:641` now pins `origin/master`. An agent resolving a `DAG.json` conflict literally looks for a `main` branch that does not exist. `AGENTS.md` calls the `rules` block "the contract", so the mismatch should be corrected to `master` in this PR.

### 3. Low: `tools/check_node_loss.py` still defaults to `origin/main`, so a direct run fails on this fork

`tools/check_node_loss.py:147` defaults the base to `origin/main`. The gate is sound as wired: `check_map.py:641` passes `origin/master` explicitly, and I confirmed `check_node_loss.py origin/master` prints OK (base `c106531` has no `DAG.json`, so it is correctly treated as first adoption; nothing to lose). But the hub documents the checker by its own name, and a maintainer who runs `python tools/check_node_loss.py` gets `CANNOT COMPARE ... origin/main` and exit 2 (`measured`), which reads like a broken store rather than an unknown base. Fix: either change the default to `origin/master` and add `tools/check_node_loss.py` to `localModifications`, or state in AGENTS.md that only the `check_map` invocation is supported.

### 4. Low: two knowledge-note line labels point at function entries, not the D3DTS_ tokens they name

`knowledge/openxr-port-survey.md:25` says the view/projection matrices are "set through `src/engine/device3d.cpp:483` (`D3DTS_PROJECTION`) and `:533` (`D3DTS_VIEW`)". At `c106531`, `:483` is `GenerateProjectionTransform` and `:533` is `GenerateViewTransform`; the actual `SetTransform(D3DTS_PROJECTION, ...)` call is at `:530` and `SetTransform(D3DTS_VIEW, ...)` at `:553` (`measured`). The note's own disclaimer ("Re-open the file before relying on a line number") limits the harm, but a reader re-opening `:533` sees no `D3DTS_VIEW`. Fix: cite `:530` and `:553`, or say "entry points `:483` and `:533`, calls at `:530`/`:553`". A related nit: the same table's `CreateDevice` range `:310-499` stops at the `LastChanceCreateDevice` fallback; the function body runs to about `:600`.

## Verified by execution

Target: `git rev-parse HEAD`, `git write-tree`, `git status --short`, `git log --oneline c106531..HEAD`, `git diff --stat/--summary/--name-status`.

Upstream safety: `git ls-tree -r --name-only c106531` has no `docs/`, `tools/` or `.claude/` entry and none of `AGENTS.md`, `GROUND_RULES.md`, `STARTER_MANIFEST.json`, `DAG.json`, `LEDGER.md`, `RECALL_GLOSSARY.json` at the root. Therefore no appended `.gitattributes` pattern matches a path that exists at the base, and `git diff --summary` shows no mode or content change to any other upstream file. The `.gitignore` change is one added line, `/.hyperbench-recall/`. The only upstream bytes touched are `.gitattributes` (append plus the missing final newline that the append requires) and `.gitignore` (append); both are declared.

Line endings: `git ls-files --eol` shows `i/lf w/lf attr/text eol=lf` for all 24 added text files. `git check-attr` confirmed `text: set, eol: lf` for `docs/`, `tools/`, `memory/`, `knowledge/`, `.claude/` samples and the root files, and upstream samples keep `eol: unspecified` (`src/engine/D3DDevice9.cpp`) or `eol: crlf` (`VS2022/Allegiance.sln`). No HyperBench-owned file is uncovered.

Manifest truthfulness: byte comparison against hub `e98c318` found `SAME` for `.claude/skills/hyperbench-lifecycle/SKILL.md`, `docs/KNOWLEDGE_NOTES.md`, `docs/MEMORY_PROTOCOL.md`, `docs/RECALL.md`, `tools/{check_data_boundary,check_memory,check_node_loss,check_tracking,hb_modules,recall,recall_vectors}.py`, and `knowledge/TEMPLATE.md` (identical to `templates/repo-starter/knowledge/TEMPLATE.md`). `DIFF` was found for every listed file (AGENTS.md, DAG.json, LEDGER.md, memory/CANARY.md, knowledge/README.md, .gitattributes, tools/check_map.py, GROUND_RULES.md, RECALL_GLOSSARY.json, .gitignore) and for the one unlisted file, `memory/README.md` (finding 1). `tools/check_map.py` differs from the hub only at `:641` (`origin/master` vs `origin/main`), exactly as `about` claims. `hyperbenchVersion` 0.43.0 matches `hyperbench.version.json` at `e98c318`.

Checkers on this tree (exit 0 each): `check_data_boundary.py` OK; `check_map.py` OK with the expected `line-endings` floor-module warning; `check_memory.py` OK with the two expected `recorded-by 'port' has no people/ folder` warnings; also `check_tracking.py` OK (store is v1, so it adds nothing, as designed). `check_map.py`'s node-loss gate ran against `origin/master` and passed. The `line-endings` warning is expected and harmless because `.gitattributes` enforces LF for the owned paths; the declaration is a recorded skip that `hb_modules.py` cannot honor, as designed.

Knowledge note: 11 citations re-opened at `c106531` and correct: `D3DDevice9.cpp:119` (`Direct3DCreate9`), `:884` (`Present`), `:259/337/340` (FLIP and DISCARD swap effect), `camera.cpp:85-100` (symmetric projection from `m_focus`), `camera.cpp:103-115` (view matrix), `context.cpp:916` (`Begin3DLayer`), `WinTrek.cpp:285/302/426` (`CameraControl`, `SetHeadOrientation`, `m_orientationHead * *porientation`), `indicator.cpp:167/441` (`Begin3DLayer`), `dinput.cpp:1633` (`DirectInput8Create`), `WinTrek.cpp:8253` (`SenseJoystick`), `VS2022/Allegiance.sln:262` (x64 maps to Win32), plus `D3DPOOL_MANAGED` in `VBIBManager.cpp`, `VRAMManager.cpp`, `surface.cpp`. "Every VS2022 project builds Win32 only" holds: all 28 `.vcxproj` files list only `Win32` configurations. No `CreateVertexShader`/`CreatePixelShader`/`.fx` shader source exists. The "about 314 CRLF files" claim measures 315 at the base, close and honestly approximate. "No existing head tracking or TrackIR code" is consistent with the code: `SetHeadOrientation` is fed by the joystick hat and view presets, not a tracking device. Note that the only wrong line labels are finding 4.

Rulebook and records: the Steam workflow at `c106531` triggers on `next-release`, `antigravity` and `workflow_dispatch`, exactly as AGENTS.md warns. All four commits are authored and committed by `Port <323790917+psiclawops-port@users.noreply.github.com>`, matching the identity contract; branch naming matches `port/<topic>`. `DAG.json` satisfies its own rules: ids, acyclic `needs`, concrete `next`, links on the `review` node, and the `ragesaq-000` pre-adoption marker matches the N2 shape (done, adoption date, `needs: []`, no assurance, links to history, ledger line citing `c106531`). `docs/MEMORY_PROTOCOL.md` is byte-identical to the hub; the two entries carry class, date, `recorded-by` and resolvable `evidence`, and the index rows are the five required cells. Public-repo safety: no secrets, machine paths, host names or personal data found by pattern scan of every added or modified file; the only email-like strings are the allowed Port noreply address and Anthropic's Co-Authored-By noreply trailer in commit messages.

## Verified by reading only

- `tools/recall.py check-glossary` was not executed (the task forbids it because it writes `.hyperbench-recall/`). I read `check_glossary` (`recall.py:1736-1780`) and confirmed each glossary target resolves as a whole term in an indexed source, including "work map" via `work-map` in `docs/RECALL.md` and "head pose" in `knowledge/openxr-port-survey.md:57`.
- `check_map.py`'s gate wiring and `hb_modules.skipped()` semantics were read, then exercised indirectly through the passing checkers.

## Limits

No build, no network, no PR-body or Issue access, and no `recall.py` run. Knowledge-note rows marked "delegated source read" in the note itself (for example the HUD ranges) were spot-checked but not all re-opened. Line numbers apply to `c106531` only. This review does not test a headset or run the game.

## Checkpoint note

The required HyperBench lifecycle record for this review would normally go into this repository's `memory/`, `knowledge/` or `DAG.json` node. The review target forbids rewriting the target repository outside this artifact directory, so the findings are recorded here and should be folded into PR #1 by its author.