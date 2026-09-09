from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pyduckhunt.configuration import (
    load_application_configuration,
    parse_application_configuration,
    resolve_irc_server_password,
)
from pyduckhunt.irc import IRCTransport
from pyduckhunt.identity import rfc1459_casefold


def configuration_payload() -> dict[str, object]:
    return {
        "irc": {
            "host": "irc.dev.invalid",
            "port": 6697,
            "tls": True,
            "nickname": "pyDuckHunt",
            "fallback_nickname": "pyDuckHunt_",
            "channels": ["#development"],
            "password_environment": "PYDUCKHUNT_IRC_PASSWORD",
        },
        "runtime": {
            "log_level": "INFO",
            "state_directory": "state",
            "log_directory": "logs",
        },
        "game": {
            "enabled": False,
            "flights_per_day": 24,
            "golden_weight_per_eighteen": 1,
            "flight_lifetime_seconds": 300,
            "unusual_loot_chance_per_thousand": 0,
            "shop_url": "",
            "ranking_url": "",
        },
    }


class ConfigurationTests(unittest.TestCase):
    def test_sample_configuration_loads_into_exact_adapters(self) -> None:
        configuration = load_application_configuration(
            Path("config/pyduckhunt.example.toml")
        )
        self.assertEqual(configuration.irc.endpoint().host, "irc.dev.invalid")
        self.assertEqual(configuration.irc.endpoint().port, 6697)
        self.assertTrue(configuration.irc.endpoint().tls)
        self.assertFalse(configuration.irc.bot_mode)
        self.assertEqual(configuration.runtime.state_directory, Path("state"))
        self.assertIsNone(configuration.runtime.ranking_page_path)
        self.assertIsNone(configuration.runtime.metrics_page_path)
        self.assertFalse(configuration.game.enabled)
        self.assertFalse(configuration.game.anti_cheat)
        self.assertIsNone(configuration.game.shop_url)
        self.assertIsNone(configuration.game.ranking_url)
        self.assertEqual(configuration.game.statistics_excluded_nicknames, ())
        self.assertFalse(configuration.partyline.enabled)
        self.assertEqual(configuration.partyline.bind_host, "127.0.0.1")
        self.assertEqual(configuration.partyline.port, 0)
        self.assertFalse(configuration.partyline.spontaneous_launch_enabled)
        self.assertIsNone(configuration.partyline.spontaneous_launch_channel)
        self.assertEqual(configuration.partyline.spontaneous_launch_min_seconds, 0)
        self.assertEqual(configuration.partyline.spontaneous_launch_max_seconds, 0)
        self.assertEqual(
            configuration.partyline.spontaneous_launch_announcement,
            "allez, je lance un canard",
        )

    def test_partyline_is_optional_strict_and_safely_configurable(self) -> None:
        payload = configuration_payload()
        self.assertFalse(parse_application_configuration(payload).partyline.enabled)
        payload["partyline"] = {
            "enabled": True,
            "bind_host": "127.0.0.1",
            "port": 3333,
            "bootstrap_accounts": ["Operator"],
            "bootstrap_masks": ["Op[e]rator!*@trusted.example"],
            "dcc_public_ip": "203.0.113.10",
            "dcc_port_min": 50000,
            "dcc_port_max": 50010,
        }
        configuration = parse_application_configuration(payload)
        self.assertTrue(configuration.partyline.enabled)
        self.assertEqual(configuration.partyline.port, 3333)
        self.assertEqual(configuration.partyline.bootstrap_accounts, ("Operator",))
        self.assertEqual(configuration.partyline.dcc_port_max, 50010)

        invalid_values = (
            {"bind_host": "localhost"},
            {"port": 65_536},
            {"bootstrap_accounts": [], "bootstrap_masks": []},
            {"dcc_public_ip": "127.0.0.1"},
            {"dcc_port_min": 50010, "dcc_port_max": 50000},
            {"dcc_port_min": 80, "dcc_port_max": 80},
        )
        for changes in invalid_values:
            invalid = configuration_payload()
            invalid["partyline"] = {**payload["partyline"], **changes}
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                parse_application_configuration(invalid)

    def test_spontaneous_launches_are_optional_bounded_and_channel_scoped(self) -> None:
        payload = configuration_payload()
        payload["partyline"] = {
            "enabled": True,
            "bind_host": "127.0.0.1",
            "port": 3333,
            "bootstrap_accounts": ["Operator"],
            "bootstrap_masks": [],
            "dcc_public_ip": "",
            "dcc_port_min": 0,
            "dcc_port_max": 0,
            "spontaneous_launch_enabled": True,
            "spontaneous_launch_channel": "#development",
            "spontaneous_launch_min_seconds": 10_800,
            "spontaneous_launch_max_seconds": 21_600,
            "spontaneous_launch_announcement": "allez, je lance un canard",
        }
        configured = parse_application_configuration(payload).partyline
        self.assertTrue(configured.spontaneous_launch_enabled)
        self.assertEqual(configured.spontaneous_launch_channel, "#development")
        self.assertEqual(configured.spontaneous_launch_min_seconds, 10_800)
        self.assertEqual(configured.spontaneous_launch_max_seconds, 21_600)

        invalid_changes = (
            {"spontaneous_launch_enabled": 1},
            {"spontaneous_launch_channel": "#elsewhere"},
            {"spontaneous_launch_channel": "development"},
            {"spontaneous_launch_min_seconds": 899},
            {"spontaneous_launch_max_seconds": 86_401},
            {
                "spontaneous_launch_min_seconds": 20_000,
                "spontaneous_launch_max_seconds": 10_000,
            },
            {"spontaneous_launch_announcement": "bad\nmessage"},
        )
        for changes in invalid_changes:
            invalid = configuration_payload()
            invalid["partyline"] = {**payload["partyline"], **changes}
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                parse_application_configuration(invalid)

        disabled = configuration_payload()
        disabled["partyline"] = {
            **payload["partyline"],
            "enabled": False,
            "spontaneous_launch_enabled": False,
            "spontaneous_launch_channel": "",
            "spontaneous_launch_min_seconds": 0,
            "spontaneous_launch_max_seconds": 0,
        }
        self.assertFalse(
            parse_application_configuration(disabled).partyline.spontaneous_launch_enabled
        )

    def test_unknown_or_missing_fields_are_rejected(self) -> None:
        payload = configuration_payload()
        payload["unexpected"] = {}
        with self.assertRaises(ValueError):
            parse_application_configuration(payload)

        payload = configuration_payload()
        del payload["irc"]["host"]  # type: ignore[index]
        with self.assertRaises(ValueError):
            parse_application_configuration(payload)

        payload = configuration_payload()
        payload["runtime"]["unexpected"] = True  # type: ignore[index]
        with self.assertRaises(ValueError):
            parse_application_configuration(payload)

        payload = configuration_payload()
        payload["game"]["unexpected"] = True  # type: ignore[index]
        with self.assertRaises(ValueError):
            parse_application_configuration(payload)

    def test_statistics_exclusions_are_optional_canonical_and_unique(self) -> None:
        payload = configuration_payload()
        payload["game"]["statistics_excluded_nicknames"] = ["Te[u]K"]  # type: ignore[index]
        configuration = parse_application_configuration(payload)
        self.assertEqual(
            configuration.game.statistics_excluded_nicknames,
            (rfc1459_casefold("Te[u]K"),),
        )
        for excluded in (["Te[u]K", "te{u}k"], ["bad nick"], "Te[u]K"):
            invalid = configuration_payload()
            invalid["game"]["statistics_excluded_nicknames"] = excluded  # type: ignore[index]
            with self.subTest(excluded=excluded), self.assertRaises(ValueError):
                parse_application_configuration(invalid)

    def test_shop_url_is_optional_disabled_by_default_and_https_only(self) -> None:
        payload = configuration_payload()
        del payload["game"]["shop_url"]  # type: ignore[index]
        self.assertIsNone(parse_application_configuration(payload).game.shop_url)

        payload = configuration_payload()
        payload["game"]["shop_url"] = (  # type: ignore[index]
            "https://games.example/duckhunt/shop/"
        )
        self.assertEqual(
            parse_application_configuration(payload).game.shop_url,
            "https://games.example/duckhunt/shop/",
        )

        for value in (
            "http://games.example/shop/",
            "https://user:secret@games.example/shop/",
            "https://games.example/shop/#fragment",
            " https://games.example/shop/",
            "https://games.example\\shop/",
            True,
        ):
            payload = configuration_payload()
            payload["game"]["shop_url"] = value  # type: ignore[index]
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_application_configuration(payload)

    def test_ranking_url_is_optional_disabled_by_default_and_https_only(self) -> None:
        payload = configuration_payload()
        del payload["game"]["ranking_url"]  # type: ignore[index]
        self.assertIsNone(parse_application_configuration(payload).game.ranking_url)

        payload = configuration_payload()
        payload["game"]["ranking_url"] = (  # type: ignore[index]
            "https://io.teuk.org/DuckHunt/rankings"
        )
        self.assertEqual(
            parse_application_configuration(payload).game.ranking_url,
            "https://io.teuk.org/DuckHunt/rankings",
        )

        for value in (
            "http://io.teuk.org/DuckHunt/rankings",
            "https://user:secret@io.teuk.org/DuckHunt/rankings",
            "https://io.teuk.org/DuckHunt/rankings#fragment",
            " https://io.teuk.org/DuckHunt/rankings",
            "https://io.teuk.org\\DuckHunt\\rankings",
            True,
        ):
            payload = configuration_payload()
            payload["game"]["ranking_url"] = value  # type: ignore[index]
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_application_configuration(payload)

    def test_numeric_and_truth_contracts_reject_cross_typed_values(self) -> None:
        payload = configuration_payload()
        payload["irc"]["port"] = True  # type: ignore[index]
        with self.assertRaises(ValueError):
            parse_application_configuration(payload)

        payload = configuration_payload()
        payload["irc"]["tls"] = 1  # type: ignore[index]
        with self.assertRaises(ValueError):
            parse_application_configuration(payload)

        payload = configuration_payload()
        payload["irc"]["bot_mode"] = 1  # type: ignore[index]
        with self.assertRaises(ValueError):
            parse_application_configuration(payload)

        payload = configuration_payload()
        payload["game"]["anti_cheat"] = 1  # type: ignore[index]
        with self.assertRaises(ValueError):
            parse_application_configuration(payload)

        payload = configuration_payload()
        payload["game"]["enabled"] = 0  # type: ignore[index]
        with self.assertRaises(ValueError):
            parse_application_configuration(payload)

    def test_bot_mode_is_optional_and_reaches_transport_policy(self) -> None:
        payload = configuration_payload()
        configuration = parse_application_configuration(payload)
        self.assertFalse(configuration.irc.bot_mode)
        self.assertFalse(configuration.irc.transport_policy().bot_mode)

        payload["irc"]["bot_mode"] = True  # type: ignore[index]
        configuration = parse_application_configuration(payload)
        self.assertTrue(configuration.irc.bot_mode)
        self.assertTrue(configuration.irc.transport_policy().bot_mode)

    def test_anti_cheat_is_optional_strict_and_operator_controlled(self) -> None:
        payload = configuration_payload()
        configuration = parse_application_configuration(payload)
        self.assertFalse(configuration.game.anti_cheat)

        payload["game"]["anti_cheat"] = True  # type: ignore[index]
        self.assertTrue(parse_application_configuration(payload).game.anti_cheat)

    def test_channel_array_is_nonempty_unique_and_irc_safe(self) -> None:
        for channels in ([], "#pond", ["#Pond", "#pond"], ["pond"]):
            payload = configuration_payload()
            payload["irc"]["channels"] = channels  # type: ignore[index]
            with self.subTest(channels=channels), self.assertRaises(ValueError):
                parse_application_configuration(payload)

    def test_password_environment_name_is_strict(self) -> None:
        for name in ("", "lowercase", "1_PASSWORD", "BAD-NAME", True):
            payload = configuration_payload()
            payload["irc"]["password_environment"] = name  # type: ignore[index]
            with self.subTest(name=name), self.assertRaises(ValueError):
                parse_application_configuration(payload)

    def test_runtime_paths_reject_root_traversal_and_surrounding_space(self) -> None:
        for path in ("/", "../state", "state/../other", " logs"):
            payload = configuration_payload()
            payload["runtime"]["log_directory"] = path  # type: ignore[index]
            with self.subTest(path=path), self.assertRaises(ValueError):
                parse_application_configuration(payload)

    def test_ranking_page_path_is_optional_absolute_and_html_only(self) -> None:
        payload = configuration_payload()
        self.assertIsNone(
            parse_application_configuration(payload).runtime.ranking_page_path
        )
        payload["runtime"]["ranking_page_path"] = (  # type: ignore[index]
            "/var/lib/pyduckhunt/public/player-rankings.html"
        )
        self.assertEqual(
            parse_application_configuration(payload).runtime.ranking_page_path,
            Path("/var/lib/pyduckhunt/public/player-rankings.html"),
        )
        for path in ("rankings.html", "/tmp/rankings.txt", "../rankings.html", True):
            payload = configuration_payload()
            payload["runtime"]["ranking_page_path"] = path  # type: ignore[index]
            with self.subTest(path=path), self.assertRaises(ValueError):
                parse_application_configuration(payload)

    def test_metrics_page_path_is_optional_absolute_and_prometheus_only(self) -> None:
        payload = configuration_payload()
        self.assertIsNone(
            parse_application_configuration(payload).runtime.metrics_page_path
        )
        payload["runtime"]["metrics_page_path"] = (  # type: ignore[index]
            "/var/lib/pyduckhunt/metrics/pyduckhunt.prom"
        )
        self.assertEqual(
            parse_application_configuration(payload).runtime.metrics_page_path,
            Path("/var/lib/pyduckhunt/metrics/pyduckhunt.prom"),
        )
        for path in ("metrics.prom", "/tmp/metrics.txt", "../metrics.prom", True):
            payload = configuration_payload()
            payload["runtime"]["metrics_page_path"] = path  # type: ignore[index]
            with self.subTest(path=path), self.assertRaises(ValueError):
                parse_application_configuration(payload)

    def test_runtime_log_level_is_normalized_from_supported_values(self) -> None:
        payload = configuration_payload()
        payload["runtime"]["log_level"] = "warning"  # type: ignore[index]
        configuration = parse_application_configuration(payload)
        self.assertEqual(configuration.runtime.log_level, "WARNING")

        payload["runtime"]["log_level"] = "TRACE"  # type: ignore[index]
        with self.assertRaises(ValueError):
            parse_application_configuration(payload)

    def test_calibrated_game_boundary_cannot_be_overridden(self) -> None:
        cases = (
            ("flights_per_day", 17),
            ("golden_weight_per_eighteen", 2),
            ("flight_lifetime_seconds", 299),
            ("unusual_loot_chance_per_thousand", 1),
        )
        for field, value in cases:
            payload = configuration_payload()
            payload["game"][field] = value  # type: ignore[index]
            with self.subTest(field=field), self.assertRaises(ValueError):
                parse_application_configuration(payload)

    def test_password_resolution_is_explicit_optional_and_redacted(self) -> None:
        configuration = parse_application_configuration(configuration_payload())
        self.assertIsNone(resolve_irc_server_password(configuration.irc, {}))
        credential = "synthetic password"
        resolved = resolve_irc_server_password(
            configuration.irc,
            {"PYDUCKHUNT_IRC_PASSWORD": credential},
        )
        self.assertEqual(resolved, credential)
        policy = configuration.irc.transport_policy(server_password=resolved)
        self.assertNotIn(credential, repr(policy))
        self.assertNotEqual(policy, configuration.irc.transport_policy())

        transport = IRCTransport(policy)
        transport.start(0)
        registration = transport.connected(0)
        self.assertEqual(registration.actions[0].wire, b"PASS :synthetic password\r\n")
        self.assertEqual(
            registration.actions[2].wire,
            b"USER pyduckhunt 0 * pyDuckHunt\r\n",
        )

    def test_password_resolution_rejects_invalid_values_and_mapping(self) -> None:
        configuration = parse_application_configuration(configuration_payload())
        with self.assertRaises(ValueError):
            resolve_irc_server_password(configuration.irc, [])  # type: ignore[arg-type]
        for value in ("", "bad\nsecret", True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                resolve_irc_server_password(
                    configuration.irc,
                    {"PYDUCKHUNT_IRC_PASSWORD": value},  # type: ignore[dict-item]
                )

    def test_missing_malformed_and_non_utf8_files_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(ValueError):
                load_application_configuration(root / "missing.toml")
            malformed = root / "malformed.toml"
            malformed.write_text("[irc\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_application_configuration(malformed)
            invalid = root / "invalid.toml"
            invalid.write_bytes(b"\xff")
            with self.assertRaises(ValueError):
                load_application_configuration(invalid)


if __name__ == "__main__":
    unittest.main()
