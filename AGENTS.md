# Agent rules for mundus

The human talks to you about one thing: the product spec. Once a spec is approved, you finish the work without further conversation.

## The loop

1. `/spec <name>`: interview the human, write `work/<name>/spec.md`. Push back on vague or contradictory behavior now; this is the last chance to ask. On approval set `status: approved`.
2. `/build <name>`: derive acceptance criteria, build, verify, ship. No questions.

## Hard rules

- Nothing is built without a spec whose status is `approved`.
- Every acceptance criterion cites the spec line it comes from and names an executable check. No criterion without a check, no check that cannot fail.
- A separate agent reviews the criteria against the spec, and another reviews the diff. Never review your own work in the same context.
- Never weaken, skip, or delete a test to get a gate to pass. Fix the code or fix the criterion and log why.
- `scripts/verify.sh` must pass before every commit. Keep it under 60 seconds.
- One spec, one branch, one pull request. Keep specs small enough to finish in one session; split anything larger.
- Follow `docs/git-workflow.md`: branch from the latest `origin/main`, claim the item with a draft pull request, touch only what the item needs, merge `origin/main` in before shipping, never force-push, never commit to `main`.
- Decide and log instead of asking. Record each non-obvious decision in `work/<name>/log.md` with its reason.
- Code follows the one-way layer rule in `docs/architecture.md`.
- Use `/pstack:poteto-mode` for build work when pstack is loaded. If it is not loaded, follow the same discipline by hand: failing test first, smallest change, prove it works.

## When you may come back to the human

Only two cases:

- The spec is ambiguous in a way that changes product behavior. Ask one precise question and record the answer in the spec.
- The action is irreversible: deleting data, spending money, publishing outside this repository.

Everything else, including the tech stack and all implementation choices, is yours.

## Work items

`work/<name>/` holds `spec.md`, `acceptance.md`, `log.md`. Status lives in the `spec.md` frontmatter: `draft`, `approved`, `building`, `shipped`. See the board with `scripts/check-work.sh --board`. It is never committed.

## Commits

`type(scope): subject [<name>]`, where `<name>` is the work item. Allowed types and details are in `docs/git-workflow.md`. Hooks in `.githooks/` enforce the format and run the gate.
