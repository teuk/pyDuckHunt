from __future__ import annotations

import unittest

from pyduckhunt.game.commands import (
    CommandKind,
    CommandSyntaxError,
    command_usage,
    parse_command,
    rank_limit,
    validate_command,
)


class CommandParserTests(unittest.TestCase):
    def test_primary_shot_command(self) -> None:
        command = parse_command("!bang")
        self.assertIsNotNone(command)
        assert command is not None
        self.assertIs(command.kind, CommandKind.SHOT)

    def test_shot_alias_and_casefold(self) -> None:
        command = parse_command("!PAN")
        self.assertIsNotNone(command)
        assert command is not None
        self.assertIs(command.kind, CommandKind.SHOT)

    def test_query_command_keeps_arguments(self) -> None:
        command = parse_command("!duckstats OtherNick")
        self.assertIsNotNone(command)
        assert command is not None
        self.assertIs(command.kind, CommandKind.STATS)
        self.assertEqual(command.arguments, ("OtherNick",))

    def test_unknown_command_is_ignored(self) -> None:
        self.assertIsNone(parse_command("!unknown"))

    def test_prefix_must_be_first_character(self) -> None:
        self.assertIsNone(parse_command("  !bang"))

    def test_space_after_prefix_is_rejected(self) -> None:
        self.assertIsNone(parse_command("! bang"))

    def test_custom_prefix(self) -> None:
        command = parse_command(".reload", prefix=".")
        self.assertIsNotNone(command)
        assert command is not None
        self.assertIs(command.kind, CommandKind.RELOAD)

    def test_shot_and_reload_reject_arguments(self) -> None:
        for text in ("!bang now", "!reload now"):
            command = parse_command(text)
            assert command is not None
            with self.assertRaises(CommandSyntaxError):
                validate_command(command)

    def test_stats_and_inventory_accept_one_optional_nickname(self) -> None:
        for text in ("!duckstats", "!duckstats OtherNick", "!inventory", "!inventory OtherNick"):
            command = parse_command(text)
            assert command is not None
            self.assertIs(validate_command(command), command)

    def test_profile_query_rejects_two_nicknames(self) -> None:
        command = parse_command("!duckstats one two")
        assert command is not None
        with self.assertRaisesRegex(CommandSyntaxError, "duckstats"):
            validate_command(command)

    def test_shop_accepts_numeric_id_and_optional_target(self) -> None:
        for text in ("!shop", "!shop 16", "!shop 16 Target"):
            command = parse_command(text)
            assert command is not None
            self.assertIs(validate_command(command), command)

    def test_shop_rejects_non_numeric_or_extra_arguments(self) -> None:
        for text in ("!shop item", "!shop 0", "!shop 16 target extra"):
            command = parse_command(text)
            assert command is not None
            with self.assertRaises(CommandSyntaxError):
                validate_command(command)

    def test_rank_limit_defaults_and_accepts_observed_boundary(self) -> None:
        default_command = parse_command("!duckrank")
        boundary_command = parse_command("!duckrank 20")
        assert default_command is not None and boundary_command is not None
        self.assertEqual(rank_limit(default_command), 5)
        self.assertEqual(rank_limit(boundary_command), 20)

    def test_opt_in_hits_ranking_preserves_the_numeric_default(self) -> None:
        for text, expected in (("!duckrank hits", 5), ("!duckrank HITS 20", 20)):
            command = parse_command(text)
            assert command is not None
            self.assertEqual(rank_limit(command), expected)
        for text in ("!duckrank hits 0", "!duckrank hits 21", "!duckrank hits all",
                     "!duckrank hits 2 extra", "!duckrank 3 hits"):
            command = parse_command(text)
            assert command is not None
            with self.assertRaises(CommandSyntaxError):
                validate_command(command)

    def test_personal_rank_and_private_help_take_no_arguments(self) -> None:
        for text, kind in (("!myrank", CommandKind.MY_RANK),
                           ("!duckhelp", CommandKind.HELP)):
            command = parse_command(text)
            assert command is not None
            self.assertIs(command.kind, kind)
            self.assertIs(validate_command(command), command)
            extra = parse_command(text + " Hunter")
            assert extra is not None
            with self.assertRaises(CommandSyntaxError):
                validate_command(extra)

    def test_rank_limit_rejects_invalid_values(self) -> None:
        for text in ("!duckrank 0", "!duckrank 21", "!duckrank all", "!duckrank 1 2"):
            command = parse_command(text)
            assert command is not None
            with self.assertRaises(CommandSyntaxError):
                rank_limit(command)

    def test_usage_is_stable_for_each_command(self) -> None:
        self.assertEqual(command_usage(CommandKind.SHOP), "!shop [id [cible]]")
        command = parse_command("!pan")
        assert command is not None
        self.assertEqual(command_usage(command), "!bang")


if __name__ == "__main__":
    unittest.main()
