# Coin partyline

Coin exposes an optional Eggdrop-style administration surface from the same
single-owner loop as IRC and DuckHunt. It adds no daemon, thread or third-party
runtime dependency.

## Access paths

The three supported paths converge on the same login, authorization, command
dispatcher and broadcast room:

```text
telnet localhost <partyline.port>
/dcc chat Coin
/ctcp Coin CHAT
```

The configured TCP listener is independent from temporary DCC listeners. The
beta binds the former to `127.0.0.1`; setting `bind_host` to `0.0.0.0` or `::`
is an explicit decision to expose password login beyond the host. Partyline
traffic is classic plain TCP, not TLS, so loopback or a separately protected
network path is the safe default.

Active `/dcc chat Coin` requests are accepted only for public IPv4 destinations
and unprivileged ports. Loopback, private, link-local, multicast and reserved
targets are rejected before `connect`, preventing the IRC command from becoming
a generic network probe. Passive/token DCC is supported.

Server-offered `/ctcp Coin CHAT` requires `dcc_public_ip`. Coin opens one
temporary listener, sends the standard integer IPv4 DCC offer and closes the
listener after connection or 60 seconds. A nickname can hold only one offer;
at most four DCC handshakes may be pending. `dcc_port_min` and `dcc_port_max`
may select a firewall-friendly range of at most 101 ports. Zero/zero delegates
temporary port selection to the operating system.

## First owner

Initialization is deliberately stronger than an unrestricted first-come
Eggdrop bootstrap:

1. the private TOML configuration names at least one allowed Services account
   or IRC mask;
2. that identity sends `/msg Coin hello`;
3. Coin arms one ten-minute invitation and replies with the available access
   methods;
4. the operator opens DCC CHAT, or connects to the local TCP listener and enters
   the invited nickname as the handle;
5. the partyline asks twice for a new password and creates the first owner.

Repeating `/msg Coin hello` before the first owner is created renews the
ten-minute bootstrap. Once an owner exists, an authorized owner identity uses
`/msg Coin reset` instead. Coin arms a ten-minute recovery and accepts the new
password only through DCC CHAT or the loopback listener, never through IRC.
The handle, IRC account/mask and owner role are preserved, the old credential
is revoked and existing sessions for that owner are disconnected.

`/msg Coin pass ...` is explicitly refused. The password therefore never enters
IRC, application observations or command arguments. During Telnet password
entry Coin negotiates ECHO off and restores it afterward.

Credentials live in `partyline-users.json` under the configured durable state
directory. The file is mode `0600`, schema-checked, size-bounded, written with
atomic replacement and contains a per-user random salt plus an `scrypt` digest,
never the password. Symbolic links, public modes, malformed records and a second
first-owner creation fail closed.

An operator with shell access can recover the same account without putting a
secret in shell history or the process list:

```console
PYTHONPATH=/home/mediabot/DuckHunt/src \
  /home/mediabot/DuckHunt/.venv/bin/python -B -m pyduckhunt \
  partyline-password-reset \
  --state-directory /home/mediabot/pyduckhunt-pilot/state \
  --handle 'Op[e]rator'
```

The command prompts twice with terminal echo disabled and atomically rotates
only the selected credential. Restarting the Coin service afterwards closes
any partyline session that may already have been authenticated.

Every normal session asks separately for a handle and password. Input is
limited to 4096 bytes per line, output is bounded, authentication expires after
60 seconds, and failures are limited per connection and per peer address.

## Room and live information

After login, Coin displays IRC connection state, joined channels, uptime,
player count, persistence state and queue depth. Ordinary text is broadcast to
every authenticated operator as `<handle> message`. Joins, departures and
player updates are broadcast too.

Privacy-safe runtime observations are relayed for important state changes:
IRC connection state, accepted command classes, schedule changes, flight starts
or expirations and network failures. Channel text, player messages and password
material are not copied into operator logs.

Useful read-only commands are:

```text
.help
.who
.status
.dccstat
.game
.summary
.duck [#channel]
.goldenduck [#channel]
.player <nick>
.fields
```

`.dccstat` reports the public address, port mode, pending handshakes and current
DCC/Telnet sessions. `.game` reports the active target and remaining lifetime,
daily schedule cursor and next deadline, the next optional spontaneous launch,
plus aggregate players/effects/actions/curses. `.player`
reports level and XP threshold, hit statistics, best time, weapon, ammunition,
magazines, confiscation, jam, fatigue, carried ducks, credit and inventory.
`.summary` presents the configured top-five ranking and page, then the canonical
profile and inventory of each ranked player. It appends the same two views for
the last player whose shot actually fired. IRC colour controls are removed for
clean DCC and Telnet output; with one joined channel, inventory also names its
active bread count for that channel.

`.duck` starts one standard duck and `.goldenduck` (alias `.golden`) starts one
golden duck with the same calibrated three-to-five health and reward rules as
an autonomous golden flight. With one joined channel it is selected
automatically; with several, the target channel is mandatory and must currently
be joined. A launch is refused while another duck is active, while IRC is
disconnected or when persistence is backpressured.

An accepted launch uses the configured five-minute flight lifetime, consumes
detector effects normally and emits the ordinary channel appearance and private
detector notices. Its complete target settlement is journaled before game state
changes become durable. It does not consume, replace or postpone any deadline
in the autonomous daily schedule.

When spontaneous launches are enabled, Coin draws a fresh delay inside the
configured interval at startup and after every attempt. At the deadline it
starts one standard duck only on the configured joined channel. A successful
attempt sends the configured announcement immediately before the ordinary duck
appearance. A disconnected bot, missing channel, active flight or persistence
backpressure skips that occurrence and draws a new full interval; it never
polls aggressively or catches up with a burst. This transient timer changes no
durable daily-schedule cursor, while the accepted flight itself uses the same
journaled transition, bread consumption and detector notices as `.duck`.

## Replayable player administration

The first mutation surface is intentionally bounded:

```text
.giveammo <nick> [count]
.givemag <nick> [count]
.returnweapon <nick>
.passwd
.unjam <nick>
.setplayer <nick> <field> <value>
```

Grants saturate at the player's current capacity. `.setplayer` accepts the
fields listed by `.fields`; capacities, fatigue, level, XP, credit, state flags
and counters each keep their domain bounds. Reducing a capacity safely clamps
its current quantity. Invalid players, fields or values change nothing.

Every accepted update becomes an `admin_player_update` replay event containing
the owner handle, player identity, operation, field and settled integer value.
It reserves the normal persistence queue before changing memory, follows the
same digest-chained journal and snapshot lifecycle as game commands, and is
rejected atomically under backpressure. Schema 18 is therefore the first schema
that can preserve partyline administration across restart and full replay.

`.returnweapon` uses the dedicated weapon-control event and clears both daily
and permanent confiscation. A permanent confiscation cannot be bought away in
the shop; only an authenticated owner action can clear it.

`.passwd` disables Telnet echo, asks for a new 12-to-128-character password
twice and atomically replaces the stored `scrypt` verifier. Credentials created
under the former bounded policy remain accepted for login so that the owner can
perform this rotation; newly created and replacement passwords still require at
least 12 characters. No password is written to application logs.

## Owner commands on IRC

The partyline owner may issue two narrowly scoped commands in a channel Coin is
currently joined to:

```text
!rearm <nick>
!unarm [-permanent] <nick>
```

The same controls are available by private message, without the public-command
prefix:

```text
/msg Coin rearm <nick>
/msg Coin unarm [-permanent] <nick>
```

Coin resolves the sender to the private partyline owner record. Matching the
nickname alone is never sufficient: a present Services account tag must match
the stored account, while networks without that tag must present the exact IRC
prefix captured at owner bootstrap. Unauthorized attempts are consumed without
an IRC response and leave no game event.

Plain `!unarm` confiscates the weapon until the next Europe/Paris midnight refill.
`!unarm -permanent` survives every refill and blocks the shop return item until
the owner sends `!rearm`. Accepted changes reserve persistence before mutation,
carry the owner handle in an `admin_weapon_control` journal event, broadcast to
the partyline and acknowledge the result in the IRC channel or by private
NOTICE, matching the command scope.

The same owner identity may launch a flight privately:

```text
/msg Coin ducklaunch #channel
/msg Coin ducklaunch #channel 1
```

The first form starts a standard duck; the exact optional value `1` selects a
golden duck. The channel is mandatory and must be joined. Nickname-only spoofs
are silently consumed, malformed owner requests receive the exact usage, and
accepted launches are acknowledged by private NOTICE. Both forms share the
partyline launch transaction and leave the daily planning cursor untouched.

## Configuration

```toml
[partyline]
enabled = true
bind_host = "127.0.0.1"
port = 3333
bootstrap_accounts = ["operator-account"]
bootstrap_masks = ["Operator!*@trusted.example"]
dcc_public_ip = "203.0.113.10"
dcc_port_min = 50000
dcc_port_max = 50010
spontaneous_launch_enabled = true
spontaneous_launch_channel = "#community"
spontaneous_launch_min_seconds = 10800
spontaneous_launch_max_seconds = 21600
spontaneous_launch_announcement = "allez, je lance un canard"
```

The section is optional and disabled when absent. Its five spontaneous-launch
fields are optional for compatibility with existing configurations and default
to disabled, no channel, a zero interval and the announcement shown above.
Enabling spontaneous launches requires the partyline control plane, one of the
configured IRC channels and an ordered interval between 15 minutes and 24
hours. Enabling the partyline requires at least one bootstrap identity. The listener starts
before the IRC adapter and any bind failure stops startup rather than silently
running without the expected administration path. Shutdown closes partyline
and DCC sockets before persistence is drained.
