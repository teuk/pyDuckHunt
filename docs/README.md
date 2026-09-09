# Documentation

New to pyDuckHunt? Start with [installation in English](INSTALL.md#install-in-english).
Use `./install.sh --language fr` for French. Both instances use the same game engine.

## Install and play

| Guide | What it answers |
| --- | --- |
| [Install and update](INSTALL.md) | Prerequisites, language, first connection and updates |
| [Configuration](CONFIGURATION.md) · [Languages](LANGUAGES.md) | Private settings and independent FR/EN instances |
| [Troubleshooting](TROUBLESHOOTING.md) | Installation, connection, messages and recovery problems |
| [Player profiles](PLAYER_PROFILE.md) · [Shot engine](SHOT_ENGINE.md) | Progression, fatigue, accuracy and shooting |
| [Shop](SHOP.md) · [Channel items](CHANNEL_ACTIONS.md) | Equipment, bread and duck calls |
| [Collection and carry](COLLECTION_AND_CARRY.md) | Letters, duck bags and capacity |
| [Rare events](RARE_EVENTS.md) · [Legendary protection](LEGENDARY_PROTECTION.md) | Unusual ducks, loot and protection |
| [Incidents](INCIDENTS.md) · [Nuisances](NUISANCES.md) · [Curses](CURSES.md) | Cross-player effects and countermeasures |

## Run and administer

| Guide | What it answers |
| --- | --- |
| [Operator pilot](OPERATOR_PILOT.md) · [Controlled pilot](CONTROLLED_PILOT.md) | Target allowlists and live acceptance |
| [Systemd](SYSTEMD_SERVICE.md) · [Unit templates](../packaging/systemd/README.md) | Background services; adapt the supplied pilot paths |
| [Partyline](PARTYLINE.md) | Owner authentication, private planning and administration |
| [Persistence](PERSISTENCE.md) · [Privacy](PRIVACY.md) | Journal, snapshots and private data boundaries |
| [Web rankings](RANKING_PAGE.md) · [Metrics](METRICS_GRAFANA.md) | Optional publication and monitoring |

## Develop and review

- [Contributing](../CONTRIBUTING.md): reproduce a bug, submit a change or a translation.
- [Architecture](ARCHITECTURE.md): module responsibilities and deterministic state.
- [Behavioral replay](BEHAVIORAL_REPLAY.md) · [Rendering](RENDERING.md): behavior and presentation contracts.
- [IRC transport](IRC_TRANSPORT.md) · [Process shell](PROCESS_SHELL.md): connection and process boundaries.
- [Runtime lifecycle](RUNTIME_LIFECYCLE.md) · [Runtime policy](RUNTIME_POLICY.md): dispatch, pacing and shutdown.
- [Runtime adapters](RUNTIME_ADAPTERS.md) · [Settlement adapters](SETTLEMENT_ADAPTERS.md): clock, entropy and persistence integration.
- [Roadmap](ROADMAP.md) · [Release workflow](RELEASING.md) · [Changelog](../CHANGELOG.md): current status and remaining work.
- [Security policy](../SECURITY.md): report a vulnerability privately.

Some detailed guides document the existing pilot deployment. Its account, paths
and service names are examples, not requirements for your own server. Begin with
the installation guide before adapting an optional integration.
