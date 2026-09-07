# systemd packaging

`pyduckhunt@.service` is a reviewed service candidate for the explicitly
approved existing `mediabot` account. It preserves the guarded foreground
composition, adds bounded service-signal handling and requires a root-owned
per-instance authorization file outside the Git worktree.

The example authorization is disarmed. Repository validation never copies the
unit to systemd, runs `daemon-reload`, starts a process, enables an instance or
opens a network connection. See `docs/SYSTEMD_SERVICE.md` for the separate
reviewed rollout boundary.

The directory also contains an optional least-privilege ranking publisher: a
directory-watching path unit, a hardened root `oneshot` unit, an exact-schema
configuration example and a validation/copy helper. Coin writes only its
private spool file; the helper reads root-owned source/destination settings and
atomically installs one checked HTML page as `root:root`. These candidates
remain inert until a reviewed rollout installs and enables them. See
`docs/RANKING_PAGE.md`.

The publisher keeps an empty capability set. Its sole supplementary group is
`mediabot`, required to traverse the existing mode-`0750` spool boundary;
neither the spool nor the web tree needs a permission change.
The oneshot deliberately waits one second before copying, allowing the path
unit to coalesce bursts of atomic source replacements. A separate
45-start/30-second systemd ceiling remains enabled as a regression guard.

`pyduckhunt-metrics.service` is an independent, unprivileged loopback listener.
It reads one aggregate `.prom` snapshot and has no writable path. The Grafana
provisioning files live under `packaging/grafana`; they remain inert until a
reviewed rollout validates the local Prometheus configuration with the matching
`promtool`, preserves its filesystem identity and installs them. See
`docs/METRICS_GRAFANA.md`.
