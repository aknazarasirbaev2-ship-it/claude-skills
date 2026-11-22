# claude-skills

Enables the official **ECC (Everything Claude Code)** plugin for every Claude Code session opened on this repo.

`.claude/settings.json` registers the marketplace `affaan-m/ECC` and enables `ecc@ecc`. That one plugin provides all of ECC's skills (~328), agents (~72), commands (~99) and hooks. Nothing is copied here, so there are no duplicates. Upstream updates come with the plugin.

- Verify in a session: `/plugin list` should show `ecc@ecc` enabled.
- Disable it: set `"ecc@ecc": false` in `.claude/settings.json`.
- Source: https://github.com/affaan-m/ECC (MIT).
- Do NOT also install ECC manually (`npx ecc-universal ...`) in the same environment: that duplicates skills and hooks.
