# Git workflow

Goal: many agents and people work in parallel and nobody resolves a merge conflict by hand. Conflicts come from two branches editing the same lines, so every rule here either keeps branches from overlapping or keeps them short.

## Branches

- `main` is the only long-lived branch. It always passes `scripts/verify.sh`. Nobody commits or pushes to it directly.
- One work item, one branch, one pull request. Name it `work/<name>`. A branch name assigned by the session environment is also fine.
- Always branch from the latest `origin/main`: `git fetch origin main && git switch -c work/<name> origin/main`.
- Branches live hours, not days. If a build will not finish in one session, the spec is too big; split it.
- Delete the branch after merge. Never reuse a merged branch for new work.

## Claiming work

Before building, check that nobody else has the item: its status must be `approved` on `origin/main` and no open pull request may name it. Then claim it: the first commit on the branch sets `status: building`, and you push it and open a draft pull request immediately. An open pull request for a work item is the lock.

## Staying out of each other's way

- Change only what the work item needs. No drive-by reformatting, renaming, or moving of files you were not asked to change. Those belong in their own small pull request.
- Each work item writes only inside its own `work/<name>/` directory. CI rejects a pull request that changes two work items.
- Shared files are the conflict hot spots: dependency manifests and lockfiles, `AGENTS.md`, `.claude/settings.json`, `scripts/verify.sh`, CI workflows, `architecture/layers.txt`. Change them in a dedicated pull request with nothing else in it, and merge it fast.
- Never commit generated output (build artifacts, the board, caches). Generate it on demand.
- New code goes in new files inside the right layer and domain where it can. Adding a file never conflicts; editing a shared one can.
- Registries that every feature appends to (route tables, export lists) are kept sorted, one entry per line, so parallel additions land on different lines.

## Keeping up with main

- Bring `main` into your branch before opening the pull request, and again whenever `main` moves: `git fetch origin main && git merge origin/main`.
- Use merge, not rebase, to update a pushed branch. History is squashed on merge anyway, and this way nobody ever force-pushes.
- Never force-push a shared branch. Never rewrite history that someone else may have pulled.

## If a conflict happens anyway

1. `git fetch origin main && git merge origin/main`.
2. Resolve by understanding both changes, not by picking a side wholesale. For a lockfile, take `main`'s version and regenerate it with the package manager.
3. Run `scripts/verify.sh`. It fails if conflict markers remain.
4. Commit the merge and push. Log what conflicted in `work/<name>/log.md`.

If the same file keeps conflicting, that file is doing too much. Split it.

## Commits

Format, checked by the `commit-msg` hook and by CI on the pull request title:

```
type(scope): subject [work-item]
```

- `type` is one of `feat`, `fix`, `docs`, `chore`, `refactor`, `test`, `perf`, `build`, `ci`, `revert`.
- `scope` is optional. The subject line is at most 72 characters.
- `feat` and `fix` must end with the work item in brackets.
- Commit small and often. Each commit passes `scripts/verify.sh`; the `pre-commit` hook enforces it.

## Pull requests

- Open as draft at claim time. Mark ready when the build is verified.
- The title follows the commit format, because it becomes the single commit on `main`.
- Squash merge only. `main` keeps one commit per work item and a linear history.
- Merge automatically once CI is green and the branch contains the latest `main`.

## Hooks

The repository ships its hooks in `.githooks/`. Agent sessions enable them automatically at start. For a manual clone, run once:

```bash
git config core.hooksPath .githooks
```

| Hook | Does |
|---|---|
| `pre-commit` | refuses commits on `main`, runs `scripts/verify.sh` |
| `commit-msg` | checks the subject format |
| `pre-push` | refuses direct pushes to `main` |

## Repository settings

These are set once in GitHub by the owner and make the rules above binding:

- Protect `main`: require a pull request, require the `verify` check, require branches to be up to date before merging, block force pushes and deletion.
- Allow squash merging only. Disable merge commits and rebase merging.
- Enable auto-merge.
- Enable automatic deletion of head branches.
