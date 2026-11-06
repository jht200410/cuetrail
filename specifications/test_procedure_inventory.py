"""Synthetic complete-inventory, authority, concurrency and storage contracts."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from cuetrail_governance import inventory as i

p, h, w = i.p, i.h, i.w
TEXT = '每当我询问「恢复检查」时，请始终先核对备份，不要删除副本，除非恢复验证全部通过。'
QUERY = '请按既定程序处理「恢复检查」。'
HISTORY = '回顾我关于「恢复检查」的程序。'


class InventoryContracts(unittest.TestCase):
    def setUp(self):
        self.folder = TemporaryDirectory(dir=Path(__file__).resolve().parent)
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name)/'procedures.sqlite3'
        self.store = i.Inventory(self.path)
        self.direct = p.Source('direct','synthetic','u1','s1','user',TEXT,10)
        self.proposal = replace(self.direct,id='proposal',role='assistant',timestamp=11)
        self.confirm = replace(self.direct,id='confirm',session_id='s2',content=h.PREFIX+TEXT,timestamp=20)
        self.withdrawal = replace(self.direct,id='withdrawal',session_id='s3',content=w.PREFIX+TEXT,timestamp=30)

    def choose(self, query=QUERY, store=None, namespace='synthetic', subject='u1', request='r1'):
        return (store or self.store).select(query,namespace=namespace,subject_id=subject,request_id=request)

    def render(self,receipt,query=QUERY,store=None,namespace='synthetic',subject='u1',request='r1',**kwargs):
        return (store or self.store).render(receipt,query,namespace=namespace,subject_id=subject,request_id=request,**kwargs)

    def test_exact_duplicate_add_is_idempotent_and_projection_stable(self):
        self.assertEqual(self.store.add(self.direct),dict(added=True,idempotent=False))
        receipt, audit = self.choose()
        self.assertEqual(audit['inventory']['canonical_sources'],1)
        self.assertEqual(self.store.add(self.direct),dict(added=False,idempotent=True))
        self.assertEqual(self.choose()[0],receipt)

    def test_changed_source_identity_fields_rejected_without_mutation(self):
        self.store.add(self.direct)
        old,_ = self.choose()
        for changed in (replace(self.direct,content=TEXT.replace('不要','可以')),replace(self.direct,session_id='changed'),
                        replace(self.direct,role='assistant'),replace(self.direct,timestamp=12)):
            with self.assertRaises(i.SourceConflict):
                self.store.add(changed)
        self.assertEqual(self.choose()[0],old)
        self.assertTrue(self.render(old)[1]['accepted'])

    def test_typed_roles_timestamps_and_bounded_source_required(self):
        for source in (dict(id='fake'),replace(self.direct,role='external'),replace(self.direct,timestamp=True),
                       replace(self.direct,id=''),replace(self.direct,session_id=''),replace(self.direct,content='x'*64001)):
            with self.assertRaises(i.SourceIntegrityError):
                self.store.add(source)
        self.assertFalse(self.choose()[1]['accepted'])

    def test_withdrawal_auto_discovered_without_supplied_subset(self):
        self.store.add(self.direct)
        old,_ = self.choose()
        self.store.add(self.withdrawal)
        current,audit = self.choose()
        self.assertFalse(audit['accepted'])
        self.assertEqual(audit['inventory']['withdrawals'],1)
        self.assertEqual(current.procedure_receipt.selected,())
        self.assertEqual(self.render(old)[0],'')
        self.assertTrue(audit['inventory']['complete_within_stored_partition'])
        self.assertFalse(audit['inventory']['external_corpus_completeness_proven'])

    def test_entire_partition_confirmation_and_withdrawal_joins(self):
        for source in (self.proposal,self.confirm,self.withdrawal):
            self.store.add(source)
        receipt,audit = self.choose()
        self.assertFalse(audit['accepted'])
        self.assertEqual(audit['inventory']['confirmed_programs'],1)
        self.assertEqual(audit['inventory']['withdrawals'],1)
        self.assertEqual(audit['inventory']['uncompiled_source_ids'],[])
        self.assertFalse(receipt.procedure_receipt.executes_steps)

    def test_unconfirmed_assistant_advice_never_applicable(self):
        self.store.add(self.proposal)
        receipt,audit = self.choose()
        self.assertFalse(audit['accepted'])
        self.assertEqual(audit['inventory']['confirmed_programs'],0)
        self.assertFalse(receipt.procedure_receipt.adopts_long_term_rule)

    def test_unknown_or_earlier_confirmation_never_creates_authority(self):
        for timestamp in (None,True,5,11):
            with self.subTest(timestamp=timestamp):
                path=Path(self.folder.name)/f'unknown-{timestamp}.sqlite3'
                store=i.Inventory(path)
                store.add(self.proposal)
                if timestamp is True:
                    with self.assertRaises(i.SourceIntegrityError):
                        store.add(replace(self.confirm,timestamp=timestamp))
                    continue
                store.add(replace(self.confirm,timestamp=timestamp))
                _,audit=self.choose(store=store)
                self.assertFalse(audit['accepted'])
                self.assertEqual(audit['inventory']['uncompiled_source_ids'],['confirm'])

    def test_habit_withdrawal_after_proposal_before_confirmation_is_uncompiled(self):
        for source in (self.proposal,self.confirm,replace(self.withdrawal,timestamp=15)):
            self.store.add(source)
        receipt,audit = self.choose()
        self.assertTrue(audit['accepted'])
        self.assertEqual(audit['inventory']['withdrawals'],0)
        self.assertEqual(audit['inventory']['uncompiled_source_ids'],['withdrawal'])
        self.assertEqual(receipt.procedure_receipt.selected[0][0],'confirmed_habit')

    def test_role_boundary_cannot_withdraw_another_users_authority(self):
        for source in (self.direct,replace(self.withdrawal,role='assistant'),replace(self.withdrawal,id='u2-withdrawal',subject_id='u2')):
            self.store.add(source)
        receipt,audit = self.choose()
        self.assertTrue(audit['accepted'])
        self.assertEqual(audit['inventory']['canonical_sources'],2)
        self.assertEqual(audit['inventory']['withdrawals'],0)
        self.assertTrue(self.render(receipt)[1]['accepted'])

    def test_same_source_id_separate_users_and_namespaces_do_not_invalidate_or_leak(self):
        self.store.add(self.direct)
        old,_ = self.choose()
        for foreign in (replace(self.direct,subject_id='u2',content='foreign-user-secret'),
                        replace(self.direct,namespace='other',content='foreign-namespace-secret')):
            self.store.add(foreign)
        self.assertEqual(self.choose()[0],old)
        text,audit = self.render(old)
        self.assertTrue(audit['accepted'])
        self.assertNotIn('secret',text)
        self.assertEqual(audit['inventory']['canonical_sources'],1)
        self.assertFalse(self.choose(subject='u2')[1]['accepted'])

    def test_new_unsupported_source_still_invalidates_same_partition_receipt(self):
        self.store.add(self.direct)
        old,_ = self.choose()
        self.store.add(replace(self.direct,id='raw',content='这是普通叙述，不是长期规则。'))
        self.assertEqual(self.render(old)[0],'')
        fresh,audit = self.choose()
        self.assertTrue(audit['accepted'])
        self.assertEqual(audit['inventory']['uncompiled_source_ids'],['raw'])
        self.assertNotEqual(old.partition_sha256,fresh.partition_sha256)

    def test_conflict_and_explicit_withdrawal_recomputed_from_all_sources(self):
        alternate = replace(self.direct,id='alternate',timestamp=12,content=TEXT.replace('核对备份','检查恢复日志'))
        for source in (self.direct,alternate):
            self.store.add(source)
        old,audit = self.choose()
        self.assertFalse(audit['accepted'])
        self.store.add(self.withdrawal)
        current,audit = self.choose()
        self.assertTrue(audit['accepted'])
        text,_ = self.render(current)
        card = json.loads(text)[0]
        self.assertEqual(card['evidence']['source']['id'],'alternate')
        self.assertEqual(card['evidence']['status'],'source_grounded')
        self.assertEqual(self.render(old)[0],'')

    def test_later_new_explicit_authority_is_not_removed_by_earlier_withdrawal(self):
        for source in (self.direct,self.withdrawal,replace(self.direct,id='later',timestamp=40)):
            self.store.add(source)
        current,audit = self.choose()
        self.assertTrue(audit['accepted'])
        self.assertEqual(audit['inventory']['withdrawals'],1)
        card=json.loads(self.render(current)[0])[0]
        self.assertEqual(card['evidence']['source']['id'],'later')

    def test_one_time_and_short_agreement_do_not_become_recurring(self):
        for source in (replace(self.direct,content='这次我询问「恢复检查」时，请检查备份。'),self.proposal,
                       replace(self.confirm,content='好的，以后照旧。')):
            self.store.add(source)
        _,audit = self.choose()
        self.assertFalse(audit['accepted'])
        self.assertEqual(audit['inventory']['confirmed_programs'],0)

    def test_full_withdrawal_history_retains_original_and_withdrawal(self):
        for source in (self.direct,self.withdrawal):
            self.store.add(source)
        receipt,audit = self.choose(HISTORY)
        text,result = self.render(receipt,HISTORY)
        self.assertTrue(audit['accepted'] and result['accepted'])
        card=json.loads(text)[0]
        self.assertEqual(card['evidence']['source']['content'],TEXT)
        self.assertEqual(card['withdrawals'][0]['source']['content'],w.PREFIX+TEXT)
        self.assertEqual(card['applicability'],'withdrawn')

    def test_reopen_same_store_rebuilds_same_receipt_from_raw_sources(self):
        for source in (self.proposal,self.confirm):
            self.store.add(source)
        original,_=self.choose()
        reopened=i.Inventory(self.path)
        self.assertEqual(reopened.store_id,self.store.store_id)
        self.assertEqual(self.choose(store=reopened)[0],original)
        self.assertTrue(self.render(original,store=reopened)[1]['accepted'])

    def test_another_client_append_invalidates_cached_selection(self):
        self.store.add(self.direct)
        old,_=self.choose()
        other=i.Inventory(self.path)
        other.add(self.withdrawal)
        self.assertEqual(self.render(old)[0],'')
        self.assertFalse(self.choose()[1]['accepted'])

    def test_concurrent_idempotent_writers_record_one_source(self):
        def add(_):
            return i.Inventory(self.path).add(self.direct)
        with ThreadPoolExecutor(max_workers=8) as pool:
            results=list(pool.map(add,range(8)))
        self.assertEqual(sum(v['added'] for v in results),1)
        self.assertEqual(self.choose()[1]['inventory']['canonical_sources'],1)

    def test_concurrent_conflicting_same_identity_cannot_overwrite(self):
        alternate=replace(self.direct,content=TEXT.replace('核对备份','检查恢复日志'))
        def add(source):
            try:
                return i.Inventory(self.path).add(source)['added']
            except i.SourceConflict:
                return 'conflict'
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(add,[self.direct,alternate]))
        self.assertEqual(results.count(True),1)
        self.assertEqual(results.count('conflict'),1)
        self.assertEqual(self.choose()[1]['inventory']['canonical_sources'],1)

    def test_canonical_body_corruption_blocks_cached_and_fresh_selection(self):
        self.store.add(self.direct)
        old,_=self.choose()
        with closing(sqlite3.connect(self.path)) as db, db:
            body=json.loads(db.execute('select body from procedure_sources').fetchone()[0])
            body['content']=body['content'].replace('不要','可以')
            db.execute('update procedure_sources set body=?',(json.dumps(body,ensure_ascii=False,sort_keys=True),))
        self.assertEqual(self.render(old)[0],'')
        self.assertIsNone(self.choose()[0])

    def test_duplicate_json_or_noncanonical_serialization_rejected(self):
        self.store.add(self.direct)
        old,_=self.choose()
        with closing(sqlite3.connect(self.path)) as db, db:
            body=db.execute('select body from procedure_sources').fetchone()[0]
            body=body.replace('"id":','"id":"duplicate","id":',1)
            db.execute('update procedure_sources set body=?',(body,))
        self.assertIsNone(self.choose()[0])
        self.assertEqual(self.render(old)[0],'')

    def test_store_identity_change_rejects_previous_handle_and_receipt(self):
        self.store.add(self.direct)
        old,_=self.choose()
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("update procedure_meta set value='another-store' where key='store_id'")
        self.assertIsNone(self.choose()[0])
        self.assertEqual(self.render(old)[0],'')

    def test_separate_identical_store_never_accepts_other_stores_receipt(self):
        self.store.add(self.direct)
        old,_=self.choose()
        other=i.Inventory(Path(self.folder.name)/'other.sqlite3')
        other.add(self.direct)
        self.assertEqual(self.render(old,store=other)[0],'')

    def test_unrelated_database_is_rejected_without_table_changes(self):
        path=Path(self.folder.name)/'unrelated.sqlite3'
        with closing(sqlite3.connect(path)) as db, db:
            db.execute('create table unrelated (id text)')
        with self.assertRaises(i.SourceIntegrityError):
            i.Inventory(path)
        with closing(sqlite3.connect(path)) as db, db:
            self.assertEqual(db.execute("select name from sqlite_master where type='table'").fetchall(),[('unrelated',)])

    def test_request_identity_scope_mode_and_budget_boundaries(self):
        self.store.add(self.direct)
        receipt,_=self.choose()
        for kwargs in (dict(request='r2'),dict(subject='u2'),dict(namespace='other'),dict(query=HISTORY),dict(max_chars=1)):
            self.assertEqual(self.render(receipt,**kwargs)[0],'')
        self.assertIsNone(self.choose('随便聊聊。')[0])

    def test_sql_looking_partition_identity_is_literal_and_isolated(self):
        strange="u1' OR 1=1 --"
        self.store.add(replace(self.direct,subject_id=strange))
        self.assertFalse(self.choose()[1]['accepted'])
        receipt,audit=self.choose(subject=strange)
        self.assertTrue(audit['accepted'])
        self.assertTrue(self.render(receipt,subject=strange)[1]['accepted'])

    def test_all_inventory_database_handles_closed_after_operations(self):
        connections=[]
        real_connect=sqlite3.connect
        def connect(*args,**kwargs):
            db=real_connect(*args,**kwargs)
            connections.append(db)
            return db
        with patch.object(sqlite3,'connect',connect):
            store=i.Inventory(self.path)
            store.add(self.direct)
            receipt,_=self.choose(store=store)
            self.render(receipt,store=store)
        self.assertEqual(len(connections),4)
        for db in connections:
            with self.assertRaises(sqlite3.ProgrammingError):
                db.execute('select 1')


if __name__ == '__main__':
    unittest.main()
