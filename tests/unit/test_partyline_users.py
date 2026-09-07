from __future__ import annotations

import json
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from pyduckhunt.partyline.users import (
    PartylineCredentialError,
    PartylineUserStore,
    _password_digest,
)


class PartylineUserStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "state" / "partyline-users.json"
        self.store = PartylineUserStore(self.path)

    def test_first_owner_is_private_hashed_atomic_and_verifiable(self) -> None:
        credential = "correct horse battery staple"
        user = self.store.create_first_owner(
            "Op[e]rator",
            credential,
            42,
            irc_account="Operator",
            irc_mask="Op[e]rator!user@example",
        )
        self.assertEqual(user.role, "owner")
        self.assertEqual(os.stat(self.path).st_mode & 0o777, 0o600)
        encoded = self.path.read_text(encoding="utf-8")
        self.assertNotIn(credential, encoded)
        self.assertIsNotNone(self.store.verify("op{e}rator", credential))
        self.assertIsNone(self.store.verify("Op[e]rator", "incorrect password"))
        self.assertEqual(self.store.users(), (user,))
        self.assertEqual(
            self.store.owner_for_irc(
                "op{e}rator",
                prefix="Op[e]rator!elsewhere@elsewhere",
                account="OPERATOR",
            ),
            user,
        )
        self.assertEqual(
            self.store.owner_for_irc(
                "Op[e]rator",
                prefix="Op[e]rator!user@example",
                account=None,
            ),
            user,
        )
        self.assertIsNone(
            self.store.owner_for_irc(
                "Op[e]rator",
                prefix="Op[e]rator!user@example",
                account="Other",
            )
        )
        self.assertIsNone(
            self.store.owner_for_irc(
                "Op[e]rator",
                prefix="Op[e]rator!intruder@example",
                account=None,
            )
        )

    def test_second_owner_and_short_password_are_rejected(self) -> None:
        with self.assertRaises(PartylineCredentialError):
            self.store.create_first_owner(
                "Owner",
                "short",
                1,
                irc_account=None,
                irc_mask="Owner!u@host",
            )
        self.store.create_first_owner(
            "Owner",
            "a sufficiently long password",
            2,
            irc_account=None,
            irc_mask="Owner!u@host",
        )
        with self.assertRaises(PartylineCredentialError):
            self.store.create_first_owner(
                "Other",
                "another sufficiently long password",
                3,
                irc_account=None,
                irc_mask="Other!u@host",
            )

    def test_legacy_password_can_authenticate_once_then_be_rotated(self) -> None:
        current = self.store.create_first_owner(
            "Owner",
            "a sufficiently long password",
            2,
            irc_account="Owner",
            irc_mask="Owner!u@host",
        )
        legacy_password = "legacy-pass"
        legacy = replace(
            current,
            password_digest=_password_digest(legacy_password, current.salt),
        )
        self.store._write((legacy,))

        self.assertIsNotNone(self.store.verify("owner", legacy_password))
        rotated = self.store.change_password("OWNER", "new strong owner password")
        self.assertEqual(rotated.created_at_ns, legacy.created_at_ns)
        self.assertEqual(rotated.irc_account, legacy.irc_account)
        self.assertNotEqual(rotated.salt, legacy.salt)
        self.assertIsNone(self.store.verify("Owner", legacy_password))
        self.assertIsNotNone(
            self.store.verify("Owner", "new strong owner password")
        )

        with self.assertRaises(PartylineCredentialError):
            self.store.change_password("Owner", "too short")

    def test_symlink_public_mode_and_schema_tampering_are_rejected(self) -> None:
        target = self.path.parent / "target.json"
        target.parent.mkdir()
        target.write_text('{"users":[],"version":1}\n', encoding="utf-8")
        target.chmod(0o600)
        self.path.symlink_to(target)
        with self.assertRaises(PartylineCredentialError):
            self.store.users()
        self.path.unlink()
        self.path.write_text('{"users":[],"version":1}\n', encoding="utf-8")
        self.path.chmod(0o644)
        with self.assertRaises(PartylineCredentialError):
            self.store.users()
        self.path.chmod(0o600)
        self.path.write_text(json.dumps({"version": 2, "users": []}), encoding="utf-8")
        with self.assertRaises(PartylineCredentialError):
            self.store.users()


if __name__ == "__main__":
    unittest.main()
