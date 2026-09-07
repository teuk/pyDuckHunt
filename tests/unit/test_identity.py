from __future__ import annotations

import unittest

from pyduckhunt.identity import rfc1459_casefold, same_irc_name


class IRCIdentityTests(unittest.TestCase):
    def test_ascii_letters_are_case_insensitive(self) -> None:
        self.assertTrue(same_irc_name("Hunter", "hUNTER"))

    def test_rfc1459_special_pairs_are_equivalent(self) -> None:
        self.assertEqual(rfc1459_casefold("A[\\]^"), "a{|}~")

    def test_distinct_nicknames_remain_distinct(self) -> None:
        self.assertFalse(same_irc_name("hunter-one", "hunter-two"))


if __name__ == "__main__":
    unittest.main()
