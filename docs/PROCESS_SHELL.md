# Process shell and application bridge

DH019 adds the final process-neutral composition layer before a controlled IRC
pilot. It is an injectable component, not a command-line activation path or a
service definition.

## Input boundary

`IRCGameBridge` receives already-parsed messages exposed by a ready transport.
It accepts only `PRIVMSG` commands addressed to one configured channel. Notices,
tag-only messages, private messages, unknown commands and other channels are
ignored. Known commands with invalid public syntax receive one bounded response
without creating a replay record.

The bridge reads no clock, random source, member list or secret. Its caller
injects the monotonic timestamp and an event resolver. That resolver turns the
current immutable state and exact command context into one fully settled
`ReplayEvent`.

## Settlement boundary

Before dispatch, the bridge verifies that the replay event preserves:

- the injected timestamp and RFC1459 actor identity;
- the parsed command kind, alias and arguments; or
- for a purchase, the exact numeric item and optional target.

Only runtime command and runtime purchase events are accepted, so durable
throttle windows cannot be bypassed. Shot rolls, incidents, loot, variable
magnitudes, charged costs, deadlines and target presence remain explicit
settlements. The process observer consumes only forwarded membership facts;
after a complete NAMES reply, that roster supplies target presence and the
calibrated live incident boundary. Unusual-loot policy remains disabled.

## Output boundary

Transition outcomes and read-only query projections share the four-line render
limit. The orchestrator reserves persistence first, then the socket adapter
atomically reserves space for the entire IRC response batch. A capacity failure
cancels the transition reservation and leaves state unchanged. The adapter
flushes queued bytes through its existing non-blocking partial-write path.

## Lifecycle guard

`ProcessShell` is single-owner and accepts monotonic timestamps. Startup fails
before connector use unless its explicit activation guard is true. The caller
must pass the validated `game.enabled` value; the sample configuration remains
false.

Shutdown stops command admission and IRC transport first. `QUIT`, peer closure
and the exact transport timeout retain their existing behavior. Persistence is
drained and the final snapshot is written only after transport reaches
`stopped`. An application failure is latched as a bounded category and enters
the same shutdown path without exposing exception text.

Automated coverage uses injected byte streams and local `socketpair()` peers.
It performs no DNS lookup, public TCP connection, service action or production
activation.

The development pilot builder adds an independent exact endpoint and channel
allowlist on top of `game.enabled`. It returns the composed shell before
`start`, so recovery and wiring can be reviewed without dialing anything.

The DH021 operator runner is a separate direct-call boundary. It starts only a
successfully built pilot, schedules only after IRC reaches `ready`, and converts
an explicit control request or keyboard interruption into the existing
transport-first shutdown. DH022 adds a foreground CLI only after a no-I/O
preflight and exact live-target confirmation. The later service wrapper reuses
that exact boundary and only translates `SIGTERM` or `SIGINT` into a control
request; the shell itself still owns no signal or daemon policy.
