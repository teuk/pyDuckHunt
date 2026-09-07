# Runtime clock, schedule and operator loop

DH021 connects the durable daily schedule to a concrete process clock without
moving clock or entropy reads into the game engine.

## UTC-compatible monotonic timeline

`SystemRuntimeClock` samples the operating-system monotonic clock and wall clock
once. Later values advance only by monotonic deltas, projected onto the sampled
UTC-compatible epoch. A wall-clock correction during the process therefore
cannot move game time backwards. Startup fails before connection if that
projected time precedes the recovered durable state.

## Daily schedule adapter

`CalibratedScheduleSource` draws 24, 21 or 18 distinct hours without replacement,
one minute for each hour, the unchanged one-in-eighteen target kind and golden
health when required. Every draw passes through the existing bounded integer source.

`RuntimeSchedulingAdapter` installs the current UTC-day plan through a replay
event, preserves an already recovered plan and dispatches its next durable tick.
A poll arriving no more than one second late may retain the exact scheduled
timestamp. A later poll consumes the missed deadline without a catch-up flight.
An active flight similarly consumes the exact slot without drawing target
entropy. Public flight output uses the same bounded priority sink as commands.
The active flight's exact expiration is considered before the next schedule
slot, so the five-minute escape needs no player command to advance time.

When `game.anti_cheat` is enabled, the operator composes a
`RandomizedFlightAppearanceSource` from the live `SystemIntegerSource`. The
adapter draws presentation only inside the renderer for an accepted
`FLIGHT_STARTED` transition. Schedule installation, missed slots, active-flight
skips and bookkeeping transitions consume no appearance entropy. The live
source ultimately uses `secrets.randbelow`, avoiding predictable process-local
pseudo-random state and modulo bias.

Appearance entropy is deliberately presentation-only and is not journaled.
Recovery therefore preserves every mechanical decision while a future visual
line remains unknowable until its flight is actually emitted.

The adapter does not invent a policy for uncalibrated unusual loot, incidents
or IRC membership. Translation of durable purchased channel actions remains a
separate later boundary.

## Explicit operator loop

`OperatorPilotRunner.run` is the only new connection-starting call. It requires
an already double-authorized `PilotRuntime`, the matching scheduling adapter and
an explicit `PilotControl`. A stop request is thread-safe and first-writer-wins.
It stops transport first, prevents reconnection, waits for the bounded transport
shutdown and then lets the shell drain persistence.

A stop requested before `run` closes the recovered runtime without opening a
stream. Keyboard interruption becomes an ordinary operator stop. Unexpected
runner failures force the existing bounded stop deadline before the error is
re-raised.

DH022 adds a foreground command-line launcher behind a separate side-effect-free
preflight and exact target confirmation. It adds no daemon, service file or
automatic invocation. Automated coverage uses injected clocks and a local
`socketpair()` only.
