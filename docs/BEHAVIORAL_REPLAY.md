# Calibrated behavioral replay

The behavioral replay suite converts high-confidence observations into small,
synthetic event traces. Raw IRC logs, real nicknames and private timestamps are
research inputs only and never enter the public repository.

## Scenario catalog

The suite fixes six cross-layer scenarios:

1. a golden hunt followed by the ordered `DUCK HUNT` collection, completion
   bundle, ammunition refill, daily bag thresholds and TARDIS activation;
2. the exact Europe/Paris bag and fatigue reset followed by TARDIS expiration;
3. distinct wild-shot, empty-trigger, jammed-trigger and compulsive-reload karma
   counters;
4. a targeted glare purchase, source attribution, accuracy reduction and
   one-shot consumption;
5. one incident chain containing both deflection and armor absorption;
6. one persisted daily schedule, golden selection and throttled query sequence.

All actors use synthetic names. Every random or time-dependent value is already
settled in the event: no replay test reads the clock, samples entropy or opens a
socket.

## Verification contract

Each event must survive its canonical payload round trip. The suite then checks
human-readable terminal facts for each scenario, including profile counters,
effects, schedule cursor and outcome kinds.

For every scenario, a real digest-chained journal is built and a snapshot is
written at every possible event boundary, including before the first event and
after the last. Recovery from every cut must produce the same terminal state.
This detects event fields that were applied live but omitted from persistence,
snapshot-only state, incorrect tail replay and non-deterministic transitions.

Finally, every rendered outcome is passed through the real IRC framing boundary.
The semantic response remains at most four fragments and every wire line remains
within 512 bytes. The suite performs no live IRC action.
