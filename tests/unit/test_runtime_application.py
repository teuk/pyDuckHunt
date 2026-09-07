from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path

from pyduckhunt.game.commands import CommandKind
from pyduckhunt.game.model import GameState
from pyduckhunt.irc import parse_irc_line
from pyduckhunt.persistence import JournalFile, ReplayEvent, SnapshotStore
from pyduckhunt.runtime import (
    BridgeStatus,
    DispatchStatus,
    EventResolutionError,
    IRCCommandContext,
    IRCGameBridge,
    RuntimeOrchestrator,
)


def resolved_event(state: GameState, context: IRCCommandContext) -> ReplayEvent:
    command = context.command
    if command.kind is CommandKind.SHOP and command.arguments:
        return ReplayEvent.runtime_purchase(
            context.now_ns,
            context.nickname,
            int(command.arguments[0]),
            0,
            target_nickname=(
                command.arguments[1] if len(command.arguments) == 2 else None
            ),
            target_present=True if len(command.arguments) == 2 else None,
        )
    return ReplayEvent.runtime_command(
        context.now_ns,
        context.nickname,
        command,
    )


class IRCGameBridgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.journal = JournalFile(root / "events.jsonl")
        self.snapshots = SnapshotStore(root / "snapshot.json")
        self.batches: list[tuple[bytes, ...]] = []
        self.runtime, _ = RuntimeOrchestrator.open(
            self.journal,
            self.snapshots,
            self.batches.append,
            persistence_capacity=2,
            snapshot_interval=None,
        )
        self.addCleanup(self._close_runtime)
        self.bridge = IRCGameBridge(
            self.runtime,
            ("#pond",),
            resolved_event,
        )

    def _close_runtime(self) -> None:
        if self.runtime.persistence.state.value in ("running", "closing"):
            self.runtime.close(2)

    @staticmethod
    def message(text: str, *, command: str = "PRIVMSG", channel: str = "#pond"):
        return parse_irc_line(f":Hunter!u@example {command} {channel} :{text}")

    def test_query_is_rendered_enqueued_and_persisted(self) -> None:
        result = self.bridge.handle(1, self.message("!duckstats"))
        self.assertEqual(result.status, BridgeStatus.DISPATCHED)
        assert result.dispatch is not None
        self.assertEqual(result.dispatch.status, DispatchStatus.ACCEPTED)
        self.assertEqual(result.priority_batch, self.batches[-1])
        self.assertTrue(result.priority_batch[0].startswith(b"NOTICE Hunter :"))
        self.assertIn("Profil".encode(), result.priority_batch[0])
        assert result.dispatch.persistence_ticket is not None
        result.dispatch.persistence_ticket.wait(2)
        records = self.journal.read_records()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].event.command_kind, CommandKind.STATS)

    def test_profile_inventory_and_catalog_are_private_notices(self) -> None:
        for now_ns, text, expected_lines in (
            (1, "!duckstats", 2),
            (2, "!inventory", 1),
            (3, "!shop", 1),
        ):
            with self.subTest(text=text):
                result = self.bridge.handle(now_ns, self.message(text))
                self.assertTrue(result.priority_batch)
                self.assertEqual(len(result.priority_batch), expected_lines)
                self.assertTrue(
                    all(
                        wire.startswith(b"NOTICE Hunter :")
                        for wire in result.priority_batch
                    )
                )
                if text == "!duckstats":
                    self.assertIn(b"[Arme]", result.priority_batch[0])
                    self.assertIn(b"[Tableau de chasse]", result.priority_batch[1])
                if text == "!inventory":
                    self.assertIn(b"[Inventaire]", result.priority_batch[0])
                if text == "!shop":
                    self.assertNotIn(b"https://", result.priority_batch[0])
                assert result.dispatch is not None
                assert result.dispatch.persistence_ticket is not None
                result.dispatch.persistence_ticket.wait(2)

        ranking = self.bridge.handle(4, self.message("!duckrank 5"))
        self.assertTrue(ranking.priority_batch[0].startswith(b"PRIVMSG #pond :"))

    def test_configured_shop_url_reaches_the_private_notice(self) -> None:
        bridge = IRCGameBridge(
            self.runtime,
            ("#pond",),
            resolved_event,
            shop_url="https://games.example/duckhunt/shop/",
        )
        result = bridge.handle(1, self.message("!shop"))
        self.assertIn(
            b"https://games.example/duckhunt/shop/",
            result.priority_batch[0],
        )
        assert result.dispatch is not None
        assert result.dispatch.persistence_ticket is not None
        result.dispatch.persistence_ticket.wait(2)

    def test_configured_ranking_url_reaches_a_separate_public_line(self) -> None:
        bridge = IRCGameBridge(
            self.runtime,
            ("#pond",),
            resolved_event,
            ranking_url="https://io.teuk.org/DuckHunt/rankings",
        )
        result = bridge.handle(1, self.message("!duckrank"))
        self.assertEqual(len(result.priority_batch), 2)
        self.assertTrue(
            all(
                wire.startswith(b"PRIVMSG #pond :")
                for wire in result.priority_batch
            )
        )
        self.assertIn(b"[TOP 5]", result.priority_batch[0])
        self.assertIn(
            b"https://io.teuk.org/DuckHunt/rankings",
            result.priority_batch[1],
        )
        assert result.dispatch is not None
        assert result.dispatch.persistence_ticket is not None
        result.dispatch.persistence_ticket.wait(2)

    def test_successful_live_shot_exposes_xp_and_level_progression(self) -> None:
        started = self.runtime.dispatch(
            ReplayEvent.start_flight(1, 100),
            lambda transition: (),
        )
        self.assertEqual(started.status, DispatchStatus.ACCEPTED)
        assert started.persistence_ticket is not None
        started.persistence_ticket.wait(2)

        result = self.bridge.handle(2, self.message("!bang"))
        self.assertEqual(result.status, BridgeStatus.DISPATCHED)
        rendered = b" ".join(result.priority_batch)
        self.assertIn(b"[10 xp]", rendered)
        self.assertIn(b"niv. 1", rendered)
        self.assertIn(b"progression : 10/20", rendered)
        assert result.dispatch is not None
        assert result.dispatch.persistence_ticket is not None
        result.dispatch.persistence_ticket.wait(2)

    def test_purchase_target_is_checked_before_dispatch(self) -> None:
        result = self.bridge.handle(1, self.message("!shop 999 Friend"))
        self.assertEqual(result.status, BridgeStatus.DISPATCHED)
        assert result.dispatch is not None
        assert result.dispatch.persistence_ticket is not None
        result.dispatch.persistence_ticket.wait(2)
        event = self.journal.read_records()[0].event
        self.assertEqual(event.item_id, 999)
        self.assertEqual(event.target_nickname, "Friend")

    def test_unknown_wrong_channel_and_non_privmsg_are_ignored(self) -> None:
        for message in (
            self.message("ordinary text"),
            self.message("!unknown"),
            self.message("!duckstats", channel="#elsewhere"),
            self.message("!duckstats", command="NOTICE"),
        ):
            with self.subTest(message=message):
                self.assertEqual(
                    self.bridge.handle(1, message).status,
                    BridgeStatus.IGNORED,
                )
        self.assertEqual(self.batches, [])
        self.assertEqual(self.runtime.state, GameState())

    def test_known_bad_syntax_has_one_nonpersistent_response(self) -> None:
        result = self.bridge.handle(1, self.message("!reload later"))
        self.assertEqual(result.status, BridgeStatus.INVALID)
        self.assertIn(b"syntaxe", result.priority_batch[0])
        self.assertEqual(self.batches, [result.priority_batch])
        self.assertEqual(self.runtime.state, GameState())
        self.assertEqual(self.journal.read_records(), ())

    def test_safe_settlement_rejection_has_one_nonpersistent_response(self) -> None:
        def rejected(state: GameState, context: IRCCommandContext) -> ReplayEvent:
            raise EventResolutionError("Commande impossible dans cet état.")

        bridge = IRCGameBridge(self.runtime, ("#pond",), rejected)
        result = bridge.handle(1, self.message("!reload"))
        self.assertEqual(result.status, BridgeStatus.INVALID)
        self.assertIn("Commande impossible".encode(), result.priority_batch[0])
        self.assertEqual(self.runtime.state, GameState())
        self.assertEqual(self.journal.read_records(), ())

    def test_resolver_identity_mismatch_is_rejected_without_mutation(self) -> None:
        def mismatch(state: GameState, context: IRCCommandContext) -> ReplayEvent:
            return ReplayEvent.runtime_command(
                context.now_ns,
                "Other",
                context.command,
            )

        bridge = IRCGameBridge(self.runtime, ("#pond",), mismatch)
        with self.assertRaises(ValueError):
            bridge.handle(1, self.message("!reload"))
        self.assertEqual(self.batches, [])
        self.assertEqual(self.runtime.state, GameState())

    def test_backpressure_is_visible_without_state_or_journal_mutation(self) -> None:
        first = self.runtime.persistence.reserve()
        second = self.runtime.persistence.reserve()
        assert first is not None and second is not None
        result = self.bridge.handle(1, self.message("!reload"))
        self.assertEqual(result.status, BridgeStatus.DISPATCHED)
        assert result.dispatch is not None
        self.assertEqual(result.dispatch.status, DispatchStatus.BACKPRESSURED)
        self.assertIn("Service occupé".encode(), result.priority_batch[0])
        self.assertEqual(self.runtime.state, GameState())
        self.assertEqual(self.journal.read_records(), ())
        first.cancel()
        second.cancel()

    def test_last_flight_provider_is_explicit_and_strict(self) -> None:
        bridge = IRCGameBridge(
            self.runtime,
            ("#pond",),
            resolved_event,
            last_flight_provider=lambda state, now_ns: 3_661_000_000_000,
        )
        result = bridge.handle(1, self.message("!lastduck"))
        self.assertIn(b"1h01mn01s", result.priority_batch[0])

        invalid = IRCGameBridge(
            self.runtime,
            ("#pond",),
            resolved_event,
            last_flight_provider=lambda state, now_ns: True,
        )
        with self.assertRaises(ValueError):
            invalid.handle(2, self.message("!lastduck"))

    def test_bridge_rejects_time_travel_and_foreign_thread_mutation(self) -> None:
        self.bridge.handle(10, self.message("ordinary"))
        with self.assertRaises(ValueError):
            self.bridge.handle(9, self.message("ordinary"))
        errors: list[Exception] = []

        def foreign_handle() -> None:
            try:
                self.bridge.handle(10, self.message("ordinary"))
            except Exception as error:
                errors.append(error)

        thread = threading.Thread(target=foreign_handle)
        thread.start()
        thread.join(2)
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], RuntimeError)

    def test_bridge_policy_rejects_ambiguous_values(self) -> None:
        with self.assertRaises(ValueError):
            IRCGameBridge(self.runtime, ["#pond"], resolved_event)  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            IRCGameBridge(self.runtime, ("pond",), resolved_event)
        with self.assertRaises(ValueError):
            IRCGameBridge(self.runtime, ("#Pond", "#pond"), resolved_event)
        with self.assertRaises(ValueError):
            IRCGameBridge(
                self.runtime,
                ("#pond",),
                resolved_event,
                shop_url="http://games.example/shop/",
            )
        with self.assertRaises(ValueError):
            IRCGameBridge(
                self.runtime,
                ("#pond",),
                resolved_event,
                ranking_url="http://games.example/rankings/",
            )


if __name__ == "__main__":
    unittest.main()
