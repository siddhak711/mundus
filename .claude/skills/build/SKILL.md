---
name: build
description: Build an approved spec end to end with no human conversation. Derives acceptance criteria, implements, verifies, reviews, and ships.
argument-hint: <name>
---

# /build <name>

Precondition: `work/<name>/spec.md` has `status: approved` (or `building`, to resume). Otherwise stop and say so.

Run every step to completion without asking the human anything. The only exceptions are in `AGENTS.md` under "When you may come back to the human".

1. **Claim.** Follow `docs/git-workflow.md`. Fetch `origin/main` and confirm the item is `approved` there and no open pull request names it; if one does, stop and report. Branch from `origin/main`. Set `status: building`, create `acceptance.md` and `log.md` from `work/_templates/`, commit, push, and open a draft pull request. That pull request is the lock.
2. **Acceptance criteria.** For every numbered behavior in the spec write at least one criterion in `acceptance.md`, citing the behavior number and naming the exact command or test that checks it. Add criteria for error and edge cases the spec implies.
3. **Criteria review.** Spawn a fresh subagent with only the spec and `acceptance.md`. Ask it to list behaviors with no criterion, criteria with no executable check, and checks that could pass while the behavior is broken. Fix what it finds and record the outcome under `Criteria review`.
4. **Stack, first build only.** If the repository has no code yet, choose the stack, log the choice and reason, add lint, typecheck and test gates under `scripts/verify.d/`, and add the layer import checker required by `docs/architecture.md` with a test proving a backward import fails. These are mandatory acceptance criteria of the first build.
5. **Build.** Use `/pstack:poteto-mode` if available and pick the matching playbook. Write the failing check first, then the smallest change that passes it. Follow `docs/architecture.md`.
6. **Verify.** Run `scripts/verify.sh` and every check in `acceptance.md`. Record the command and observed result per criterion under `## Verification` in `log.md`. A criterion without observed evidence is not done.
7. **Diff review.** Spawn a fresh subagent with the spec, `acceptance.md` and the diff (use `/pstack:interrogate` if available). Ask it to break the change. Fix real findings, rerun step 6, and record findings and resolutions under `## Review`.
8. **Ship.** Merge the latest `origin/main` into the branch and rerun step 6 if anything came in. Set `status: shipped`, commit, push, fill in the pull request with the spec link and evidence, mark it ready, and enable squash auto-merge. If auto-merge is unavailable, leave the pull request open and say so.
9. **Report.** Three short parts: what shipped, the evidence, the decisions you made. No questions.

If a criterion cannot be met, do not weaken it silently. Either fix the code, or record in `log.md` why the criterion was wrong and what replaced it.
