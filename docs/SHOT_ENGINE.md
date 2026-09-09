# Deterministic shot engine

The critical shot path contains no random generator. Its caller supplies one
`ShotAttempt` containing baseline probabilities, rolls and the already-resolved
noise policy. Probabilities use integer basis points from 0 to 10000; rolls use
the closed interval 1 to 10000.

New live settlement records `fatigue_penalty_bps`: three percentage points per
fatigue point above 12.00, using the pre-shot state, with active endurance
immunity and a 100-point cap. `game.accuracy.shot_accuracy` composes tonic,
tremor, glare, the scope bonus and this settled penalty in that order, then
clamps the result to 0–100%. The renderer uses the same calculation for the
current profile. Historical attempts without the optional penalty retain zero;
replay never recomputes their fatigue penalty using a newer policy.

Fired outcomes carry the applied penalty for an accurate `[fatigué]` status.
The marker does not claim fatigue caused a particular random miss or incident.
Jams, empty shots and other blocked attempts do not show a fired-shot marker.

## Settlement order

One shot command is settled in this order:

1. advance the monotonic clock and expire due state;
2. reject a confiscated weapon;
3. block hunting while a non-expired soaked effect is active;
4. reject an already-jammed or empty weapon;
5. if no target exists, apply a limited-use trigger lock before firing;
6. apply decay to reliability, then sand and one ordinary or permanent
   self-lubrication reduction to the resulting jam risk;
7. apply tonic, tremor and glare to base accuracy, then add the sight magnitude;
8. consume sand at the trigger pull and force a jam when sabotage is present;
9. on a random jam, preserve ammunition, sight, glare and fatigue state;
10. require an injected incident when unerring miss would otherwise miss;
11. on a fired shot, consume frenzy-adjusted rounds, the sight use and glare;
12. add the replayed fatigue gain after composing burden and frenzy multipliers;
13. when the preceding flight was killed no more than three seconds ago,
   classify the fired bang as late, retain its exact delay and apply no wild or
   incident penalty;
14. on an inaccurate shot, apply the injected noise decision unless suppressed;
15. on an accurate shot, apply ammunition damage and the frenzy multiplier;
16. keep a resistant target active until health reaches zero;
17. on the killing shot, add the target reward and any charm magnitude, then
   apply confusion;
18. increment the golden-hit counter only for a killed golden target;
19. apply one validated, already-selected loot award only to a standard kill;
20. on a miss, debit the injected miss and optional wild-shot penalties;
21. if an incident was injected, settle its complete ricochet chain atomically;
22. after a fired shot, refill an empty weapon from one reserve magazine when
   automatic reload is active.

The effective accuracy, jam risk, active ammunition item, damage, remaining
health and noise suppression decision are explicit outcome fields. Renderers
can therefore produce a response without reconstructing game logic or inferring
ammunition from damage modified by another effect.

## Replay boundary

The journal records target kind, maximum health, reward and every field of the
injected shot attempt, including its fixed-point fatigue gain and optional
nested loot award. Recovery replays those
concrete values. It never recomputes a
probability, chooses a new roll or decides again whether noise ends a flight.
Nested incident targets, defenses and penalties are recorded in the same command
intent. Target-effect purchases record their settled target identity and
presence fact; the active effect keeps its source identity.

The default attempt preserves the foundational behavior: no jam, full accuracy,
one point of damage, one fatigue point and no noise escape. This keeps earlier
deterministic tests valid while the future runtime supplies calibrated live
probabilities and gains.

## Deliberate exclusions

Channel attraction, rendering and flight scheduling have separate ordering
rules. Random target and loot selection remain outside this transition. The
engine accepts only a catalog-validated, already-selected target or award.

## Thermos and overexcitation

Live thermos purchases set fatigue to -3.00. Each point below zero costs three
accuracy points. Settlement records `overexcitation_penalty_bps` separately from
positive-fatigue penalties, using the pre-shot state; endurance suppresses it.
The engine applies only the recorded value. `[surexcité]` describes that shot
even if its subsequent fatigue gain reaches zero. No marker attributes a
specific miss to this one modifier.

## Calculated scope bonus

New live shots with an equipped scope record `scope_bonus_points`, including
zero. The formula is floor((10000 - base_accuracy_bps) / 300), giving whole
percentage points. It uses pre-modifier base accuracy, then adds the bonus
after tonic, tremor and glare, before fatigue penalties. A successful trigger
still consumes one of the six uses; blocked and jammed attempts keep their
existing consumption rules. A level change changes subsequent scope bonuses.

A missing field retains the stored historical scope magnitude, so old replay
outcomes are never recalculated. An override has no effect without a scope.
