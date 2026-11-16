# Development

## Layout

```
.claude-plugin/marketplace.json   this repository is also a plugin marketplace
plugins/agentic-review/
  .claude-plugin/plugin.json
  CONTRACT.md                     folder layout, file names, record schema, scripts, who reads what
  skills/                         the commands: new, run (+ phases.md, the playbook), status, add-pdfs, share
  agents/                         the 13 agent briefs
  workflows/                      annotate.js, late-pdfs.js (the large fan-outs)
  hooks/                          hooks.json, ar_hook.py, access.json
  bin/                            ar-* scripts: state, validate, merge, refcheck, count, citemap, bib, edition, share…
  lib/                            shared Python helpers; lib/edition/ is the reading edition (page, figures, viewer)
  templates/                      review.json, PROTOCOL.md, record.schema.json, the annotation guide, figure examples
  tests/                          unit tests for the scripts and hooks
  evals/                          an example case for `claude plugin eval`
docs/                             this documentation
scripts/pack.py                   packs a release zip
pyproject.toml, uv.lock, Makefile the development tools (uv, ruff, ty)
```

Scripts use the Python standard library only. Skills call them as `"${CLAUDE_PLUGIN_ROOT}/bin/<script>"`, with the
review folder first; each one prints its usage with `--help`.

## Checks

The development tools are managed by [uv](https://docs.astral.sh/uv/): [ruff](https://docs.astral.sh/ruff/)
lints and formats, [ty](https://docs.astral.sh/ty/) checks types (the scripts in `bin/` included).

```bash
make install   # uv sync: ruff and ty in .venv
make check     # ruff, ruff format --check, ty and the unit tests, as CI runs them
make format    # fix what ruff can
claude plugin validate --strict . && claude plugin validate --strict plugins/agentic-review
```

CI (`.github/workflows/tests.yml`) runs the checks, the tests on Python 3.9 and 3.12, and a test pack on every
push. The plugin itself needs no dependency: keep the scripts on the standard library and Python 3.9.

## Releasing

1. Set the new version in `plugins/agentic-review/.claude-plugin/plugin.json` and `pyproject.toml`, and add its
   section at the top of `CHANGELOG.md`.
2. `make pack` checks that the three agree and builds `dist/agentic-review-<version>.zip`.
3. Tag and push: `git tag v<version> && git push origin v<version>`. The release workflow runs the checks, packs
   the zip and publishes a GitHub release with it, its SHA-256 and the CHANGELOG section as notes.

## Changing the workflow

- **An agent's behaviour**: edit its brief in `agents/<role>.md`. The orchestrator adds only run-specific details
  (folder, id, slice, decisions), so the brief is the place for anything general.
- **What an agent may open**: `hooks/access.json` (or `.agentic-review/access.json` in one review).
- **A phase's steps**: the section of that phase in `skills/run/phases.md`.
- **A file or a field**: update `CONTRACT.md`, the schema in `templates/`, and the script that reads it, with a test.

To use your changes, fork the repository and install from your fork, or point Claude Code at your copy with
`claude --plugin-dir ./plugins/agentic-review`.
