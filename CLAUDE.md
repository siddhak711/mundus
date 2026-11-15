# Repository rules for Claude

All shared rules live in `AGENTS.md` so every agent reads the same ones. Follow them exactly:

@AGENTS.md

Claude-specific: `.claude/hooks/no-ai-attribution.sh` enforces the attribution rules and blocks commits that break
them.
