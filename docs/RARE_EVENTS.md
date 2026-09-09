# Rare targets and post-kill loot

Rare-event entropy is resolved before the pure game transition. The engine and
replay journal receive only concrete target and award facts.

## Target kinds

| Kind | Initial health | Base reward | Profile counter |
| --- | ---: | ---: | --- |
| Standard | positive | 10 xp | general hits |
| Golden | 3–5 | 12 xp × initial health | general and golden hits |
| Mechanical | 1 | 0 xp | general hits |

Target kind, initial health and reward are validated as one catalog boundary.
Current health may fall after a surviving hit, but the persisted initial health
and reward never change.

## Standard loot selection

The caller supplies one integer roll from 1 through 1000 for every standard
catalog entry. Entries are evaluated in fixed order and the first successful
threshold wins, so a kill can receive at most one award. A bounded multiplier of
one or two may scale thresholds before selection. Variable equipment magnitude
is also injected; the game does not draw it.

The calibrated catalog covers decorative junk, ammunition, reserve magazines,
the observed self-equipment subset and experience awards from 10 through 100.
The abundance amulet raises the bounded multiplier from one to two. Uncalibrated
unusual-reward frequency is intentionally left at zero in the sample
configuration rather than assigned an invented probability. A caller may inject
one already-selected unusual award; replay stores only that concrete fact.

## Observed unusual rewards

The unusual catalog includes vouchers worth 10, 20, 50 or 75 shop-credit
points; promotion coupons of 10, 25 or 50 percent for their observed 24-hour,
48-hour or seven-day variants; and abundance, endurance, blessing, baker and
prankster amulets. It also includes the observed ammunition family: 24-hour and
48-hour recyclers, warrior and eternal-warrior unlimited reserves, plus the
unique permanent extended magazine, large ammunition bag and military
recycler. Permanent protection variants add indestructible sunglasses, a
tearproof raincoat and military self-lubrication from level 20, then a permanent
killing license from level 30. The catalog also represents the seven letters of
the eight-slot `DUCK HUNT` phrase, decorative `Q`, and the 24-hour TARDIS bag.
These awards remain concrete injected facts; their sub-percent selection
frequency is not approximated.

Every catalog entry carries one non-persisted presentation tier derived from
the observed player-response contract. Discoveries append exactly one compact
marker when the item is above the ordinary tier:

| Tier | IRC marker | Presentation color |
| --- | --- | --- |
| Unusual | `[item inhabituel]` | green |
| Rare | `[item rare]` | blue |
| Very rare | `[item très rare]` | purple |
| Legendary | `[item légendaire]` | orange |

The tier is catalog metadata rather than replay state: the concrete loot key
already persisted in the event remains the single source of truth. Standard
equipment, detector discoveries, curse scrolls, decorative junk and the false
`Q` letter stay untagged. Experience magazines, vouchers, reward effects,
valid collection letters and permanent upgrades use their observed tiers.

Shop credit pays the rounded catalog price before durable experience. Promotion
prices use nearest-integer half-up settlement, so a 50-percent coupon prices a
7-point item at 4 points. Only one promotion coupon may remain active. The
blessing amulet consumes its sole use to neutralize the next acquired curse.
Endurance suppresses fatigue gain for 24 hours. Baker and prankster effects
respectively add one hour of channel bread or schedule a mechanical target at
exactly ten minutes after every later kill.

Hundred-hit milestones grant 50, 75, 100 and 125 credit at 100 through 400
kills, then 150 credit at every later hundred. The award is committed inside
the same killing transition.

## Runtime selection

One new injected daily schedule contains 24 unique ordered deadlines
inside its UTC day regardless of durable community progress. Each scheduled
flight uses an injected integer from 1 through 18;
the first value selects a golden target and all others select a standard target.
Golden health is injected from 3 through 5 and every flight uses the observed
five-minute lifetime. The policy is pure: it validates timestamps and rolls but
never reads the wall clock or samples entropy.

## Acquisition

Only a killing shot on a standard target may carry loot. The award is committed
after the target reward and before automatic reload, inside the same immutable
transition. Equipment refreshes or replaces its own catalog group without an
experience charge. Curse-scroll acquisition requires level 5 and one injected
supported curse identity.

Permanent upgrades are unique inventory facts. Protection acquisition removes
an already-pending matching nuisance; later purchases are still charged when
the permanent equipment blocks them. Full interaction details are in
`docs/LEGENDARY_PROTECTION.md`.

Replay stores the selected award, never the selection rolls. Recovery therefore
repeats acquisition exactly without sampling or consulting external state.
The final missing letter carries its already-selected bounded reward bundle;
completion applies it with a 50-point voucher and ammunition refill while
emitting one flood-safe public outcome. See `docs/COLLECTION_AND_CARRY.md`.
