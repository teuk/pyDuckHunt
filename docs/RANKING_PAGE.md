# Public ranking page

Coin can generate one standalone HTML ranking from the same immutable
`GameState` used by replay and IRC `!duckrank`. The optional runtime setting
is:

```toml
ranking_page_path = "/absolute/private/spool/player-rankings.html"
```

This private spool path is independent from the player-facing HTTPS address.
The latter is configured under `[game]` and may therefore follow any
operator-controlled publication route:

```toml
ranking_url = "https://games.example/DuckHunt/rankings"
```

When present, `!duckrank` shows its colored top five and then this complete
page on a separate public line. When absent, the command remains link-free.

Non-playing operators may be excluded consistently from every statistical
projection without deleting their durable history:

```toml
statistics_excluded_nicknames = ["Te[u]K"]
```

The same RFC1459-aware list applies to `!duckstats`, `!duckrank`, partyline
`.summary`, this HTML page and aggregate Prometheus player totals.

When omitted or empty, no page is generated. The path must be absolute, end in
`.html` and point into an existing real directory. Startup publishes the
recovered state. Every later page follows a successfully appended replay event,
so a visible row never runs ahead of the durable journal. Page failures are
counted and logged as bounded `RANKING` lifecycle facts; they never latch game
persistence or interrupt IRC.

## Content contract

The HTML exporter is deterministic, script-free and capped at 4 MiB. It escapes
all nicknames, contains a restrictive content-security policy and uses the same
stable order as IRC: hits descending, best time ascending, then canonical IRC
identity. It exposes only durable game-profile facts. It does not publish
hostmasks, account data, raw IRC text, secrets or private logs.

The page shows the available XP balance rather than invented lifetime earnings.
The displayed accuracy is the calibrated weapon accuracy for the current level.
There is no per-player last-activity column because that fact is not part of the
durable model.

The final table column exposes the same current facts as IRC `!inventory` for
each ranked hunter: weapon state, ammunition, magazines, carried ducks, letter
collection, durable equipment, active effects and remaining bounds, shop credit,
channel bread and curses. The bag icon provides a native multiline hover hint;
hover or keyboard focus opens the styled card, while click or tap keeps the
script-free `<details>` panel open. Nicknames and every inventory fragment are
HTML-escaped, and statistically excluded operators receive no row or inventory.
This is part of the generated page itself and does not change the privileged
spool-to-web publication service.

The desktop grid deliberately groups the original 24 facts into eleven columns:
identity, hunting totals, best time, progression, weapon, condition, ammunition,
shot history, accident history and the final inventory cell. No statistic is
removed. The table uses the available width without a forced 2200-pixel canvas;
below 1180 pixels the same facts become two-column player cards, then one column
on narrow phones. Consequently the inventory control is reachable without a
hidden horizontal scrollbar at every supported width.

The generated document carries the same compact editorial visual system as the
static site: restrained status colors, flat surfaces, readable table typography
and a responsive card representation on narrow screens.

## Least-privilege publication

The bot should not own or write the Apache document root. The packaged pattern
separates generation from publication:

1. Coin atomically replaces a mode-`0644` spool file below its existing writable
   pilot directory.
2. `pyduckhunt-ranking-publish.path` watches the containing spool directory,
   so replacing the file with a new inode cannot detach the watch.
3. The root service waits one second before reading the source. Changes that
   arrive during that interval remain coalesced by the path unit, so a burst of
   durable game transitions publishes the newest complete page without
   exhausting systemd's service-start allowance. An explicit 45-start ceiling
   over 30 seconds remains as a regression guard; rate limiting is not disabled.
4. A root `oneshot` service opens both directories and the source through
   anchored, no-follow descriptors, then validates owner, mode, size, page
   markers and absence of executable markup.
5. The service copies only that file into the dedicated ranking route and
   atomically replaces `index.html` as `root:root`.

Source and destination are selected by the root-owned exact-schema file
`/etc/pyduckhunt/ranking-publish.toml`:

```toml
source_file = "/home/backupwws/pyduckhunt/pilot/public/player-rankings.html"
target_file = "/var/www/io.teuk.org/public/DuckHunt/rankings/index.html"
```

The publisher rejects a symbolic, non-root-owned, group/world-writable,
oversized or unknown-field configuration. The packaged service still grants
read and write access only to the reviewed source and destination directories;
changing either directory therefore requires a matching reviewed unit update.
The path unit also watches `/etc/pyduckhunt`, so an atomic configuration-file
replacement requests a fresh publication just like a spool replacement.

The publisher has no network access, no capabilities, a read-only home and
system tree, one read-only spool path and one exact writable web directory.
Coin therefore receives no Apache ownership, sudo rule or general vhost write
permission.

The source tree has a deliberate `0750 mediabot:mediabot` boundary. Because
the root oneshot drops every capability, it receives `SupplementaryGroups=mediabot`
solely to traverse that boundary. The helper still validates that the source
directory and generated file belong to `mediabot`, while the target directory
must belong to root. No permission or ACL on either live tree is relaxed.

## Operator checks

After a reviewed installation, verify both layers:

```bash
systemctl is-active pyduckhunt-ranking-publish.path
systemctl status pyduckhunt-ranking-publish.service --no-pager
/usr/local/libexec/pyduckhunt-publish-ranking \
  --config /etc/pyduckhunt/ranking-publish.toml --check
```

The source and published files must both contain
`PYDUCKHUNT_RANKING_PAGE_V1`, while the public target remains owned by root and
is not group/world writable.

If a deployment predating the debounce reached `start-limit-hit`, install the
reviewed unit first, run `systemctl daemon-reload`, reset the failed states of
both the service and path units, restart the path unit, and force one service
start. The final check must show the path unit `active`, the oneshot result
`success`, and byte-identical source and public pages. Resetting the failure
without installing the debounce only postpones the same outage.
