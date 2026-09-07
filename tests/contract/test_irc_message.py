from __future__ import annotations

import unittest

from pyduckhunt.irc import (
    IRCProtocolError,
    notice_text_budget,
    parse_irc_line,
    privmsg_text_budget,
    render_irc_message,
    render_notice,
    render_notice_bounded,
    render_pong,
    render_privmsg,
    render_privmsg_bounded,
)


class IRCMessageContractTests(unittest.TestCase):
    def test_parse_prefixed_privmsg(self) -> None:
        message = parse_irc_line(":Hunter!user@example.test PRIVMSG #pond :!bang\r\n")
        self.assertEqual(message.command, "PRIVMSG")
        self.assertEqual(message.nickname, "Hunter")
        self.assertEqual(message.params, ("#pond", "!bang"))

    def test_parse_ping_without_wire_ending(self) -> None:
        message = parse_irc_line("PING :server.example")
        self.assertEqual(message.command, "PING")
        self.assertEqual(message.params, ("server.example",))

    def test_parse_ircv3_tags_and_escapes(self) -> None:
        message = parse_irc_line(
            "@time=2026-08-29T12:00:00Z;label=one\\stwo\\:three :n!u@h NOTICE x :ok"
        )
        self.assertEqual(message.tag("label"), "one two;three")
        self.assertEqual(message.tag("time"), "2026-08-29T12:00:00Z")

    def test_parse_replaces_invalid_utf8_without_losing_frame(self) -> None:
        message = parse_irc_line(b":n!u@h PRIVMSG #pond :caf\xff\r\n")
        self.assertEqual(message.params[-1], "caf\ufffd")

    def test_parse_rejects_embedded_newline(self) -> None:
        with self.assertRaises(IRCProtocolError):
            parse_irc_line("PING :one\r\nPRIVMSG #pond :two")

    def test_parse_rejects_more_than_fifteen_parameters(self) -> None:
        with self.assertRaises(IRCProtocolError):
            parse_irc_line("COMMAND " + " ".join(str(index) for index in range(16)))

    def test_parse_rejects_oversized_wire_line(self) -> None:
        with self.assertRaises(IRCProtocolError):
            parse_irc_line(b"NOTICE x :" + (b"a" * 501) + b"\r\n")

    def test_parse_accepts_exact_wire_limit(self) -> None:
        message = parse_irc_line(b"NOTICE x :" + (b"a" * 500) + b"\r\n")
        self.assertEqual(len(message.params[-1]), 500)

    def test_parse_counts_assumed_ending_for_unterminated_bytes(self) -> None:
        with self.assertRaises(IRCProtocolError):
            parse_irc_line(b"NOTICE x :" + (b"a" * 501))

    def test_render_privmsg_uses_trailing_parameter(self) -> None:
        self.assertEqual(
            render_privmsg("#pond", "quick response"),
            b"PRIVMSG #pond :quick response\r\n",
        )

    def test_privmsg_budget_produces_exact_wire_limit(self) -> None:
        budget = privmsg_text_budget("#pond")
        wire = render_privmsg_bounded("#pond", ("x" * (budget - 1)) + " ")
        self.assertEqual(len(wire), 512)

    def test_notice_budget_produces_exact_wire_limit(self) -> None:
        budget = notice_text_budget("Hunter")
        wire = render_notice_bounded("Hunter", ("x" * (budget - 1)) + " ")
        self.assertEqual(len(wire), 512)

    def test_bounded_notice_preserves_short_text(self) -> None:
        self.assertEqual(
            render_notice_bounded("Hunter", "inventaire vide"),
            render_notice("Hunter", "inventaire vide"),
        )

    def test_bounded_notice_truncates_at_utf8_boundary(self) -> None:
        wire = render_notice_bounded("Hunter", "🦆" * 200)
        self.assertLessEqual(len(wire), 512)
        decoded = wire.decode("utf-8")
        self.assertTrue(decoded.endswith("…\r\n"))
        self.assertNotIn("�", decoded)

    def test_bounded_privmsg_truncates_at_utf8_boundary(self) -> None:
        wire = render_privmsg_bounded("#pond", "🦆" * 200)
        self.assertLessEqual(len(wire), 512)
        decoded = wire.decode("utf-8")
        self.assertTrue(decoded.endswith("…\r\n"))
        self.assertNotIn("�", decoded)

    def test_bounded_privmsg_preserves_short_text(self) -> None:
        self.assertEqual(
            render_privmsg_bounded("#pond", "coin coin"),
            render_privmsg("#pond", "coin coin"),
        )

    def test_bounded_privmsg_rejects_injection_before_truncation(self) -> None:
        with self.assertRaises(IRCProtocolError):
            render_privmsg_bounded("#pond", "safe\r\nOPER root")

    def test_bounded_privmsg_rejects_an_oversized_suffix(self) -> None:
        with self.assertRaises(IRCProtocolError):
            render_privmsg_bounded("#pond", "x" * 600, ellipsis="y" * 600)

    def test_render_empty_final_parameter(self) -> None:
        self.assertEqual(render_irc_message("NOTICE", ("nick", "")), b"NOTICE nick :\r\n")

    def test_render_serializes_tags(self) -> None:
        self.assertEqual(
            render_irc_message("TAGMSG", ("#pond",), tags={"label": "one two;three"}),
            b"@label=one\\stwo\\:three TAGMSG #pond\r\n",
        )

    def test_render_rejects_output_injection(self) -> None:
        with self.assertRaises(IRCProtocolError):
            render_privmsg("#pond", "safe\r\nOPER intruder")

    def test_render_rejects_oversized_utf8_output(self) -> None:
        with self.assertRaises(IRCProtocolError):
            render_privmsg("#pond", "\N{DUCK}" * 125)

    def test_render_pong_preserves_ping_parameters(self) -> None:
        ping = parse_irc_line("PING one :two")
        self.assertEqual(render_pong(ping), b"PONG one two\r\n")

    def test_render_pong_rejects_another_command(self) -> None:
        with self.assertRaises(IRCProtocolError):
            render_pong(parse_irc_line("NOTICE nick :hello"))


if __name__ == "__main__":
    unittest.main()
