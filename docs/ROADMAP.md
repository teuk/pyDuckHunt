# Roadmap

pyDuckHunt is a public beta. This is an acceptance plan, not a release calendar.
Completed implementation and automated tests do not replace live validation.

## Before a release

These gates remain open until maintainers record evidence for a candidate commit.
The current version remains `0.1.0-dev`; no release is scheduled.

| Priority | Work remaining | Completion evidence |
| --- | --- | --- |
| 1 | Finish the English live pilot alongside the French beta | Same source commit; separate configuration/state; player commands, shop, notices, Owner planning and restart observed in both languages. |
| 1 | Rehearse installation and updates on a fresh supported Linux host | Follow the public guide as a new operator in `en` and `fr`; record OS/Python, READY, graceful stop, recovery and rollback outcome. |
| 1 | Make systemd setup portable | Remove dependence on the original pilot account and paths from the install procedure; verify isolated services and writable directories on another host. |
| 1 | Validate distribution artifacts | Build source/wheel artifacts; install outside the checkout; check entry point, translations, license and matching version metadata. Current editable-install CI is only part of this work. |
| 2 | Complete gameplay and translation feedback | Resolve reproducible beta issues; confirm item promises, timing, fatigue and accuracy text against actual behavior. |
| 2 | Finish operational acceptance | Rehearse reconnect, coherent backup/recovery, update and rollback; retain private evidence without publishing player data. |
| Final | Review a release candidate | Full suite and GitHub CI green on that revision, remaining issues triaged, release notes and explicit maintainer approval. |

For each gate record the commit, environment, procedure, result and remaining
limitations. Keep raw logs and identities private. See [release workflow](RELEASING.md).

## Recent beta improvements

- [x] Fixed daily base of 24 flights with durable, private planning.
- [x] Bread and duck-call behavior aligned with the retained Tcl 2.11 rules.
- [x] Fatigue, thermos, scope and shot feedback made consistent with game state.
- [x] English/French presentation and explicit installer language selection.
- [x] Shared-source language isolation and deterministic regression contracts.

## Foundation

- [x] Python package skeleton.
- [x] Local validation lanes.
- [x] Public-tree policy.
- [x] Initial reviewed commit and public GitHub repository.
- [x] Non-root local beta installer with a disabled first-run configuration.

## Game engine

- [x] Protocol contracts, command parser and RFC1459 identity.
- [x] Flight sessions, monotonic clock and deterministic arbitration.
- [x] Foundational shooting and reload transitions.
- [x] Durable channel-action deadlines and injected scheduling boundary.
- [x] Pure daily-flight and loot selection policy with injected entropy.
- [x] Durable runtime scheduler and injected random-source adapter.
- [x] Replayable command throttling and channel safety policy.
- [x] Profiles, calibrated progression, ammunition reserves and inventory core.
- [x] Current v3 level weapons, accuracy, reliability, defenses and penalties.
- [x] High-confidence shop catalog, atomic settlements and effect lifetimes.
- [x] Deterministic shot equipment and resistant-target health.
- [x] Cross-player incidents, defensive settlement and confiscation recovery.
- [x] Targeted nuisances, countermeasures and source-attributed replay.
- [x] Rendered player statistics, query projections and bounded response templates.
- [x] Reference-complete two-notice hunting sheet and compact inventory projection.
- [x] Observed 1–31 shop catalog, fatigue and purification prerequisites.
- [x] Fixed-point fatigue accumulation and complete curse modifier composition.
- [x] Rare flight identities, standard loot and composed modifier scenarios.
- [x] High-confidence vouchers, promotions and unusual amulets.
- [x] Ammunition recyclers, unlimited reserves and permanent capacity variants.
- [x] Remaining observed legendary protection variants.
- [x] Letter collection and carried-duck capacity.
- [x] Operator-controlled anti-cheat flight appearance variety.

## Operations

- [x] Versioned digest-chained journal.
- [x] Atomic checksummed snapshots and recovery.
- [x] Deterministic synthetic replay foundation.
- [x] Asynchronous persistence worker and backpressure policy.
- [x] Single-owner process-neutral dispatch and clean shutdown lifecycle.
- [x] Calibrated behavioral replay suite.
- [x] Process-neutral IRC transport and in-memory fake-server integration.
- [x] Socket, verified TLS and strict configuration adapters.
- [x] Guarded process shell and I/O-to-game message bridge.
- [x] Concrete settlement adapters and exact development pilot gate.
- [x] UTC-compatible runtime scheduling and operator-controlled pilot loop.
- [x] Explicit live-target preflight and confirmed foreground pilot launcher.
- [x] Privacy-safe READY and lifecycle telemetry for reviewed pilot evidence.
- [x] Eggdrop-style authenticated partyline, DCC access and replayable player administration.
- [x] Guarded partyline launch of standard and golden flights without schedule drift.
- [x] Partyline top-five summary with canonical player and last-shooter views.
- [x] Partyline-owner IRC rearm and temporary/permanent confiscation controls.
- [x] Owner-only private IRC flight launch and bounded spontaneous extra flights.
- [x] Reviewed live development IRC pilot execution.
- [ ] Complete public beta feedback and compatibility cycle.
- [x] Optional operator-controlled shop URL with a link-free default.
- [x] Signal-controlled and disarmed systemd service candidate.
- [ ] Production release candidate and guarded rollout.
