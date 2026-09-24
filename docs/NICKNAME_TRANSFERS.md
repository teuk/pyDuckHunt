# Nickname transfers

Coin follows the deferred nickname contract of Duck Hunt 2.11. An IRC `NICK`
message is evidence of a possible identity change, not permission to move a
score immediately.

## Deferred decision

Coin tracks a rename when the old nickname has a profile, the new nickname has
a profile, or the old nickname is already the destination of a pending chain.
The pending record contains only the two canonical IRC identities, their
display nicknames and a one-hour monotonic deadline. No hostmask or raw IRC
message enters game state.

The score remains under the old nickname until the new nickname participates.
Participation includes the actor of every public game command and an explicit
profile, inventory or shop target. Immediately before that command is settled:

- if only the old profile exists, it is renamed;
- if both profiles exist, they are merged into the new nickname;
- if only the new profile exists, it remains unchanged;
- if neither exists, only the pending record is consumed.

This order prevents a passing `NICK` event from taking over a populated profile
without later participation, while retaining the original game's behavior.

## Chains, cancellation and expiry

A chain such as `First` to `Second` to `Third` keeps `First` as its source and
follows `Third` as its current destination. Returning to the source cancels the
unconsumed chain. A `PART` from the configured game channel or a `QUIT` also
cancels it. Unconsumed transfers expire after one hour.

RFC1459 casemapping is used throughout. A change that only alters equivalent
IRC casing does not create a transfer.

## Merge contract

When both identities already have profiles, Coin keeps the destination display
nickname and applies the reference principles to the richer Python state:

- available XP, hunting counters and durable debit counters are summed;
- the fastest reaction time is retained;
- unique inventory stacks are retained at their greatest quantity;
- the most restrictive jammed or confiscated weapon state wins;
- ammunition already consumed by both profiles is deducted from the resulting
  level capacity;
- effects, scheduled actions, curses, command throttles and the last-shooter
  pointer are rekeyed to the surviving profile and deduplicated.

No earlier journal entry or snapshot is edited.

## Durability

Schema 25 stores pending transfers in snapshots. `track_nick_change`,
`resolve_nick_transfer` and `cancel_nick_transfer` are append-only replay
events. A restart therefore reaches the same decision and terminal state as the
live process. Schema-24 and older snapshots decode with no pending transfers.

The persistence reservation is acquired before applying any transfer. If the
bounded queue is full, a player command receives the normal busy response and
neither its identity transfer nor its game action is applied.
