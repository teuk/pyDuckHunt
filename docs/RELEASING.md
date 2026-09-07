# Releasing pyDuckHunt

pyDuckHunt is currently a public beta. Until the beta exit criteria are met,
`VERSION` remains `0.1.0-dev` and maintainers must not create a tag or GitHub
Release.

pyDuckHunt remains development software until a stable version is explicitly
approved. A normal commit must not create a tag or GitHub Release.

## Candidate contract

1. Start from a clean `main` branch and a reviewed public source tree.
2. Run `tools/project_guard.py` and the relevant targeted tests.
3. Run the fast lane while iterating.
4. Run the full lane exactly once, visibly and immediately before the candidate
   commit:

   ```bash
   PYTHONPATH=src .venv/bin/python tools/validate.py --lane full --progress
   ```

5. Stage only reviewed project files. Exclude private configuration, runtime
   state, logs, research material, operator helpers, archives and audio.
6. Verify the staged diff and scan it for credentials before committing.
7. Push without rewriting public history and require GitHub Actions to pass.

## Stable releases

A stable release additionally requires an explicit stable version, matching
package metadata, an annotated tag and reproducible source artefacts. Those
steps are not part of the initial development commit.

## License and attribution

The source is distributed under CC BY-NC-SA 3.0. The attribution in `LICENSE`
and `README.md` must remain present in every source archive.
