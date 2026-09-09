from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from pyduckhunt.game.model import GameState, PlayerState
from pyduckhunt.identity import rfc1459_casefold
from pyduckhunt.publishing import (
    PrometheusMetricsPublisher,
    RuntimeMetricsSnapshot,
    StatePublisherFanout,
    render_prometheus_metrics,
)


def runtime(**overrides: object) -> RuntimeMetricsSnapshot:
    values: dict[str, object] = {
        "generated_at_ns": 2_000_000_000,
        "started_at_ns": 1_000_000_000,
        "process_state": "running",
        "transport_state": "ready",
        "connected": True,
        "ready_entries": 1,
        "bridge_dispatched": 4,
        "bridge_invalid": 1,
        "bridge_ignored": 2,
        "schedule_accepted": 3,
        "schedule_backpressured": 0,
        "network_failures": 0,
        "persistence_pending": 0,
        "state_publication_attempts": 5,
        "state_publication_failures": 0,
        "metrics_publication_attempts": 2,
        "metrics_publication_failures": 0,
        "schedule_flight_count": 24,
        "schedule_next_index": 3,
        "schedule_next_deadline_ns": 3_000_000_000,
        "schedule_community_progress": 7,
        "schedule_recommended_flight_count": 24,
    }
    values.update(overrides)
    return RuntimeMetricsSnapshot(**values)  # type: ignore[arg-type]


class MetricsPageTests(unittest.TestCase):
    def test_rendering_is_aggregate_ascii_and_bounded_cardinality(self) -> None:
        nickname = "PrivateHunter"
        player = PlayerState(
            key=rfc1459_casefold(nickname),
            nickname=nickname,
            hits=12,
            misses=3,
            golden_hits=1,
            best_time_ms=475,
        )
        payload = render_prometheus_metrics(
            GameState(now_ns=2_000_000_000, players=(player,)),
            runtime(),
        )
        rendered = payload.decode("ascii")
        self.assertNotIn(nickname, rendered)
        self.assertIn("pyduckhunt_players 1", rendered)
        self.assertIn("pyduckhunt_hits_total 12", rendered)
        self.assertIn("pyduckhunt_golden_hits_total 1", rendered)
        self.assertIn("pyduckhunt_best_time_seconds 0.475", rendered)
        self.assertIn('pyduckhunt_process_state{state="running"} 1', rendered)
        self.assertEqual(rendered.count('state="running"'), 1)

    def test_runtime_snapshot_rejects_cross_typed_and_inconsistent_values(self) -> None:
        for values in (
            {"connected": 1},
            {"process_state": "unknown"},
            {"schedule_next_index": 25},
            {"state_publication_attempts": 1, "state_publication_failures": 2},
        ):
            with self.subTest(values=values), self.assertRaises(ValueError):
                runtime(**values)

    def test_configured_admin_is_absent_from_aggregate_statistics(self) -> None:
        players = tuple(
            sorted(
                (
                    PlayerState(rfc1459_casefold("Te[u]K"), "Te[u]K", hits=99),
                    PlayerState(rfc1459_casefold("gaby"), "gaby", hits=12),
                ),
                key=lambda player: player.key,
            )
        )
        rendered = render_prometheus_metrics(
            GameState(now_ns=2_000_000_000, players=players),
            runtime(),
            excluded_nicknames=("Te[u]K",),
        ).decode("ascii")
        self.assertIn("pyduckhunt_players 1", rendered)
        self.assertIn("pyduckhunt_hits_total 12", rendered)

    def test_publisher_replaces_one_regular_file_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "pyduckhunt.prom"
            publisher = PrometheusMetricsPublisher(target)
            publisher.publish_state(GameState(now_ns=1))
            self.assertFalse(target.exists())
            publisher.publish_runtime(runtime(), GameState(now_ns=2))
            self.assertTrue(target.is_file())
            self.assertEqual(os.stat(target).st_mode & 0o777, 0o644)
            self.assertEqual(tuple(root.glob(f".{target.name}.*")), ())
            first = target.read_bytes()
            publisher.publish_runtime(
                runtime(bridge_dispatched=5),
                GameState(now_ns=3),
            )
            self.assertNotEqual(target.read_bytes(), first)

    def test_publisher_rejects_unsafe_paths_and_targets(self) -> None:
        for path in ("relative.prom", "/", "/tmp/not-prom.txt"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                PrometheusMetricsPublisher(path)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "metrics.prom"
            real = root / "real.prom"
            real.write_text("safe", encoding="ascii")
            target.symlink_to(real)
            publisher = PrometheusMetricsPublisher(target)
            with self.assertRaises(ValueError):
                publisher.publish_runtime(runtime(), GameState())

    def test_fanout_runs_every_publisher_and_reports_failure(self) -> None:
        calls: list[str] = []

        def broken(state: GameState) -> None:
            calls.append("broken")
            raise OSError("synthetic")

        def healthy(state: GameState) -> None:
            calls.append("healthy")

        fanout = StatePublisherFanout((broken, healthy))
        with self.assertRaises(RuntimeError):
            fanout.publish(GameState())
        self.assertEqual(calls, ["broken", "healthy"])


if __name__ == "__main__":
    unittest.main()
