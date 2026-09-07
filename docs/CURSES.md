# Deterministic curse composition

Curses are durable negative modifiers selected outside the deterministic game
engine. The engine receives only an already-active catalog entry and applies it
at the command timestamp. Reaching a curse deadline removes it before the
command settles.

| Key | Lifetime | Deterministic effect |
| --- | ---: | --- |
| `burden` | 24 hours | multiply fired-shot fatigue gain by 2 |
| `confusion` | 24 hours | divide final hit experience by 2 |
| `decay` | 24 hours | reduce weapon reliability by 33 percent |
| `frenzy` | 4 hours | consume up to 2 rounds, double damage and fatigue gain |
| `one_armed` | 3 hours | block explicit reload commands |
| `slowness` | 4 hours | defer shot and reload commands by exactly 5 seconds |
| `tremor` | 24 hours | reduce base shot accuracy by 25 percent |
| `unerring_miss` | 4 hours | require an injected incident for any fired miss |

## Numeric order

All percentages use integer arithmetic. Decay first reduces the reliability
remaining after the injected base jam risk; sand and grease then modify the
resulting risk. Tonic and tremor modify base accuracy, glare halves it, and the
scope bonus is added last. Ammunition selects base damage before frenzy doubles
it. Lucky-charm experience is added before confusion divides the total.

Burden and frenzy multiply the caller-injected centi-point fatigue gain. A
fired shot applies both multipliers, caps the profile at 100.00 and exposes the
settled delta in its primary outcome. A trigger that jams, is sabotaged, is
locked or is otherwise blocked does not add fatigue.

## Deferred commands

Slowness does not block the event loop. The first shot or reload transition is
side-effect free and emits an exact `defer_until_ns`. The future runtime may
resubmit the same command at that timestamp with an explicit `delay_settled`
flag. Both intents are canonical replay data; recovery never sleeps or derives
a deadline from wall-clock time.

Unerring miss likewise keeps external selection outside the engine. If the
settled accuracy and target state would miss, the shot intent must contain the
complete incident chain. Missing data rejects the transition before ammunition,
effects or fatigue change.
