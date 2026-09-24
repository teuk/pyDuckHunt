# Private observation coverage

`tools/observation_coverage.py` converts an existing digest-chained event journal
into aggregate coverage for the controlled `IO-001` through `IO-020` scenarios.
It is an offline diagnostic: it does not connect to IRC, write game state, change
configuration or alter MenzAgitat's game rules.

## Run a bounded report

Run the tool from the checkout with the same Python environment used by
pyDuckHunt. The journal must be an absolute path to a regular, non-symlink file
of at most 64 MiB.

```bash
.venv/bin/python tools/observation_coverage.py \
  --journal /absolute/private/path/events.jsonl \
  --snapshot /absolute/private/baseline/snapshot.json \
  --after-sequence 2411 \
  --require-events \
  --format markdown
```

The snapshot must bind to the same verified journal at or before the sequence
floor. Its state and digest establish the semantic replay boundary; older
events are still covered by the journal-chain validation but are not replayed
through current rules. The sequence floor excludes baseline history from the
evidence counters. Use `--through-sequence` to seal a closed interval. Markdown
is intended for a private operator report; TSV is available for a private
ledger.

The command writes only to standard output. Redirect it into a private directory
with mode `0700` and create the destination file under a restrictive umask.

## Honest status model

| Status | Meaning |
| --- | --- |
| `OBSERVED` | The aggregate journal threshold for this scenario was met. |
| `PARTIAL` | At least one required component exists, but the scenario is incomplete. |
| `NOT-OBSERVED` | No qualifying journal transition exists in the selected range. |
| `EXTERNAL-EVIDENCE` | The event journal cannot prove this scenario. |

`OBSERVED` is deliberately narrower than `PASS`. A complete scenario acceptance
also needs its normalized presentation, state deltas and operator receipts. The
report therefore never claims that the fourteen-day protocol passed.

Service restart, host reboot, IRC reconnect, visible nickname change and Owner
planning remain external. They require systemd, boot, transport or private
presentation evidence and are never guessed from event timing.

## Privacy boundary

The report contains scenario identifiers, fixed labels, sequence bounds, one
journal digest and aggregate counters. It never emits:

- nicknames, account names or hostmasks;
- raw IRC commands, replies or conversations;
- player inventory, profile rows or exact future deadlines;
- server credentials or private planning details.

The source journal remains private and must not be committed. Public tests use
synthetic events only.
