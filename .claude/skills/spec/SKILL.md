---
name: spec
description: Settle a product spec with the human. Use when the user wants to define, change, or approve what to build. This is the only stage where the human is asked questions.
argument-hint: <name>
---

# /spec <name>

Goal: an approved `work/<name>/spec.md` that an agent can build from with no further questions.

1. `<name>` is lowercase letters, digits and hyphens. If `work/<name>/spec.md` does not exist, create it from `work/_templates/spec.md` with `status: draft` and today's date. If it exists, continue from it.
2. Restate the goal in your own words and confirm it.
3. Interview. Ask only about product behavior: who uses it, what they see, what happens in each case, what is out of scope. Do not ask about implementation, stack, or architecture; those are yours to decide during the build.
4. Challenge the spec before accepting it. Find contradictions, missing cases (empty, error, concurrent, permission), and behaviors that cannot be checked. Say plainly when something is vague.
5. Write each behavior as a numbered, observable statement that a test or command could check.
6. Keep it small. If the work will not fit one build session, split it into several specs and say so.
7. `Open questions` must be empty before approval.
8. When the human approves, set `status: approved`, run `scripts/check-work.sh`, and commit `docs(spec): approve <name> [<name>]` on a branch from the latest `origin/main`, following `docs/git-workflow.md`. A spec reaches `main` through its own small pull request so that others can see and claim it.

After approval the conversation is over. Tell the human to run `/build <name>`, or start it if they asked you to.
