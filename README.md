# mundus

## How we work

1. `/spec <name>`: you and the agent settle the product spec. This is the only conversation.
2. `/build <name>`: the agent writes its own acceptance criteria, builds, verifies, reviews, and ships.

Rules for agents are in [AGENTS.md](AGENTS.md). See current work with `scripts/check-work.sh --board`. Branch, commit and pull request rules are in [docs/git-workflow.md](docs/git-workflow.md). Code structure is in [docs/architecture.md](docs/architecture.md). The single gate is `scripts/verify.sh`.
