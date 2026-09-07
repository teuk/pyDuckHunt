# Contributing

pyDuckHunt is developed in small, reviewable rounds.

## Local validation

```bash
export PYTHONPATH=src
.venv/bin/python tools/project_guard.py
.venv/bin/python -m compileall -q src tools tests
.venv/bin/python tools/validate.py --lane fast --progress
```

The full lane is reserved for an explicitly approved precommit round:

```bash
export PYTHONPATH=src
.venv/bin/python tools/validate.py --lane full --progress
```

Do not commit runtime configuration, credentials, state, logs, private research
material, generated exports or local helper scripts.

Use a pull request for review. CI must pass on every supported Python version,
and the full lane must pass before merge.
