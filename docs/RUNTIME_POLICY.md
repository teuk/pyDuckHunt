# Runtime scheduling and admission policy

The runtime boundary turns injected schedules, command timestamps and random
rolls into concrete game facts. It does not open sockets, read a wall clock,
sleep, create timers or write persistence.

## Daily flights

- A UTC-day schedule contains 24 unique deadlines through 24 community hits,
  21 through 99 hits and 18 from 100 hits onward.
- Every deadline lies inside the represented day.
- The builder consumes one distinct injected hour and one injected minute per
  slot. A selected midnight deadline moves to 00:01 so it cannot collide with
  the daily planning callback.
- A kind roll from 1 through 18 selects a golden target on 1 and a standard
  target otherwise.
- Golden health is a separate injected integer from 3 through 5.
- Every selected flight has a fixed lifetime of 300 seconds.

Mechanical targets remain explicit consequences of durable channel actions and
do not enter the scheduled random weighting.

The schedule and its next unconsumed index are part of canonical state. The
adaptive count is selected only when a new UTC-day plan is installed; progress
changes never replace the current day's plan. An installation replay event
stores every concrete deadline. A tick at an exact
deadline may dispatch one already-selected flight. A tick without a selection
consumes that deadline as missed. Every earlier deadline is also consumed as
missed, so restart recovery never launches a catch-up burst or samples a target
again. An active flight blocks selection at that deadline; the caller records a
tick without a selection instead.

The runtime treats an active flight's 300-second expiration as a concrete
wake-up deadline. It dispatches a replayable time advance at the exact
expiration even without IRC traffic, announces the escape once and stores the
completed flight for `!lastduck`.

## Command admission

Public runtime events use independent rolling windows whose accepted-request
expirations are durable:

| Scope | Command | Maximum | Window |
| --- | --- | ---: | ---: |
| Player | shot | 30 | 600 s |
| Player | reload | 15 | 120 s |
| Player | stats | 2 | 120 s |
| Player | last flight | 1 | 300 s |
| Player | shop | 3 | 600 s |
| Channel | all public commands | 30 | 600 s |

Inventory and ranking have no separate player window; the channel-wide safety
window still applies. Admission checks the applicable player window and the
channel window atomically. A rejected command changes neither window and never
reaches the game or shop transition. The first rejection may produce a concise
player notice; further notices for the same blocking window stay silent for 60
seconds. A request is admissible again at the exact first expiration deadline.

Low-level game and purchase transitions remain available for deterministic
domain tests and trusted internal actions. Public adapters and their replay
events are the only paths that mutate throttle state.

## Loot

Standard loot starts from its exact ordered per-thousand thresholds. Positive
karma reduces junk linearly and doubles every useful standard drop at +100%;
negative karma only raises junk, up to twice its base threshold in the current
standard slice. An active abundance amulet doubles each resulting bounded
threshold. Selection uses the post-kill profile, so the killing duck contributes
immediately. Effective karma also scales the settled base jam risk from half at
+100% to double at -100%, within the absolute bound. The runtime may also accept
a concrete unusual award selected by an external policy; that award must belong
to the unusual catalog.

The public sample leaves the unusual chance at zero. This is a deliberate
calibration boundary, not a claim that unusual rewards never occur. A later
pilot round may set the frequency without changing acquisition or replay.
