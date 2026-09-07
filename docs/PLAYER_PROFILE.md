# Player profile core

The player profile is part of the deterministic game state. Every change is an
immutable transition and can therefore be reproduced from the event journal.

## Progression

A regular hit grants 10 experience points. A golden target grants 12 points per
point of its initial health, while a mechanical target grants no base experience.
Points carry across level boundaries
and a single grant may cross several levels. The current calibrated target is:

| Displayed level | Target multiplier | Required progress |
| --- | ---: | ---: |
| 1–60 | 10 | `(level + 1) × 10` |
| 61–69 | 20 | `(level + 1) × 20` |
| 70–79 | 30 | `(level + 1) × 30` |
| 80–89 | 40 | `(level + 1) × 40` |
| 90–99 | 50 | `(level + 1) × 50` |

The spendable balance includes completed level bands and current progress.
Purchases and penalties can therefore cross downward level boundaries. A debit
never creates debt: penalties stop at a level-1 zero balance, while purchases
reject an insufficient total balance before changing state.

The profile also records the experience actually paid to successful shop
purchases. Shop credit is reported separately by purchase outcomes and does not
inflate this durable spent-experience total.

## Hunting sheet

`!duckstats` renders two semantic notices. The first contains total earned and
currently spendable experience, the calibrated level title, experience still
required for the next level, fatigue, karma, experience per duck and experience
spent. It continues with theoretical accuracy, effective firing accuracy,
base weapon reliability plus its karma modifier, armor, deflection, jam state
and durable jam/confiscation counts.

The second notice contains best time, regular and golden hits, misses, empty and
already-jammed trigger pulls, compulsive reloads, wild shots, accidents and the
number of shots that actually fired. It closes with received, fatal, deflected
and absorbed stray-shot totals. Effective accuracy is computed from fired shots
only; empty, jammed, sabotaged and locked trigger pulls are excluded. Weapon
jams and fired shots are independent durable counters.

## Ammunition

A new profile starts at level 1 with a six-shot machine gun and two reserve
magazines. Weapon type, accuracy, reliability, clip size, reserve capacity,
armor, deflection and experience penalties follow the maintained v3 level
table. Level bands change the weapon at 10, 20, 30, 40 and 60; arc and crossbow
shots are silent. Combat values beyond the published table use its level-100
boundary.

A valid reload requires an empty weapon, fills it and consumes exactly one
reserve magazine. Any remaining round refuses the reload, preserves both
ammunition and reserves, and counts as a compulsive reload; an empty reserve
cannot reload. Weapon capacity and reserve capacity are separate fields so
equipment can upgrade either one.
Crossing a weapon boundary changes both base capacities atomically while
preserving an already-earned positive reserve-capacity bonus.

The permanent extended magazine adds one round to the current and every later
weapon capacity from level 10. The permanent large ammunition bag adds one
reserve slot from level 20. Each upgrade is unique and appears in inventory;
finding it again does not stack another capacity bonus.

The 24-hour warrior amulet and 48-hour eternal variant make the reserve
temporarily unlimited. Manual and automatic reloads then work at zero stored
magazines without decrementing that stored count. Inventory displays the
reserve as `∞` while the effect is active.

Three exact ammunition recyclers use one replayed roll from 1 through 30 for
each trigger pull: the 24-hour model succeeds on 10 values, the 48-hour premium
model on 15, and the permanent level-20 military model on 3. A successful roll
consumes no round. When several variants overlap, the strongest active
probability applies.

A jammed weapon cannot fire. The failed trigger pull consumes neither ammunition
nor a limited-use sight. Reloading a jammed weapon clears the obstruction without
consuming a reserve magazine; a later reload follows the normal reserve rule.
Creating a new jam increments the durable jam count; pulling the trigger again
while the weapon is already jammed increments only the separate jammed-trigger
counter.

A confiscated weapon cannot shoot or reload. Its state and confiscation count
are durable; the calibrated weapon-return purchase clears only the active
confiscation flag.

## Inventory

Inventory stacks are unique and sorted by a stable lowercase item key. Adding an
existing key merges quantities; removing the last unit removes the stack.
Display names, effects, rarity and shop prices are not stored in the stack and
are supplied by the separate shop catalog.

The profile also carries the ordered eight-slot `DUCK HUNT` collection and the
number of ducks held during the current Europe/Paris calendar day. Inventory renders both facts
compactly. The bag becomes encumbered at six ducks and overloaded at eleven;
later fired shots receive respectively two or three times their base fatigue.
The 24-hour TARDIS bag suppresses that multiplier while leaving the count
visible. The next Paris midnight empties the bag and resets fatigue. Complete rules are
in `docs/COLLECTION_AND_CARRY.md`.

## Active effects

Effects live in game state rather than inventory. They carry a monotonic
identifier, their catalog identity, scope, activation time and either an exact
deadline, a remaining-use counter, or both. Player-scoped effects require an
existing canonical player owner. Channel-scoped effects have no player owner.

Advancing the game clock removes every effect whose deadline has been reached.
Consuming the final use removes a use-bounded effect immediately.

## Fatigue and curses

Fatigue is a durable fixed-point value from 0.00 to 100.00, stored as integer
centi-points. Every fired shot carries a replayed base gain. Burden and frenzy
multiply that gain in catalog order, the final value is bounded at 100.00, and
non-firing outcomes such as jams, sabotage and trigger locks add nothing.

Espresso records a concrete relief of at most 5.00. A thermos records the exact
post-purchase target from 0.00 to 10.00. A targeted tonic records its concrete
relief while adding a one-hour accuracy modifier. An infusion immediately adds
6.00, then removes its exact bounded contribution at the one-hour deadline
without crossing below zero.

Curses are distinct from shop effects. Each has a catalog key, monotonic
identifier, owner and exact deadline. All eight catalog entries now compose
inside shot, reload, reward, fatigue and command-timing transitions. Purification
still removes every owned active curse atomically. The complete rules are in
`docs/CURSES.md`.

## Cross-player statistics

Profiles persist incidents caused, shots received, deflections, armor
absorptions and deaths. One ricochet chain may touch several profiles, but all
updates remain inside the same immutable shot transition.

The profile also keeps a separate golden-hit counter. It advances only when a
golden target reaches zero health, independently of the general hit counter.

## Karma

Karma follows the historical TCL formula, represented exactly in integer basis
points. Let `good = 2 × hits` and `bad = wild shots + 3 × incidents caused +
0.25 × (empty shots + jammed-weapon shots + compulsive reloads)`. Base karma is
`100 × (good - bad) / (good + bad)`. An inactive profile is neutral at zero. A
miss while a duck is flying is not a wild shot; firing with no active duck is.
An empty trigger pull, trying to fire before clearing an already-jammed weapon,
and trying to reload while ammunition remains each have their own durable counter.

Successful duck-call and bread purchases add 2.00 temporary karma. Successful
glare, sand, water and sabotage purchases subtract 2.00; tonic and infusion do
the same when bought for another player. The modifier moves 0.12 toward zero at
each exact two-hour deadline. Effective karma is base plus modifier, bounded
from -100% through +100%.

The profile response displays the resulting value from -100% through +100%.
It also shows a non-zero temporary component separately. Positive karma biases
bush searches toward useful loot: junk becomes less likely and every useful
standard drop reaches twice its legacy threshold at +100%. Negative karma can
only increase the junk threshold in the current standard slice, up to twice the
legacy value. Positive karma halves the base weapon-jam risk at +100%, while
-100% doubles it within the absolute 100% bound. All adjustments use bounded
integer arithmetic and compose with the abundance amulet before the concrete
award is written to the journal.
