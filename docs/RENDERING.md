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
not reveal it, and the first successful bang exposes its golden identity in the
survival or kill response. Mechanical targets retain their explicit label.
Catalog entries are bounded plain UTF-8 text without
URLs or IRC controls; framing adds presentation controls afterward and still
enforces the complete 512-byte wire limit.

## Command surface

The public parser recognizes these calibrated forms:

- `!bang` and `!pan`
- `!reload`
- `!shop [id [target]]`
- `!inventory [nickname]`
- `!duckstats [nickname]`
- `!lastduck`
- `!duckrank [limit]`

Profile, inventory and catalog queries are returned privately to the requester
as IRC `NOTICE` messages. Ranking and game activity remain visible in the
channel. The shop query is one bounded NOTICE containing the compact purchase
syntax and, only when configured, the operator-controlled HTTPS catalog URL;
the 31-item catalog is no longer repeated over IRC. The link-free default keeps
an unpublished or retired page out of player responses.

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
The same compact inventory response includes the daily duck bag, its carry
state, the `DUCK HUNT` slots and an active TARDIS marker. Crossing the six- or
eleven-duck boundary adds a short carry tag to the existing hit line. Completing
the phrase emits one summary line regardless of bundle size. Successful shots
deliberately retain separate public hit and bush-search lines. The hit line uses
the channel supplied by the IRC command context, one-decimal reaction time,
total hunts, experience and level progression; it never embeds a
deployment-specific channel name.

`!duckrank` defaults to five hunters while retaining the explicit 1–20
boundary. Its first public line uses a compact colored podium with medals for
the leading three places. When `ranking_url` is configured, a second public
line links to the complete ranking page. The two semantic lines are deliberately
kept separate instead of being packed together. A shop identifier must be a
positive ASCII integer; whether the item exists or requires a target remains a
game-engine decision so it can produce a precise player outcome.

Successful purchases whose useful value is settled at runtime expose that exact
value immediately: the targeting scope announces its accuracy percentage and
the lucky charm announces its per-duck experience bonus. The renderer reads the
value already stored in the transition outcome and never draws it again.

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
