# Integration tests

Transport and persistence integration tests live here. The IRC transport uses
an in-memory fake peer that fragments byte streams, records emitted actions and
advances an injected clock. Local `socketpair()` tests exercise the real
non-blocking stream adapter without DNS, TCP egress or public endpoints. Real
network connections are forbidden in the automated test suite.

The process-shell scenario uses another local socket pair to cover registration,
one ready-channel command, bounded response output, asynchronous persistence,
transport-first shutdown and final recovery.

The controlled-pilot scenario additionally passes the exact double activation
gate, verifies that composition itself opens no stream, then uses a local socket
pair for one query, persisted response and clean recovered shutdown.

The operator-runner scenario uses another local socket pair and injected clock.
It proves that only direct invocation starts the stream, installs the durable
daily plan after readiness and obeys an explicit operator stop without DNS or
public network egress.

The operator-launcher scenario repeats that local boundary through the exact
confirmation gate and verifies the public `0644` transcript. CLI preflight
tests assert that no state, log or stream is created before confirmation.
