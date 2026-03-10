# CHANGELOG


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
