# Targeted nuisance interactions

Targeted purchases are deterministic settlements. The caller injects a target
nickname and a current presence fact; the catalog decides whether presence or
weapon access is required. The game state stores both the target owner and the
canonical source identity so later outcomes remain attributable after recovery.

## Interaction matrix

| Item | Target gate | Lifetime | Counter or remedy | Shot-time result |
| --- | --- | --- | --- | --- |
| glare | known and present | one fired shot | sunglasses or permanent model block | halves base accuracy |
| sand | known and armed | one trigger pull | grease or military self-lubrication block; bore brush removes | doubles jam risk |
| water | known and present | one hour | raincoat or tearproof model block; dry clothes remove | blocks shooting |
| sabotage | known and armed | one trigger pull | bore brush removes | forces a jam |

The buyer is charged when a valid countermeasure blocks a nuisance. A duplicate,
unknown target, missing presence, unavailable weapon or inapplicable remedy is
rejected before charging. Sunglasses and raincoats remain active after blocking;
grease is consumed when it blocks sand. Their permanent legendary counterparts
are inventory facts and are never consumed. Military self-lubrication also
halves the final jam risk exactly once, even if ordinary grease is active.

Sand and sabotage may target an absent known player because they apply to the
stored weapon state. Glare and water require live presence. Self-targeting is a
valid deterministic case and follows the same rules.

Arc and crossbow owners are immune to sand and sabotage, as specified by the v3
level table. Those purchases are rejected before charging and create no effect.
Their silent shots also cannot frighten a duck merely because a shot missed.

## Trigger ordering

1. expire due effects;
2. resolve weapon availability, then block a shot while soaked;
3. preserve pending nuisances when the weapon is already jammed or empty;
4. apply sand to the jam threshold and consume it;
5. trigger sabotage before ammunition is consumed;
6. keep glare pending if a random jam occurs;
7. consume glare only after a shot is fired.

The engine receives probability rolls from its caller and never samples inside
the transition. Replay uses the same purchase facts, effect source and shot
attempt, so protection and nuisance outcomes remain byte-for-byte reproducible.
