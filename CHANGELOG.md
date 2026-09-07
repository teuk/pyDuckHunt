# Changelog

All notable changes to pyDuckHunt will be documented in this file.

## Unreleased

### Fixed

- Partyline recovery is now possible without deleting its private identity
  database: `/msg Coin reset` arms a short owner-bound DCC/loopback reset, and
  `partyline-password-reset` provides an echo-free shell recovery path.
- Incident selection now matches the retained reference rate of four events
  in 79 eligible bangs: the five-percent draw applies to every fired shot at an
  active duck and, when selected, turns that shot into the incident miss.
  Selected rolls and defenses are written to the private application log.
- Incident messages no longer label a hunter as tired merely because the shot
  added one fatigue point. Existing partyline passwords from the bounded legacy
  policy authenticate again and can be replaced immediately with `.passwd`.
- Bangs received within three seconds after a kill are now reported with their
  exact delay and pay only the miss penalty; later bangs remain explicit wild
  shots. The live operator also restores synchronized, five-percent hunting
  incidents with visible ricochet, armor and fatal outcomes.
- Player weapons, loaded ammunition, reserve magazines, fatigue and carried
  ducks now reset at Europe/Paris midnight, including automatic CET/CEST
  changes. Golden flights also remain visually ordinary until the first
  successful bang reveals them.
- Ranking publication now debounces bursts of atomic spool replacements before
  running the hardened root oneshot. Its explicit start-rate ceiling retains
  failure protection without disabling a busy channel's path watcher.
- `!inventory` now reports the actual remaining lifetime of the suppressor, just
  like every other time-bounded active item, and avoids repeating the nominal
  duration or percentage of promotion coupons.
- Equipment found while searching the bushes now explains its effective bonus,
  lifetime, remaining-use model or permanent protection in the acquisition
  message.

### Added

- First reviewed public GitHub repository contract, including full CI,
  community health files, package metadata and a source-derived Creative
  Commons BY-NC-SA 3.0 attribution.
- Safe local beta installer with a project virtual environment, a non-overwriting
  disabled configuration and no implicit IRC or systemd activation.

- Prerelease schema 20 for durable fired-shot, weapon-jam and spent-experience
  totals reconstructed from the complete journal during migration.
- The complete two-notice `!duckstats` hunting sheet: global experience,
  level title and remainder, profitability, theoretical and effective shot
  statistics, weapon reliability and the complete hunting/accident counters.

- Partyline `.summary` with the configured top-five link, canonical profiles,
  inventories and the durable last shooter.
- Owner-identity-bound IRC `!rearm` and `!unarm [-permanent]` administration,
  with replayable temporary and permanent weapon confiscation. The same
  commands are accepted by private `/msg Coin rearm|unarm` administration.
- Prerelease schema 19 for durable permanent confiscation and last-shot identity.
- Replayable `.duck` and `.goldenduck` partyline launches with joined-channel,
  active-flight and persistence guards, while preserving the daily schedule.
- Optional Eggdrop-style Coin partyline over local TCP, active DCC CHAT,
  server-offered CTCP CHAT and passive/token DCC.
- Identity-allowlisted `/msg Coin hello` first-owner bootstrap with private
  atomic `scrypt` credential storage and Telnet password echo suppression.
- Partyline broadcasts, Coin/DuckHunt status, player profiles and replayable
  bounded ammunition, magazine, weapon, jam and player-field administration.
- Prerelease schema 18 for audit-attributed `admin_player_update` journal events.
- Adaptive next-day plans with 24, 21 or 18 flights from community progress.
- Stable application log and privacy-safe schedule change/30-minute DEBUG facts.
- Durable last-flight history and autonomous exact five-minute flight expiration.
- Rich two-line successful-shot and bush-search IRC presentation.
- Deterministic responsive HTML ranking generated only from durable state.
- Least-privilege path/oneshot publication with a root-owned Apache target.
- Compact, restrained ranking presentation aligned with the complete site.
- Aggregate Prometheus snapshots without player labels, served on loopback only.
- Provisioned Grafana dashboard for runtime, activity, schedule and failures.
- Compact `--progress` validation output with successful test details suppressed.
- Canonical player-facing durations in compact seconds, minutes and hours.

- Initial Python project foundation.
- Public-tree policy and local validation lanes.
- GitHub Actions fast validation workflow.
- Strict IRC parsing and rendering contracts with a 512-byte wire limit.
- RFC1459 identity normalization and observed command vocabulary.
- Immutable flight state with monotonic timing and deterministic shot arbitration.
- Versioned digest-chained event journal with strict corruption detection.
- Checksummed atomic snapshots and deterministic tail recovery.
- Calibrated level progression with deterministic hit rewards and overflow.
- Magazine reserves with finite reload consumption and exhaustion outcomes.
- Canonical typed inventory stacks persisted in prerelease schema 2.
- Thirty-one-entry deterministic shop catalog with explicit scopes and boundaries.
- Atomic experience settlement for direct grants and active effects.
- Exact effect expiration, limited-use consumption and exclusive replacement.
- Replayable settled costs and injected magnitudes in prerelease schema 3.
- Replayable shot baselines and rolls expressed in integer basis points.
- Durable target health and jammed-weapon state in prerelease schema 4.
- Equipment-aware damage, accuracy, jam, trigger-lock, noise and reward rules.
- Atomic cross-player incident chains with injected deflection and armor rolls.
- Durable confiscation and incident counters with deterministic weapon return.
- Life, liability and safe-conduct protection settled in one replayable event.
- Downward progression across purchase and penalty boundaries in schema 5.
- Targeted glare, sand, water and sabotage with explicit source attribution.
- Sunglasses, grease, dry clothes, bore brush and raincoat countermeasures.
- Presence-aware and weapon-aware nuisance settlement in prerelease schema 6.
- Calibrated argument contracts for the stable player command vocabulary.
- Pure French profile, inventory, shop, ranking and outcome response templates.
- Optional operator-controlled HTTPS shop page with a link-free default.
- Target-specific PRIVMSG budgeting with safe UTF-8 shortening at 512 bytes.
- Four-line response boundary for latency-sensitive player commands.
- Durable scheduled actions for bounded duck calls and exact mechanical flights.
- One-use private flight alerts that are consumed only by a successful spawn.
- Durable bounded fatigue with replayed espresso, thermos and targeted relief.
- One-hour tonic and infusion modifiers plus post-shot automatic reload.
- Typed bounded curse foundation and atomic purification in prerelease schema 7.
- Fixed-point fatigue accumulation with replayed centi-point shot gains.
- Complete deterministic composition for all eight calibrated curse modifiers.
- Replayable five-second command deferral without sleeping in the game engine.
- Exact thermos targets and immediate, reversible infusion fatigue settlement.
- Prerelease schema 8 for fixed-point profiles, shots, delays and shop intents.
- Persisted standard, golden and mechanical flight identities with exact rewards.
- Health-scaled golden rewards and a durable golden-hit profile counter.
- Ordered standard loot catalog with injected per-entry selection rolls.
- Atomic post-kill ammunition, magazine, equipment, experience and curse awards.
- Replayable nested loot settlements and prerelease schema 9.
- Durable shop vouchers, promotion coupons and bounded unusual reward effects.
- Pure daily target and loot selection with explicit injected entropy.
- Canonical daily schedule cursors with exact ticks and restart-safe missed deadlines.
- Atomic per-player and channel-wide rolling command admission windows.
- Replayable runtime commands, purchases and schedule events in prerelease schema 11.
- Bounded asynchronous journal and snapshot worker with failure latching.
- Single-owner runtime dispatch that reserves durability before state mutation.
- Startup recovery, full-queue backpressure and draining shutdown contracts.
- Incremental IRC byte-stream framing with atomic 512-byte validation.
- Process-neutral IRC registration, channel, timeout and reconnect state machine.
- In-memory fake IRC peer for fragmented traffic and clean-lifecycle tests.
- Strict TOML configuration with explicit, redacted environment-secret resolution.
- Non-blocking socket adapter with verified TLS hostname handling.
- Local socket-pair integration for partial I/O, reconnect and shutdown flows.
- Strict ready-channel IRC-to-game bridge with injected replay settlements.
- Atomic application output admission through the bounded socket adapter.
- Configuration-guarded process shell with transport-first clean shutdown.
- Local socket-pair command, response, persistence and recovery integration.
- Single-owner concrete settlement for foundational shots and catalog purchases.
- Checked operating-system entropy and injected presence or incident adapters.
- Double-gated development pilot composition with exact destination allowlisting.
- Local socket-pair coverage of gated composition, response, persistence and stop.
- UTC-compatible monotonic process clock with backward-time failure boundaries.
- Concrete daily-plan entropy, bounded lateness and restart-safe missed slots.
- Explicit operator-controlled pilot loop with transport-first bounded shutdown.
- Local socket-pair runner coverage without DNS or public network egress.
- Side-effect-free live-target preflight with absolute runtime-path resolution.
- Exact-confirmation foreground pilot CLI and mode-0644 operator transcripts.
- Historical fixed-point karma with a distinct durable wild-shot counter.
- Schema-11 recovery migration by full journal replay into prerelease schema 12.
- Post-kill karma bias toward equipment and experience instead of junk.
- Complete observed karma formula with empty-shot, jammed-weapon and compulsive
  reload counters, plus the decaying shop modifier in prerelease schema 13.
- Bounded karma influence on settled weapon-jam risk.
- Current v3 level-policy catalog through level 100, including weapon bands,
  accuracy, reliability, ammunition, defenses and experience penalties.
- Schema-14 recovery replay for corrected progression and level armament.
- Exact 1/3, 1/2 and permanent 1/10 ammunition recyclers with replayed
  one-through-thirty settlement in prerelease schema 15.
- Warrior and eternal-warrior amulets with bounded unlimited-reserve reloads.
- Unique permanent extended-magazine and large-ammunition-bag capacity upgrades.
- Level-gated permanent sunglasses, raincoat, self-lubrication and killing
  license protections with unique durable inventory facts.
- Permanent nuisance counters that drain matching pending effects, block later
  hostile purchases and preserve exact incident or jam settlement.
- Durable eight-slot `DUCK HUNT` collection with duplicate-safe phrase-order
  settlement and a replayed bounded completion bundle.
- Daily carried-duck bags with exact encumbered and overloaded fatigue bands,
  UTC reset and a 24-hour TARDIS exemption in prerelease schema 16.
- Six calibrated synthetic behavioral traces covering hunting, collection,
  karma, nuisances, incidents, scheduling, throttling and bounded rendering.
- Snapshot recovery verification at every event cut of every behavioral trace.
- Privacy-safe foreground pilot telemetry for READY acquisition, lifecycle
  changes, aggregate command handling, scheduling and network-failure counts.
- Signal-controlled `service-run` composition that restores process handlers
  after bounded transport and persistence shutdown.
- A disarmed systemd service candidate with exact-target preflight, a
  root-controlled confirmation boundary and two explicit writable paths.

### Changed

- Make `!inventory` follow the compact reference layout with one orange
  `[Inventaire]` heading, weapon, ammunition, magazines, bag, letters and
  concise owned-item labels in display order.
- Add owner-only private `ducklaunch #channel [1]` flight control and optional
  randomized standard launches with a configurable announcement, bounded
  interval and no daily-schedule drift.
- Consume the oldest active channel-bread stack at each successful flight start,
  report the resulting count in purchase confirmations and merge temporary
  effects into the canonical inventory section.
- Complete the once-per-UTC-day refill by restoring confiscated weapons and
  filling ammunition and reserve magazines alongside the existing fatigue and
  duck-bag reset; expose active channel bread in `!inventory` and lock the
  successful-shot XP/level presentation through the live IRC bridge.
- Move the privileged ranking publisher paths into a root-owned exact-schema
  configuration and watch the spool directory so atomic page replacement
  reliably triggers publication. Give the capability-free root oneshot only
  the supplementary `mediabot` group needed to traverse the private spool.
- Make `!duckrank` default to a colored top five and append the independently
  configurable public ranking-page URL on its own channel line.
- Restore the four observed loot rarity markers with a stable green, blue,
  purple and orange tier palette derived from catalog metadata.
- Render encumbered and overloaded carry warnings in red on both successful
  hit and inventory responses.
- Refuse manual reloads whenever ammunition remains, preserving both the loaded
  rounds and reserve magazines while retaining the compulsive-reload counter.
- Explain the one-use NOTICE when a duck detector is found and deliver that
  private alert exactly once when the next flight successfully starts.
- Display an active suppressor beside the equipped weapon, including its
  remaining lifetime, instead of burying it in the generic effect list.
- Allow a paid lucky-charm reroll to replace its active magnitude and restart
  its 24-hour deadline while preserving the previous charm on failed payment
  and keeping historical duplicate rejections stable during journal replay.
- Announce the settled targeting-scope percentage and lucky-charm experience
  bonus in the purchase confirmation instead of hiding them until inventory.
- Settle noisy-miss escapes with the historical 5% decision instead of making
  every non-silent miss end the active flight.
- Route profile, inventory and shop-catalog queries to private IRC NOTICE
  responses and compact the complete shop fallback from four lines to two.
- Display karma in the compact profile while keeping weapon state in inventory.
- Greedily compact adjacent response fragments within the IRC byte budget, move
  weapon and reserve status from `!duckstats` to `!inventory`, and keep the
  ordinary forms of both commands to one private NOTICE.
- Replace the dense two-line IRC shop catalog with one private NOTICE linking to
  the maintained web catalog, and expose the temporary karma component in stats.
- Align every useful standard drop with the documented twofold maximum at
  +100% karma.
- Correct the level-70 progression boundary, activate level-derived live shot
  settlement, and make arc and crossbow shots silent and nuisance-immune.
- Start new hunters with the v3 level-1 machine gun and show the level-derived
  weapon name inside the existing compact `!inventory` response.
- Keep letter discoveries and collection completion to one public line, and add
  bag, letter and TARDIS state to the existing compact inventory response.
- Require an observed IRC READY state before a stopped foreground pilot can
  return operational success.
