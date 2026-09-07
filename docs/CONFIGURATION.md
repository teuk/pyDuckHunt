# Configuration boundary

pyDuckHunt loads one exact TOML schema through
`load_application_configuration`. Unknown, missing required or cross-typed
fields are rejected before a socket or runtime directory can be created.

## Sections

The supported document requires exactly `irc`, `runtime` and `game` sections
and accepts one optional exact `partyline` section.
The disarmed example in `config/pyduckhunt.example.toml` is the canonical
shape.

IRC configuration validates the hostname, port, TLS truth value, primary and
fallback nicknames, unique RFC1459 channels, the optional `bot_mode` truth
value and the name of the environment variable that may contain a server
password. `bot_mode` defaults to false; when enabled, the transport requests
user mode `+B` after the welcome and before joining channels. Runtime
configuration validates a supported log level, safe state and log paths, and an
optional absolute `ranking_page_path` ending in `.html` and an optional absolute
`metrics_page_path` ending in `.prom`. When configured, Coin
generates a standalone ranking from recovered and newly durable state; omission
keeps public export disabled. See `RANKING_PAGE.md` for the publication boundary.
The metrics path receives only aggregate, bounded-cardinality observations; its
omission disables Prometheus export. See `METRICS_GRAFANA.md`.
Game configuration keeps the
adaptive 24/21/18-flight schedule, one-in-eighteen golden weight, five-minute
flight lifetime and disabled unusual-loot boundary exact. Its optional
`shop_url` is either empty or omitted, which keeps `!shop` link-free, or one
bounded credential-free HTTPS URL selected by the operator. The optional
`ranking_url` follows the same strict HTTPS boundary. Empty or omitted keeps
`!duckrank` link-free; when configured, it points players to the separately
published complete ranking without coupling IRC rendering to its deployment
hostname. The optional
`anti_cheat` truth value defaults to false. A live operator may enable it to
draw independently randomized flight trails, silhouettes and utterances from
the same operating-system-backed bounded integer source used by runtime
settlement.

Partyline configuration is disabled when omitted. When enabled, it validates
an IPv4 or IPv6 bind address, TCP port, first-owner account/mask allowlists,
optional public DCC IPv4 address and either zero/zero or one ordered DCC range
of at most 101 unprivileged ports. The beta binds the permanent listener to
loopback. Five optional fields can independently enable standard spontaneous
flights on one configured IRC channel, bound the randomized delay to 15 minutes
through 24 hours and select the public announcement. Their omission preserves
the disabled behavior of existing configurations. See `PARTYLINE.md` for
bootstrap, DCC, spontaneous-launch and exposure rules.

## Secrets

The IRC section contains only the name of a server-password environment
variable. Secret resolution requires an explicit environment mapping; the
loader never reads
the process environment implicitly. A missing variable means that no IRC
server password is configured. Empty values, NUL and line breaks are rejected.

The resolved password is excluded from the transport policy representation.
When present, it is rendered as `PASS` before `NICK` and `USER`. Tests use only
synthetic credentials.

Partyline user passwords are not TOML values or environment variables. They are
entered only through an ECHO-suppressed partyline session and stored as salted
`scrypt` digests in the durable state directory.

## Activation

Loading and validating configuration does not connect to IRC, enable the game,
create directories or start a process. Pilot composition requires
`game.enabled` plus a separately injected armed gate containing the exact
endpoint and ordered channels. It recovers state but returns before connection
startup. The canonical example deliberately remains false. The foreground pilot
command requires a separately supplied exact endpoint, ordered channel list and
literal confirmation; no service or automatic connection is installed.

The optional systemd candidate keeps the same application configuration. A
separate root-controlled environment file repeats the exact target arguments
and the complete live confirmation; it contains no game setting or IRC secret.
`service-run` refuses any mismatch before opening runtime files or a stream.

Presentation randomization changes no hit probability, target health, reward,
schedule deadline or replay event. It only makes exact-line automation less
reliable. The canonical example stays disabled so a copied configuration never
changes its public output implicitly.

Spontaneous launches likewise never consume or move a daily schedule deadline.
The interval timer is process-local and draws a fresh full delay after each
successful or skipped occurrence, preventing restart catch-up bursts. An
accepted target still crosses the ordinary replay and priority-response
boundary before appearing on IRC.

For pilot commands, relative state and log paths are anchored to the directory
containing the configuration file. The two resolved directories must be
separate, accessible and free of symbolic-link components. Preflight validates
them without creating either directory.

The ranking and metrics paths are deliberately different: both must already be
absolute. Their parents are validated again by each publisher and may not be a
symbolic link. The preflight creates neither spool directory and touches neither
output file.
