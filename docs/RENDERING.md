# Player response rendering

Player-facing output is a projection of immutable game facts plus, when the
operator explicitly enables anti-cheat presentation, one already-drawn flight
appearance. Rendering itself does not sample randomness, read a clock, open a
socket or mutate game state.

## Flight appearance

The anti-cheat catalog contains 32 flight trails, 120 composable silhouettes,
40 calls and 31 spoken lines. Six independent bounded draws select the trail,
wing, eye, beak, utterance family and utterance, allowing 272,640 complete
standard appearances. Calls retain a three-in-four weight so the channel still
sounds like a duck hunt while spoken lines remain frequent enough to give each
flight personality.

The existing grey trail, bold silhouette and reset boundaries are preserved.
A golden target deliberately uses the standard arrival projection: misses do
not reveal it, and the first successful impact exposes it as a `super-canard`
in the survival or kill response. Mechanical targets retain their explicit
label and electrical hit signature.
Catalog entries are bounded plain UTF-8 text without
URLs or IRC controls; framing adds presentation controls afterward and still
enforces the complete 512-byte wire limit.

## Command surface

The public parser recognizes these calibrated forms:

- `!bang` and `!pan`
- `!reload`
- `!shop [id [target]]`
- `!shop info <id>`
- `!inventory [nickname]`
- `!duckstats [nickname]`
- `!lastduck`
- `!duckrank [limit]`
- `!duckrank hits [limit]`
- `!myrank`
- `!duckhelp`

Profile, inventory, personal rank, help and catalog queries are returned privately to the requester
as IRC `NOTICE` messages. Ranking and game activity remain visible in the
channel. The shop query is one bounded NOTICE containing the compact purchase
syntax and, only when configured, the operator-controlled HTTPS catalog URL;
the 31-item catalog is no longer repeated over IRC. `!shop info <id>` returns
one private NOTICE with the item name, nominal XP price, scope and applicable
catalog limits; it never purchases the item or creates a hunter. Discounts and
credits are settled only at purchase. The link-free default keeps an
unpublished or retired page out of player responses.

The final IRC framing greedily joins adjacent response fragments whenever the
target-specific 512-byte budget permits it. Commands therefore use the fewest
wire lines their complete response requires. `!duckstats` deliberately keeps
its complete reference hunting sheet on two semantic NOTICE lines. The first is
`[Profil]`, `[Stats]` and `[Arme]`; the second is `[Tableau de chasse]` and
`[Accidents]`. Its section labels use the same orange IRC color as the reference
inventory heading.

Ammunition, reserve magazines and weapon state are reported by `!inventory`,
together with the active bread count on the current channel. The projection has
one `[Inventaire]` heading followed by weapon, rounds, magazines, bag, letter
slots and concise owned-item labels. Carried permanent items, the suppressor,
active temporary effects and bread share this single section; an active
suppressor appears exactly once as the first item and includes its actual
remaining lifetime. Every other time-bounded player effect follows the same
rule; use-bounded equipment reports its remaining uses and permanent equipment
does not invent an expiry. Promotion coupons show their percentage once and
their actual remaining lifetime once. Curses are appended only when present.
When this section grows beyond one IRC line, inventory items continue on
additional private NOTICE lines at whole-item boundaries. The recipient's
512-byte wire budget is checked before sending, so later items stay visible.
The same compact inventory response includes the daily duck bag, its carry
state, the `DUCK HUNT` slots and an active TARDIS marker. Crossing the six- or
eleven-duck boundary adds a short carry tag to the existing hit line. Completing
the phrase emits one detailed reward line regardless of bundle size. Successful shots
deliberately retain separate public hit and bush-search lines. The hit line uses
the channel supplied by the IRC command context, one-decimal reaction time,
total hunts, experience and level progression; it never embeds a
deployment-specific channel name. It also retains the reference ammunition
signature: explosive hits say `*BOUM*`, silent bows and crossbows say `*TCHAK*`,
and other ordinary or AP hits say `*BANG*`; a killed super-canard additionally
exposes `[mun. expl.]` or `[mun. AP]`. The renderer consumes the explicit
ammunition item and settled player level stored in the outcome rather than
guessing from damage, because curse composition can alter damage independently.

Empty-magazine, unjam and exhausted-reserve responses include the settled
round and magazine counts. Ordinary, super and mechanical escapes retain their
distinct labels and trail, while a noise escape uses its own frightened trail.
The active `!lastduck` response reports elapsed presence without publishing the
remaining deadline.

`!duckrank` defaults to five hunters by available XP while retaining the explicit
1–20 boundary. `!duckrank hits [limit]` opts into the existing ducks-hit order
used by the ranking page; the XP form and its order do not change. The selected
view appears in the heading. The first public line uses a compact colored podium with medals for
the leading three places. Each entry shows available XP, ducks hit and the
number of golden ducks within that total. Longer rankings continue on
additional bounded IRC lines without dropping a hunter. Identities configured in
`statistics_excluded_nicknames` are omitted before ordering and limiting, so
an operator never displaces a hunter. Direct `!duckstats` lookup returns the
same unknown-hunter response for an excluded identity, and the partyline
summary omits it even when it is the last shooter. When `ranking_url` is
configured, a second public line links to the complete ranking page. The two
semantic lines are deliberately kept separate instead of being packed
together. `!myrank` privately reports the requester's position in both
existing ranking orders, including the total ranked players and their current
XP and duck counts. Excluded or unknown nicknames receive the same unknown-hunter
reply as `!duckstats`. `!duckhelp` privately lists player commands in the
instance language. Neither command registers a new hunter or writes a query
event. A purchase identifier must be a positive ASCII integer; whether the item
exists or requires a target remains a game-engine decision so it can produce a
precise player outcome. The private `info` subcommand requires exactly one
positive ASCII identifier of at most four digits and reports unknown items
without dispatching a game event.

Successful purchases whose useful value is settled at runtime expose that exact
value immediately: the targeting scope announces its accuracy percentage and
the lucky charm announces its per-duck experience bonus. The renderer reads the
value already stored in the transition outcome and never draws it again.
Every supported shop item has an item-specific confirmation explaining its
settled effect. Purchase credits, discounts and level loss remain suffix facts,
so restoring established prose does not change any debit or grant.

Wild shots use the historical explicit warning and show miss and wild penalties
separately. A bang during the three-second post-kill grace window instead says
exactly how late it arrived and never carries a wild-shot label. Incident
transitions replace the ordinary miss line with one visible ricochet, armor or
fatal-accident line containing the settled penalties and confiscation marker.

## Priority response boundary

Each command may provide at most four semantic response fragments. Adjacent
fragments are compacted before transmission. Every resulting line is rendered
through a conservative target-specific byte budget and is at most 512 bytes
including the IRC command, target and CRLF terminator. Oversized text is
shortened only at a valid UTF-8 boundary and receives an ellipsis.

Control characters used for IRC presentation are allowed, while NUL, carriage
return and line feed are rejected before any shortening. This prevents output
injection from being hidden beyond the visible byte boundary.

## Deterministic projections

Profile, golden-hit count, fatigue, inventory, effects, curses, shop and ranking
responses depend
only on the supplied game state. Fixed-point fatigue is rendered exactly, so a
stored value of 672 centi-points is displayed as `6.72` without floating-point
rounding. Last-flight display reads the durable active or completed flight and
the injected game clock. Ranking ties are settled by hit count, best time and
canonical IRC identity in that order.

The renderer returns text first. IRC framing is a separate final step, allowing
unit tests and replay tools to inspect responses without a network connection.
A randomized appearance is injected only for one accepted scheduled flight;
the renderer retains its deterministic legacy projection when none is supplied.
Loot acquisitions have their own bounded player response after the priority hit
line. Equipment discoveries explain what the item changes and state its
canonical duration, use count or permanent status; settled random bonuses such
as scope accuracy and lucky-charm experience are rendered from the outcome.
Finding a duck detector explains its one-use private alert immediately.
Non-ordinary loot appends exactly one colored tier marker: green
`[item inhabituel]`, blue `[item rare]`, purple `[item très rare]` or orange
`[item légendaire]`. Carry warnings are hazards rather than rewards, so both
`[encombré]` and `[surchargé]` are red in hit and inventory projections.
Scheduled-action outcomes remain silent here, while the runtime scheduler routes
each detector outcome exactly once through the bounded IRC NOTICE path.

## Scope units

Scope purchase and loot messages use percentage points and explain the rounded
one-third formula. The displayed value is the current bonus, not a random
roll. Profile and inventory use the same live formula; a subsequent level
change updates it without restoring any uses. Zero is displayed as +0.

Bread inventory shows the active count and states that one piece applies to one
flight, without a countdown to the first expiration. No player-facing exact
attraction or daily-flight deadline is disclosed. Owner planning shows separate
attraction and expiry times privately and never promises absent bread.
Consuming a piece is bookkeeping-only and emits no additional channel line; the
purchase confirmation and inventory remain the visible sources of bread state.
