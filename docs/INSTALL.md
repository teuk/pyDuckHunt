# Installing the pyDuckHunt beta

pyDuckHunt is beta software. There is no published tag or GitHub Release yet;
the supported installation source is the latest reviewed `main` revision.

## Requirements

- Git;
- Python 3.11 or newer;
- the Python `venv` module;
- network access when `pip` needs the declared build backend.

On Debian 12 or 13, install the platform prerequisites as root:

```bash
apt update
apt install --yes git python3 python3-venv
```

Then switch to the unprivileged account that will run the bot. Do not run the
project installer as root:

```bash
git clone https://github.com/teuk/pyDuckHunt.git
cd pyDuckHunt
./install.sh
```

The installer creates `.venv`, installs the checkout in editable mode and
creates `config/pyduckhunt.toml` with mode `0600` only when that file is absent.
The copied configuration remains disabled and uses reserved `.invalid`
destinations. Re-running the installer preserves an existing configuration.

Use the read-only prerequisite check whenever needed:

```bash
./install.sh --check
```

## First configuration

Edit `config/pyduckhunt.toml` and keep `game.enabled = false` while reviewing
the IRC destination, nickname, channels, state and log directories. Store an
optional IRC password in the environment variable named by
`password_environment`; never put the password in TOML or on the command line.

Run the exact preflight described by the CLI before enabling the game:

```bash
.venv/bin/pyduckhunt pilot-check \
  --config config/pyduckhunt.toml \
  --allow-host irc.example.net \
  --allow-port 6697 \
  --allow-tls \
  --allow-channel '#duckhunt'
```

The preflight makes no connection and prints the literal confirmation required
for a foreground beta run. Enable the game only after reviewing that complete
target. The repository never launches the bot automatically.

## Updating the beta

Stop the operator-controlled bot first, preserve the ignored configuration and
durable state, then update and reinstall:

```bash
git pull --ff-only
./install.sh
```

Review `CHANGELOG.md` before restarting. The optional systemd candidate is an
advanced, separately authorized deployment boundary; it is not installed by
`install.sh`. See [Controlled systemd service candidate](SYSTEMD_SERVICE.md).
