# Persistence and recovery

pyDuckHunt uses a versioned append-only journal and periodic atomic snapshots.
Both formats contain only game state and synthetic identifiers; runtime secrets
and raw IRC traffic never belong in either format.

Shot attempts may include `fatigue_penalty_bps`, an integer from 0 to 10000.
New live settlement records nonzero penalties; zero is omitted so previous
canonical event bodies and their digest chains remain byte-for-byte stable.
Missing values decode to zero and preserve historical outcomes. No snapshot
field, player counter or existing journal entry is rewritten by this change.
Once a nonzero penalty is journaled, recovery requires this reader or a newer
compatible one. An installer must not restore an older reader after the durable
state has advanced; preserving new gameplay takes precedence over source rollback.

## Priority boundary

Disk durability is deliberately outside the latency-sensitive response path.
The runtime follows this order:

1. reserve one bounded persistence slot without waiting;
2. apply the deterministic transition;
3. enqueue the priority response bytes;
4. expose the new immutable state;
5. submit the replay intent to the persistence worker.

If no slot is available, the command is rejected without a state transition or
journal request. The persistence worker owns journal appends, `fsync` and
snapshots. Startup recovery remains synchronous and finishes before the runtime
accepts input. The worker must never call back into the response transport.

## Journal

Each canonical JSONL record carries a contiguous sequence, the previous record
digest and its own SHA-256 digest. Reads reject partial lines, schema drift,
sequence gaps, chain breaks and payload changes.

The journal writer is single-process. Each bounded record is emitted with one
`O_APPEND` write and may be synchronised with `fsync`.

## Snapshots

Snapshots contain the complete immutable game state plus the journal sequence
and digest they cover. A snapshot is written to a private temporary file,
flushed, synchronised, atomically replaced, then followed by a directory
`fsync`.

Recovery validates the complete journal chain, checks that the snapshot belongs
to that chain, and replays only the uncovered tail.

The calibrated behavioral suite writes a snapshot at every possible boundary of
six synthetic multi-domain traces and requires identical terminal state after
recovery. This exercises complete-tail replay, current snapshots and canonical
event payloads without importing private IRC logs. See
`docs/BEHAVIORAL_REPLAY.md`.

New lucky-charm purchases may carry one bounded `replace_active_effect` replay
decision. The field is emitted only when replacement was authorized. Legacy
purchase records omit it and therefore retain their original duplicate
rejection during complete-journal recovery.

The background worker maintains its own replay state and writes periodic
snapshots from that state. Clean shutdown drains accepted intents and writes a
final snapshot when needed. The first append or snapshot error is latched,
fails queued tickets and prevents further admission. See
`docs/RUNTIME_LIFECYCLE.md` for the complete contract.

## Prerelease schema

Schema 21 adds `admin_channel_item` events for owner-provided bread and duck
calls. They preserve the authenticated owner handle, exact shop item and the
already-drawn call deadline, while deliberately carrying no player identity or
XP debit. Channel actions may therefore have no player source; schema 20 and
older actions retain their required player source unchanged.

Schema 20 adds exact fired-shot, newly-created-jam and spent-experience counters
to each player. Every source event already contains the deterministic shot or
purchase settlement needed to rebuild them, so recovery from a schema-19 or
older snapshot deliberately replays the complete append-only journal once. The
next atomic snapshot stores the reconstructed totals directly. A shop-credit
debit does not count as spent experience, and a rejected purchase, empty pull,
already-jammed pull or trigger lock cannot increment a successful settlement
counter.

Schema 19 records the canonical key of the last player whose shot actually
fired, plus an explicit permanent-confiscation flag on each player. Dedicated
`admin_weapon_control` events preserve the authenticated owner handle, target
and one of the bounded rearm, daily-unarm or permanent-unarm operations. Older
snapshots replay their complete journal, reconstructing the last shooter while
defaulting historical confiscations to daily recovery semantics.

Schema 18 adds replayable partyline player administration. Each accepted event
contains the authenticated owner handle, target player, bounded operation,
canonical field and settled integer value. It is admitted through the same
reservation and background worker as public game actions. Partyline credentials
remain in their separate private store and never enter game snapshots or the
journal. Older snapshots replay their complete journal before a schema-18
snapshot is written.

Schema 17 adds one durable last-flight record: identity, kind, start, exact end,
conclusion and optional actor. Hits, noise escapes and untouched five-minute
expirations therefore survive restart and make `!lastduck` independent of
process-local memory. Older snapshots replay their complete journal before the
next schema-17 snapshot is written.

Schema 16 adds the ordered eight-slot letter collection, daily carried-duck
count and canonical calendar-day marker to every profile. The marker now follows
Europe/Paris midnight without changing its persisted integer shape. Schema-15 and older
profiles migrate with an empty collection and bag anchored to the recovered
state time. Letter events may carry one bounded concrete completion bundle;
legacy three-field loot payloads remain canonical and decode unchanged.

Schema 15 adds the optional exact one-through-thirty ammunition-recycler roll
to replayed shots. Older shot events omit the field and decode it as no roll;
recovery from schemas 11 through 14 replays the complete journal so permanent
capacity upgrades and the new settlement boundary are rebuilt.

Schema 14 marks the level-policy correction. It keeps the same canonical player
fields, but recovery from schema 11 through 13 replays the complete journal so
the corrected level-70 boundary, starting ammunition and level-derived weapon
capacities are rebuilt rather than copied from an older snapshot.

Schema 13 completes the durable karma state. Alongside schema 12's wild-shot
counter it stores empty trigger pulls, attempts made with an already-jammed
weapon, compulsive reloads, the temporary shop modifier and its next exact decay
deadline. It still stores fatigue in integer centi-points, shop credit, the
golden-hit counter, complete flight identity, bounded reward effects and nested
post-kill loot awards. Shot gains, shop relief or targets, command-delay
settlement, scheduled channel actions and active curses remain explicit.

Runtime recovery adds the complete fixed 24-flight UTC-day plan, its next
unconsumed index and bounded command-window expirations. Schedule installation,
schedule ticks, public commands and public purchases have distinct replay
events. A tick carries the concrete flight selection when one was dispatched;
recovery never draws it again. Schema-11, schema-12 and schema-13 journal records
and snapshots remain strictly validated. Recovery from an older snapshot
replays the complete append-only journal once, then the next snapshot is written
in the current schema.

The asynchronous worker changes runtime ownership only. It does not change the
canonical event or snapshot field set.

## Negative fatigue and legacy thermos purchases

Players now admit fixed-point fatigue from -300 to 10000. New live thermos
targets are -300; explicit historical targets from 0 to 1000 remain accepted.
No existing journal payload or snapshot is rewritten. An optional shot field
`overexcitation_penalty_bps` (0..10000) is omitted when zero. Missing means zero,
including for old shots; it is never recomputed during replay. Old byte payloads
and hash chains retain their canonical form. Once negative fatigue or the new
shot field is written, keep this reader or a newer compatible reader.

## Calculated scopes without rewriting history

Shot attempts may contain `scope_bonus_points` (integer 0..33). Missing means
legacy stored effect magnitude; explicit zero means no bonus. Null is rejected.
Old payloads omit the field and retain their canonical bytes and journal hashes.
New live shots record the formula result, including for previously equipped
scopes. Existing snapshots/effect magnitudes and remaining uses stay unchanged.
Keep the new reader once an event containing this field has been written.

## Hourly bread rule (schema 22)

`enable_hourly_bread` activates the new rule at the current durable clock. It
changes no player, flight, effect, action or existing schedule. The optional
`bread_plan_effect_ids` state array is absent on historical states and present
on modern ones; an empty array means the rule is active with no bread in the
last plan. `with_player` preserves it. `replan_bread_schedule` records the exact
chosen day/times and derives its bread fingerprint from effects at event time.
It validates base-plus-bread count and retention of the nearest existing time.

Legacy schema-21 checkpoints need no rebuild, since the extension changes no
historical outcome. Older migrations retain their rebuild policy. New delayed
calls may remain overdue while blocked and are completed one by one only when
a matching flight succeeds; ordinary advances and bread replans retain them.
No live journal or snapshot is edited by the installer; activation is a new
normal journaled runtime transition after service start.

## Counted duck noise (schema 23)

New live shot attempts record `noisy_miss_limit=3`. Flight snapshots optionally
carry `noisy_misses`; it is omitted until a counted miss occurs. Both fields
are absent from old encodings, preserving historical event/state payloads.
Schemas 21 and 22 remain authoritative checkpoints. Recovery does not edit
scores, inventory, bread, schedules or active flight deadlines. A flight already
active at deployment starts its counter on the next eligible miss; earlier
noise is not guessed. Restart and replay retain subsequently recorded misses.
Old shot events still use their original `frighten_on_miss` decision.
