# Deterministic shop core

The shop is split into catalog, pricing and settlement. The observed 1–31
surface now has explicit nominal prices and deterministic boundaries.

## Supported catalog slice

| ID | Stable key | Nominal XP | Grant | Scope | Boundary |
| ---: | --- | ---: | --- | --- | --- |
| 1 | `single_round` | 7 | ammunition | player | direct |
| 2 | `reserve_magazine` | 16 | magazine | player | direct |
| 3 | `penetrating_ammunition` | 15 | effect | player | 24 hours |
| 4 | `explosive_ammunition` | 25 | effect | player | 24 hours |
| 5 | `weapon_return` | 40 | direct | player | confiscated weapon only |
| 6 | `weapon_grease` | 5 | effect | player | 24 hours |
| 7 | `targeting_scope` | 5 | effect | player | 6 uses; floor((100 − base accuracy) / 3) points |
| 8 | `infrared_lock` | 15 | effect | player | 6 uses or 24 hours |
| 9 | `suppressor` | 5 | effect | player | 24 hours |
| 10 | `lucky_charm` | 13 | effect | player | 24 hours |
| 11 | `sunglasses` | 5 | effect | player | 24 hours |
| 12 | `dry_clothes` | 9 | remedy | player | soaked state only |
| 13 | `bore_brush` | 6 | remedy | player | sand or sabotage only |
| 14 | `mirror_glare` | 5 | target effect | player | next fired shot |
| 15 | `weapon_sand` | 7 | target effect | player | next trigger pull |
| 16 | `soaked_clothes` | 10 | target effect | player | 1 hour |
| 17 | `weapon_sabotage` | 14 | target effect | player | next trigger pull |
| 18 | `life_insurance` | 8 | effect | player | 1 use or 7 days |
| 19 | `liability_insurance` | 5 | effect | player | 2 days |
| 20 | `duck_call` | 8 | scheduled action | channel | injected within 10 minutes |
| 21 | `channel_bread` | 4 | effect | channel | 1 hour per stack; retained at takeoff; +20s per piece |
| 22 | `duck_detector` | 4 | effect | player | next successful flight |
| 23 | `mechanical_duck` | 20 | scheduled action | channel | exactly 10 minutes |
| 24 | `espresso` | 5 | fatigue relief | player | up to 5 settled points |
| 25 | `coffee_thermos` | 10 | fatigue target | player | sets fatigue to -3.00; overexcitation |
| 26 | `raincoat` | 15 | effect | player | 24 hours |
| 27 | `strong_tonic` | 10 | target effect | player | 1 hour |
| 28 | `herbal_infusion` | 9 | target effect | player | 1 hour |
| 29 | `safe_conduct` | 15 | effect | player | 24 hours |
| 30 | `automatic_reloader` | 20 | effect | player | 24 hours |
| 31 | `purification_ritual` | 30 | direct | player | active curses only |

The two ammunition types share one exclusive group, so buying either replaces
the other. The channel effect stacks with independent deadlines. The lucky
charm is deliberately rerollable: every successful repeat purchase charges its
settled price, replaces the previous charm with the newly injected magnitude
and starts a fresh 24-hour deadline. The new value may be lower, equal or higher.
The replacement decision is recorded in new replay events, so a historical
duplicate rejected under the previous rule stays rejected during recovery.
Other effects reject a duplicate without charging the player.

Target effects require a known profile and carry the buyer's canonical identity
as their durable source. Glare and water additionally require the target to be
present. Sand and sabotage may be applied to an absent player only while that
player's weapon remains available. A duplicate target effect is rejected before
charging.

Sunglasses block glare without being consumed. Grease blocks sand and is
consumed. A raincoat blocks water without being consumed. Dry clothes remove an
existing soaked effect, while the bore brush removes sand and sabotage together;
both remedies reject an inapplicable purchase without charging. Buying grease
cleans existing sand, and buying a raincoat also removes an existing soaked
effect.

The targeting scope adds one third of the gap between the current level
base accuracy and 100%, rounded down to whole percentage points. It is not
random: base 67% gives +11 points, or 78% before other modifiers. Six uses and
the 5 XP price are unchanged. Existing equipped scopes use this formula for
new live shots, keeping their remaining uses. Level changes update the bonus;
fatigue, overexcitation, glare and other modifiers do not inflate it.
At 98–99% base accuracy the rounded bonus is zero, shown explicitly.

New purchases record the bonus after paying (including any level drop). Scope
loot uses the post-kill level. Old recorded magnitudes remain valid for legacy
replay. The lucky charm retains its random magnitude in the range 1–10.
An unaffordable lucky-charm reroll leaves the existing charm unchanged.

The duck call records an injected deadline within ten minutes. The mechanical
duck records an exact ten-minute deadline. A waiting detector is consumed only
when a new flight actually starts. Live bread instead remains active for its
whole one-hour lifetime and adds 20 seconds per piece to new flight lifetimes.
Adding or expiring bread redraws the 24 + active-bread plan, with the next time
preserved on addition and on partial expiry. New bread is limited to 20 pieces.
See `docs/CHANNEL_ACTIONS.md`.

Successful duck-call and bread purchases each add 2.00 to the buyer's temporary
karma modifier. Successful glare, sand, water and sabotage purchases subtract
2.00, including a self-targeted nuisance. Tonic and infusion subtract 2.00 only
when offered to another player. A rejected purchase changes no karma. The
modifier is bounded to ±100.00 and moves 0.12 toward zero every two hours.

Espresso records concrete fixed-point relief bounded by 5.00 and the current
profile. A newly purchased thermos sets fatigue to -3.00, at the unchanged catalog
price of 10 XP. Each point below zero costs three accuracy percentage points,
so -3.00 costs nine points. The purchase confirmation gives the before/after
values. This is a fixed target, not a ten-point reduction or a random draw.
Active endurance suppresses this penalty. Historical journal targets from 0.00
to 10.00 remain valid and replay unchanged using their recorded value. The tonic applies settled relief to a present target and reduces that
target's base shot accuracy by ten percent for one hour. The infusion adds up to
6.00 immediately and records that exact contribution for removal at its
one-hour deadline.

Automatic reload consumes one reserve magazine after a fired shot empties the
weapon; it never creates reserves and does not run for a jammed trigger pull.
Purification removes every active curse owned by the buyer atomically and is
rejected without charge when no curse is active.

Weapon return is rejected without charge while the player is already armed.
Life insurance is consumed by the first incident exposure and grants three
times the shooter's pre-settlement level. Liability insurance divides each
incident penalty by three using integer truncation. Safe conduct takes
precedence over liability insurance and waives both incident penalties and
confiscation for its lifetime.

## Atomic settlement

One purchase transition performs these checks in order:

1. expire effects and curses and dispatch actions due at the command timestamp;
2. resolve the catalog entry and validate its injected magnitude, deadline or
   fatigue relief or target;
3. resolve target presence and weapon prerequisites when required;
4. reject full direct grants, inapplicable remedies or a forbidden duplicate;
5. verify the available experience;
6. debit the concrete settled price;
7. grant, schedule, block, cleanse or remove the bounded state atomically;
8. apply any settled temporary-karma change;
9. emit one explicit purchase outcome.

The settlement accepts a concrete charge between zero and the nominal price so
future discount and voucher policies can remain outside the critical state
transition. Replay records that charge, any magnitude, action deadline and
fatigue settlement exactly.

Unsupported identifiers are rejected without creating a profile, charging
experience or changing effects. Runtime randomness, flight dispatch and curse
acquisition stay outside settlement.

The shot engine applies the two ammunition multipliers, weapon grease, the
limited-use sight, trigger lock, suppressor, reward modifier and all supported
shot-time nuisances. See `docs/NUISANCES.md` for their ordering contract.
Incident protections are settled by `docs/INCIDENTS.md`.

## Concise item confirmations and shot feedback

Scope purchase and loot confirmations show the price (for purchases), six uses
and current bonus; the formula remains documented here and on the shop page.
A missed shot says "Raté" regardless of ammunition, as in Tcl 2.11. Explosive
hits retain "BOUM" and triple damage. Explosive ammo remains a 24-hour effect;
an ordinary fired round is spent on a miss. Noise escape uses three cumulative
unsuppressed misses on the same standard duck, shared by all players. Golden
and mechanical ducks are immune; silencers and silent weapons prevent noise.
The lucky charm adds its stored bonus to the duck reward: a normal 10-XP duck
with a +6 charm awards 16 XP, unless another explicit effect modifies rewards.
