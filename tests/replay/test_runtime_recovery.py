from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pyduckhunt.game.commands import Command, CommandKind
from pyduckhunt.game.model import FlightKind, OutcomeKind
from pyduckhunt.game.runtime import build_daily_schedule, select_scheduled_flight
from pyduckhunt.persistence import JournalFile, ReplayEvent, SnapshotStore, recover
from pyduckhunt.persistence.replay import replay_records, snapshot_from_result


SCHEDULE = build_daily_schedule(0, tuple(range(18)), (0,) * 18)
STATS = Command(CommandKind.STATS, "duckstats")


class RuntimeRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.journal = JournalFile(root / "events.jsonl")
        self.snapshots = SnapshotStore(root / "snapshot.json")

    def test_recovery_preserves_schedule_cursor_and_throttle_windows(self) -> None:
        self.journal.append(ReplayEvent.install_daily_schedule(0, 0, SCHEDULE))
        self.journal.append(
            ReplayEvent.schedule_tick(
                SCHEDULE[0],
                selection=select_scheduled_flight(2),
            )
        )
        self.journal.append(ReplayEvent.runtime_command(SCHEDULE[0], "Hunter", STATS))
        recovered = recover(self.snapshots, self.journal)
        self.assertEqual(recovered.state.daily_schedule.next_index, 1)
        self.assertEqual(len(recovered.state.throttle_windows), 2)
        self.assertEqual(recovered.state.flight.kind, FlightKind.STANDARD)

    def test_snapshot_restart_skips_missed_deadlines_without_starting_a_flight(self) -> None:
        self.journal.append(ReplayEvent.install_daily_schedule(0, 0, SCHEDULE))
        prefix = replay_records(self.journal.read_records())
        self.snapshots.write(snapshot_from_result(prefix))
        self.journal.append(ReplayEvent.schedule_tick(SCHEDULE[2] + 1))
        recovered = recover(self.snapshots, self.journal)
        self.assertIsNone(recovered.state.flight)
        self.assertEqual(recovered.state.daily_schedule.next_index, 3)
        self.assertEqual(len(recovered.transitions), 1)

    def test_recovery_reuses_the_persisted_golden_settlement(self) -> None:
        self.journal.append(ReplayEvent.install_daily_schedule(0, 0, SCHEDULE))
        self.journal.append(
            ReplayEvent.schedule_tick(
                SCHEDULE[0],
                selection=select_scheduled_flight(1, golden_health_roll=5),
            )
        )
        recovered = recover(self.snapshots, self.journal)
        self.assertEqual(recovered.state.flight.kind, FlightKind.GOLDEN)
        self.assertEqual(recovered.state.flight.health, 5)
        self.assertEqual(recovered.state.flight.reward_experience, 60)

    def test_recovery_replays_a_throttled_command_without_applying_it(self) -> None:
        self.journal.append(ReplayEvent.runtime_command(0, "Hunter", STATS))
        self.journal.append(ReplayEvent.runtime_command(1, "Hunter", STATS))
        self.journal.append(ReplayEvent.runtime_command(2, "Hunter", STATS))
        recovered = recover(self.snapshots, self.journal)
        last = recovered.transitions[-1]
        self.assertEqual(last.outcomes[-1].kind, OutcomeKind.COMMAND_THROTTLED)
        self.assertNotIn(OutcomeKind.QUERY, tuple(value.kind for value in last.outcomes))


if __name__ == "__main__":
    unittest.main()
