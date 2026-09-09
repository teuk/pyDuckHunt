# Troubleshooting

Use the configuration and checkout belonging to the affected instance. Two bots
can share source while keeping different languages, state and IRC destinations.

## Installation and language

| Symptom | Check |
| --- | --- |
| Python or `venv` is missing | Install the [prerequisites](INSTALL.md#requirements), then run `./install.sh --check --language en`. |
| The installer refuses root | Run it as the unprivileged bot account; only system package installation needs root. |
| `Existing language differs` | The installer protects an existing configuration. Edit its existing `[game]` section and restart the instance; see [language changes](INSTALL.md#change-the-language-of-an-existing-instance). |
| Installation finished but the bot is absent | A fresh installation is disabled and starts no process. Follow [configure and start](INSTALL.md#configure-and-start). |
| A French sentence appears in English mode | Confirm which private configuration the process uses and that it was restarted. Custom announcements and external websites have their own language; see [scope](LANGUAGES.md#scope). Report untranslated built-in messages with the command and synthetic names. |

## Connecting and receiving replies

Run `pilot-check` with the exact configuration, server, port, TLS mode and
channels from [the installation guide](INSTALL.md#2-check-the-exact-target).
It opens no IRC connection. It requires `game.enabled = true` after the target
has been reviewed. Copy the complete printed confirmation into the launch command.

| Symptom | Check |
| --- | --- |
| Target or confirmation rejected | Configured fields and allowlist arguments must agree; repeat `--allow-channel` in configured order. Do not guess the confirmation. |
| TLS failure or no connection | Confirm the listener's TLS mode with the server operator. A plain listener needs `tls = false` and `--allow-plain`; do not disable verification on a TLS listener. |
| Connected but not ready | Look for `transport=ready connected=yes` in that instance's application log. Check nickname conflicts, channel access and any server authentication requirement. |
| No public answer to a query | Check private NOTICE messages in your IRC client. Profiles, inventory and Owner planning can arrive privately. |
| `duckplanning` is refused | It requires authenticated Owner access. A matching nickname alone grants no access; see [partyline setup](PARTYLINE.md). |
| Commands are throttled | Respect the stated retry delay. Avoid repeated retries while gathering a reproduction. |

Do not publish an Owner plan or use a live command that buys an item or launches
a duck just to gather diagnostics. Use a separate test channel for reproductions.

## Bread, duck calls and accuracy

Bread lasts up to one hour and remains present across flights; seeing it after
a duck is shot is expected. It affects attraction and extends new flight
lifetimes. A duck call requests an extra duck. Exact effects and private planning
are described in [channel items](CHANNEL_ACTIONS.md); neither item is a promise
that the next daily slot will move.

For changing hit chances, inspect fatigue and active equipment in your profile
and inventory. See [player profiles](PLAYER_PROFILE.md), [shop rules](SHOP.md)
and [shot mechanics](SHOT_ENGINE.md). A theoretical probability is not a promise
that a particular shot will hit.

## Updating and recovering

Stop the affected instance gracefully before taking a coherent backup of its
private configuration and complete state directory. Record the current commit.
Do not delete a journal or edit scores to make a recovery error disappear.
Preserve the original files and consult [persistence](PERSISTENCE.md).

If multiple services use one checkout, coordinate source updates and restart
each instance to load the same revision. Keep their state and credentials separate.
The shipped [systemd candidate](SYSTEMD_SERVICE.md) contains pilot-specific paths;
review those before using it elsewhere.

## Report a reproducible problem

Start with the [bug form](https://github.com/teuk/pyDuckHunt/issues/new?template=bug_report.yml).
Include the commit (`git rev-parse --short HEAD`), Python version, operating
system, `fr` or `en`, launch method, and a minimal command sequence with synthetic
identities. Give expected and actual behavior; exact player names are unnecessary.

Never attach a full private configuration, state directory, credential or raw IRC
transcript. Use the [private security channel](../SECURITY.md) for vulnerabilities.
