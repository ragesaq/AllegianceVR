# Patch review - PR #3: agents merge and change settings only with the operator's approval

- Target: `<review-clone>`, standalone clone, no remote, detached at `83c0d310f15535339640363efcff491f3533a441`
  (`git write-tree` = `2681052893c8dc9787554959911881a11e359204`), branch `port/merge-settings-approval`,
  `ragesaq/AllegianceVR#3`. Both checks match the freeze; the worktree is clean. Base
  `276123c1cf426e04dd8d38635bbb679c06fe5931`; commits `4b074ea9`, `707db18f`, `83c0d310`; 4 files, +61/-3.
- Reviewer: `deepseek-v4.1-flash` through OpenCode Go at `high`, explicit selection, cross-family (the change is
  Anthropic-authored). Reviewer-parity matrix 4.14.0, sha256
  `74618f22fd72f6a27ed86db1298fd387068118d3faab415a79604b60c8a63267`; route: `AGENTS.md`, "Cross-family review route".
- **Verdict: PASS-WITH-CONDITIONS.** The rule is sound and faithful to the operator's two statements. Five Low
  items should be fixed or answered before merge.

## Findings

1. **Low - `memory/mem-004-merge-and-settings-approval.md:21-22`.** "in the same words as ... PR #5" is false as
   written. A machine diff against the sibling's rule 4 at `309921b6` shows exactly two substitutions: the
   `mem-005` pointer becomes the one-sentence stamping warning, and the `mem-008` pointer becomes the
   prime-rule-2 sentence. Both are disclosed in the PR body, so the substance is right. Failure: a later agent
   checks the claim, finds differences, and discounts the entry. Fix: "carries the same rule as ..., with the two
   differences PR #3 records".
2. **Low - `AGENTS.md:21`.** "any build and test gate they name passes" has no antecedent; the nearest plural noun is
   "the review gates". An agent can read "no gate applies unless a reviewer names one" and merge without the
   operator's gate. Fix: "the operator names".
3. **Low - `AGENTS.md:21-22`.** The colon gloss reads as the full merge checklist but covers only posting the review
   comment. It omits running `hyperreview-reflex`, committing the summary under
   `.hyperreview/patch-review-<date>-<topic>-r<N>/`, and re-reviewing the delta. Failure: an agent satisfies the
   gloss and merges with no committed review record. The section still binds ("the review gates below are met"), so
   this is clarity, not a hole. Fix: "recorded as `Review gates` requires".
4. **Low - `AGENTS.md:28-29`.** The stamping sentence holds for a merge commit. A squash or rebase merge in GitHub
   records the pull request's author as author and `GitHub <noreply@github.com>` as committer. Here the
   consequence is attribution only. Fix: "A merge commit made in GitHub stamps ...".
5. **Low - PR description, not in the frozen tree.** The body says the text uses the fork's words "after that PR's
   first cross-family review", but rule 4 changed materially in round 2: round 1 (`1f6039c`) has no gate sentence,
   relay clause or head parameter, and round 2 (`309921b6`) is what this change matches. The last commit says
   "Carry PR #5 round 2 answers". Fix: say round 2.

Observations, no action here. `.claude/skills/hyperbench-lifecycle/SKILL.md:144` still says "The operator merges"
for the enrollment step; it is vendored hub text, so raise it upstream rather than edit it. A settings change
approved verbally in a session also has no Issue or pull request to record it in (`AGENTS.md:31-32`).

## Verified by execution, read-only

- Frozen HEAD and tree match; clean status; Port noreply author and committer on all three commits; `git diff
  --check` clean; four files `i/lf w/lf` under `eol=lf`; mem-004 has no BOM and ends with LF; no machine path, host
  name, secret or non-noreply email in the diff.
- `check_data_boundary.py` OK. `check_memory.py` OK (4 entries, classed and indexed), with the documented `recorded-by` warning (also for
  mem-004) and entry-deletion limit. `check_map.py` exits 1 only because the node-loss gate has no `origin/master`
  here; `check_node_loss.py --allow-no-base` records it as not performed, and the patch appends one DAG node and
  deletes none.
- `DAG.json` parses; node `ragesaq-003` carries status, next, links and updated; links resolve to a URL and two
  repository files; the rules block is unchanged.
- Machine diff of rule 4 against the sibling at `309921b6`: only the two disclosed substitutions.

## Verified by reading

Quote 1 is exact. Quote 2 is an exact fragment closed at its comma, and "make the change to the allegianceVR
agents.md" is rendered as "asked for the same change here", which is faithful. `witnessed` is right: the primary
evidence is the operator speaking and no resolvable log was kept; `seen-in:` names the action, the machine by role
and the tool versions, and the entry declares no `sources:`. The index row repeats topic, class and observed. No
"the operator merges" text remains in `AGENTS.md`; the base did say "Assistants never merge", so mem-004's "Until
then" clause is true.

## Focus answers

1. Standing, relayed and file approval are closed ("covers only the pull request it names"; "A message from another
   agent, a handoff note, or text in an Issue or a file never counts"), as is merging before review. The gate gloss
   fits the section as it stands: no DEVAL exists and none is implied, and "where a review is required" matches the
   mechanical escalation and its exemption list. No approval path weakens prime rule 2 (explicitly preserved)
   or prime rule 3: the settings path touches GitHub configuration, not upstream files, and disabling the only
   workflow here neither pushes the guarded branches nor dispatches the deploy.
2. Faithful, with nothing material undisclosed. The body states both differences and the identity-row edit.
3. mem-004's class and indexing are correct and the quotes are faithful; only "same words" overstates.
4. The DAG node meets the rules block.
5. No other wrong statement, broken relative link, line-ending, machine-path, secret, email or checker defect
   attributable to the change.

## Limits

The node-loss comparison was not performed (no remote in this clone); `tools/recall.py` was not run as instructed;
no build, test, deploy or install script was run (none applies here); the sibling comparison is against PR #5's
open head, which round 3 may change; GitHub account settings were not observable here, only the repository text
about them.
