"""Real native store/API contracts with deterministic synthetic embeddings only."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

try:
    import fastapi
    import httpx
    import numpy as np
except ImportError as error:
    raise unittest.SkipTest("Install CueTrail native optional dependencies") from error

HERE=Path(__file__).resolve().parent
REPO=HERE.parent
sys.path[:0]=[str(REPO/'src'),str(REPO/'vendor/context-weave-exact32'),str(HERE)]
from adaptive_evidence.core import Config,ConflictError,MemoryStore
from cuetrail_native.integration import inject,memory_store_class,project
from cuetrail_governance import confirmation as h,withdrawal as w

ENGLISH='Always include the backup checksum when I ask about backup checks.'
QUERY='How should I prepare backup checks?'
ZH='每当我询问「恢复检查」时，请遵守以下步骤：\n1. 先核对备份来源。\n2. 不要删除副本，除非验证全部通过。'
GUARDED='每当我询问「恢复检查」且「环境=隔离；备份=已验证」时，请遵守以下步骤：\n1. 先核对备份来源。\n2. 不要删除副本，除非验证全部通过。'
STAMP=1700000000000


class FakeEncoder:
    identity='cuetrail-native-synthetic-contract-v1'
    model='synthetic-local-contract'
    batch_size=10
    def encode(self,texts,*,query=False):
        values=np.zeros((len(texts),64),dtype=np.float32)
        for index,text in enumerate(texts):
            values[index,0]=0.01
            for token in re.findall(r'\w+',text.casefold()):
                position=int.from_bytes(hashlib.sha256(token.encode()).digest()[:4],'big')%64
                values[index,position]+=1
        return values


class NativeContracts(unittest.TestCase):
    def setUp(self):
        self.folder=TemporaryDirectory(dir=HERE)
        self.addCleanup(self.folder.cleanup)
        self.path=Path(self.folder.name)/'native.sqlite3'
        self.base=MemoryStore(self.path,FakeEncoder(),Config())
        self.current=memory_store_class(MemoryStore)(self.path,FakeEncoder(),Config())

    def add(self,text=ENGLISH,*,user='u1',role='user',timestamp=STAMP,request='r1',session='s1'):
        return self.current.add(user_id=user,request_id=request,session_id=session,
            messages=[dict(role=role,content=text,timestamp=timestamp)])

    def search(self,query=QUERY,*,user='u1',base=False,top_k=100):
        return (self.base if base else self.current).search(user_id=user,query=query,top_k=top_k,mode='query_document_evidence')

    def cards(self,hits):
        return [json.loads(v['content'].removeprefix('[CueTrail Procedure] ')) for v in hits if v['id'].startswith('cuetrail-procedure:')]

    def test_current_code_really_changes_supported_native_search(self):
        self.add()
        baseline=self.search(base=True)
        current=self.search()
        self.assertTrue(self.current.procedure_trace['applied'])
        self.assertNotEqual(current,baseline)
        self.assertEqual(current[0],baseline[0])
        card=self.cards(current)[0]
        self.assertEqual(card['kind'],'english')
        self.assertEqual(card['program']['evidence']['quote'],ENGLISH)
        self.assertEqual(card['program']['authority'],'user_constraint')
        self.assertEqual(card['trigger']['query_scope']['quote'],'backup checks')
        self.assertFalse(card['executes_steps'])
        self.assertFalse(card['adopts_long_term_rule'])
        self.assertLessEqual(len('\n\n'.join(v['content'] for v in current)),24000)

    def test_unsupported_fact_and_negated_topic_requests_fall_back_exactly(self):
        self.add()
        for query in ('Is the backup checks note stored?','How should I write about hiking, not backup checks?','What is the weather?'):
            self.assertEqual(self.search(query),self.search(query,base=True))
            self.assertFalse(self.current.procedure_trace['applied'])

    def test_assistant_and_one_time_do_not_gain_user_authority(self):
        self.add(role='assistant')
        self.assertEqual(self.search(),self.search(base=True))
        self.add('Always include the backup checksum when I ask about backup checks for this task.',user='task')
        query='How should I prepare backup checks for this task?'
        self.assertEqual(self.search(query,user='task'),self.search(query,user='task',base=True))

    def test_add_idempotence_conflict_and_user_isolation_are_native(self):
        self.assertGreater(self.add(),0)
        self.assertEqual(self.add(),0)
        with self.assertRaises(ConflictError):
            self.add(ENGLISH.replace('checksum','reference'))
        self.assertEqual(self.search(user='other'),[])
        self.assertEqual(self.current.procedural_injections,0)

    def test_conflicting_english_versions_abstain_and_retain_originals(self):
        self.add()
        self.add(ENGLISH.replace('include the backup checksum','report the backup reference'),request='r2',timestamp=STAMP+1)
        self.assertEqual(self.search(),self.search(base=True))
        with closing(self.current.connect()) as db:
            rows=db.execute('select content from sources where user_id=?',('u1',)).fetchall()
        self.assertEqual(len(rows),2)

    def test_late_exact_withdrawal_suppresses_bound_english_program(self):
        self.add()
        self.assertTrue(self.cards(self.search()))
        self.add(w.PREFIX+ENGLISH,request='withdrawal',timestamp=STAMP+1)
        self.assertEqual(self.search(),self.search(base=True))
        self.assertEqual(self.current.procedure_trace['withdrawn_or_uncertain_authorities'],1)

    def test_unknown_withdrawal_order_abstains_without_claiming_latest_wins(self):
        self.add()
        self.add(w.PREFIX+ENGLISH,request='withdrawal',timestamp=None)
        self.assertEqual(self.search(),self.search(base=True))
        history='Recall my backup checks procedure.'
        cards=self.cards(self.search(history))
        self.assertEqual(cards[0]['withdrawals'][0]['effect'],'abstain_unknown_withdrawal_order')
        self.assertEqual(cards[0]['display_mode'],'historical_attribution_only')

    def test_earlier_withdrawal_cannot_remove_later_explicit_authority(self):
        self.add(w.PREFIX+ENGLISH,request='withdrawal',timestamp=STAMP-1)
        self.add(timestamp=STAMP)
        self.assertTrue(self.cards(self.search()))

    def test_chinese_whole_steps_and_two_source_confirmation_are_live(self):
        self.add(ZH,role='assistant',request='advice')
        query='请按既定程序处理「恢复检查」。'
        self.assertEqual(self.search(query),self.search(query,base=True))
        self.add(h.PREFIX+ZH,request='confirmation',timestamp=STAMP+1)
        output=self.search(query)
        cards=self.cards(output)
        self.assertEqual(len(cards),1,self.current.procedure_trace)
        card=cards[0]
        self.assertEqual(card['kind'],'confirmed_habit')
        self.assertEqual(card['program']['proposal']['source']['role'],'assistant')
        self.assertEqual(card['program']['confirmation_source']['role'],'user')
        self.assertFalse(card['program']['behavior_independently_observed'])
        self.assertEqual([a['quote'] for a in card['program']['proposal']['actions']],ZH.splitlines()[1:])

    def test_confirmed_habit_withdrawal_is_applied_before_native_injection(self):
        for request,text,role,ts in [('advice',ZH,'assistant',STAMP),('confirmation',h.PREFIX+ZH,'user',STAMP+1),
                                    ('withdrawal',w.PREFIX+ZH,'user',STAMP+2)]:
            self.add(text,role=role,request=request,timestamp=ts)
        query='请按既定程序处理「恢复检查」。'
        self.assertEqual(self.search(query),self.search(query,base=True))

    def test_guarded_program_requires_all_literal_current_assertions(self):
        self.add(GUARDED)
        missing='在「环境=隔离」条件下，请按既定程序处理「恢复检查」。'
        self.assertEqual(self.search(missing),self.search(missing,base=True))
        query='在「备份=已验证；环境=隔离」条件下，请按既定程序处理「恢复检查」。'
        cards=self.cards(self.search(query))
        self.assertEqual(len(cards),1,self.current.procedure_trace)
        card=cards[0]
        self.assertEqual(card['kind'],'guarded')
        self.assertEqual(card['trigger']['evidence_basis'],'current_user_assertion_only')
        self.assertTrue(card['trigger']['current_assertions']['source']['id'].startswith('current-search-input:'))
        self.assertFalse(card['external_state_verified'])
        self.assertEqual(card['program']['source']['timestamp'],STAMP)

    def test_guarded_unknown_original_timestamp_and_explicit_withdrawal_abstain(self):
        query='在「备份=已验证；环境=隔离」条件下，请按既定程序处理「恢复检查」。'
        self.add(GUARDED,user='unknown',timestamp=None)
        self.assertEqual(self.search(query,user='unknown'),self.search(query,user='unknown',base=True))
        self.add(GUARDED)
        self.add(w.PREFIX+GUARDED,request='withdrawal',timestamp=STAMP+1)
        self.assertEqual(self.search(query),self.search(query,base=True))

    def test_large_document_and_top_k_one_remain_exact_native_paths(self):
        self.add()
        self.assertEqual(self.search(top_k=1),self.search(base=True,top_k=1))
        self.add(('Synthetic source document backup checks reference.\n'*500),request='document',timestamp=STAMP+1)
        self.assertEqual(self.search(),self.search(base=True))
        self.assertEqual(self.current.procedure_trace['reason'],'protected_native_path')

    def test_sixteen_concurrent_searches_keep_document_and_user_state_separate(self):
        self.add()
        self.add(('Synthetic source document backup checks reference.\n'*500),user='document',request='document')
        def task(index):
            user='u1' if index%2 else 'document'
            hits=self.search(user=user)
            return user,bool(self.cards(hits)),self.current.procedure_trace
        with ThreadPoolExecutor(max_workers=16) as pool:
            results=list(pool.map(task,range(16)))
        for user,has_cards,trace in results:
            self.assertEqual(has_cards,user=='u1',trace)
        self.assertEqual(self.current.procedural_injections,8)

    def test_whole_card_budget_protects_first_hit_and_never_truncates(self):
        hits=[dict(id='native-1',content='x'*50,score=1),dict(id='native-2',content='y'*50,score=0.5)]
        card=dict(program=dict(id='p'),body='z'*200)
        output,audit=inject(hits,[card],top_k=100,context_chars=100)
        self.assertEqual(output,hits)
        self.assertFalse(audit['applied'])

    def test_projection_rejects_foreign_user_and_rebuilds_after_new_source(self):
        self.add()
        with closing(self.current.connect()) as db:
            rows=[dict(v) for v in db.execute('select * from sources')]
        with self.assertRaises(ValueError):
            project(rows,'foreign')
        before=self.search()
        self.add(ENGLISH.replace('include the backup checksum','report the backup reference'),request='new')
        after=self.search()
        self.assertTrue(self.cards(before))
        self.assertFalse(self.cards(after))

    def test_safe_audit_has_hashes_ids_and_counts_without_source_or_query_text(self):
        self.add()
        path=Path(self.folder.name)/'audit.jsonl'
        with patch.dict(os.environ,CUETRAIL_PROCEDURE_AUDIT=str(path)):
            self.search()
        value=json.loads(path.read_text('utf8'))
        self.assertTrue(value['applied'])
        self.assertIn('current_input_sha256',value)
        self.assertNotIn(ENGLISH,path.read_text('utf8'))
        self.assertNotIn(QUERY,path.read_text('utf8'))

    def test_concurrent_add_between_ranking_and_projection_abstains(self):
        self.add()
        original=self.current.ranked
        written=[]
        def ranked(*args,**kwargs):
            result=original(*args,**kwargs)
            if not written:
                written.append(True)
                self.add('A new synthetic source arrives during ranking.',request='concurrent')
            return result
        with patch.object(self.current,'ranked',ranked):
            hits=self.search()
        self.assertEqual(self.cards(hits),[])
        self.assertEqual(self.current.procedure_trace['reason'],'source_or_trigger_integrity_fallback')

    def test_real_fastapi_auth_add_search_and_current_health_contract(self):
        from fastapi.testclient import TestClient
        from cuetrail_native import server
        original_get=server.native.get_store
        def get_fixture():
            return self.current
        get_fixture.cache_clear=lambda:None
        server.app.dependency_overrides[original_get]=get_fixture
        try:
            with patch.object(server.native,'get_store',get_fixture),patch.dict(os.environ,
                    MEMORY_API_KEY='synthetic-contract-only',AE_MODE='query_document_evidence'),TestClient(server.app) as client:
                health=client.get('/health').json()
                self.assertTrue(health['current_procedural_code'])
                self.assertEqual(health['version'],'cuetrail-v0.30-procedural-v77')
                self.assertEqual(health['baseline_source_version'],'0.32.0')
                self.assertEqual(health['generative_llm_calls_in_memory_service'],0)
                payload=dict(user_id='api',request_id='api-r1',session_id='api-s1',messages=[dict(role='user',content=ENGLISH,timestamp=STAMP)])
                self.assertEqual(client.post('/add',json=payload).status_code,401)
                headers={'X-Api-Key':'synthetic-contract-only'}
                self.assertEqual(client.post('/add',json=payload,headers=headers).status_code,200)
                self.assertEqual(client.post('/add',json=payload,headers=headers).status_code,200)
                changed=dict(payload,messages=[dict(role='user',content='A different synthetic write.')])
                self.assertEqual(client.post('/add',json=changed,headers=headers).status_code,409)
                search=dict(user_id='api',query=QUERY,top_k=100)
                self.assertEqual(client.post('/search',json=search).status_code,401)
                response=client.post('/search',json=search,headers=headers)
                self.assertEqual(response.status_code,200)
                self.assertTrue(self.cards(response.json()['data']))
                self.assertEqual(client.post('/search',json=dict(search,label='forbidden'),headers=headers).status_code,422)
                other=client.post('/search',json=dict(search,user_id='foreign'),headers=headers)
                self.assertEqual(other.json(),dict(data=[]))
        finally:
            server.app.dependency_overrides.clear()


if __name__=='__main__':
    unittest.main()
