from __future__ import annotations

import threading
import unittest

from pyduckhunt.game.commands import Command, CommandKind
from pyduckhunt.game.curses import curse_spec
from pyduckhunt.game.engine import start_flight
from pyduckhunt.game.karma import KARMA_DECAY_PERIOD_NS
from pyduckhunt.game.loot import acquire_loot
from pyduckhunt.game.model import (
    ActiveCurse,
    FlightKind,
    GameState,
    IncidentAttempt,
    IncidentTargetAttempt,
    LootAward,
    OutcomeKind,
    PlayerState,
)
from pyduckhunt.persistence.replay import apply_replay_event
from pyduckhunt.runtime import (
    CalibratedEventResolver,
    EventResolutionError,
    HISTORICAL_NOISY_MISS_ESCAPE_BPS,
    IRCCommandContext,
    SettlementPolicy,
    SystemIntegerSource,
)


class SequenceSource:
    def __init__(self, *values: int) -> None:
        self.values = list(values)
        self.calls: list[tuple[int, int]] = []

    def __call__(self, minimum: int, maximum: int) -> int:
        self.calls.append((minimum, maximum))
        if not self.values:
            raise AssertionError("unexpected entropy draw")
        return self.values.pop(0)


def context(
    kind: CommandKind,
    invoked_as: str,
    *arguments: str,
    now_ns: int = 1,
) -> IRCCommandContext:
    return IRCCommandContext(
        now_ns,
        "Hunter",
        "#pond",
        Command(kind, invoked_as, tuple(arguments)),
    )


class RuntimeSettlementTests(unittest.TestCase):
    def test_query_needs_no_entropy_or_presence_lookup(self) -> None:
        entropy = SequenceSource()
        resolver = CalibratedEventResolver(
            entropy,
            lambda channel, nickname: (_ for _ in ()).throw(AssertionError()),
        )
        command_context = context(CommandKind.STATS, "duckstats")
        event = resolver(GameState(), command_context)
        self.assertEqual(event.command_kind, CommandKind.STATS)
        self.assertIsNone(event.shot_attempt)
        self.assertEqual(entropy.calls, [])

    def test_standard_kill_draws_ordered_loot_and_required_magnitude(self) -> None:
        entropy = SequenceSource(
            1,
            10_000,
            *(1_000 for _ in range(6)),
            1,
            *(1_000 for _ in range(11)),
            9,
        )
        resolver = CalibratedEventResolver(entropy, lambda channel, nickname: True)
        state = start_flight(
            GameState(),
            0,
            lifetime_ns=100,
            kind=FlightKind.STANDARD,
        ).state
        event = resolver(state, context(CommandKind.SHOT, "bang"))
        assert event.shot_attempt is not None
        self.assertEqual(event.shot_attempt.accuracy_roll, 1)
        self.assertEqual(event.shot_attempt.jam_roll, 10_000)
        self.assertEqual(event.shot_attempt.loot.key, "targeting_scope")
        self.assertEqual(event.shot_attempt.loot.magnitude, 9)
        self.assertEqual(entropy.values, [])

    def test_killing_hit_immediately_improves_the_same_bush_search(self) -> None:
        entropy = SequenceSource(
            1,
            10_000,
            20,
            1_000,
            1_000,
            14,
            *(1_000 for _ in range(14)),
        )
        resolver = CalibratedEventResolver(entropy, lambda channel, nickname: True)
        state = start_flight(GameState(), 0, lifetime_ns=100).state
        event = resolver(state, context(CommandKind.SHOT, "bang"))
        assert event.shot_attempt is not None
        self.assertEqual(event.shot_attempt.loot.key, "penetrating_ammunition")
        self.assertEqual(entropy.values, [])

    def test_effective_karma_adjusts_the_settled_jam_risk(self) -> None:
        policy = SettlementPolicy(base_jam_bps=1_000)
        positive = CalibratedEventResolver(
            SequenceSource(1, 10_000),
            lambda channel, nickname: True,
            policy=policy,
        )(
            GameState(players=(PlayerState("hunter", "Hunter", hits=1),)),
            context(CommandKind.SHOT, "bang"),
        )
        negative = CalibratedEventResolver(
            SequenceSource(1, 10_000),
            lambda channel, nickname: True,
            policy=policy,
        )(
            GameState(players=(PlayerState("hunter", "Hunter", wild_shots=1),)),
            context(CommandKind.SHOT, "bang"),
        )
        assert positive.shot_attempt is not None
        assert negative.shot_attempt is not None
        self.assertEqual(positive.shot_attempt.base_jam_bps, 500)
        self.assertEqual(negative.shot_attempt.base_jam_bps, 2_000)

    def test_active_recycler_draws_one_exact_replayed_thirtieth(self) -> None:
        state = acquire_loot(
            GameState(players=(PlayerState("hunter", "Hunter"),)),
            "Hunter",
            LootAward("ammo_recycler"),
            0,
        ).state
        entropy = SequenceSource(1, 10_000, 7)
        event = CalibratedEventResolver(
            entropy,
            lambda channel, nickname: True,
        )(state, context(CommandKind.SHOT, "bang"))
        assert event.shot_attempt is not None
        self.assertEqual(event.shot_attempt.recycler_roll, 7)
        self.assertEqual(entropy.calls, [(1, 10_000), (1, 10_000), (1, 30)])

    def test_default_settlement_uses_the_players_level_policy(self) -> None:
        event = CalibratedEventResolver(
            SequenceSource(9_900, 10_000),
            lambda channel, nickname: True,
        )(
            GameState(players=(PlayerState("hunter", "Hunter", level=93),)),
            context(CommandKind.SHOT, "bang"),
        )
        assert event.shot_attempt is not None
        self.assertEqual(event.shot_attempt.base_accuracy_bps, 9_900)
        self.assertEqual(event.shot_attempt.base_jam_bps, 700)
        self.assertEqual(event.shot_attempt.miss_penalty, 9)
        self.assertEqual(event.shot_attempt.wild_penalty, 16)
        self.assertFalse(event.shot_attempt.frighten_on_miss)

    def test_new_player_uses_level_one_settlement(self) -> None:
        entropy = SequenceSource(5_500, 10_000)
        event = CalibratedEventResolver(
            entropy,
            lambda channel, nickname: True,
        )(GameState(), context(CommandKind.SHOT, "bang"))
        assert event.shot_attempt is not None
        self.assertEqual(event.shot_attempt.base_accuracy_bps, 5_500)
        self.assertEqual(event.shot_attempt.base_jam_bps, 1_500)
        self.assertEqual((event.shot_attempt.miss_penalty, event.shot_attempt.wild_penalty), (1, 1))
        self.assertFalse(event.shot_attempt.frighten_on_miss)
        self.assertEqual(entropy.calls, [(1, 10_000), (1, 10_000)])

    def test_noisy_active_miss_uses_the_historical_five_percent_boundary(self) -> None:
        state = start_flight(GameState(), 0, lifetime_ns=100).state
        frightened_entropy = SequenceSource(
            10_000,
            10_000,
            HISTORICAL_NOISY_MISS_ESCAPE_BPS,
        )
        frightened = CalibratedEventResolver(
            frightened_entropy,
            lambda channel, nickname: True,
        )(state, context(CommandKind.SHOT, "bang"))
        assert frightened.shot_attempt is not None
        self.assertTrue(frightened.shot_attempt.frighten_on_miss)
        self.assertEqual(
            tuple(
                outcome.kind
                for outcome in apply_replay_event(state, frightened).outcomes
            ),
            (OutcomeKind.MISS, OutcomeKind.FLIGHT_FRIGHTENED),
        )
        self.assertEqual(
            frightened_entropy.calls,
            [(1, 10_000), (1, 10_000), (1, 10_000)],
        )

        retained_entropy = SequenceSource(
            10_000,
            10_000,
            HISTORICAL_NOISY_MISS_ESCAPE_BPS + 1,
        )
        retained = CalibratedEventResolver(
            retained_entropy,
            lambda channel, nickname: True,
        )(state, context(CommandKind.SHOT, "bang"))
        assert retained.shot_attempt is not None
        self.assertFalse(retained.shot_attempt.frighten_on_miss)
        retained_result = apply_replay_event(state, retained)
        self.assertEqual(
            tuple(outcome.kind for outcome in retained_result.outcomes),
            (OutcomeKind.MISS,),
        )
        self.assertIsNotNone(retained_result.state.flight)

    def test_noise_draw_is_skipped_for_hits_and_silent_misses(self) -> None:
        resistant = start_flight(
            GameState(),
            0,
            lifetime_ns=100,
            health=2,
        ).state
        hit_entropy = SequenceSource(1, 10_000)
        hit = CalibratedEventResolver(
            hit_entropy,
            lambda channel, nickname: True,
        )(resistant, context(CommandKind.SHOT, "bang"))
        assert hit.shot_attempt is not None
        self.assertFalse(hit.shot_attempt.frighten_on_miss)
        self.assertEqual(hit_entropy.calls, [(1, 10_000), (1, 10_000)])

        silent_state = start_flight(
            GameState(players=(PlayerState("hunter", "Hunter", level=40),)),
            0,
            lifetime_ns=100,
        ).state
        silent_entropy = SequenceSource(10_000, 10_000)
        silent = CalibratedEventResolver(
            silent_entropy,
            lambda channel, nickname: True,
        )(silent_state, context(CommandKind.SHOT, "bang"))
        assert silent.shot_attempt is not None
        self.assertFalse(silent.shot_attempt.frighten_on_miss)
        self.assertEqual(silent_entropy.calls, [(1, 10_000), (1, 10_000)])

    def test_jam_settlement_uses_the_modifier_after_due_decay(self) -> None:
        player = PlayerState(
            "hunter",
            "Hunter",
            karma_modifier_basis_points=200,
            karma_decay_at_ns=KARMA_DECAY_PERIOD_NS,
        )
        event = CalibratedEventResolver(
            SequenceSource(1, 10_000),
            lambda channel, nickname: True,
            policy=SettlementPolicy(base_jam_bps=1_000),
        )(
            GameState(players=(player,)),
            context(
                CommandKind.SHOT,
                "bang",
                now_ns=KARMA_DECAY_PERIOD_NS,
            ),
        )
        assert event.shot_attempt is not None
        self.assertEqual(event.shot_attempt.base_jam_bps, 991)

    def test_purchase_settles_price_magnitude_deadline_and_fatigue(self) -> None:
        scope_entropy = SequenceSource(12)
        scope = CalibratedEventResolver(
            scope_entropy,
            lambda channel, nickname: True,
        )(GameState(), context(CommandKind.SHOP, "shop", "7"))
        self.assertEqual((scope.charged_cost, scope.magnitude), (5, 12))
        self.assertFalse(scope.replace_active_effect)

        charm = CalibratedEventResolver(
            SequenceSource(8),
            lambda channel, nickname: True,
        )(GameState(), context(CommandKind.SHOP, "shop", "10"))
        self.assertEqual((charm.charged_cost, charm.magnitude), (13, 8))
        self.assertTrue(charm.replace_active_effect)

        deadline_entropy = SequenceSource(300)
        call = CalibratedEventResolver(
            deadline_entropy,
            lambda channel, nickname: True,
        )(
            GameState(),
            context(CommandKind.SHOP, "shop", "20", now_ns=100),
        )
        self.assertEqual(call.scheduled_for_ns, 300)

        thermos_entropy = SequenceSource(644)
        thermos = CalibratedEventResolver(
            thermos_entropy,
            lambda channel, nickname: True,
        )(GameState(), context(CommandKind.SHOP, "shop", "25"))
        self.assertEqual(thermos.fatigue_target_centi, 644)

    def test_target_presence_and_fatigue_are_settled_from_injected_state(self) -> None:
        state = GameState(
            players=(
                PlayerState("hunter", "Hunter", level=30, experience=300),
                PlayerState(
                    "target",
                    "Target",
                    level=30,
                    experience=300,
                    fatigue_centi=1_772,
                ),
            )
        )
        lookups: list[tuple[str, str]] = []
        resolver = CalibratedEventResolver(
            SequenceSource(),
            lambda channel, nickname: lookups.append((channel, nickname)) or True,
        )
        event = resolver(
            state,
            context(CommandKind.SHOP, "shop", "27", "Target"),
        )
        self.assertEqual(event.target_nickname, "Target")
        self.assertTrue(event.target_present)
        self.assertEqual(event.fatigue_relief_centi, 1_772)
        self.assertEqual(lookups, [("#pond", "Target")])

    def test_non_target_item_with_target_is_a_safe_public_rejection(self) -> None:
        resolver = CalibratedEventResolver(
            SequenceSource(),
            lambda channel, nickname: True,
        )
        with self.assertRaises(EventResolutionError) as captured:
            resolver(
                GameState(),
                context(CommandKind.SHOP, "shop", "1", "Target"),
            )
        self.assertEqual(
            captured.exception.public_message,
            "Cet objet n'accepte pas de cible.",
        )

    def test_unerring_miss_requires_and_accepts_an_incident_source(self) -> None:
        spec = curse_spec("unerring_miss")
        assert spec is not None
        state = GameState(
            players=(
                PlayerState("hunter", "Hunter"),
                PlayerState("victim", "Victim"),
            ),
            next_curse_id=2,
            curses=(
                ActiveCurse(
                    1,
                    "unerring_miss",
                    "hunter",
                    0,
                    spec.duration_ns,
                    spec.magnitude,
                ),
            ),
        )
        command_context = context(CommandKind.SHOT, "bang")
        unavailable = CalibratedEventResolver(
            SequenceSource(1, 10_000),
            lambda channel, nickname: True,
        )
        with self.assertRaises(EventResolutionError):
            unavailable(state, command_context)

        incident = IncidentAttempt((IncidentTargetAttempt("Victim"),))
        resolver = CalibratedEventResolver(
            SequenceSource(1, 10_000),
            lambda channel, nickname: True,
            incident_source=lambda game, command, attempt: incident,
        )
        event = resolver(state, command_context)
        assert event.shot_attempt is not None
        self.assertEqual(event.shot_attempt.incident, incident)

    def test_sources_policy_and_owner_contracts_are_strict(self) -> None:
        with self.assertRaises(ValueError):
            SettlementPolicy(base_accuracy_bps=True)
        with self.assertRaises(ValueError):
            SettlementPolicy(unusual_loot_chance_per_thousand=1)
        bad = CalibratedEventResolver(
            lambda minimum, maximum: maximum + 1,
            lambda channel, nickname: True,
        )
        with self.assertRaises(ValueError):
            bad(GameState(), context(CommandKind.SHOT, "bang"))

        resolver = CalibratedEventResolver(
            SequenceSource(),
            lambda channel, nickname: True,
        )
        errors: list[Exception] = []

        def foreign_call() -> None:
            try:
                resolver(GameState(), context(CommandKind.STATS, "duckstats"))
            except Exception as error:
                errors.append(error)

        thread = threading.Thread(target=foreign_call)
        thread.start()
        thread.join(2)
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], RuntimeError)

    def test_system_integer_source_is_inclusive_and_checks_its_backend(self) -> None:
        source = SystemIntegerSource(lambda span: span - 1)
        self.assertEqual(source(4, 9), 9)
        invalid = SystemIntegerSource(lambda span: True)
        with self.assertRaises(RuntimeError):
            invalid(1, 2)


if __name__ == "__main__":
    unittest.main()
