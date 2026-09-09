# French and English instances

Choose the message language when installing a new instance:

```bash
./install.sh --language en
```

The generated configuration is private (0600), disabled, and points to an
invalid example endpoint until configured. `./install.sh --check --language en`
is read-only. Existing configurations are never overwritten: a conflicting
explicit choice fails before installation changes anything.

For an existing instance, set the following field in its private configuration,
under its existing `[game]` section, then gracefully restart that instance:

```toml
language = "en"
```

Accepted values are exactly `fr` and `en`. A missing field means French, so
current Coin installations remain French without configuration edits.

## Scope

English covers game responses, every shop item, effects and loot, level titles,
profiles, inventory, rankings, duck calls, command usage and refusals, detector
notices, private Owner planning and automatic partyline planning updates.
Generated ranking text also follows the instance language. Operator diagnostics
and protocol field names remain stable; existing English technical messages
stay English in both modes. Dates in Owner planning remain explicitly labelled
Europe/Paris: changing language does not change a deadline or time zone.

Command names remain compatible: `!bang`, `!shop`, `!duckstats`, `!inventory`,
`!duckplanning`, Owner `!pain`/`!appeau`, and `.duckplanning` do not change.
Nicknames, channel names, URLs, user chat and custom announcement text are never
machine-translated. The standard spontaneous announcement has an English
counterpart; operators should write other custom announcements in their chosen
language. An external shop/help website keeps its own editorial language.

Owner confirmations and exact plans stay private NOTICE replies. Ordinary
players cannot obtain the Owner plan in either language; shop confirmations do
not reveal precise future flight times.

## One checkout, independent pilots

Run the French beta and English pilot from the same reviewed checkout and
Python environment. Use separate processes, private configurations, state,
logs, service names and any generated web destinations. Never copy the beta
journal, scores or partyline passwords into the English test instance.

For the Teuk development pilot the selected channel is `#duckhunt-en`; the live
French game remains on its configured EpiKnet channel. The endpoint and TLS mode
must be taken from the actual development IRCd configuration, then repeated in
`pilot-check` / `service-run` allowlist arguments. Do not reuse the beta target
arguments. A language setting is never an authorization to join a network.

The same source update applies to both instances. A restart of each process is
needed to load changed Python source; there is no English source branch or fork.

## Maintaining the catalogue

`messages_en.py` maps French source templates to English. Translate the template
before interpolating dynamic values; preserve every positional field and format
specifier. `i18n.py` scopes context to synchronous instance callbacks and passes
language explicitly to background ranking publication. Do not store translated
messages or language in replay events or add language branches to game rules.

The supplied Duck Hunt Tcl 2.11 `en.msg` vocabulary is credited to MenzAgitat
(2015–2016), under the project's CC BY-NC-SA 3.0 license. Messages introduced by
pyDuckHunt are translated to match its current mechanics, not old Tcl prices.

The bilingual regression tests cover catalogue fields, FR/EN isolation, private
routing, identical paid-item and scheduling journals/entropy, and installer
configuration preservation. Existing French rendering contracts remain active.
