# claude-skills

A private Claude Code marketplace with one plugin, `ecc` — a curated cut of [affaan-m/ECC](https://github.com/affaan-m/ECC) v2.2.3 (MIT).

`.claude/settings.json` enables `ecc@claude-skills` for every Claude Code session opened on this repo.

## What is inside `plugins/ecc`
- **Agents:** all 72, byte-identical to upstream.
- **Hooks:** all of them, plus the `scripts/` they run, byte-identical to upstream.
- **Skills:** 42 hand-picked ones (out of 328): coding standards, TDD, security review, git workflow, API/backend/frontend/Python/TypeScript/React patterns, e2e & browser QA, deep research, docs lookup, DB/Docker/deploy, context management, MCP/prompt/agent/LLM-cost/eval skills, and `continuous-learning` + `continuous-learning-v2` (the hooks need those two).
- **Not included:** the other 286 skills and the legacy command shims.

## Use
- Verify in a new session: `/plugin list` shows `ecc@claude-skills`.
- Disable: set `"ecc@claude-skills": false` in `.claude/settings.json`.
- Add a skill: copy its folder from upstream `skills/` into `plugins/ecc/skills/`.
- Do not also install the upstream `ecc@ecc` plugin — it would duplicate agents, hooks and skills.
