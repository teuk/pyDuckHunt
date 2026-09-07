# Runtime lifecycle

The process-neutral runtime keeps the game event loop free of journal and
snapshot I/O. It does not open sockets, start a service or choose production
process policy.

The IRC connection state machine is process-neutral too. One I/O owner
owns stream framing, registration, channel membership, timeout and reconnection
decisions. Its socket adapter executes only explicit connect, send and close
actions. The guarded shell now composes that non-blocking adapter, the optional
non-blocking partyline and the game event-loop owner; it does not daemonize,
install signals, open a service or select production entropy.

The controlled development builder requires both configuration activation and
an exact injected destination allowlist. It performs recovery and composition
through step 6, then returns an unstarted shell. The operator runner advances
that exact object only through an explicit call. The repository CLI reaches it
only after a no-I/O target preflight and an exact literal confirmation supplied
to a separate foreground command.

The service wrapper leaves the shell process-neutral. It owns `SIGTERM` and
`SIGINT` only on the main thread, translates either into the runner's existing
control request and restores the previous handlers after completion.

## Startup

Startup is synchronous and ordered:

1. load and validate configuration, then explicitly resolve any server password;
2. validate and recover the latest snapshot and journal tail;
3. construct the bounded persistence worker from the recovered boundary;
4. start the single persistence worker;
5. expose the recovered game state to the single event-loop owner;
6. construct the IRC transport, TCP/TLS adapter and optional partyline on the
   I/O owner;
7. start the configured partyline listener, failing startup if its exact bind is
   unavailable;
8. begin accepting public game input after registration and channel joins
   complete.

The shell enforces step 7 through the transport's `ready` state and separately
requires the explicit game activation guard. The repository sample leaves that
guard false.

Configuration validation creates no directory and opens no connection. Input
cannot race recovery because the orchestrator and IRC adapters do not exist
until recovery succeeds.

## Priority path

For one accepted replay intent, the event-loop owner performs this sequence:

1. reserve one persistence slot without waiting;
2. apply the pure transition and render its response;
3. place the complete wire-byte batch in the priority sink;
4. expose the new immutable state;
5. commit the replay intent to the background worker.

The worker independently replays every accepted intent before appending it. Its
private replay state is therefore the source for periodic and final snapshots.
It never calls the response sink or mutates the orchestrator state.

## Backpressure

Capacity covers reservations, queued requests and the request currently being
written. When no slot is available, reservation fails immediately. The
orchestrator may emit a bounded busy response, but it does not apply the event,
change state or create a journal request.

Rendering and priority-sink failures cancel the reservation and also leave game
state unchanged.

The IRC bridge validates the settled replay event before reserving persistence.
It rejects actor, command, item or target mismatches, so an external settlement
adapter cannot substitute a different durable intent for the parsed message.

## Failure

The first journal or snapshot error is latched. The current ticket and every
queued ticket fail, new reservations are rejected, and the runtime must stop
accepting input. A journal entry that preceded a failed periodic snapshot
remains recoverable from the journal tail.

## Shutdown

Clean shutdown stops admission, drains accepted requests in FIFO order, writes
one final snapshot when new state is not yet covered, and joins the non-daemon
worker thread. Open reservations make shutdown invalid because their outcome is
not yet known. Timeout values bound waiting; they do not abandon the worker.

Partyline and temporary DCC sockets close when shutdown admission begins. The
IRC transport then enters stopping before persistence is closed, emits one bounded
`QUIT`, and disables reconnection. Connection loss or the exact stop deadline
then moves it permanently to stopped. This contract is tested with an in-memory
IRC peer; no automated test opens a network connection.

Only after transport reports `stopped` does the shell drain and close the
persistence worker. Application exceptions are reduced to one bounded failure
category, stop admission and enter the same transport-first shutdown path.
The operator runner applies the same ordering to control requests and keyboard
interruptions. An unexpected runner failure forces the transport's existing
stop deadline before re-raising the original error.

The service wrapper applies that ordering to both supported process signals.
Its systemd candidate allows 15 seconds for transport and persistence shutdown
and restarts only after a non-zero runtime failure.

The foreground launcher records only target, configuration path, password
presence, recovered sequence and terminal category. Its operator transcript is
mode `0644`; secret values and IRC traffic are excluded.
