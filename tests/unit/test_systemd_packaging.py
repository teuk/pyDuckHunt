from __future__ import annotations

import json
import os
import runpy
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
UNIT_PATH = ROOT / "packaging" / "systemd" / "pyduckhunt@.service"
ENVIRONMENT_PATH = ROOT / "packaging" / "systemd" / "pyduckhunt.env.example"
DOCUMENTATION_PATH = ROOT / "docs" / "SYSTEMD_SERVICE.md"
RANKING_PATH_UNIT = ROOT / "packaging" / "systemd" / "pyduckhunt-ranking-publish.path"
RANKING_SERVICE_UNIT = ROOT / "packaging" / "systemd" / "pyduckhunt-ranking-publish.service"
RANKING_PUBLISHER = ROOT / "packaging" / "systemd" / "pyduckhunt-publish-ranking"
RANKING_CONFIGURATION = (
    ROOT / "packaging" / "systemd" / "pyduckhunt-ranking-publish.toml.example"
)
METRICS_UNIT = ROOT / "packaging" / "systemd" / "pyduckhunt-metrics.service"
GRAFANA_PROVIDER = ROOT / "packaging" / "grafana" / "pyduckhunt-dashboard.yaml"
GRAFANA_DASHBOARD = ROOT / "packaging" / "grafana" / "pyduckhunt-coin.json"
PROMETHEUS_HELPER = ROOT / "packaging" / "prometheus" / "pyduckhunt-prometheus-config"


class SystemdPackagingTests(unittest.TestCase):
    def test_candidate_files_exist_and_the_authorization_is_disarmed(self) -> None:
        self.assertTrue(UNIT_PATH.is_file())
        self.assertTrue(ENVIRONMENT_PATH.is_file())
        self.assertTrue(DOCUMENTATION_PATH.is_file())
        environment = ENVIRONMENT_PATH.read_text(encoding="utf-8")
        self.assertIn("irc.example.invalid", environment)
        self.assertIn('PYDUCKHUNT_CONFIRM_LIVE="DISARMED"', environment)
        self.assertNotIn("--allow-plain", environment)

    def test_unit_requires_preflight_exact_confirmation_and_service_mode(self) -> None:
        unit = UNIT_PATH.read_text(encoding="utf-8")
        self.assertIn("ExecStartPre=", unit)
        self.assertIn(" pilot-check $PYDUCKHUNT_TARGET_ARGS", unit)
        self.assertIn(" service-run $PYDUCKHUNT_TARGET_ARGS", unit)
        self.assertIn("--confirm-live ${PYDUCKHUNT_CONFIRM_LIVE}", unit)
        self.assertIn("EnvironmentFile=/etc/pyduckhunt/%i.env", unit)
        self.assertIn("EnvironmentFile=-/etc/pyduckhunt/%i.secret.env", unit)
        self.assertIn("ConditionPathExists=/etc/pyduckhunt/%i.env", unit)
        self.assertIn(
            "ConditionPathIsSymbolicLink=!/etc/pyduckhunt/%i.env",
            unit,
        )
        self.assertNotIn("ConditionPathIsRegular", unit)
        self.assertNotIn("/bin/sh", unit)
        self.assertNotIn("/bin/bash", unit)
        self.assertEqual(unit.count("Environment=PYTHONUNBUFFERED=1"), 1)

    def test_unit_runs_unprivileged_and_stops_through_sigterm(self) -> None:
        unit = UNIT_PATH.read_text(encoding="utf-8")
        self.assertIn("User=mediabot", unit)
        self.assertIn("Group=mediabot", unit)
        self.assertIn("KillSignal=SIGTERM", unit)
        self.assertIn("TimeoutStopSec=15s", unit)
        self.assertIn("Restart=on-failure", unit)
        self.assertNotIn("User=root", unit)

    def test_unit_limits_privilege_network_and_writable_paths(self) -> None:
        unit = UNIT_PATH.read_text(encoding="utf-8")
        for directive in (
            "NoNewPrivileges=true",
            "ProtectHome=read-only",
            "ProtectSystem=strict",
            "ProtectProc=invisible",
            "ProcSubset=pid",
            "RemoveIPC=true",
            "PrivateDevices=true",
            "PrivateTmp=true",
            "RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6",
            "CapabilityBoundingSet=",
            "AmbientCapabilities=",
            "SystemCallArchitectures=native",
        ):
            self.assertIn(directive, unit)
        writable = [
            line
            for line in unit.splitlines()
            if line.startswith("ReadWritePaths=")
        ]
        self.assertEqual(
            writable,
            [
                "ReadWritePaths=/home/mediabot/pyduckhunt-pilot/state",
                "ReadWritePaths=/home/backupwws/pyduckhunt/pilot",
            ],
        )

    def test_ranking_publisher_is_narrow_hardened_and_root_owned_only(self) -> None:
        path_unit = RANKING_PATH_UNIT.read_text(encoding="utf-8")
        service = RANKING_SERVICE_UNIT.read_text(encoding="utf-8")
        publisher = RANKING_PUBLISHER.read_text(encoding="utf-8")
        configuration = RANKING_CONFIGURATION.read_text(encoding="utf-8")
        self.assertIn(
            "PathChanged=/home/backupwws/pyduckhunt/pilot/public",
            path_unit,
        )
        self.assertNotIn(
            "PathChanged=/home/backupwws/pyduckhunt/pilot/public/player-rankings.html",
            path_unit,
        )
        self.assertIn(
            "PathChanged=/etc/pyduckhunt",
            path_unit,
        )
        self.assertNotIn(
            "PathChanged=/etc/pyduckhunt/ranking-publish.toml",
            path_unit,
        )
        self.assertIn("Type=oneshot", service)
        self.assertIn("StartLimitIntervalSec=30", service)
        self.assertIn("StartLimitBurst=45", service)
        self.assertIn("ExecStartPre=/usr/bin/sleep 1", service)
        self.assertNotIn("StartLimitIntervalSec=0", service)
        self.assertLess(
            service.index("ExecStartPre=/usr/bin/sleep 1"),
            service.index("ExecStart=/usr/local/libexec/pyduckhunt-publish-ranking"),
        )
        self.assertIn(
            "--config /etc/pyduckhunt/ranking-publish.toml",
            service,
        )
        self.assertIn("ProtectSystem=strict", service)
        self.assertIn("ProtectHome=read-only", service)
        self.assertIn("RestrictAddressFamilies=AF_UNIX", service)
        self.assertIn("CapabilityBoundingSet=", service)
        self.assertIn("SupplementaryGroups=mediabot", service)
        self.assertIn(
            "ReadOnlyPaths=/etc/pyduckhunt/ranking-publish.toml",
            service,
        )
        self.assertIn("ReadOnlyPaths=/home/backupwws/pyduckhunt/pilot/public", service)
        self.assertIn("ReadWritePaths=/var/www/io.teuk.org/public/DuckHunt/rankings", service)
        self.assertNotIn("User=mediabot", service)
        self.assertIn(
            'source_file = "/home/backupwws/pyduckhunt/pilot/public/player-rankings.html"',
            configuration,
        )
        self.assertIn(
            'target_file = "/var/www/io.teuk.org/public/DuckHunt/rankings/index.html"',
            configuration,
        )
        self.assertNotIn("/home/backupwws/pyduckhunt/pilot/public", publisher)
        self.assertNotIn("/var/www/io.teuk.org/public/DuckHunt/rankings", publisher)
        self.assertIn("tomllib.loads", publisher)
        self.assertIn("publisher configuration ownership or mode is unsafe", publisher)
        self.assertIn("O_NOFOLLOW", publisher)
        self.assertIn("dir_fd=directory_descriptor", publisher)
        self.assertIn("os.fchown(descriptor, expected_uid, expected_gid)", publisher)
        self.assertIn("os.replace(", publisher)
        self.assertNotIn("curl", publisher)

    def test_ranking_publisher_reads_config_and_replaces_only_its_target(self) -> None:
        publisher = runpy.run_path(str(RANKING_PUBLISHER))
        load_configuration = publisher["load_configuration"]
        open_directory = publisher["open_directory"]
        read_source = publisher["read_source"]
        validate = publisher["validate"]
        publish = publisher["publish"]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_directory = root / "spool"
            target_directory = root / "public"
            source_directory.mkdir(mode=0o750)
            target_directory.mkdir(mode=0o750)
            source = source_directory / "ranking.html"
            target = target_directory / "index.html"
            payload = (
                b"<!-- PYDUCKHUNT_RANKING_PAGE_V1 -->"
                b'<meta name="generator" content="Coin / pyDuckHunt">'
            )
            source.write_bytes(payload)
            source.chmod(0o644)
            configuration = root / "publisher.toml"
            configuration.write_text(
                f'source_file = "{source}"\n'
                f'target_file = "{target}"\n',
                encoding="utf-8",
            )
            configuration.chmod(0o644)

            configured = load_configuration(
                str(configuration),
                expected_uid=os.getuid(),
            )
            source_descriptor = open_directory(
                configured.source_directory,
                expected_uid=os.getuid(),
            )
            try:
                rendered = read_source(
                    source_descriptor,
                    configured.source_name,
                    os.getuid(),
                )
            finally:
                os.close(source_descriptor)
            validate(rendered)
            target_descriptor = open_directory(
                configured.target_directory,
                expected_uid=os.getuid(),
            )
            try:
                publish(
                    target_descriptor,
                    configured.target_name,
                    rendered,
                    expected_uid=os.getuid(),
                    expected_gid=os.getgid(),
                )
            finally:
                os.close(target_descriptor)
            self.assertEqual(target.read_bytes(), payload)
            self.assertEqual(target.stat().st_mode & 0o777, 0o644)

    def test_metrics_listener_is_loopback_only_unprivileged_and_read_only(self) -> None:
        unit = METRICS_UNIT.read_text(encoding="utf-8")
        self.assertIn("User=mediabot", unit)
        self.assertIn("--listen 127.0.0.1 --port 9817", unit)
        self.assertIn("IPAddressDeny=any", unit)
        self.assertIn("IPAddressAllow=localhost", unit)
        self.assertIn("ProtectSystem=strict", unit)
        self.assertIn("ProtectHome=read-only", unit)
        self.assertIn("ReadOnlyPaths=/home/backupwws/pyduckhunt/pilot/metrics", unit)
        self.assertIn("CapabilityBoundingSet=", unit)
        self.assertNotIn("ReadWritePaths=", unit)
        self.assertNotIn("User=root", unit)

    def test_grafana_dashboard_is_provisioned_without_player_dimensions(self) -> None:
        provider = GRAFANA_PROVIDER.read_text(encoding="utf-8")
        dashboard = json.loads(GRAFANA_DASHBOARD.read_text(encoding="utf-8"))
        rendered = GRAFANA_DASHBOARD.read_text(encoding="utf-8")
        self.assertIn("/var/lib/grafana/dashboards/pyduckhunt", provider)
        self.assertEqual(dashboard["uid"], "pyduckhunt-coin")
        self.assertEqual(dashboard["refresh"], "15s")
        self.assertEqual(dashboard["timezone"], "utc")
        self.assertGreaterEqual(len(dashboard["panels"]), 12)
        self.assertIn("$DS_PROMETHEUS", rendered)
        self.assertNotIn("nickname", rendered.casefold())
        self.assertNotIn("player_key", rendered.casefold())

    def test_prometheus_helper_is_atomic_and_loopback_specific(self) -> None:
        helper = PROMETHEUS_HELPER.read_text(encoding="utf-8")
        self.assertIn("127.0.0.1:9817", helper)
        self.assertIn("scrape_timeout: 5s", helper)
        self.assertIn("os.replace", helper)
        self.assertIn("os.fsync", helper)
        self.assertNotIn("0.0.0.0", helper)


if __name__ == "__main__":
    unittest.main()
