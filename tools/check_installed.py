#!/usr/bin/env python3
"""Check a disposable CI installation; never connect or start the game.

Run with the installed environment's Python and without PYTHONPATH. This checks
the install.sh output, not an operator's configured live instance.
"""
from __future__ import annotations

import argparse
import importlib.metadata
from pathlib import Path
import stat
import sys


def check(root: Path, language: str) -> None:
    # No sys.path fallback: a missing installed package must fail this check.
    from pyduckhunt import __version__
    from pyduckhunt.configuration import load_application_configuration
    from pyduckhunt.i18n import current_language, language_context, tr
    from pyduckhunt.messages_en import EN

    def need(condition: bool, message: str) -> None:
        if not condition:
            raise ValueError(message)

    path = root / "config/pyduckhunt.toml"
    need(path.is_file() and not path.is_symlink(), "missing regular generated configuration")
    need(stat.S_IMODE(path.stat().st_mode) == 0o600, "generated configuration must be private (0600)")
    config = load_application_configuration(path)
    need(config.game.language == language, "generated language differs from the requested language")
    need(not config.game.enabled and not config.partyline.enabled, "fresh configuration must stay disabled")
    need(config.irc.host.endswith(".invalid"), "fresh endpoint must remain an invalid example")
    need(importlib.metadata.version("pyduckhunt") == __version__, "installed version metadata differs")
    need(bool(EN), "installed English catalogue is empty")
    source = "Le canard s'échappe. {0}·°'`'°-.,¸¸.·°'`{1}"
    with language_context(language):
        expected = "The duck escapes." if language == "en" else "Le canard s'échappe."
        need(tr(source, "", "").startswith(expected + " "),
             "installed message language is incorrect")
    need(current_language() == "fr", "language context leaked after rendering")
    for directory in ("state", "logs"):
        need(not (root / directory).exists(), "installation unexpectedly created runtime data")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--language", choices=("en", "fr"), required=True)
    args = parser.parse_args()
    try:
        check(Path(__file__).resolve().parents[1], args.language)
    except (OSError, ValueError, ImportError, importlib.metadata.PackageNotFoundError) as error:
        print(f"[KO] Disposable installation check failed: {error}", file=sys.stderr)
        return 1
    print(f"[OK] Installed {args.language} package, messages and private disabled configuration.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
