from __future__ import annotations

import threading
import unittest

from pyduckhunt.game.model import FlightKind, Outcome, OutcomeKind
from pyduckhunt.rendering import (
    FLIGHT_BEAKS,
    FLIGHT_CALLS,
    FLIGHT_EYES,
    FLIGHT_LINES,
    FLIGHT_TRAILS,
    FLIGHT_WINGS,
    FlightAppearance,
    RandomizedFlightAppearanceSource,
    render_outcome,
    render_wire_response,
)


class SequenceIntegerSource:
    def __init__(self, *values: int) -> None:
        self.values = list(values)
        self.calls: list[tuple[int, int]] = []

    def __call__(self, minimum: int, maximum: int) -> int:
        self.calls.append((minimum, maximum))
        if not self.values:
            raise AssertionError("unexpected appearance draw")
        return self.values.pop(0)


class FlightAppearanceTests(unittest.TestCase):
    def test_catalog_is_exact_unique_plain_text_and_link_free(self) -> None:
        self.assertEqual(len(FLIGHT_TRAILS), 32)
        self.assertEqual(len(FLIGHT_WINGS), 2)
        self.assertEqual(len(FLIGHT_EYES), 20)
        self.assertEqual(len(FLIGHT_BEAKS), 3)
        self.assertEqual(len(FLIGHT_CALLS), 40)
        self.assertEqual(len(FLIGHT_LINES), 31)
        for values in (
            FLIGHT_TRAILS,
            FLIGHT_WINGS,
            FLIGHT_EYES,
            FLIGHT_BEAKS,
            FLIGHT_CALLS,
            FLIGHT_LINES,
        ):
            self.assertEqual(len(values), len(set(values)))
            self.assertTrue(all("://" not in value for value in values))

    def test_source_draws_every_component_and_selects_spoken_line(self) -> None:
        integers = SequenceIntegerSource(31, 1, 19, 2, 1, 30)
        source = RandomizedFlightAppearanceSource(integers)
        appearance = source()
        self.assertEqual(
            appearance,
            FlightAppearance(FLIGHT_TRAILS[31], "/_ø-", FLIGHT_LINES[30]),
        )
        self.assertEqual(
            integers.calls,
            [(0, 31), (0, 1), (0, 19), (0, 2), (1, 4), (0, 30)],
        )

    def test_source_uses_three_in_four_weight_for_calls(self) -> None:
        integers = SequenceIntegerSource(0, 0, 0, 0, 4, 39)
        appearance = RandomizedFlightAppearanceSource(integers)()
        self.assertEqual(appearance.silhouette, "\\_O<")
        self.assertEqual(appearance.utterance, FLIGHT_CALLS[39])
        self.assertEqual(integers.calls[-1], (0, 39))

    def test_source_rejects_bad_bound_result_and_foreign_thread(self) -> None:
        with self.assertRaises(RuntimeError):
            RandomizedFlightAppearanceSource(SequenceIntegerSource(True))()

        source = RandomizedFlightAppearanceSource(
            SequenceIntegerSource(0, 0, 0, 0, 1, 0)
        )
        failures: list[BaseException] = []

        def invoke() -> None:
            try:
                source()
            except BaseException as error:
                failures.append(error)

        thread = threading.Thread(target=invoke)
        thread.start()
        thread.join()
        self.assertEqual(len(failures), 1)
        self.assertIsInstance(failures[0], RuntimeError)

    def test_appearance_contract_rejects_controls_and_oversized_text(self) -> None:
        for appearance in (
            ("", "\\_O<", "COIN"),
            ("trail\n", "\\_O<", "COIN"),
            ("trail", "\\_O<", "\x0304COIN"),
            ("trail", "x" * 9, "COIN"),
            ("trail", "\\_O<", "x" * 121),
        ):
            with self.subTest(appearance=appearance), self.assertRaises(ValueError):
                FlightAppearance(*appearance)

    def test_golden_arrival_is_indistinguishable_from_a_standard_flight(self) -> None:
        appearance = FlightAppearance(
            FLIGHT_TRAILS[0],
            "/_ø-",
            max(FLIGHT_LINES, key=len),
        )
        standard = render_outcome(
            Outcome(OutcomeKind.FLIGHT_STARTED, flight_kind=FlightKind.STANDARD),
            flight_appearance=appearance,
        )[0]
        self.assertIn("\x0314", standard)
        self.assertIn("\x02/_ø-\x0f", standard)
        self.assertIn(appearance.utterance, standard)
        self.assertLessEqual(len(render_wire_response("#pond", (standard,))[0]), 512)

        golden = render_outcome(
            Outcome(OutcomeKind.FLIGHT_STARTED, flight_kind=FlightKind.GOLDEN),
            flight_appearance=appearance,
        )[0]
        self.assertEqual(golden, standard)
        self.assertNotIn("CANARD DORÉ", golden)

    def test_first_successful_bang_reveals_a_golden_flight(self) -> None:
        miss = render_outcome(
            Outcome(OutcomeKind.MISS, actor="Hunter", flight_kind=FlightKind.GOLDEN)
        )[0]
        survived = render_outcome(
            Outcome(
                OutcomeKind.FLIGHT_SURVIVED,
                actor="Hunter",
                flight_kind=FlightKind.GOLDEN,
                damage_dealt=1,
            )
        )[0]
        killed = render_outcome(
            Outcome(
                OutcomeKind.HIT,
                actor="Hunter",
                flight_kind=FlightKind.GOLDEN,
                experience_awarded=36,
            )
        )[0]
        self.assertNotIn("CANARD DORÉ", miss)
        self.assertIn("CANARD DORÉ", survived)
        self.assertIn("CANARD DORÉ", killed)


if __name__ == "__main__":
    unittest.main()
