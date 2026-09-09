"""Real bilingual rendering, isolation, wire routing and journal parity."""
from __future__ import annotations

import ast
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from string import Formatter
import tempfile
import tomllib
import unittest

from pyduckhunt.configuration import load_application_configuration, parse_application_configuration
from pyduckhunt.game.commands import parse_command
from pyduckhunt.game.level_policy import level_policy
from pyduckhunt.game.model import GameState, Outcome, OutcomeKind, PlayerState, FlightKind
from pyduckhunt.i18n import current_language, language_context, localized, tr
from pyduckhunt.messages_en import EN
from pyduckhunt.irc import parse_irc_line
from pyduckhunt.persistence import JournalFile, SnapshotStore
from pyduckhunt.publishing.ranking_page import render_ranking_page, RankingPagePublisher
from pyduckhunt.rendering import render_inventory, render_outcome, render_profile, render_query, render_wire_notice
from pyduckhunt.rendering.flight_appearance import FLIGHT_CALLS, FLIGHT_LINES, FlightAppearance
from pyduckhunt.runtime import IRCGameBridge, RuntimeOrchestrator, RuntimeSchedulingAdapter, CalibratedScheduleSource
from pyduckhunt.time_format import format_duration_ns
from tests.unit.test_runtime_application import resolved_event

ROOT = Path(__file__).resolve().parents[2]


class BilingualTests(unittest.TestCase):
    def setUp(self):
        self.player = PlayerState(key='hunter', nickname='Hunter', level=9, hits=58,
                                  fatigue_centi=1800, experience=30)
        self.state = GameState(players=(self.player,))

    def test_language_is_optional_and_strict(self):
        data = tomllib.loads((ROOT/'config/pyduckhunt.example.toml').read_text())
        del data['game']['language']
        self.assertEqual(parse_application_configuration(data).game.language, 'fr')
        for language in ('fr','en'):
            data['game']['language'] = language
            self.assertEqual(parse_application_configuration(data).game.language, language)
        for language in ('de','EN','',True,1,None):
            data['game']['language'] = language
            with self.assertRaises(ValueError): parse_application_configuration(data)

    def test_catalogue_preserves_every_template_field_and_format(self):
        def fields(text):
            return Counter((field,spec,conv) for _,field,spec,conv in Formatter().parse(text)
                           if field is not None)
        for source, target in EN.items():
            with self.subTest(source=source[:75]):
                self.assertIsInstance(target,str)
                self.assertTrue(target)
                if '{0' in source: self.assertEqual(fields(source),fields(target))

    def test_every_literal_translation_call_is_present(self):
        missing=[]
        for path in (ROOT/'src/pyduckhunt').rglob('*.py'):
            if path.name=='messages_en.py': continue
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id=='tr':
                    if node.args and isinstance(node.args[0],ast.Constant):
                        key=node.args[0].value
                        if isinstance(key,str) and key not in EN: missing.append((path.name,key))
        self.assertEqual(missing,[])

    def test_default_french_survives_english_render(self):
        original=render_profile(self.state,'Hunter')
        en=render_profile(self.state,'Hunter',language='en')
        self.assertIn('[Profile]',en[0]); self.assertIn('[Hunting record]',en[1])
        self.assertIn('[tired]',en[0]); self.assertIn('58 ducks',en[1])
        self.assertEqual(render_profile(self.state,'Hunter'),original)
        self.assertEqual(render_profile(self.state,'Hunter',language='fr'),original)
        self.assertEqual(current_language(),'fr')

    def test_context_resets_after_failure_and_nested_render(self):
        @localized
        def fail():
            self.assertEqual(current_language(),'en')
            raise RuntimeError('test')
        with self.assertRaises(RuntimeError): fail(language='en')
        self.assertEqual(current_language(),'fr')
        with language_context('en'):
            self.assertIn('[Profil]',render_profile(self.state,'Hunter',language='fr')[0])
            self.assertEqual(current_language(),'en')
        self.assertEqual(current_language(),'fr')

    def test_threads_do_not_share_language(self):
        def run(language):
            return [render_profile(self.state,'Hunter',language=language)[0] for _ in range(20)]
        with ThreadPoolExecutor(max_workers=2) as pool:
            fr,en=list(pool.map(run,('fr','en')))
        self.assertTrue(all('[Profil]' in text for text in fr))
        self.assertTrue(all('[Profile]' in text for text in en))

    def test_dynamic_names_urls_and_targets_are_not_translated(self):
        player=replace(self.player,key='canard',nickname='canard')
        state=replace(self.state,players=(player,))
        message=render_outcome(Outcome(OutcomeKind.HIT,actor='canard',player=player),language='en')[0]
        self.assertTrue(message.startswith('canard > '))
        wires=render_wire_notice('canard',render_inventory(state,'canard',language='en'))
        self.assertTrue(all(wire.startswith(b'NOTICE canard :') for wire in wires))
        from pyduckhunt.rendering import render_shop
        url='https://example.test/canard/pain/'
        self.assertIn(url,render_shop(url,language='en')[0])

    def test_all_flight_lines_have_english_renderings(self):
        for utterance in (*FLIGHT_LINES,*FLIGHT_CALLS):
            with self.subTest(utterance=utterance):
                appearance=FlightAppearance('trail','\\_O<',utterance)
                line=render_outcome(Outcome(OutcomeKind.FLIGHT_STARTED),flight_appearance=appearance,language='en')[0]
                self.assertIn(EN.get(utterance,utterance),line)
                self.assertNotRegex(line,r'\b(?:canarde|tirez|sifflote|COIN|COUAC)\b')

    def test_every_outcome_and_shop_item_renders_in_english(self):
        for kind in OutcomeKind:
            outcome=Outcome(kind,actor='Hunter',player=self.player,item_id=21,
                            notice_emitted=True,channel_effect_count=2,loot_key='xp_20')
            with self.subTest(kind=kind):
                lines=render_outcome(outcome,channel='#duckhunt-en',language='en')
                self.assertTrue(all(isinstance(line,str) for line in lines))
                self.assertNotRegex(' '.join(lines),r'\b(?:canard|canards|Tu|Ton|Tes|Achat|raté|arme|Chasseur|fouillant)\b')
                for wire in render_wire_notice('Hunter',lines): self.assertLessEqual(len(wire),512)
        for item_id in range(1,32):
            with self.subTest(item=item_id):
                line=render_outcome(Outcome(OutcomeKind.SHOP_PURCHASED,actor='Hunter',player=self.player,
                   item_id=item_id,charged_experience=4,effect_magnitude=(6 if item_id==10 else 20 if item_id==21 else 11),channel_effect_count=2),
                   channel='#duckhunt-en',language='en')[0]
                self.assertNotRegex(line,r'\b(?:Tu|Ton|morceau|munitions|lunette|thermos de café|trèfle)\b')

    def test_english_weapon_and_level_labels_at_every_level(self):
        for level in range(1,101):
            with self.subTest(level=level):
                player=replace(self.player,level=level,experience=0)
                state=replace(self.state,players=(player,))
                inventory=render_inventory(state,'Hunter',language='en')[0]
                self.assertIn(EN[level_policy(level).weapon_label],inventory)
                self.assertNotRegex(render_profile(state,'Hunter',language='en')[0],r'chasseur|canards|déplumeur')

    def test_durations_use_english_units_without_changing_values(self):
        self.assertEqual(format_duration_ns(3661000000000),'1h01mn01s')
        self.assertEqual(format_duration_ns(3661000000000,language='en'),'1h01m01s')

    def test_paid_bread_and_call_do_not_disclose_clock(self):
        for item in (20,21):
            text=render_outcome(Outcome(OutcomeKind.SHOP_PURCHASED,actor='Hunter',player=self.player,
                item_id=item,charged_experience=4,channel_effect_count=2,due_at_ns=1726000000000000000),
                channel='#duckhunt-en',language='en')[0]
            self.assertNotIn('1726000000',text)
            self.assertNotIn('UTC',text)
            self.assertNotIn('CEST',text)
        self.assertIn('stays in place',render_outcome(Outcome(OutcomeKind.SHOP_PURCHASED,
            actor='Hunter',player=self.player,item_id=21,channel_effect_count=2,effect_magnitude=20),language='en')[0])

    def test_ranking_page_and_background_publisher_use_instance_language(self):
        french=render_ranking_page(self.state)
        english=render_ranking_page(self.state,language='en')
        self.assertIn(b'lang="en"',english);self.assertIn(b'Hunter <em>rankings.',english)
        self.assertIn(b'lang="fr"',french); self.assertEqual(render_ranking_page(self.state),french)
        self.assertNotIn('Afficher l’inventaire'.encode(),english)
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'rank.html'
            publisher=RankingPagePublisher(p,language='en')
            with ThreadPoolExecutor(max_workers=1) as pool:pool.submit(publisher.publish,self.state).result()
            self.assertEqual(p.read_bytes(),english)

    def test_two_live_bridges_keep_identical_state_and_journal(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtimes=[];outputs=[]
            try:
                for language in ('fr','en'):
                    root=Path(tmp)/language;root.mkdir();batches=[]
                    runtime,_=RuntimeOrchestrator.open(JournalFile(root/'events.jsonl'),SnapshotStore(root/'snapshot.json'),batches.append,snapshot_interval=None)
                    runtimes.append(runtime)
                    bridge=IRCGameBridge(runtime,('#duckhunt-en',),resolved_event,language=language)
                    for now,command in enumerate(('!duckstats','!inventory','!shop','!shop 999','!reload'),start=1):
                        result=bridge.handle(now,parse_irc_line(':Hunter!u@test PRIVMSG #duckhunt-en :'+command))
                        if result.dispatch and result.dispatch.persistence_ticket:result.dispatch.persistence_ticket.wait(2)
                    outputs.append(batches)
                self.assertEqual(runtimes[0].state,runtimes[1].state)
                self.assertEqual((Path(tmp)/'fr/events.jsonl').read_bytes(),(Path(tmp)/'en/events.jsonl').read_bytes())
                self.assertIn(b'[Profil]',outputs[0][0][0]);self.assertIn(b'[Profile]',outputs[1][0][0])
                for batches in outputs:
                    self.assertTrue(all(wire.startswith(b'NOTICE Hunter :') for batch in batches[:3] for wire in batch))
            finally:
                for runtime in runtimes:runtime.close(2)

    def test_english_owner_planning_items_and_automatic_partyline_remain_private(self):
        from tests.unit.test_partyline_runtime import PartylineRuntimeTests, drain
        from pyduckhunt.persistence import ReplayEvent
        fixture = PartylineRuntimeTests('runTest')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.controller.language = 'en'
        fixture.runtime.dispatch(ReplayEvent.enable_hourly_bread(0), lambda _: ())
        dcc = fixture._bootstrap_over_offered_dcc('isolated bilingual test password')
        start = len(fixture.wires)
        for now, command in enumerate(('!pain', '!appeau', '!duckplanning'), 20):
            fixture.controller.handle_irc(now, parse_irc_line(
                '@account=Operator :ChangedNick!u@host PRIVMSG #marsh :' + command), 'Coin')
        wires = [wire for batch in fixture.wires[start:] for wire in batch]
        self.assertTrue(wires)
        self.assertTrue(all(wire.startswith(b'NOTICE ChangedNick :') for wire in wires))
        text = b' '.join(wires)
        self.assertIn(b'bread', text)
        self.assertIn(b'duck call', text)
        self.assertIn(b'Flights 01-06', text)
        self.assertNotIn(b'Prochain quotidien', text)
        before = len(fixture.wires)
        fixture.controller.handle_irc(23, parse_irc_line(
            '@account=Other :ChangedNick!u@host PRIVMSG #marsh :!duckplanning'), 'Coin')
        self.assertEqual(len(fixture.wires), before)
        dcc.sendall(b'.duckplanning\n')
        fixture._poll_twice(24)
        self.assertIn(b'Flights 01-06', drain(dcc))
        fixture.controller.observe_runtime('DUCKPLANNING reason=channel-items-change actions=1 bread=1')
        fixture._poll_twice(25)
        automatic = drain(dcc)
        self.assertIn(b'duckplanning changed', automatic)
        self.assertIn(b'Flights 01-06', automatic)
        self.assertEqual(len(fixture.wires), before)

    def test_paid_items_and_scheduled_flights_keep_identical_state_and_entropy(self):
        from pyduckhunt.persistence import Snapshot, ReplayEvent
        from pyduckhunt.persistence.journal import GENESIS_DIGEST
        from pyduckhunt.runtime import CalibratedEventResolver
        from tests.unit.test_runtime_scheduling_adapter import SequenceIntegerSource
        with tempfile.TemporaryDirectory() as tmp:
            results = []
            for language in ('fr', 'en'):
                root = Path(tmp) / language
                root.mkdir()
                player = replace(self.player, experience=90, fatigue_centi=0)
                store = SnapshotStore(root / 'snapshot.json')
                store.write(Snapshot(0, GENESIS_DIGEST, GameState(players=(player,))))
                batches = []
                runtime, _ = RuntimeOrchestrator.open(JournalFile(root/'events.jsonl'), store,
                                                      batches.append, snapshot_interval=None)
                try:
                    entropy = SequenceIntegerSource()
                    adapter = RuntimeSchedulingAdapter(runtime, ('#duckhunt-en',),
                        CalibratedScheduleSource(entropy), language=language)
                    adapter.step(0)
                    bridge = IRCGameBridge(runtime, ('#duckhunt-en',),
                        CalibratedEventResolver(entropy, lambda *_: True), language=language)
                    for now, command in enumerate(('!shop 21', '!shop 20'), 1):
                        bridge.handle(now, parse_irc_line(':Hunter!u@host PRIVMSG #duckhunt-en :' + command))
                    self.assertTrue(any(e.item_id == 21 for e in runtime.state.effects))
                    self.assertTrue(any(a.item_id == 20 for a in runtime.state.scheduled_actions))
                    due = runtime.state.scheduled_actions[0].due_at_ns
                    adapter.step(due)
                    self.assertIsNotNone(runtime.state.flight)
                    runtime.persistence.flush(2)
                    results.append((runtime.state, entropy.calls,
                                    (root/'events.jsonl').read_bytes(), batches))
                finally:
                    runtime.close(2)
            self.assertEqual(results[0][:3], results[1][:3])
            english = b' '.join(wire for batch in results[1][3] for wire in batch)
            self.assertIn(b'bread', english)
            self.assertIn(b'duck call', english)
            self.assertNotIn(b'Tu ach', english)


if __name__=='__main__':unittest.main()
