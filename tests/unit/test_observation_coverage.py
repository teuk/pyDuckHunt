from __future__ import annotations

import tempfile
import unittest
from collections import Counter
from pathlib import Path

from pyduckhunt.game.commands import Command, CommandKind
from pyduckhunt.persistence import JournalFile, ReplayEvent
from pyduckhunt.persistence.replay import replay_records, snapshot_from_result
from pyduckhunt.persistence.snapshot import SnapshotStore
from tools.observation_coverage import (
    MAX_JOURNAL_BYTES,
    build_report,
    render_markdown,
    render_tsv,
    validate_journal_path,
    validate_snapshot_path,
    _scenario_results,
)


class ObservationCoverageTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.path = self.root / "events.jsonl"
        self.journal = JournalFile(self.path, sync=False)

    def test_verified_journal_marks_an_ordinary_start_and_expiry_observed(self) -> None:
        self.journal.append(ReplayEvent.start_flight(1, 1))
        self.journal.append(ReplayEvent.advance_time(2))

        report = build_report(self.journal.read_records())
        first = report.scenarios[0]

        self.assertEqual(first.identifier, "IO-001")
        self.assertEqual(first.status, "OBSERVED")
        self.assertEqual(
            dict(first.evidence),
            {"ordinary_started": 1, "ordinary_expired": 1},
        )
        self.assertEqual(report.records_in_scope, 2)
        self.assertEqual(report.first_sequence, 1)
        self.assertEqual(report.last_sequence, 2)

    def test_sequence_floor_replays_context_but_excludes_earlier_evidence(self) -> None:
        self.journal.append(ReplayEvent.start_flight(1, 1))
        self.journal.append(ReplayEvent.advance_time(2))

        report = build_report(self.journal.read_records(), after_sequence=1)
        first = report.scenarios[0]

        self.assertEqual(first.status, "PARTIAL")
        self.assertEqual(
            dict(first.evidence),
            {"ordinary_started": 0, "ordinary_expired": 1},
        )
        self.assertEqual(report.records_in_scope, 1)

    def test_sealed_snapshot_is_a_valid_semantic_replay_boundary(self) -> None:
        self.journal.append(ReplayEvent.start_flight(1, 1))
        first = self.journal.read_records()
        recovered = replay_records(first)
        snapshot_path = self.root / "snapshot.json"
        SnapshotStore(snapshot_path).write(snapshot_from_result(recovered))
        self.journal.append(ReplayEvent.advance_time(2))
        snapshot = SnapshotStore(validate_snapshot_path(snapshot_path)).read()
        assert snapshot is not None

        report = build_report(
            self.journal.read_records(),
            after_sequence=1,
            initial_state=snapshot.state,
            replay_after_sequence=snapshot.journal_sequence,
            initial_digest=snapshot.journal_digest,
        )

        self.assertEqual(report.replay_boundary_sequence, 1)
        self.assertEqual(report.records_in_scope, 1)
        self.assertEqual(dict(report.scenarios[0].evidence)["ordinary_expired"], 1)

    def test_query_coverage_is_aggregate_and_does_not_print_identity(self) -> None:
        self.journal.append(
            ReplayEvent.runtime_command(
                1,
                "PrivateHunter",
                Command(CommandKind.STATS, "duckstats"),
            )
        )
        report = build_report(self.journal.read_records())
        markdown = render_markdown(report)

        self.assertNotIn("PrivateHunter", markdown)
        self.assertNotIn("duckstats", markdown)
        self.assertIn("stats_self=1", markdown)
        stats = next(value for value in report.scenarios if value.identifier == "IO-008")
        self.assertEqual(stats.status, "PARTIAL")

    def test_complete_multi_component_rules_require_every_component(self) -> None:
        partial = _scenario_results(Counter({"empty": 2, "jammed": 1}))
        partial_weapon = next(value for value in partial if value.identifier == "IO-006")
        self.assertEqual(partial_weapon.status, "PARTIAL")

        complete = _scenario_results(
            Counter({"empty": 2, "jammed": 1, "unjammed": 1})
        )
        complete_weapon = next(value for value in complete if value.identifier == "IO-006")
        self.assertEqual(complete_weapon.status, "OBSERVED")

    def test_two_bread_threshold_is_not_claimed_from_one_piece(self) -> None:
        one_piece = _scenario_results(
            Counter(
                {
                    "bread_purchase": 1,
                    "bread_consumed": 1,
                    "bread_extended_takeoff": 1,
                }
            )
        )
        bread = next(value for value in one_piece if value.identifier == "IO-013")
        self.assertEqual(bread.status, "PARTIAL")

    def test_external_scenarios_are_never_inferred_from_journal_counts(self) -> None:
        results = _scenario_results(Counter({"service_restart": 99}))
        external = {value.identifier: value for value in results[15:]}

        self.assertEqual(set(external), {"IO-016", "IO-017", "IO-018", "IO-019", "IO-020"})
        self.assertTrue(
            all(value.status == "EXTERNAL-EVIDENCE" for value in external.values())
        )

    def test_tsv_has_one_row_per_protocol_scenario(self) -> None:
        report = build_report(())
        lines = render_tsv(report).splitlines()

        self.assertEqual(lines[0], "scenario_id\tstatus\tevidence\tnote")
        self.assertEqual(len(lines), 21)
        self.assertTrue(lines[1].startswith("IO-001\tNOT-OBSERVED\t"))
        self.assertTrue(lines[-1].startswith("IO-020\tEXTERNAL-EVIDENCE\t"))

    def test_range_contract_rejects_reversed_boundary(self) -> None:
        with self.assertRaisesRegex(ValueError, "greater than"):
            build_report((), after_sequence=10, through_sequence=10)

    def test_replay_boundary_digest_must_match_verified_journal(self) -> None:
        self.journal.append(ReplayEvent.advance_time(1))
        with self.assertRaisesRegex(ValueError, "digest"):
            build_report(
                self.journal.read_records(),
                after_sequence=1,
                replay_after_sequence=1,
                initial_digest="f" * 64,
            )

    def test_path_contract_rejects_relative_symlink_and_oversized_files(self) -> None:
        self.path.write_bytes(b"\n")
        with self.assertRaisesRegex(ValueError, "absolute"):
            validate_journal_path(Path("events.jsonl"))

        link = self.root / "events-link.jsonl"
        link.symlink_to(self.path)
        with self.assertRaisesRegex(ValueError, "non-symlink"):
            validate_journal_path(link)

        oversized = self.root / "oversized.jsonl"
        with oversized.open("wb") as handle:
            handle.truncate(MAX_JOURNAL_BYTES + 1)
        with self.assertRaisesRegex(ValueError, "analysis limit"):
            validate_journal_path(oversized)


if __name__ == "__main__":
    unittest.main()
