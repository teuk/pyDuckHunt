# Controlled systemd service candidate

The repository contains a service candidate for the approved unprivileged
`mediabot` account and the existing pilot state. Merely checking out, building
or validating the project cannot install, enable or start this unit.

## Authorization boundary

`pyduckhunt@.service` reads one root-controlled environment file named after
the systemd instance. That file supplies the same explicit target allowlist as
`pilot-check` and a separate literal confirmation for `service-run`.

The shipped example is deliberately unusable: it names a placeholder endpoint
and its confirmation is `DISARMED`. A reviewed rollout must replace both values
with the exact application configuration and the complete confirmation printed
by a successful preflight. No password belongs in this file; the IRC password,
when required, remains in the separately protected environment named by the
application configuration. If that password is needed, it belongs in the
optional root-only `/etc/pyduckhunt/INSTANCE.secret.env`, not in the target
authorization file.

## Shutdown contract

`service-run` installs handlers for `SIGTERM` and `SIGINT` on the main thread.
Either signal requests the same transport-first bounded stop used by the
foreground pilot: IRC output is drained, the socket is closed and persistence
writes its final snapshot before the process returns. The original signal
handlers are restored after the run. A wrong confirmation is rejected before
handlers, runtime files or network streams are opened.

The unit gives this sequence 15 seconds. A clean operator stop exits zero and
is not restarted; an actual runtime failure is subject to the bounded
`Restart=on-failure` policy.

## Filesystem boundary

The service runs as `mediabot` with a read-only home and system tree. Its only
write exceptions are the existing durable state and pilot transcript
directories:

- `/home/mediabot/pyduckhunt-pilot/state`
- `/home/backupwws/pyduckhunt/pilot`

The source, application configuration and systemd authorization remain
read-only to the service sandbox. The unit also removes capabilities, prevents
privilege escalation and restricts address families to Unix, IPv4 and IPv6.

When `[partyline]` is enabled, the same service process owns its configured TCP
listener and temporary DCC sockets. The existing address-family policy already
permits both; no capability is added. The beta keeps the permanent listener on
loopback, while a configured DCC range remains an explicit host-firewall
decision. Its private credential database stays below the existing durable
state write exception.

The optional ranking spool remains below the already authorized pilot tree.
Coin never needs a write exception for the Apache document root. The separate
`pyduckhunt-ranking-publish.path` watches the atomic spool directory. Its
hardened root `oneshot` reads the exact source and destination files from
`/etc/pyduckhunt/ranking-publish.toml`, validates the generated HTML and
copies only that page into its dedicated public route as `root:root`.
It retains an empty capability set and uses only the supplementary `mediabot`
group to cross the private spool's existing `0750` directory boundary.
Its one-second `ExecStartPre` window coalesces rapid atomic spool replacements;
the explicit 45-start/30-second ceiling remains enabled as a defensive guard
and therefore no longer trips during ordinary bursts of durable transitions.
Their exact contract and failure isolation are documented in
`docs/RANKING_PAGE.md`.

## Reviewed rollout outline

These are documentation steps, not actions performed by validation:

1. Re-run `pilot-check` against the exact intended destination.
2. Create `/etc/pyduckhunt/INSTANCE.env` as root, group-readable only by
   `mediabot`, and copy the exact printed confirmation into it. Refuse symbolic
   links and use a separate mode-`0600` secret environment only when required.
3. Verify the unit and environment paths without starting it.
4. Install the unit in `/etc/systemd/system`, run `daemon-reload`, then start
   the chosen instance without enabling it.
5. Prove IRC READY, command handling, durable recovery and graceful stop.
6. Enable the instance only after that separate foreground review passes.

The guarded rollout script will perform these steps explicitly and retain a
private rollback copy. DH037 only delivers and validates the candidate files.
