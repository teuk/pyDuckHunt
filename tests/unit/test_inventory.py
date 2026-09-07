from __future__ import annotations

import unittest

from pyduckhunt.game.inventory import add_item, item_quantity, remove_item
from pyduckhunt.game.model import InventoryStack, PlayerState


PLAYER = PlayerState(key="hunter", nickname="Hunter")


class InventoryTests(unittest.TestCase):
    def test_missing_item_has_zero_quantity(self) -> None:
        self.assertEqual(item_quantity(PLAYER, "lucky_token"), 0)

    def test_add_creates_a_stack(self) -> None:
        updated = add_item(PLAYER, "lucky_token", 2)
        self.assertEqual(updated.inventory, (InventoryStack("lucky_token", 2),))

    def test_add_merges_and_sorts_stacks(self) -> None:
        updated = add_item(add_item(PLAYER, "target_lens"), "lucky_token", 2)
        updated = add_item(updated, "target_lens", 3)
        self.assertEqual(
            updated.inventory,
            (InventoryStack("lucky_token", 2), InventoryStack("target_lens", 4)),
        )

    def test_remove_decrements_a_stack(self) -> None:
        updated = remove_item(add_item(PLAYER, "lucky_token", 3), "lucky_token")
        self.assertEqual(item_quantity(updated, "lucky_token"), 2)

    def test_remove_last_item_drops_the_stack(self) -> None:
        updated = remove_item(add_item(PLAYER, "lucky_token"), "lucky_token")
        self.assertEqual(updated.inventory, ())

    def test_remove_rejects_insufficient_quantity(self) -> None:
        with self.assertRaises(ValueError):
            remove_item(PLAYER, "lucky_token")

    def test_item_identifiers_are_bounded_and_stable(self) -> None:
        for key in ("UPPER", "two words", "-leading", "a" * 65):
            with self.subTest(key=key):
                with self.assertRaises(ValueError):
                    add_item(PLAYER, key)

    def test_truth_value_is_not_a_quantity(self) -> None:
        with self.assertRaises(ValueError):
            add_item(PLAYER, "lucky_token", True)


if __name__ == "__main__":
    unittest.main()
