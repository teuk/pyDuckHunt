# Bread and scheduled channel actions

Each item-21 purchase costs 4 XP, grants +2 temporary karma and creates one
independent bread effect for at most one hour. Owner `!pain` creates the same
effect without charging or creating a player. A maximum of 20 active pieces is
accepted; a refused player purchase spends nothing.

Every piece records one attraction deadline inside its active hour. The first
later takeoff consumes the oldest piece and adds 20 seconds to that duck's normal
lifetime. This applies equally to daily, called, mechanical and Owner-launched
flights. Bread bought while a duck is already present cannot extend that duck;
it waits for the next takeoff. Two pieces can therefore affect at most two
flights. Once consumed, a piece's separate attraction is already satisfied and
cannot create another duck.

The scheduler keeps exactly 24 daily slots. Bread deadlines are separate from
the daily plan: when a deadline arrives on an idle channel, it requests one
standard or golden flight using the normal selection policy. A due duck call has
priority when both are ready; that called takeoff consumes one bread and prevents
a duplicate attraction. While another flight is active, paid calls and bread
attractions wait. Bread that reaches its one-hour expiry first disappears without
launching or extending a duck. Expiry alone is not a runtime wake-up.

Duck calls retain their injected deadline within ten minutes, and mechanical
actions their exact ten-minute deadline. Both stay durably queued while a flight
blocks them. A successful matching start completes only one due action. The
detector retains its one-shot private alert contract.

Player confirmations describe the duration and effect but never expose an exact
future time. Owner `duckplanning` shows the immutable daily slots, separate bread
attractions, action deadlines, current flight and bread expirations in
Europe/Paris. `!duckstats` and `!inventory` remain private NOTICE replies to the
requesting nickname.

## Upgrade compatibility

Schema 24 stores `bread_policy_version=2`. A schema-23-or-older checkpoint first
replays its historical hourly-bread behavior exactly, then the live scheduler
records one `migrate_bread_policy` event. Active paid bread is retained, receives
a deterministic attraction inside its remaining lifetime and any expanded
25–44-slot plan is normalized to 24 without resetting its processed cursor.
Old `enable_hourly_bread` and `replan_bread_schedule` events remain readable;
existing snapshots and journal records are never rewritten.
