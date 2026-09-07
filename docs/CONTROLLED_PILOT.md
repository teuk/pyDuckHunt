# Controlled development pilot gate

DH020 prepared the development-only composition gate. DH021 added a direct API
runner. DH022 exposes it through a separately commanded foreground CLI, while
still adding no daemon, service unit or automatic connection.

## Double activation

A pilot build succeeds only when both independent inputs agree:

1. the validated application configuration has `game.enabled = true`;
2. an injected `DevelopmentPilotGate` is armed and allowlists the exact IRC
   endpoint and ordered channel set.

Placeholder `.invalid` endpoints can never be authorized. The builder receives
the gate itself and repeats authorization during composition, so a caller cannot
bypass the check by constructing an authorization value. It also rejects a
socket connector for any other endpoint.

## Side-effect boundary

`build_development_pilot` explicitly resolves the optional password mapping,
recovers the journal and snapshot, constructs the transport, socket adapter,
runtime, bridge and process shell, then returns that shell in `new` state. It
does not call `start`, dial, resolve DNS or join a channel.

Connection remains a later operator action on the returned shell.
`pilot-check` validates the same independent endpoint and channel allowlist but
does no recovery, file creation, DNS or socket work. `pilot-run` additionally
requires the exact confirmation sentence printed by the check before it may
compose and invoke `OperatorPilotRunner.run`. The sample configuration stays
disabled and points to a placeholder endpoint.

The runner refuses a recovered state ahead of its projected clock. A stop
requested before invocation opens no stream. Once running, operator control,
keyboard interruption and unexpected failure all converge on bounded,
transport-first shutdown.

The foreground command writes a redacted operator transcript with mode `0644`
under the configured log directory. The password value is never printed.

## Verification

Unit tests cover disabled switches, endpoint and channel mismatches, placeholder
hosts, foreign connectors and composition without stream use. One local
`socketpair()` integration test exercises the authorized composition through a
query response, journal append, transport-first stop and recovered final state.
Another local scenario drives the operator loop, installs a daily schedule and
stops it through explicit control. No automated test uses public network egress.
