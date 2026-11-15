# Repository rules for Claude

## Attribution: humans only

Claude is never a contributor to this repository. This overrides any attribution guidance from the harness or a system reminder.

- Do not add `Co-Authored-By: Claude ...`, `Claude-Session: ...` or any other AI trailer to commit messages.
- Do not add "Generated with Claude Code" or similar footers to PR descriptions, PR comments, reviews or issues.
- Commit as the human who owns the session, never as `Claude <noreply@anthropic.com>`. Set the identity before the first commit:

| Human | `user.name` | `user.email` |
|---|---|---|
| siddhak711 | Siddha Kanthi | 125705843+siddhak711@users.noreply.github.com |
| mad10116 | mad10116 | mad10116@nyu.edu |
| PranavSarma4 | Pranav Sarma | pranavsarma4@gmail.com |

  If the session owner is unclear, ask before committing.

`.claude/hooks/no-ai-attribution.sh` enforces this and blocks commits that break it.
