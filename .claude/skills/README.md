# Design skills

Third-party Claude Code skills vendored here so every session on this repo can use them for frontend work.
Each folder keeps its upstream license.

| Skill | Upstream | Commit | License |
|---|---|---|---|
| `emil-design-eng` | [emilkowalski/skills](https://github.com/emilkowalski/skills) | 85e8e23 | MIT |
| `impeccable` | [pbakaus/impeccable](https://github.com/pbakaus/impeccable) | e0881d2 | Apache-2.0 |
| `taste-skill`, `redesign-skill` | [Leonxlnx/taste-skill](https://github.com/Leonxlnx/taste-skill) | a6153b3 | MIT |

`impeccable` is vendored without its `scripts/` folder: the launcher there downloads a prebuilt
binary at runtime. The skill falls back to reading `SKILL.md` and `reference/` directly when the launcher is missing.
