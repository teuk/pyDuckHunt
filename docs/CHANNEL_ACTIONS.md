# Bread and scheduled channel actions

Live bread follows the reference method-2 behaviour. Each item-21 purchase
costs 4 XP, grants +2 temporary karma and creates an independent one-hour effect.
Owner bread uses the same channel effect without charging a player. A maximum
of 20 active pieces is accepted for new player and Owner requests; refusals do
not spend XP. Existing historical surplus is retained until expiry, with the
attraction count capped at 20.

Bread remains in place across every successful flight during that hour. At each
new takeoff, the engine adds 20 seconds per active piece to the flight's normal
lifetime, including called, mechanical and Owner flights. Adding or expiring
bread does not change the expiry of a duck already in flight. No piece is eaten
or removed by takeoff and no false consumption announcement is emitted.

The scheduler's fixed base is 24 slots per UTC day. Adding bread or expiring a
piece redraws a whole-day plan of 24 + active pieces. Hours are selected without
replacement, resetting the hour pool when exhausted; minutes are unique within
the resulting day. The nearest existing future time is retained on addition,
and also on expiry while at least one piece remains. When the last piece
expires the plan is redrawn with 24 slots. This is attraction, not a guarantee
of an additional duck during the hour. Past times in the newly drawn plan are
not fired retroactively. Existing UTC boundaries and Europe/Paris display are
preserved; the underlying reference scheduling method is used without changing
the bot's operating timezone or configured base quota.

Expiry participates in the runtime wake-up even without chat activity. Bread
fingerprints and concrete plan draws are journaled; reconnecting or restarting
with unchanged bread does not redraw the schedule. Paid duck calls and mechanical
actions remain queued across bread expiry/replanning, including while another
flight blocks them. A successful matching start completes only one due action.

The detector retains its one-shot private alert contract. All precise planning,
expiry and delay diagnostics go to the Owner NOTICE, partyline or application
log. Player confirmations contain durations and effects, not takeoff times.

The first live scheduler step writes an explicit `enable_hourly_bread` event.
Before that event, old purchases and flights replay their original one-hour /
one-consumption semantics. Existing flight deadlines and old player scores are
not recalculated. New `replan_bread_schedule` events contain the chosen deadlines.
Schema 22 carries the optional bread plan fingerprint; schema-21 checkpoints
remain authoritative and byte-identical old event payloads remain valid.
