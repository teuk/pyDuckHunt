# Permanent legendary protection

Legendary selection remains outside the deterministic transition. The engine
accepts one already-selected award, validates its recipient level and persists
the resulting unique inventory fact. Re-acquiring the same award cannot stack
its protection.

| Award | Minimum level | Permanent result |
| --- | ---: | --- |
| `indestructible_sunglasses` | 20 | blocks glare |
| `tearproof_raincoat` | 20 | blocks water |
| `military_self_lubricating_system` | 20 | blocks sand and halves jam risk |
| `permanent_killing_license` | 30 | waives incident penalties and confiscation |

Acquiring one of the first three awards removes an already-pending matching
nuisance atomically. A later hostile purchase still charges its buyer, reports
that it was blocked and leaves the permanent item untouched. Ordinary grease
and military self-lubrication do not stack: the effective jam risk is halved
once after decay and sand modifiers.

The killing license protects only the incident portion of a missed shot. Miss
and wild-shot penalties, target statistics and the rest of the incident chain
continue to settle normally. No award restores a weapon confiscated before the
protection was acquired.

All four protections reuse the canonical inventory already covered by the
current persistence schema. No new snapshot or journal field is required.
