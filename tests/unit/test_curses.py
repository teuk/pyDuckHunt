from __future__ import annotations

import unittest

from pyduckhunt.game.curses import CURSE_CATALOG, HOUR_NS, curse_spec, validate_active_curse
from pyduckhunt.game.model import ActiveCurse


class CurseCatalogTests(unittest.TestCase):
    def test_supported_curses_are_unique_and_bounded(self) -> None:
        keys = tuple(curse.key for curse in CURSE_CATALOG)
        self.assertEqual(len(keys), len(set(keys)))
        self.assertTrue(all(curse.duration_ns > 0 for curse in CURSE_CATALOG))

    def test_calibrated_duration_and_magnitude(self) -> None:
        self.assertEqual(curse_spec("confusion").duration_ns, 24 * HOUR_NS)
        self.assertEqual(curse_spec("confusion").magnitude, 2)
        self.assertEqual(curse_spec("slowness").duration_ns, 4 * HOUR_NS)
        self.assertEqual(curse_spec("slowness").magnitude, 5)

    def test_active_curse_must_match_catalog(self) -> None:
        valid = ActiveCurse(1, "tremor", "hunter", 0, 24 * HOUR_NS, 25)
        validate_active_curse(valid)
        with self.assertRaises(ValueError):
            validate_active_curse(
                ActiveCurse(1, "tremor", "hunter", 0, 24 * HOUR_NS, 24)
            )


if __name__ == "__main__":
    unittest.main()
