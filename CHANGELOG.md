# CHANGELOG


## v0.4.0 (2026-03-10)

### Chores

- Bump GitHub Actions to Node.js 24-compatible versions
  ([`bc823cd`](https://github.com/federico-reppucci/tidyup/commit/bc823cde7c642de299d86f7eadf0653c0cf77ded))

actions/checkout v4 → v6, actions/setup-python v5 → v6

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Update Homebrew formula for v0.3.1 [skip ci]
  ([`517837f`](https://github.com/federico-reppucci/tidyup/commit/517837fac846f0dd81def2594c9820ef5fc72354))

### Documentation

- Add conventional commits section to CLAUDE.md
  ([`becb451`](https://github.com/federico-reppucci/tidyup/commit/becb4513787198d855c5278103d48e3ed850f8f8))

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

### Features

- Add tidyup config command for persistent settings
  ([`a8366e1`](https://github.com/federico-reppucci/tidyup/commit/a8366e1d891a4434c3b912f5e613bce0a97ad23e))

New `tidyup config [key] [value]` subcommand to view/update settings without hand-editing JSON.
  Supports friendly aliases (e.g. `model` for `ollama_model`). Also bumps per-batch LLM timeout
  minimum from 60s to 120s.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>


## v0.3.1 (2026-03-10)

### Bug Fixes

- Fix .git ownership in release workflow, update formula to v0.3.0
  ([`ae01235`](https://github.com/federico-reppucci/tidyup/commit/ae012357981cfc830b45ffe390d4f78fd43e0365))

PSR's Docker container leaves .git owned by root, breaking the subsequent commit step. Added chown
  to fix permissions. Also manually updated the formula for v0.3.0 since CI couldn't push it.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>


## v0.3.0 (2026-03-10)

### Features

- Add automated release pipeline with python-semantic-release
  ([`5794351`](https://github.com/federico-reppucci/tidyup/commit/5794351ca9a26bd9e08a72146bc6b8577a6e9542))

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>


## v0.2.0 (2026-03-10)


## v0.1.0 (2026-02-27)
