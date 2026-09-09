# Contributing

Bug reports, translation corrections and small pull requests are welcome.
Check the [roadmap](docs/ROADMAP.md) and [existing issues](https://github.com/teuk/pyDuckHunt/issues)
before starting a larger change. English and French reports are both welcome.

## Report a problem

Use the [bug form](https://github.com/teuk/pyDuckHunt/issues/new?template=bug_report.yml)
with a commit, Python version, OS, message language and minimal reproduction.
Replace people and channels with synthetic examples. See
[troubleshooting](docs/TROUBLESHOOTING.md) before attaching diagnostics.
Vulnerabilities belong in the [private security channel](SECURITY.md).

## Prepare a change

Fork the repository, clone your fork and create a topic branch from `main`.
Run `./install.sh --language en` as your normal account to prepare `.venv`;
installation does not connect to IRC. Use `--language fr` for a new French setup.

Keep changes small and explain the player or operator problem they solve.
Update the relevant guide and changelog when observable behavior changes.
Retain the original author's attribution and project license.

For translations, follow [catalogue maintenance](docs/LANGUAGES.md#maintaining-the-catalogue):
preserve formatting fields, privacy routing and dynamic values. French and
English use the same rules, entropy and replay state. Do not add a language fork
to the game engine. Add a regression test when it demonstrates a real defect;
simple wording corrections do not need tests that only repeat the new sentence.

## Local validation

```bash
export PYTHONPATH=src
.venv/bin/python tools/project_guard.py
.venv/bin/python tools/validate.py --lane targeted --progress \
  --test tests.unit.test_i18n
.venv/bin/python tools/validate.py --lane fast --progress
```

Replace the targeted module with the tests relevant to your change. The full
lane is reserved for the final precommit round; run it once with progress visible:

```bash
export PYTHONPATH=src
.venv/bin/python tools/validate.py --lane full --progress
```

Do not commit runtime configuration, credentials, state, logs, private research
material, generated exports or local helper scripts.

Use a pull request for review. CI must pass on every supported Python version,
and the full lane must pass before merge.
Record what ran and what remains untested in the pull request. Live IRC acceptance
is a separate check on an authorized test channel. Ordinary contributions create
no tag or release; see [release workflow](docs/RELEASING.md).
