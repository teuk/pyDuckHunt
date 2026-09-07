# Letter collection and carried ducks

The historical `DUCK HUNT` letter collection and the daily duck bag are durable,
deterministic profile facts. Selection remains outside the game transition: the
engine receives one concrete unusual award and never samples hidden entropy.

## Letter collection

The eight ordered slots are `D U C K H U N T`. A matching award fills the first
still-empty slot for that letter, so the two `U` positions are acquired in phrase
order. Finding an already-complete letter is harmless. The decorative `Q` award
does not alter the collection.

The final missing letter must carry an already-selected completion bundle. The
engine applies that bounded bundle atomically, resets all eight slots, restores
the current weapon and reserve magazines to their possibly upgraded capacities,
and grants 50 points of shop credit. Nested letter awards are rejected. Replay
stores the exact bundle, not the draw that produced it.

Completion produces one public outcome even when the bundle contains several
items. Ordinary discoveries show the compact slot state on one line; inventory
shows the same state without creating an additional IRC response.

## Daily duck bag

Every standard or golden kill adds one carried duck. Mechanical targets do not.
The bag is empty at five ducks or fewer, encumbered from six through ten, and
overloaded from eleven onward. Those states multiply the base fatigue of later
fired shots by two or three respectively. The killing shot that crosses a
threshold keeps its previous multiplier; the resulting hit response displays
the new carry state. Both warning markers are rendered in red on hit and
inventory projections so a fatigue hazard cannot look like neutral metadata.

At the first transition into a new Europe/Paris calendar day, the engine empties every bag, resets
fatigue, restores a confiscated weapon and fills both the loaded ammunition and
reserve magazines to their possibly upgraded capacities. The exact day start is
persisted as a canonical date marker so restart and replay cannot repeat or skip
that reset. CET and CEST transitions follow the system time-zone database. A confiscation
or ammunition use later in the same day therefore remains effective. The daily
reset does not clear a jam or consume, complete or alter letter slots.

The 24-hour TARDIS bag removes the carry multiplier while active without hiding
or discarding the carried-duck count. Inventory displays the count, current
carry state, letter slots and active TARDIS compactly on its existing lines.
