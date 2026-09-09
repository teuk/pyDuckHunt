# Install and run pyDuckHunt

pyDuckHunt is beta software. Install the reviewed `main` branch; there is no
published tag or GitHub Release yet.

## Requirements

- Git and Python 3.11 or newer, including `venv`;
- network access if `pip` needs the declared build backend;
- an IRC server and a channel where you are allowed to run the bot.

On Debian, install prerequisites as root:

```bash
apt update
apt install --yes git python3 python3-venv
```

Run all remaining commands as the unprivileged account that will run the bot.

## Install in English

```bash
git clone https://github.com/teuk/pyDuckHunt.git
cd pyDuckHunt
./install.sh --language en
```

The installer creates `.venv`, installs the checkout in editable mode, and
creates `config/pyduckhunt.toml` with mode `0600` if it does not already exist.
The new file has `game.language = "en"`, is disabled and uses an invalid example
server. Installation does not connect to IRC or start a service.

Use `--language fr` for French. Omitting the flag defaults to French for a new
configuration and preserves the language of an existing one. An explicit
conflicting choice fails before installation changes any files.

To check prerequisites without installing or writing configuration:

```bash
./install.sh --check --language en
```

## Configure and start

### 1. Edit the private configuration

Open `config/pyduckhunt.toml`. Set the following fields in its **existing**
sections; keep the other required settings from the generated example:

| Section | Fields to review |
| --- | --- |
| `[irc]` | `host`, `port`, `tls`, `nickname`, `fallback_nickname`, `channels` |
| `[runtime]` | Separate `state_directory` and `log_directory` for this instance |
| `[game]` | `language = "en"`; set `enabled = true` once the target is reviewed |

Use `tls = true` for a TLS listener and `tls = false` for a confirmed plain IRC
listener. Match the server's actual port; a port number alone does not prove TLS.
If a server password is required, supply the environment variable named by
`password_environment`. Do not put the password in the TOML file or command line.

`enabled = true` is required by `pilot-check`. Changing this value alone does
not connect: a separate launch command is still required.

### 2. Check the exact target

The following is a **template**: replace the server, port and channel with the
same values you entered in the configuration. Use `--allow-plain` instead of
`--allow-tls` when `irc.tls = false`.

```bash
.venv/bin/pyduckhunt pilot-check \
  --config config/pyduckhunt.toml \
  --allow-host irc.example.net \
  --allow-port 6697 \
  --allow-tls \
  --allow-channel '#duckhunt'
```

Repeat `--allow-channel` for every configured channel, in the same order.
The check validates the configuration and target without opening a connection
or creating runtime files. It prints a complete line beginning with `CONNECT`.

### 3. Start in the foreground

Repeat the same arguments with `pilot-run`, adding the **complete confirmation
printed by your check**. This example assumes the nickname is `pyDuckHunt`:

```bash
.venv/bin/pyduckhunt pilot-run \
  --config config/pyduckhunt.toml \
  --allow-host irc.example.net \
  --allow-port 6697 \
  --allow-tls \
  --allow-channel '#duckhunt' \
  --confirm-live 'CONNECT ircs://irc.example.net:6697/#duckhunt AS pyDuckHunt'
```

For plain IRC, the confirmation starts with `CONNECT irc://`. Use the printed
value rather than guessing it. Wait for `transport=ready connected=yes`, then
try `!shop`, `!duckstats` and `!inventory` on your channel. Press `Ctrl-C` for a
graceful stop that preserves state.

For a background service, see [systemd setup](SYSTEMD_SERVICE.md). For Owner
access and private planning, see [partyline setup](PARTYLINE.md). These are
separate, explicit setup steps.

## Change the language of an existing instance

Edit the existing `[game]` section of the private configuration used by that
instance, which may be outside the repository:

```toml
language = "en"
```

Restart only that instance. Use `"fr"` to switch back; a missing field means
French. The language changes messages, not rules, scores, objects or deadlines.
Do not create a second `[game]` section or replace the whole configuration.
See [languages](LANGUAGES.md) for shared-source FR/EN pilots.

## Update an installation

Gracefully stop the instance and back up its private configuration and durable
state. From the same checkout:

```bash
git pull --ff-only
./install.sh
```

The existing language is preserved. Review [CHANGELOG.md](../CHANGELOG.md), then
restart the instance. If several services use this checkout, restart each to
load the updated source while keeping their configurations and state separate.
