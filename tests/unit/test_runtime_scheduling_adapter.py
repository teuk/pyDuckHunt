from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path

from pyduckhunt.game.commands import Command, CommandKind
from pyduckhunt.game.model import FlightKind, GameState, ShotAttempt
from pyduckhunt.game.runtime import BOOTSTRAP_DAILY_FLIGHT_COUNT
from pyduckhunt.persistence import JournalFile, ReplayEvent, SnapshotStore
from pyduckhunt.rendering import FlightAppearance
from pyduckhunt.runtime import (
    CalibratedScheduleSource,
    RuntimeOrchestrator,
    RuntimeSchedulingAdapter,
    SchedulingPolicy,
    SystemRuntimeClock,
)


class SequenceIntegerSource:
    def __init__(self, *values: int) -> None:
        self.values = list(values)
        self.calls: list[tuple[int, int]] = []

    def __call__(self, minimum: int, maximum: int) -> int:
        self.calls.append((minimum, maximum))
        return self.values.pop(0) if self.values else minimum


class SequenceNanoseconds:
    def __init__(self, *values: int) -> None:
        self.values = list(values)

    def __call__(self) -> int:
        if not self.values:
            raise AssertionError("unexpected clock sample")
        return self.values.pop(0)


class CountingAppearanceSource:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self) -> FlightAppearance:
        self.calls += 1
        return FlightAppearance("trail", "/_ø-", "POUÊT")


SHOT = Command(CommandKind.SHOT, "bang")


class RuntimeSchedulingAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.output: list[tuple[bytes, ...]] = []
        self.runtime, _ = RuntimeOrchestrator.open(
            JournalFile(self.root / "events.jsonl"),
            SnapshotStore(self.root / "snapshot.json"),
            self.output.append,
            snapshot_interval=None,
        )
        self.addCleanup(self.runtime.close, 2)

    def adapter(
        self,
        source: SequenceIntegerSource | None = None,
        *,
        lateness_ns: int = 1_000_000_000,
        anti_cheat: bool = False,
        appearance_source: CountingAppearanceSource | None = None,
    ) -> tuple[RuntimeSchedulingAdapter, SequenceIntegerSource]:
        selected = source or SequenceIntegerSource()
        return (
            RuntimeSchedulingAdapter(
                self.runtime,
                ("#pond",),
                CalibratedScheduleSource(selected),
                policy=SchedulingPolicy(lateness_ns),
                anti_cheat=anti_cheat,
                flight_appearance_source=appearance_source,
            ),
            selected,
        )

    def test_system_clock_projects_utc_anchor_with_monotonic_progress(self) -> None:
        monotonic = SequenceNanoseconds(10, 15, 21)
        clock = SystemRuntimeClock(monotonic, lambda: 1_000)
        self.assertEqual(clock.now_ns(), 1_005)
        self.assertEqual(clock.now_ns(), 1_011)

        backwards = SystemRuntimeClock(SequenceNanoseconds(10, 9), lambda: 1_000)
        with self.assertRaises(RuntimeError):
            backwards.now_ns()

    def test_schedule_source_draws_unique_hours_minutes_and_golden_health(self) -> None:
        integers = SequenceIntegerSource()
        source = CalibratedScheduleSource(integers)
        deadlines = source.daily_schedule(0)
        self.assertEqual(len(deadlines), 18)
        self.assertEqual(len(set(deadlines)), 18)
        self.assertEqual(deadlines[0], 60_000_000_000)
        self.assertEqual(len(integers.calls), 36)
        selection = source.flight_selection()
        self.assertEqual((selection.kind, selection.health), (FlightKind.GOLDEN, 3))
        self.assertEqual(integers.calls[-2:], [(1, 18), (3, 5)])
        bootstrap_integers = SequenceIntegerSource()
        bootstrap = CalibratedScheduleSource(bootstrap_integers).daily_schedule(
            0,
            BOOTSTRAP_DAILY_FLIGHT_COUNT,
        )
        self.assertEqual(len(bootstrap), BOOTSTRAP_DAILY_FLIGHT_COUNT)
        self.assertEqual(len(bootstrap_integers.calls), 48)
        with self.assertRaises(ValueError):
            CalibratedScheduleSource(SequenceIntegerSource()).daily_schedule(0, 20)

    def test_flight_expires_and_is_announced_at_its_exact_deadline(self) -> None:
        adapter, _ = self.adapter()
        adapter.step(0)
        schedule = self.runtime.state.daily_schedule
        assert schedule is not None
        first = schedule.deadlines_ns[0]
        adapter.step(first)
        flight = self.runtime.state.flight
        assert flight is not None
        self.assertEqual(adapter.step(flight.expires_at_ns - 1).next_deadline_ns, flight.expires_at_ns)
        expired = adapter.step(flight.expires_at_ns)
        self.assertIsNone(self.runtime.state.flight)
        self.assertIsNotNone(self.runtime.state.last_flight)
        assert self.runtime.state.last_flight is not None
        self.assertEqual(self.runtime.state.last_flight.ended_at_ns, flight.expires_at_ns)
        self.assertTrue(any(b"s'\xc3\xa9chappe" in wire for wire in self.output[-1]))
        self.assertTrue(any(dispatch.transition is not None for dispatch in expired.dispatches))

    def test_anti_cheat_draws_only_for_an_accepted_started_flight(self) -> None:
        appearances = CountingAppearanceSource()
        adapter, _ = self.adapter(
            anti_cheat=True,
            appearance_source=appearances,
        )
        adapter.step(0)
        self.assertEqual(appearances.calls, 0)
        schedule = self.runtime.state.daily_schedule
        assert schedule is not None
        adapter.step(schedule.deadlines_ns[0])
        self.assertEqual(appearances.calls, 1)
        self.assertTrue(any("POUÊT".encode() in wire for wire in self.output[-1]))

    def test_detector_alert_is_routed_once_as_a_private_notice(self) -> None:
        adapter, _ = self.adapter()
        adapter.step(0)
        schedule = self.runtime.state.daily_schedule
        assert schedule is not None

        self.runtime.dispatch(
            ReplayEvent.start_flight(1, 100),
            lambda transition: (),
        )
        self.runtime.dispatch(
            ReplayEvent.command(2, "Hunter", SHOT, shot_attempt=ShotAttempt()),
            lambda transition: (),
        )
        self.runtime.dispatch(
            ReplayEvent.purchase(3, "Hunter", 22, 4),
            lambda transition: (),
        )
        self.output.clear()

        adapter.step(schedule.deadlines_ns[0])
        batch = self.output[-1]
        notices = tuple(wire for wire in batch if wire.startswith(b"NOTICE Hunter :"))
        self.assertEqual(len(notices), 1)
        self.assertIn("détecteur".encode(), notices[0])
        self.assertTrue(any(wire.startswith(b"PRIVMSG #pond :") for wire in batch))
        self.assertEqual(self.runtime.state.effects, ())

    def test_anti_cheat_policy_requires_exact_callable_source_pairing(self) -> None:
        for anti_cheat, appearance_source in (
            (True, None),
            (False, CountingAppearanceSource()),
            (1, None),
            (True, 7),
        ):
            with self.subTest(
                anti_cheat=anti_cheat,
                appearance_source=appearance_source,
            ), self.assertRaises(ValueError):
                RuntimeSchedulingAdapter(
                    self.runtime,
                    ("#pond",),
                    CalibratedScheduleSource(SequenceIntegerSource()),
                    anti_cheat=anti_cheat,  # type: ignore[arg-type]
                    flight_appearance_source=appearance_source,  # type: ignore[arg-type]
                )

    def test_install_then_bounded_late_poll_uses_exact_deadline(self) -> None:
        adapter, _ = self.adapter()
        installed = adapter.step(0)
        self.assertEqual(len(installed.dispatches), 1)
        schedule = self.runtime.state.daily_schedule
        assert schedule is not None
        first = schedule.deadlines_ns[0]
        self.assertEqual(installed.next_deadline_ns, first)

        launched = adapter.step(first + 500_000_000)
        self.assertEqual(len(launched.dispatches), 1)
        assert self.runtime.state.flight is not None
        self.assertEqual(self.runtime.state.flight.spawned_at_ns, first)
        self.assertEqual(self.runtime.state.flight.kind, FlightKind.GOLDEN)
        self.assertTrue(any(b"PRIVMSG #pond :" in wire for wire in self.output[-1]))

    def test_startup_after_deadline_skips_without_flight_draw_or_burst(self) -> None:
        adapter, integers = self.adapter()
        adapter.step(120_000_000_000)
        schedule = self.runtime.state.daily_schedule
        assert schedule is not None
        self.assertEqual(schedule.next_index, 1)
        self.assertIsNone(self.runtime.state.flight)
        self.assertEqual(len(integers.calls), 48)

    def test_active_flight_skips_due_slot_without_consuming_entropy(self) -> None:
        adapter, integers = self.adapter()
        adapter.step(0)
        schedule = self.runtime.state.daily_schedule
        assert schedule is not None
        first = schedule.deadlines_ns[0]
        self.runtime.dispatch(
            ReplayEvent.start_flight(first - 1, 10_000_000_000),
            lambda transition: (),
        )
        calls_before = len(integers.calls)
        adapter.step(first)
        self.assertEqual(len(integers.calls), calls_before)
        self.assertEqual(self.runtime.state.daily_schedule.next_index, 1)
        self.assertIsNotNone(self.runtime.state.flight)

    def test_policy_time_and_owner_contracts_are_strict(self) -> None:
        with self.assertRaises(ValueError):
            SchedulingPolicy(True)
        adapter, _ = self.adapter()
        adapter.step(0)
        with self.assertRaises(ValueError):
            adapter.step(-1)

        errors: list[Exception] = []

        def foreign_step() -> None:
            try:
                adapter.step(1)
            except Exception as error:
                errors.append(error)

        thread = threading.Thread(target=foreign_step)
        thread.start()
        thread.join(2)
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], RuntimeError)


if __name__ == "__main__":
    unittest.main()
