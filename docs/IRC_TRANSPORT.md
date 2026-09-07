# IRC transport

The IRC transport is a process-neutral state machine. It does not open a
socket, resolve a hostname, start a thread or read configuration. A separate
socket adapter executes its explicit connect, send and close actions.

## Stream boundary

`IRCLineBuffer` accepts immutable byte chunks and emits complete CRLF-terminated
wire lines. It preserves an incomplete tail across calls, enforces the 512-byte
IRC limit and rejects empty lines, bare line feeds, embedded carriage returns
and oversized incomplete frames. A failed feed does not change the buffered
tail.

## Session states

The transport moves through these states:

1. `new` to `connecting` when startup requests one connection;
2. `registering` after the adapter reports a connected stream;
3. `joining` after a matching `001` welcome;
4. `ready` after the bot has joined every configured channel;
5. `backoff` after a connection or protocol-lifecycle failure;
6. `stopping` while a graceful `QUIT` is pending;
7. `stopped` when no later reconnection is permitted.

Only the constructing thread may advance the state machine. All timestamps are
non-negative monotonic nanoseconds, and truth values are rejected as numeric
inputs.

## TCP and TLS adapter

`IRCSocketConnector` opens one bounded TCP connection. TLS endpoints use
Python's verified client context and the configured hostname for certificate
verification. The connector accepts injected dialer and TLS factories so tests
never resolve a public hostname or contact a network.

Connection establishment is a bounded I/O-owner operation, outside the game
transition owner. After TCP and TLS setup, `IRCSocketAdapter` switches the byte
stream to non-blocking mode. It bounds reads per poll and pending output bytes,
preserves partial sends, classifies failures without exposing exception or
secret text, and rejects clock errors before stream I/O.

## Registration and input

On connection, the transport emits exact `NICK` and `USER` lines. Numeric 433
selects one validated fallback nickname; a second collision closes the stream
and enters backoff. When the configured bot-mode flag is enabled, a matching
welcome first emits `MODE <current nickname> +B`, then one `JOIN` per configured
channel. The mode therefore also follows a validated fallback nickname.
RFC1459 casemapping is used for nicknames and channel membership.

`PING` is answered immediately in every connected state. Application
`PRIVMSG`, `NOTICE` and `TAGMSG` messages are exposed only after all joins are
confirmed. Membership facts (`JOIN`, `PART`, `QUIT`, `NICK`, `KICK`, `353` and
`366`) are also exposed to the process observer so the live incident adapter
can maintain a synchronized, in-memory roster without retaining hostmasks. A
kick of the current nickname schedules a join for that channel without
inventing game state.

Application output follows the reverse boundary. The transport accepts an
immutable batch only in `ready`, validates every complete wire line before
returning send actions, and preserves batch order. The socket adapter reserves
capacity for the entire batch before appending any byte. A full output buffer
therefore rejects the priority sink atomically instead of committing a game
transition whose response could not be queued.

## Timeouts and reconnection

Handshake, idle and shutdown deadlines are exact injected policy values.
Reconnect delays form a non-empty bounded sequence: consecutive failures move
through the sequence and then remain at its final value. Reaching `ready`
resets the next failure to the first delay. Missed ticks produce one connection
request, never a catch-up burst.

Clean shutdown emits one `QUIT`, waits for connection loss or the exact stop
deadline, and never reconnects. A server `ERROR` during shutdown also ends in
`stopped`.

## Test peer

`tests.support.fake_irc.FakeIRCServer` feeds arbitrary in-memory byte chunks to
the framing and transport contracts. Additional integration tests use local
`socketpair()` streams to exercise the real non-blocking byte adapter. They
cover fragmented registration, fallback nicknames, split PING frames, exact
backoff, peer closure and clean shutdown without creating a network connection.

The process-shell integration additionally sends one synthetic command through
a local socket pair, observes the bounded response, waits for its journal
ticket, stops transport and then verifies final recovery.
