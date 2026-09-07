# Architecture

pyDuckHunt separates latency-sensitive decisions from slower operational work.

## Critical path

1. Receive and timestamp the IRC message.
2. Resolve the player identity.
3. Apply the command in one deterministic event loop.
4. Emit the priority response.
5. Queue persistence and secondary output.

No external HTTP call, AI provider, full-file scan or synchronous database
query belongs before the priority response.

## Layers

- `game`: immutable state, deterministic rules and explicit outcomes.
- `rendering`: pure profile, inventory, shop, ranking and outcome projections.
- `irc`: strict framing, process-neutral connection state and TCP/TLS adapters.
- `configuration`: strict TOML decoding and explicit secret resolution.
- `persistence`: journal, snapshots and recovery.
- `runtime`: process lifecycle and orchestration.

The protocol parser, transport state machine and game engine never open a
socket. The transport converts injected stream and clock facts into explicit
connect, send and close actions. A separate adapter executes those actions on a
non-blocking TCP or verified TLS stream. The guarded process shell timestamps
ready application messages and hands them to the single game event loop. Its
bridge accepts only configured-channel `PRIVMSG` commands and verifies that an
injected replay settlement matches the parsed actor, command, item and target
before dispatch. See `docs/IRC_TRANSPORT.md`, `docs/PROCESS_SHELL.md` and
`docs/CONFIGURATION.md` for the operational boundaries. Concrete runtime
settlement and the development-only destination gate are specified in
`docs/SETTLEMENT_ADAPTERS.md` and `docs/CONTROLLED_PILOT.md`.
The foreground command boundary and its no-I/O preflight are documented in
`docs/OPERATOR_PILOT.md`.

The rendering layer consumes immutable state and settled outcomes. A public
command can produce at most four response lines, and the IRC boundary shortens
each line at a valid UTF-8 boundary using the exact target-specific byte
budget. See `docs/RENDERING.md` for the player-facing contract.

Persistence receives replay intents only after the priority response has been
queued. A bounded slot is reserved before the transition, so a full persistence
queue rejects the command without changing game state. The background worker
independently replays each accepted intent and owns journal and snapshot I/O.
Its append-only journal, atomic snapshots and deterministic recovery are
specified in `docs/PERSISTENCE.md`.

The calibrated behavioral suite composes those boundaries into synthetic
multi-event traces. It replays every trace from a snapshot taken at every event
cut and verifies the same terminal state plus bounded IRC rendering. Private
observation logs are not fixtures. See `docs/BEHAVIORAL_REPLAY.md`.

## Runtime ownership

The process-neutral runtime has one event-loop owner and one persistence owner.
Only the event-loop owner may apply a public transition or enqueue a priority
response. Only the persistence worker may append the journal or write a
snapshot. Startup recovery completes before either owner accepts input, and
clean shutdown drains accepted intents before writing the final snapshot. See
`docs/RUNTIME_LIFECYCLE.md` for the lifecycle, backpressure and failure rules.

The current shell composes the non-blocking adapter and game bridge on that
event-loop owner. It may also compose one non-blocking partyline whose local
TCP, DCC and IRC-bootstrap inputs all converge on one authentication and command
dispatcher. Read-only views consume immutable state; administrative mutations
enter the same replay/persistence boundary as public commands. See
`docs/PARTYLINE.md`.

The development pilot builder first requires configuration
activation plus an exact injected destination allowlist, then returns an
unstarted shell. The operator runner starts only that authorized shell, drives
its clock and durable daily schedule, and accepts a thread-safe external stop
request. No such process policy is hidden inside the deterministic transport or
game layers. The CLI can invoke it only after a separate no-I/O preflight and an
exact literal target confirmation; no service invokes it automatically.

## Player state

Player profiles are immutable values inside the game state. Progression,
ammunition reserves and inventory operations are pure functions, so a live
transition and a recovered replay produce identical profiles. Inventory entries
use bounded stable keys rather than display text; the later rendering layer may
localize those keys without changing persistence.

Shop commands cross a settlement boundary only after pricing has produced a
concrete charge and any variable magnitude has been injected. The journal keeps
those concrete values, never an instruction to roll them again. Scheduled
deadlines, fixed-point fatigue changes and settled thermos targets follow the
same rule. Direct grants,
player effects and channel effects are committed atomically with the experience
debit. Every active effect has a monotonic identifier and is bounded by a
deadline, a use count, or both.

Target effects add a source identity and settle against an injected presence
fact. The engine can therefore attribute later glare, sand, water and sabotage
outcomes without consulting IRC membership during replay. Countermeasures and
remedies are applied inside the same immutable purchase transition. See
`docs/NUISANCES.md` for the interaction matrix.

Shot settlement receives integer baseline probabilities and already-generated
rolls. The game engine applies active equipment, consumes bounded uses, updates
target health and emits the effective values in its outcome. The same complete
shot attempt is written to the replay journal; recovery never samples again.
See `docs/SHOT_ENGINE.md` for the ordering contract.

Flight type and loot selection follow the same entropy boundary. The caller
injects one validated standard, golden or mechanical target and, on an eligible
standard kill, at most one selected loot award. The engine persists the concrete
facts and never samples them during recovery. See `docs/RARE_EVENTS.md`.

Fatigue is stored in integer centi-points. A shot intent records its concrete
base gain, then active fatigue multipliers compose in the pure transition.
Slowness never sleeps inside the engine: the first command emits an exact
deferred deadline, and a later replay intent explicitly marks that deadline as
settled. See `docs/CURSES.md` for the complete modifier order.

An eligible fired shot may carry a fully injected incident chain, which forces
the miss path. The engine
debits miss and incident penalties, follows each deflection, applies armor,
settles insurance, updates both profiles and records any confiscation as one
immutable transition. The IRC runtime renders those outcomes but does not
automatically kick a fatal target; any such channel action remains a separate
operator-authorized policy. The runtime never decides the incident result.
See `docs/INCIDENTS.md` for the complete boundary.

## Clock and randomness

Production timing will use a monotonic high-resolution clock. Tests inject the
clock, and random policies must resolve their values before a transition
is journaled so every scenario is reproducible.

The concrete clock anchors one wall-clock sample to monotonic deltas, giving
daily UTC alignment without rereading an adjustable wall clock. The runtime
schedule adapter persists the generated plan before consuming it and applies a
bounded one-second lateness policy. See `docs/RUNTIME_ADAPTERS.md`.

The concrete runtime settlement adapter accepts an explicit integer source,
presence source and optional incident source. Its operating-system integer
adapter is inclusive and bounded; deterministic tests inject finite sequences.
Uncalibrated unusual loot and incident frequency remain disabled.

Current state transitions reject backward time, expire flights and effects at
their exact deadlines, dispatch due channel actions, expire curses, and allocate
strictly increasing identifiers. Shot rolls and variable action deadlines are
injected and replayable. Random selection remains deliberately outside the game
engine. The runtime layer persists the complete daily plan, consumes missed
deadlines without catch-up bursts and records the concrete target selected at an
exact tick. It also applies durable rolling command windows before public game
or shop transitions. See `docs/CHANNEL_ACTIONS.md` and
`docs/RUNTIME_POLICY.md` for the scheduler and admission boundaries.
Standard loot selection receives a complete tuple of injected rolls and returns
the first catalog success.
