# Deterministic cross-player incidents

An incident is part of the shot transition that caused it. The engine receives
an ordered, bounded target chain with integer deflection and armor probabilities,
their already-generated rolls, and concrete experience penalties. It never
selects a nickname or samples randomness.

The live settlement adapter performs one five-percent draw for each otherwise
valid fired bang while a flight is active. This reproduces the retained
historical sample (4 incidents / 79 bangs). Selection forces the shot onto the
miss-and-incident path; fatigue is accumulated independently and never causes
an accident. A selected event is summarized in the private application log with
its trigger, target and defense rolls.

## Settlement order

1. debit the miss penalty and the wild-shot penalty when no flight existed;
2. resolve safe conduct and liability insurance from active shooter effects;
3. confiscate the weapon once unless safe conduct is active;
4. for each injected target, debit one incident penalty from the shooter;
5. increment shooter and target counters;
6. pay and consume single-use life insurance before defense resolution;
7. compare deflection first, then armor;
8. continue only after deflection, stopping after absorption or a fatal result.

Safe conduct and the permanent killing license waive incident penalties and
confiscation but do not waive the miss or wild-shot penalty. The permanent
license is a unique level-30 inventory fact and never expires. Liability
insurance divides every incident penalty by three with integer truncation. Life
insurance grants three times the shooter's level captured before settlement and
is consumed even when the target deflects or absorbs the projectile.

## Outcome boundary

Each exposed target produces one explicit outcome: deflected, absorbed or
fatal. It carries the target, ricochet index, defense values, settled penalty,
insurance award and whether confiscation or protection applied. A renderer can
therefore describe the event without re-running game rules.

A fatal outcome is only an instruction for the future runtime. Network actions
remain outside the game engine and must follow channel policy and bot authority.

## Replay boundary

Schema 5 stores every target and roll inside the command event and persists all
profile counters plus confiscation state. Recovery reproduces the complete
chain exactly. Raw channel membership and message text never enter durable game
state.
