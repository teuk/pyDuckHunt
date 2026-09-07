from __future__ import annotations

import unittest

from pyduckhunt.time_format import format_duration_ms, format_duration_ns


class TimeFormatTests(unittest.TestCase):
    def test_milliseconds_use_compact_seconds_minutes_and_hours(self) -> None:
        cases = (
            (0, "0s"),
            (1, "0.001s"),
            (999, "0.999s"),
            (1_000, "1s"),
            (1_234, "1.234s"),
            (59_999, "59.999s"),
            (60_000, "1mn00s"),
            (114_000, "1mn54s"),
            (154_200, "2mn34.2s"),
            (3_600_000, "1h00mn00s"),
            (3_903_000, "1h05mn03s"),
            (86_400_000, "24h00mn00s"),
        )
        for value, expected in cases:
            with self.subTest(value=value):
                self.assertEqual(format_duration_ms(value), expected)

    def test_nanoseconds_follow_the_same_visible_contract(self) -> None:
        self.assertEqual(format_duration_ns(154_200_000_000), "2mn34s")
        self.assertEqual(format_duration_ns(3_903_000_000_000), "1h05mn03s")
        self.assertEqual(format_duration_ns(1), "<1s")

    def test_invalid_values_are_rejected(self) -> None:
        for formatter in (format_duration_ms, format_duration_ns):
            for value in (-1, True, 1.5, "1"):
                with self.subTest(formatter=formatter.__name__, value=value):
                    with self.assertRaises(ValueError):
                        formatter(value)  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
