"""Live settlement, durable noise, and player-visible item promises."""
from dataclasses import replace
from pathlib import Path
import json
import hashlib
import tempfile
import unittest

from pyduckhunt.game.commands import Command, CommandKind
from pyduckhunt.game.engine import start_flight, apply_command
from pyduckhunt.game.model import GameState, PlayerState, ShotAttempt, FlightKind, OutcomeKind
from pyduckhunt.game.shop import purchase
from pyduckhunt.game.loot import acquire_loot
from pyduckhunt.game.model import LootAward
from pyduckhunt.persistence import ReplayEvent, JournalFile, SnapshotStore, recover
from pyduckhunt.persistence.snapshot import Snapshot
from pyduckhunt.persistence.journal import GENESIS_DIGEST
from pyduckhunt.persistence.codec import encode_game_state, decode_game_state, CodecError, canonical_json_bytes
from pyduckhunt.persistence.replay import apply_replay_event, snapshot_from_result
from pyduckhunt.rendering import render_outcomes
from pyduckhunt.runtime import CalibratedEventResolver, IRCCommandContext, SettlementPolicy

SECOND = 1_000_000_000
SHOT = Command(CommandKind.SHOT, 'bang')

def funded(level=9):
    return GameState(players=(PlayerState('hunter', 'Hunter', level=level, experience=80),))

def flying(*, item=None, kind=FlightKind.STANDARD, level=9):
    state = funded(level)
    if item:
        state = purchase(state, 'Hunter', item, SECOND).state
    return start_flight(state, 2*SECOND, lifetime_ns=300*SECOND,
                        kind=kind, health=5 if kind is FlightKind.GOLDEN else 1).state

def resolve(state, now, nick='Hunter', hit=False, incident=None):
    rolls = iter((1 if hit else 10_000, 10_000))
    def draw(low, high):
        return next(rolls) if high == 10_000 else high
    return CalibratedEventResolver(draw, lambda channel, nickname: True,
                                  incident_source=incident)(
        state, IRCCommandContext(now, nick, '#pond', SHOT))

class TclShotFeedbackTests(unittest.TestCase):
    def test_all_ammo_types_flee_on_third_noisy_miss_and_spend_rounds(self):
        for item in (None, 3, 4):
            with self.subTest(item=item):
                state = flying(item=item)
                effects = state.effects
                ammo = state.players[0].ammo
                for count in range(1, 4):
                    event = resolve(state, (2+count*2)*SECOND)
                    result = apply_replay_event(state, event)
                    state = result.state
                    self.assertEqual(state.players[0].ammo, ammo-count)
                    self.assertEqual(state.effects, effects)
                    text = ' '.join(render_outcomes(result.outcomes, channel='#pond'))
                    self.assertIn('Raté.', text)
                    self.assertNotIn('*BANG*', text)
                    self.assertNotIn('*BOUM*', text)
                    if count < 3:
                        self.assertEqual(state.flight.noisy_misses, count)
                    else:
                        self.assertIsNone(state.flight)
                        self.assertIn('Effrayé', text)

    def test_counter_is_shared_between_players(self):
        state = flying()
        for count, nick in enumerate(('Hunter', 'Other', 'Hunter'), 1):
            state = apply_replay_event(state, resolve(state, (2+2*count)*SECOND, nick)).state
        self.assertIsNone(state.flight)
        self.assertEqual(state.player('hunter').misses, 2)
        self.assertEqual(state.player('other').misses, 1)

    def test_super_and_mechanical_ducks_survive_five_misses(self):
        for kind in (FlightKind.GOLDEN, FlightKind.MECHANICAL):
            state = flying(item=4, kind=kind)
            for count in range(1, 6):
                state = apply_replay_event(state, resolve(state, (2+2*count)*SECOND)).state
                self.assertIsNotNone(state.flight)
            self.assertEqual(state.flight.noisy_misses, 5)

    def test_silencer_preserves_existing_count_until_it_expires(self):
        state = flying()
        state = apply_replay_event(state, resolve(state, 4*SECOND)).state
        state = purchase(state, 'Hunter', 9, 5*SECOND).state
        for count in range(3):
            state = apply_replay_event(state, resolve(state, (6+2*count)*SECOND)).state
        self.assertEqual(state.flight.noisy_misses, 1)
        state = replace(state, effects=())
        state = apply_replay_event(state, resolve(state, 12*SECOND)).state
        self.assertEqual(state.flight.noisy_misses, 2)
        state = apply_replay_event(state, resolve(state, 14*SECOND)).state
        self.assertIsNone(state.flight)

    def test_level_silent_weapon_does_not_count(self):
        state = flying(level=40)
        for count in range(1, 6):
            event = resolve(state, (2+2*count)*SECOND)
            self.assertIsNone(event.shot_attempt.noisy_miss_limit)
            state = apply_replay_event(state, event).state
        self.assertIsNone(state.flight.noisy_misses)

    def test_empty_jammed_and_throttled_commands_do_not_count(self):
        state = flying()
        state = apply_replay_event(state, resolve(state, 4*SECOND)).state
        for changes in ({'ammo':0}, {'jammed':True}):
            blocked = replace(state, players=(replace(state.players[0], **changes),))
            result = apply_replay_event(blocked, resolve(blocked, 6*SECOND))
            self.assertEqual(result.state.flight.noisy_misses, 1)
        # Runtime throttle rejects the next trigger before it reaches the engine.
        state = replace(state, players=(replace(state.players[0], ammo=0),))
        for _ in range(31):
            event = resolve(state, 4*SECOND)
            result = apply_replay_event(state, event)
            if any(o.kind is OutcomeKind.COMMAND_THROTTLED for o in result.outcomes):
                self.assertEqual(result.state.flight, state.flight)
                break
            state=result.state
        else:
            self.fail('runtime shot throttle was not exercised')

    def test_forced_incident_miss_counts_once(self):
        from pyduckhunt.game.model import IncidentAttempt, IncidentTargetAttempt
        incident = IncidentAttempt((IncidentTargetAttempt('Other', armor_roll=10000,
                                                        deflection_roll=10000),))
        state = flying()
        event = resolve(state, 4*SECOND, hit=True, incident=lambda *args: incident)
        result = apply_replay_event(state, event)
        self.assertEqual(result.state.flight.noisy_misses, 1)

    def test_hit_and_new_flight_preserve_or_reset_counter(self):
        state = flying(kind=FlightKind.GOLDEN)
        state = apply_replay_event(state, resolve(state, 4*SECOND)).state
        state = apply_replay_event(state, resolve(state, 6*SECOND, hit=True)).state
        self.assertEqual(state.flight.noisy_misses, 1)
        state = start_flight(state, 303*SECOND, lifetime_ns=300*SECOND).state
        self.assertIsNone(state.flight.noisy_misses)

    def test_explosive_hit_keeps_boom_and_triple_damage(self):
        state = flying(item=4, kind=FlightKind.GOLDEN)
        result = apply_replay_event(state, resolve(state, 4*SECOND, hit=True))
        self.assertEqual(result.state.flight.health, 2)
        self.assertIn('*BOUM*', ' '.join(render_outcomes(result.outcomes)))
        self.assertEqual(result.state.effects, state.effects)

    def test_clover_bought_during_flight_awards_ten_plus_six_twice(self):
        state = flying(item=4)
        state = purchase(state, 'Hunter', 10, 3*SECOND, magnitude=6).state
        for now in (4*SECOND, 10*SECOND):
            before = state.players[0].experience
            result = apply_replay_event(state, resolve(state, now, hit=True))
            hit = next(o for o in result.outcomes if o.kind is OutcomeKind.HIT)
            self.assertEqual(hit.experience_awarded, 16)
            self.assertEqual(result.state.players[0].experience, before+16)
            self.assertIn('16 xp', ' '.join(render_outcomes(result.outcomes)))
            state = start_flight(result.state, now+SECOND, lifetime_ns=300*SECOND).state

    def test_scope_purchase_and_loot_are_concise(self):
        bought = purchase(funded(), 'Hunter', 7, SECOND, magnitude=11)
        found = apply_command(flying(), 'Hunter', SHOT, 4*SECOND,
            shot_attempt=ShotAttempt(loot=LootAward('targeting_scope', magnitude=11)))
        for result in (bought, found):
            text = ' '.join(render_outcomes(result.outcomes))
            self.assertIn('6 tirs', text)
            self.assertIn('+11 points', text)
            for forbidden in ('Bonus calculé', 'arrondi', '(100', '/ 3'):
                self.assertNotIn(forbidden, text)

    def test_legacy_events_and_state_keep_their_exact_encoding(self):
        state = flying()
        payload = encode_game_state(state)
        self.assertNotIn('noisy_misses', payload['flight'])
        self.assertEqual(encode_game_state(decode_game_state(payload, schema_version=22)), payload)
        for escape in (False, True):
            event = ReplayEvent.command(4*SECOND, 'Hunter', SHOT,
                shot_attempt=ShotAttempt(base_accuracy_bps=0, frighten_on_miss=escape))
            raw = event.to_payload()
            self.assertNotIn('noisy_miss_limit', raw['shot_attempt'])
            self.assertEqual(ReplayEvent.from_payload(raw).to_payload(), raw)
            result = apply_replay_event(state, event)
            if escape:
                self.assertIsNone(result.state.flight)
            else:
                self.assertIsNone(result.state.flight.noisy_misses)

    def test_counter_survives_journal_checkpoint_and_restart(self):
        state = flying(item=4)
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp);store=SnapshotStore(path/'snapshot.json');journal=JournalFile(path/'events.jsonl')
            store.write(Snapshot(0, GENESIS_DIGEST, state))
            # Existing schema 22 checkpoint remains authoritative.
            raw=json.loads(store.path.read_text());raw['schema']=22
            body = {key:value for key,value in raw.items() if key != 'checksum'}
            raw['checksum']=hashlib.sha256(canonical_json_bytes(body)).hexdigest()
            store.path.write_bytes(canonical_json_bytes(raw)+b'\n')
            for now in (4*SECOND, 6*SECOND):
                event=resolve(state, now);journal.append(event)
                state=apply_replay_event(state,event).state
            recovered=recover(store,journal)
            self.assertEqual(recovered.state,state)
            store.write(snapshot_from_result(recovered))
            self.assertEqual(recover(store,journal).state.flight.noisy_misses,2)
            event=resolve(state,8*SECOND);journal.append(event)
            self.assertIsNone(recover(store,journal).state.flight)

    def test_noise_fields_reject_malformed_inputs(self):
        state=apply_replay_event(flying(),resolve(flying(),4*SECOND)).state
        for bad in (None, True, -1, 1.0):
            raw=encode_game_state(state);raw['flight']['noisy_misses']=bad
            with self.assertRaises((ValueError, CodecError)):
                decode_game_state(raw)
        for bad in (None, True, 0, 101, 3.0):
            raw=resolve(flying(),4*SECOND).to_payload();raw['shot_attempt']['noisy_miss_limit']=bad
            with self.assertRaises((ValueError, CodecError)):
                ReplayEvent.from_payload(raw)
        with self.assertRaises(ValueError):
            ShotAttempt(noisy_miss_limit=3,frighten_on_miss=True)
        with self.assertRaises(CodecError):
            decode_game_state(encode_game_state(state),schema_version=22)
