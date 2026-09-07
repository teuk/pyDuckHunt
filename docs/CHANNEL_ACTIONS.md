# Scheduled channel actions

Channel-wide purchases that create a future event are durable game facts rather
than in-process timers. Each scheduled action carries a monotonic identifier,
the catalog item, its source player, creation time and exact due time.

The duck call accepts an injected deadline strictly after purchase and no later
than ten minutes afterward. The mechanical duck always uses an exact ten-minute
delay. The caller resolves the variable call delay before settlement, and the
journal records that concrete deadline so recovery never samples it again.

Advancing the game clock removes every due action and emits one
`channel_action_due` outcome. Simultaneous actions are ordered by due time and
then identifier. A later runtime dispatcher will translate those outcomes into
real or mechanical flights; no timer, socket or channel operation exists in the
game engine.

The duck detector is a player-scoped one-use effect. A successfully started
flight consumes every waiting detector and emits a private-alert outcome. A
rejected start while another flight is active consumes nothing. IRC NOTICE
routing is performed once per detector owner by the runtime scheduling adapter.

Channel bread is also tied to a successful start: one active stack is consumed,
oldest activation and then lowest identifier first. Other active stacks remain
available until a later flight or their independent one-hour deadline. Rejected
starts consume no bread.
