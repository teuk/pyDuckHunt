from __future__ import annotations

import unittest

from pyduckhunt.irc import IRCLineBuffer, IRCProtocolError


class IRCLineBufferTests(unittest.TestCase):
    def test_fragmented_line_is_reassembled_exactly(self) -> None:
        framer = IRCLineBuffer()
        self.assertEqual(framer.feed(b"PING :ser"), ())
        self.assertEqual(framer.pending_bytes, 9)
        self.assertEqual(framer.feed(b"ver\r"), ())
        self.assertEqual(framer.feed(b"\n"), (b"PING :server\r\n",))
        self.assertEqual(framer.pending_bytes, 0)

    def test_multiple_lines_and_tail_are_preserved(self) -> None:
        framer = IRCLineBuffer()
        self.assertEqual(
            framer.feed(b"PING :one\r\nPING :two\r\nNOTICE"),
            (b"PING :one\r\n", b"PING :two\r\n"),
        )
        self.assertEqual(framer.pending_bytes, 6)
        self.assertEqual(framer.feed(b" x :ok\r\n"), (b"NOTICE x :ok\r\n",))

    def test_exact_wire_limit_can_arrive_in_two_chunks(self) -> None:
        framer = IRCLineBuffer()
        prefix = b"NOTICE x :" + (b"a" * 500)
        self.assertEqual(len(prefix), 510)
        self.assertEqual(framer.feed(prefix + b"\r"), ())
        self.assertEqual(framer.feed(b"\n"), (prefix + b"\r\n",))

    def test_oversized_complete_line_is_rejected_atomically(self) -> None:
        framer = IRCLineBuffer()
        framer.feed(b"PING")
        with self.assertRaises(IRCProtocolError):
            framer.feed(b"x" * 507 + b"\r\n")
        self.assertEqual(framer.pending_bytes, 4)

    def test_oversized_unterminated_line_is_rejected(self) -> None:
        framer = IRCLineBuffer()
        with self.assertRaises(IRCProtocolError):
            framer.feed(b"x" * 511)

    def test_bare_line_feed_and_embedded_carriage_return_are_rejected(self) -> None:
        with self.assertRaises(IRCProtocolError):
            IRCLineBuffer().feed(b"PING :x\n")
        with self.assertRaises(IRCProtocolError):
            IRCLineBuffer().feed(b"PING\r :x")

    def test_empty_wire_line_is_rejected(self) -> None:
        with self.assertRaises(IRCProtocolError):
            IRCLineBuffer().feed(b"\r\n")

    def test_reset_drops_only_the_pending_fragment(self) -> None:
        framer = IRCLineBuffer()
        framer.feed(b"PING :old")
        framer.reset()
        self.assertEqual(framer.pending_bytes, 0)
        self.assertEqual(framer.feed(b"PING :new\r\n"), (b"PING :new\r\n",))

    def test_chunk_contract_rejects_mutable_and_text_values(self) -> None:
        framer = IRCLineBuffer()
        with self.assertRaises(ValueError):
            framer.feed(bytearray(b"PING"))
        with self.assertRaises(ValueError):
            framer.feed("PING")


if __name__ == "__main__":
    unittest.main()
