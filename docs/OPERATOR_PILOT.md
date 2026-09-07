# Foreground development pilot

The CLI exposes three explicit operator commands. Nothing runs from import,
package installation, an empty command line or the disarmed sample
configuration.

## Preflight

The check requires the configuration path and a second copy of the exact live
destination:

```bash
PYTHONPATH=src .venv/bin/python -m pyduckhunt pilot-check \
  --config /absolute/path/pyduckhunt.toml \
  --allow-host irc.development.example \
  --allow-port 6697 \
  --allow-tls \
  --allow-channel '#development'
```

It validates the TOML document, `game.enabled`, endpoint, ordered channels,
password value when present, runtime paths and recovery-directory access. It
prints the exact confirmation sentence for the next command. It creates no
directory, opens no journal or snapshot, performs no DNS lookup and opens no
socket.

Relative runtime paths are anchored to the configuration file's directory.
State and operator-log directories must be separate and may not cross symbolic
links. For the development host, the log directory can be configured below
`/home/backupwws/pyduckhunt`; pilot transcripts are created with mode `0644`.

## Explicit run

Repeat the exact target arguments and copy the complete confirmation printed by
the check:

```bash
PYTHONPATH=src .venv/bin/python -m pyduckhunt pilot-run \
  --config /absolute/path/pyduckhunt.toml \
  --allow-host irc.development.example \
  --allow-port 6697 \
  --allow-tls \
  --allow-channel '#development' \
  --confirm-live 'CONNECT ircs://irc.development.example:6697/#development AS pyDuckHunt'
```

`pilot-run` is the first command that may create runtime files and connect. It
runs in the foreground. `Ctrl-C` enters the existing transport-first bounded
shutdown, writes the final snapshot and reports the operator-log path.

During the run, privacy-safe `[LIVE]` facts report transport state changes,
READY acquisition, aggregate command dispositions, schedule dispatches and
fixed network-failure categories. They never copy IRC message text, player
identities or server credentials. The transcript ends with the same aggregate
summary. A clean stop without an observed READY state returns a non-zero status,
so an unreachable target cannot be mistaken for a reviewed pilot.

Every run appends the same safe facts to `pyduckhunt.log` beside its immutable
per-run transcript. At `DEBUG`, schedule state is emitted when it changes and as
one unchanged heartbeat every 30 minutes. Ignored IRC traffic is accumulated in
counters instead of producing one line per message.

## Service candidate

`service-run` requires the same application configuration, target allowlist and
literal confirmation as `pilot-run`. Its only additional behavior is to own
`SIGTERM` and `SIGINT` on the main thread and translate either signal into the
existing bounded stop request. It does not daemonize, install a unit or weaken
the live-target gate.

The repository systemd template invokes `pilot-check` as `ExecStartPre` before
`service-run`. Its separate per-instance authorization is disarmed by default
and is documented in `SYSTEMD_SERVICE.md`.

The development resolver treats membership as absent until the complete IRC
NAMES reply has synchronized the in-memory channel roster. It then uses that
same current roster for targeted purchases and the historically calibrated 5%
incident draw for each fired shot at an active flight. A selected incident
forces the miss path and writes its trigger and defenses to the private
application log. Incomplete membership still fails closed, and unusual loot
remains disabled.
