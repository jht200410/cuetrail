"""Synthetic storage behavior, with all scratch paths kept inside this directory."""
from pathlib import Path
import json
import tempfile
import unittest
from cuetrail.experimental.ledger import Ledger,SourceMutation

RUN=Path(__file__).resolve().parent


def item(sid='s1',action='avoid peanuts',stamp=1,prefix='',role='user'):
    text=prefix+'When cooking, I must '+action+'.'
    source=dict(id=sid,content=text,role=role,session_id='session',timestamp=stamp)
    draft=dict(source_id=sid,kind='conditional_constraint',condition_quote='When cooking',scope_quote='cooking',
               action_quotes=[action],connecting_quote=text)
    return dict(source=source,draft=draft)


class Contracts(unittest.TestCase):
    def setUp(self):
        self.scratch=RUN/'.test-work';self.scratch.mkdir(exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=self.scratch)
        assert Path(self.temp.name).resolve().is_relative_to(self.scratch.resolve())
        self.path=Path(self.temp.name)/'procedures.sqlite3'
        self.ledger=Ledger(self.path)

    def tearDown(self):
        self.ledger.close()
        assert Path(self.temp.name).resolve().is_relative_to(self.scratch.resolve())
        self.temp.cleanup()

    def test_durable_roundtrip_preserves_exact_procedure_and_tuple_types(self):
        entry=item();original=self.ledger.record('user1',[entry],extraction_ref='receipt:1')[0]
        self.ledger.close();self.ledger=Ledger(self.path)
        loaded=self.ledger.visible('user1',['s1'])[0]
        self.assertEqual(loaded,original);self.assertIsInstance(loaded.action_quotes,tuple)
        self.assertEqual(self.ledger.audit('user1',lambda sid:entry['source'])['verified_derivations'],1)

    def test_repeated_proposal_never_promotes_or_increments_version(self):
        entry=item(role='assistant')
        for _ in range(20):self.ledger.record('user1',[entry],extraction_ref='receipt:repeat')
        self.assertEqual(self.ledger.visible('user1',['s1']),[])
        history=self.ledger.visible('user1',['s1'],historical=True)
        self.assertEqual(len(history),1);self.assertEqual(history[0].status,'unconfirmed')
        self.assertEqual(history[0].version,1)
        audit=self.ledger.audit('user1',lambda sid:entry['source'])
        self.assertEqual(audit['version_events'],1);self.assertEqual(audit['unconfirmed_proposals'],1)

    def test_namespace_isolation_even_for_identical_source_ids(self):
        a=item();b=item(action='use seeds')
        self.ledger.record('userA',[a],extraction_ref='a')
        self.ledger.record('userB',[b],extraction_ref='b')
        self.assertEqual(self.ledger.visible('userA',['s1'])[0].action_quotes,('avoid peanuts',))
        self.assertEqual(self.ledger.visible('userB',['s1'])[0].action_quotes,('use seeds',))
        self.assertEqual(self.ledger.visible('absent',['s1'],historical=True),[])

    def test_conflicts_across_requests_abstain_and_survive_restart(self):
        self.ledger.record('user1',[item()],extraction_ref='first')
        self.ledger.record('user1',[item('s2','use peanuts',2)],extraction_ref='second')
        self.ledger.close();self.ledger=Ledger(self.path)
        self.assertEqual(self.ledger.visible('user1',['s1','s2']),[])
        history=self.ledger.visible('user1',['s1','s2'],historical=True)
        self.assertTrue(all(p.status=='conflicting' for p in history))
        self.assertEqual([p.version for p in history],[1,2])

    def test_explicit_replacement_keeps_source_and_status_history(self):
        self.ledger.record('user1',[item()],extraction_ref='first')
        newer=item('s2','use seeds',2,'From now on, ')
        current=self.ledger.record('user1',[newer],extraction_ref='second')[0]
        self.assertEqual(current.version,2);self.assertTrue(current.supersedes_ids)
        history=self.ledger.visible('user1',['s1','s2'],historical=True)
        self.assertEqual([p.status for p in history],['superseded','source_grounded'])
        self.assertEqual(self.ledger.visible('user1',['s1']),[])
        self.assertEqual(self.ledger.visible('user1',['s2']),[current])
        events=self.ledger.db.execute('SELECT COUNT(*) FROM events WHERE namespace=?',('user1',)).fetchone()[0]
        self.assertEqual(events,3)

    def test_changed_source_rolls_back_whole_batch(self):
        self.ledger.record('user1',[item()],extraction_ref='first')
        with self.assertRaises(SourceMutation):
            self.ledger.record('user1',[item('new'),item(action='use seeds')],extraction_ref='rejected')
        self.assertEqual(self.ledger.visible('user1',['new'],historical=True),[])
        self.assertEqual(len(self.ledger.visible('user1',['s1'])),1)

    def test_invalid_quote_never_enters_ledger(self):
        bad=item();bad['draft']['action_quotes']=['use peanuts']
        with self.assertRaises(ValueError):self.ledger.record('user1',[bad],extraction_ref='bad')
        self.assertEqual(self.ledger.visible('user1',['s1'],historical=True),[])

    def test_model_kind_switch_cannot_create_personal_routine(self):
        text='Whenever a student finishes, the teacher first checks the work, then closes the file.'
        source=dict(id='third-party',role='user',content=text,session_id='s',timestamp=1)
        draft=dict(source_id='third-party',kind='ordered_procedure',condition_quote='Whenever a student finishes',
                   scope_quote='student',action_quotes=['checks the work','closes the file'],connecting_quote=text)
        with self.assertRaises(ValueError):self.ledger.record('user1',[dict(source=source,draft=draft)],extraction_ref='rejected')

    def test_nested_action_quotes_cannot_masquerade_as_two_steps(self):
        text='When cooking, I always check the labels.'
        source=dict(id='overlap',role='user',content=text,session_id='s',timestamp=1)
        draft=dict(source_id='overlap',kind='ordered_procedure',condition_quote='When cooking',
                   scope_quote='cooking',action_quotes=['check the labels','the labels'],connecting_quote=text)
        with self.assertRaisesRegex(ValueError,'overlapping_action_quotes'):
            self.ledger.record('user1',[dict(source=source,draft=draft)],extraction_ref='synthetic:overlap')

    def test_unordered_habit_cannot_claim_explicit_step_order(self):
        text='When cooking, I always check the labels and wash hands.'
        source=dict(id='unordered',role='user',content=text,session_id='s',timestamp=1)
        draft=dict(source_id='unordered',kind='ordered_procedure',condition_quote='When cooking',
                   scope_quote='cooking',action_quotes=['check the labels','wash hands'],connecting_quote=text)
        with self.assertRaisesRegex(ValueError,'ordered_steps_not_explicit'):
            self.ledger.record('user1',[dict(source=source,draft=draft)],extraction_ref='synthetic:unordered')

    def test_relation_offsets_and_changed_source_audit(self):
        entry=item();entry['source']['content']='Other paragraph.\n\n'+entry['source']['content']
        entry['source']['window_start']=18
        entry['source']['window_content']=entry['source']['content'][18:]
        self.ledger.record('user1',[entry],extraction_ref='window')
        canonical={k:v for k,v in entry['source'].items() if not k.startswith('window_')}
        self.assertTrue(self.ledger.audit('user1',lambda sid:canonical)['source_fidelity_verified'])
        modified={**canonical,'content':canonical['content'].replace('peanuts','walnuts')}
        with self.assertRaises(SourceMutation):self.ledger.audit('user1',lambda sid:modified)

    def test_visibility_requires_bounded_native_source_ids(self):
        self.ledger.record('user1',[item()],extraction_ref='first')
        self.assertEqual(self.ledger.visible('user1',[]),[])
        with self.assertRaises(ValueError):self.ledger.visible('user1',[str(i) for i in range(33)])

    def test_different_named_people_never_share_a_version_chain(self):
        jordan=item(prefix='Jordan: ')
        alex=item('alex','use seeds',2,'Alex: From now on, ')
        self.ledger.record('conversation',[jordan],extraction_ref='jordan')
        self.ledger.record('conversation',[alex],extraction_ref='alex')
        visible=self.ledger.visible('conversation',['s1','alex'])
        self.assertEqual(len(visible),2);self.assertTrue(all(p.version==1 for p in visible))
        self.assertTrue(all(not p.supersedes_ids for p in visible))

    def test_unknown_validator_contract_requires_explicit_migration(self):
        self.ledger.db.execute('UPDATE metadata SET value=? WHERE key=?',('unknown-contract','contract'))
        self.ledger.db.commit()
        with self.assertRaises(ValueError):Ledger(self.path)

    def test_audit_detects_version_projection_corruption(self):
        entry=item();p=self.ledger.record('user1',[entry],extraction_ref='first')[0]
        row=self.ledger.db.execute('SELECT value_json FROM procedures WHERE namespace=? AND id=?',('user1',p.id)).fetchone()
        changed=json.loads(row[0]);changed['version']=999
        self.ledger.db.execute('UPDATE procedures SET value_json=? WHERE namespace=? AND id=?',(json.dumps(changed),'user1',p.id))
        self.ledger.db.commit()
        with self.assertRaises(SourceMutation):self.ledger.audit('user1',lambda sid:entry['source'])

    def versioned_sources(self):
        first=item();second=item('s2','use seeds',2,'From now on, ')
        self.ledger.record('user1',[first],extraction_ref='first')
        self.ledger.record('user1',[second],extraction_ref='second')
        return {x['source']['id']:x['source'] for x in (first,second)}

    def test_event_replay_detects_changed_nonfinal_transition(self):
        sources=self.versioned_sources()
        seq,value=self.ledger.db.execute('SELECT seq,new_json FROM events ORDER BY seq LIMIT 1').fetchone()
        changed=json.loads(value);changed['version']=999
        self.ledger.db.execute('UPDATE events SET new_json=? WHERE seq=?',(json.dumps(changed),seq))
        self.ledger.db.commit()
        with self.assertRaisesRegex(SourceMutation,'disconnected'):
            self.ledger.audit('user1',sources.__getitem__)

    def test_event_replay_detects_missing_original_transition(self):
        sources=self.versioned_sources()
        self.ledger.db.execute('DELETE FROM events WHERE seq=(SELECT MIN(seq) FROM events)')
        self.ledger.db.commit()
        with self.assertRaisesRegex(SourceMutation,'disconnected'):
            self.ledger.audit('user1',sources.__getitem__)

    def test_canonical_source_identity_table_is_part_of_audit(self):
        entry=item();self.ledger.record('user1',[entry],extraction_ref='first')
        self.ledger.db.execute('UPDATE sources SET identity_json=?',('{}',));self.ledger.db.commit()
        with self.assertRaisesRegex(SourceMutation,'identity'):
            self.ledger.audit('user1',lambda sid:entry['source'])

    def test_receipt_references_cannot_disappear_from_audit(self):
        entry=item();self.ledger.record('user1',[entry],extraction_ref='first')
        self.ledger.db.execute('UPDATE derivations SET extraction_ref=?',('',));self.ledger.db.commit()
        with self.assertRaisesRegex(SourceMutation,'receipt'):
            self.ledger.audit('user1',lambda sid:entry['source'])

    def test_verified_snapshot_preserves_native_scope_and_version(self):
        sources=self.versioned_sources()
        values,audit=self.ledger.verified_visible('user1',['s2'],sources.__getitem__)
        self.assertEqual(len(values),1);self.assertEqual(values[0].source_id,'s2')
        self.assertEqual(values[0].version,2);self.assertTrue(audit['event_replay_verified'])
        self.assertTrue(audit['source_identity_verified'])
        self.assertEqual(self.ledger.verified_visible('user1',[],sources.__getitem__),([],None))

    def test_verified_snapshot_rejects_changed_source_before_returning_steps(self):
        entry=item();self.ledger.record('user1',[entry],extraction_ref='first')
        changed={**entry['source'],'content':'When cooking, I must use peanuts.'}
        with self.assertRaises(SourceMutation):
            self.ledger.verified_visible('user1',['s1'],lambda sid:changed)
        self.assertFalse(self.ledger.db.in_transaction)

    def test_open_contract_change_cannot_be_ignored_by_visibility(self):
        self.ledger.db.execute('DELETE FROM metadata WHERE key=?',('contract',));self.ledger.db.commit()
        with self.assertRaisesRegex(SourceMutation,'contract'):
            self.ledger.visible('user1',['s1'])

    def test_verified_snapshot_checks_native_bound_before_source_reads(self):
        calls=[]
        with self.assertRaises(ValueError):
            self.ledger.verified_visible('user1',[str(i) for i in range(33)],calls.append)
        self.assertEqual(calls,[])

    def test_query_snapshot_never_loads_unretrieved_canonical_sources(self):
        first=item();other=item('travel','keep tickets',2)
        other['source']['content']=other['source']['content'].replace('cooking','traveling')
        other['draft'].update(condition_quote='When traveling',scope_quote='traveling',connecting_quote=other['source']['content'])
        self.ledger.record('user1',[first,other],extraction_ref='synthetic:topics')
        calls=[]
        def load(sid):
            calls.append(sid)
            if sid!='s1':raise AssertionError('Unretrieved source must not be loaded')
            return first['source']
        values,audit=self.ledger.verified_visible('user1',['s1'],load)
        self.assertEqual([p.source_id for p in values],['s1']);self.assertEqual(calls,['s1'])
        self.assertEqual(audit['verified_derivations'],1);self.assertEqual(audit['metadata_derivations_replayed'],2)
        self.assertFalse(audit['all_namespace_sources_verified'])

    def test_unretrieved_replacement_still_suppresses_obsolete_rule(self):
        sources=self.versioned_sources();calls=[]
        def load(sid):
            calls.append(sid)
            if sid!='s1':raise AssertionError('Replacement text is not in native query scope')
            return sources[sid]
        values,audit=self.ledger.verified_visible('user1',['s1'],load)
        self.assertEqual(values,[]);self.assertEqual(calls,['s1'])
        self.assertTrue(audit['event_replay_verified']);self.assertFalse(audit['all_namespace_sources_verified'])


if __name__=='__main__':unittest.main(verbosity=2)
