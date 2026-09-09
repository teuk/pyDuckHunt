# pyDuckHunt

[![CI](https://github.com/teuk/pyDuckHunt/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/teuk/pyDuckHunt/actions/workflows/ci.yml)
[![Status: Beta](https://img.shields.io/badge/Status-Beta-f0a500.svg)](#beta-status)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![License: CC BY-NC-SA 3.0](https://img.shields.io/badge/License-CC_BY--NC--SA_3.0-lightgrey.svg)](LICENSE)

A Duck Hunt game bot for IRC, with **English and French messages**, persistent
scores, a shop and private administrator tools. Both languages share the same
game rules and code.

## Install in English

Requires **Python 3.11+**, its `venv` module and Git. Run as your normal bot
account, not root. See [platform prerequisites](docs/INSTALL.md#requirements).

```bash
git clone https://github.com/teuk/pyDuckHunt.git
cd pyDuckHunt
./install.sh --language en
```

This creates `.venv` and a private **`config/pyduckhunt.toml`** with
**`language = "en"`** in `[game]`. It does not connect to IRC yet.

Next, edit that configuration with your IRC server, port, TLS setting, nickname
and channel. Then follow [configure, check and start](docs/INSTALL.md#configure-and-start)
to enable the game and launch it. No system service is installed automatically.

**French:** use `./install.sh --language fr`. French is also the default for a
new installation when `--language` is omitted.

### Switching an existing instance to English

Update the existing `[game]` section in **that instance's private configuration**:

```toml
language = "en"
```

Then restart that instance. Scores, inventory and scheduled flights are
preserved. Re-running the installer never overwrites an existing configuration;
it refuses an explicit language choice that conflicts with it.
See [language settings](docs/LANGUAGES.md) for separate FR/EN instances.

## Play

| Command | Action |
| --- | --- |
| `!bang` | Shoot a duck |
| `!reload` | Reload your weapon |
| `!duckstats` | View your profile and hunting record |
| `!inventory` | View your equipment and active effects |
| `!shop` / `!shop <number>` | Browse the shop / buy an item |

Command names stay the same in both languages. Exact flight planning is private
to authenticated Owners; ordinary players cannot request it.

The game includes 24 daily base flights, bread and duck calls, special ducks,
equipment, fatigue and persistent progression. See [shop rules](docs/SHOP.md)
and [channel items](docs/CHANNEL_ACTIONS.md) for the details.

## Documentation

- [Installation, first launch and updates](docs/INSTALL.md)
- [Configuration](docs/CONFIGURATION.md) · [Languages](docs/LANGUAGES.md)
- [Partyline and Owner commands](docs/PARTYLINE.md)
- [Systemd service setup](docs/SYSTEMD_SERVICE.md)
- [Web rankings](docs/RANKING_PAGE.md) · [Metrics](docs/METRICS_GRAFANA.md)
- [Architecture](docs/ARCHITECTURE.md) · [Changelog](CHANGELOG.md)

## Beta status

This is **beta software**, distributed from `main`, and no tag or GitHub Release
has been published yet. Back up your private configuration and state before updating.

For development validation:

```bash
PYTHONPATH=src .venv/bin/python tools/validate.py --lane fast --progress
```

The full lane is run once before a final commit; see [release workflow](docs/RELEASING.md).
Keep runtime data, credentials and private logs outside Git.

## License and credits

[CC BY-NC-SA 3.0](LICENSE). Credits: [MenzAgitat](https://scripts.eggdrop.fr/details-Duck+Hunt-s228.html),
author of the original Duck Hunt Tcl game.

Special thanks to **gaby** for live testing and detailed player feedback.
