# Releasing pyDuckHunt

pyDuckHunt is currently a public beta. Until the beta exit criteria are met,
`VERSION` remains `0.1.0-dev` and maintainers must not create a tag or GitHub
Release.

pyDuckHunt remains development software until a stable version is explicitly
approved. A normal commit must not create a tag or GitHub Release.

## Ordinary beta commits

1. Start from a clean `main` branch and a reviewed public source tree.
2. Run `tools/project_guard.py` and the relevant targeted tests.
3. Run the fast lane while iterating.
4. Run the full lane exactly once, visibly and immediately before the final
   commit:

   ```bash
   PYTHONPATH=src .venv/bin/python tools/validate.py --lane full --progress
   ```

5. Stage only reviewed project files. Exclude private configuration, runtime
   state, logs, research material, operator helpers, archives and audio.
6. Verify the staged diff and scan it for credentials before committing.
7. Push without rewriting public history and require GitHub Actions to pass.

## Release acceptance

The open gates are tracked in [the roadmap](ROADMAP.md#before-a-release).
For a candidate, record its commit, tested OS/Python versions, fresh-install
results in both languages, live IRC acceptance, persistence recovery, update and
rollback results. Retain sensitive evidence privately and publish only a sanitized
summary. A passing offline suite alone is not a live deployment qualification.

Current CI runs fast validation on Python 3.11, 3.12 and 3.13, one full job on
3.13, and separate fresh editable-install checks for English and French on 3.13.
The install checks validate the generated configuration, packaged catalogue and
configuration preservation without connecting to IRC. This is not yet a wheel
or source-archive installation test, nor a claim that every Python/OS pair is qualified.

GitHub branch protection, required checks and private vulnerability reporting
are repository settings: maintainers must verify them on GitHub. Their presence
cannot be inferred from checked-in templates or links.

## Stable releases

A stable release additionally requires an explicit stable version, matching
package metadata, an annotated tag and reproducible source artefacts. Those
steps are not part of the initial development commit.

## License and attribution

The source is distributed under CC BY-NC-SA 3.0. The attribution in `LICENSE`
and `README.md` must remain present in every source archive.
