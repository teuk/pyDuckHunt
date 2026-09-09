# Runtime settlement adapters

The game and replay layers accept concrete facts; they never read randomness,
IRC membership or environment state. `CalibratedEventResolver` is the explicit
single-owner boundary that turns a validated public command into one complete
runtime replay event.

## Injected sources

The resolver receives three narrow sources:

- an inclusive bounded integer source for shot rolls, item magnitudes, action
  deadlines and ordered standard-loot rolls; thermos targets are fixed at -300
  centi-points and need no entropy;
- a channel-presence source used only by targeted purchases;
- an optional incident source returning a complete incident chain.

`SystemIntegerSource` is the concrete operating-system entropy adapter. It
checks both requested bounds and the result returned by its backend. Tests use
finite deterministic sequences instead.

## Settled commands

Read-only queries and non-shot commands require no entropy. Purchases record the
current discounted price and every catalog-required value. Targeted items also
record the exact nickname and injected presence fact. Supplying a target to an
item that cannot accept one yields one bounded public rejection and no replay
record.

Shots derive foundational accuracy, weapon reliability, miss penalty, wild-shot
penalty and silent-weapon behavior from the shooter's current level, then apply
karma to the resulting base jam risk. A fired bang up to and including three
seconds after a kill is a late shot: it records the precise millisecond delay,
pays only the miss penalty and cannot become a wild shot or incident.
New live attempts record the Tcl 2.11 threshold of three noisy misses.
The counter belongs to the active duck and is shared by shooters; each real
unsuppressed miss counts once, including incident-forced misses. A standard
duck escapes at the threshold. Golden and mechanical ducks are immune to
noise escape. Silencers and level-granted silent weapons do not add noise;
hits, empty/jammed/blocked triggers and late/wild shots do not add misses to
the active duck. Explosive ammunition counts as one miss, like ordinary ammo.
No random noise-escape draw is made. Old attempts without this threshold retain
their recorded escape decision and do not acquire a new counter on replay.
When the player owns an active ammunition recycler, the resolver injects one exact roll from 1 through 30 into the shot
event. Explicit policy values remain available as bounded test or simulation
overrides. An eligible
standard kill draws the complete catalog roll tuple in fixed order and records
at most one selected award, including a required magnitude. A caller may inject
a complete incident settlement; a curse that mandates an incident fails safely
when that adapter is unavailable.

The live operator enables the historically observed incident decision for every
fired shot at an active flight: four incidents in the 79 real `!bang` commands
of the retained historical reference trace, represented by a five-percent draw.
A selected incident turns the otherwise accurate or inaccurate bang into its
required miss. Selection runs only after the channel's complete IRC NAMES
reply. It chooses from currently present members, excludes the shooter and bot,
and records every target and defensive roll before replay. The private runtime
log also records the selected trigger and defense values so an operator can
explain the event without disclosing credentials or raw channel membership.
Missing or incomplete membership fails closed without an incident. Unusual-loot
frequency remains disabled; a caller cannot enable it through the foundational
policy.

## Replay boundary

The resolver may preview a pure transition to determine whether a standard kill
is eligible. It does not mutate runtime state. The bridge still validates actor,
timestamp, command, item and target before the orchestrator reserves capacity
and commits the event. Recovery consumes only the recorded concrete values and
never invokes a settlement source again.
