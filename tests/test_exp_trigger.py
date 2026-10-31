"""Synthetic trigger lifecycle tests; no semantic-model or benchmark calls."""
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from cuetrail.experimental.ledger import Ledger
from test_exp_ledger import item
from cuetrail.experimental import trigger as t

RUN=Path(__file__).resolve().parent


class Contracts(unittest.TestCase):
    def setUp(self):
        scratch=RUN/'.test-work';scratch.mkdir(exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=scratch)
        self.ledger=Ledger(Path(self.temp.name)/'trigger.sqlite3')
        self.entry=item();self.sources={'s1':self.entry['source']}
        self.p=self.ledger.record('u',[self.entry],extraction_ref='synthetic:first')[0]
        self.query='Help me with cooking.';self.request='r1';self.mode='execute';self.ids=['s1']

    def tearDown(self):
        self.ledger.close();self.temp.cleanup()

    def choice(self,p=None,quote=None,decision='apply'):
        return dict(procedure_id=(p or self.p).id,query_evidence_quote=quote or self.query,decision=decision)

    def select(self,selection=None,**changes):
        args=dict(ledger=self.ledger,namespace='u',source_ids=self.ids,source_loader=self.sources.__getitem__,
                  query=self.query,request_id=self.request,mode=self.mode,
                  selection=[self.choice()] if selection is None else selection)
        args.update(changes);return t.select(**args)

    def render(self,plan,**changes):
        args=dict(plan=plan,ledger=self.ledger,namespace='u',source_ids=self.ids,
                  source_loader=self.sources.__getitem__,query=self.query,request_id=self.request,mode=self.mode)
        args.update(changes);return t.materialize(**args)

    def test_verified_trigger_preserves_condition_evidence_and_authority(self):
        plan,audit=self.select();self.assertTrue(audit['accepted'])
        cards,result=self.render(plan)
        self.assertTrue(result['accepted']);self.assertIn(self.p.evidence_quote,cards[0])
        self.assertIn('authority=user_constraint',cards[0]);self.assertFalse(result['executes_steps'])
        self.assertFalse(result['adopts_standing_rule'])

    def test_request_namespace_mode_and_query_replays_are_rejected(self):
        plan,_=self.select()
        for change in (dict(request_id='r2'),dict(namespace='other'),dict(query='another query'),dict(mode='historical_procedure')):
            cards,result=self.render(plan,**change)
            self.assertEqual(cards,[]);self.assertEqual(result['reason'],'request_binding_changed')

    def test_selection_cannot_escape_current_native_source_ids(self):
        plan,audit=self.select(source_ids=['other'])
        self.assertIsNone(plan);self.assertEqual(audit['reason'],'procedure_not_in_native_scope')

    def test_changed_source_falls_back_before_rendering(self):
        plan,_=self.select();self.sources['s1']={**self.entry['source'],'timestamp':999}
        cards,audit=self.render(plan)
        self.assertEqual(cards,[]);self.assertEqual(audit['reason'],'source_or_version_audit_failed')

    def test_replacement_after_selection_rejects_old_plan(self):
        plan,_=self.select();newer=item('s2','use seeds',2,'From now on, ')
        self.sources['s2']=newer['source'];self.ledger.record('u',[newer],extraction_ref='synthetic:second')
        cards,audit=self.render(plan)
        self.assertEqual(cards,[]);self.assertEqual(audit['reason'],'unresolved_or_superseded_version')

    def test_missing_intent_and_empty_selection_are_exact_fallbacks(self):
        for change in (dict(selection=[]),dict(mode='non_procedural'),dict(request_id='')):
            plan,audit=self.select(**change);self.assertIsNone(plan);self.assertFalse(audit['accepted'])

    def test_any_invalid_or_duplicate_choice_rejects_whole_plan(self):
        for selection in ([self.choice(),{**self.choice(),'procedure_id':'missing'}],
                          [self.choice(),self.choice()],[self.choice()]*3):
            plan,audit=self.select(selection);self.assertIsNone(plan);self.assertFalse(audit['accepted'])

    def test_proposal_is_only_attributed_history_never_execution_rule(self):
        proposal=item('proposal',role='assistant');self.sources['proposal']=proposal['source'];self.ids.append('proposal')
        p=self.ledger.record('u',[proposal],extraction_ref='synthetic:proposal')[0]
        plan,audit=self.select([self.choice(p)])
        self.assertIsNone(plan);self.assertEqual(audit['reason'],'unconfirmed_suggestion')
        self.query='What procedure was suggested for cooking?';self.mode='historical_procedure'
        plan,audit=self.select([self.choice(p,decision='historical_only')]);self.assertTrue(audit['accepted'])
        cards,audit=self.render(plan);self.assertTrue(audit['accepted'])
        self.assertIn('historical evidence; not adopted',cards[0]);self.assertIn('authority=assistant_suggestion',cards[0])
        self.assertEqual(p.status,'unconfirmed')

    def test_source_disappearing_from_native_scope_invalidates_receipt(self):
        plan,_=self.select();cards,audit=self.render(plan,source_ids=[])
        self.assertEqual(cards,[]);self.assertEqual(audit['reason'],'procedure_not_in_native_scope')

    def test_receipt_cannot_grant_execution_or_outlive_request(self):
        plan,_=self.select()
        for forged in (replace(plan,executes_steps=True),replace(plan,lifetime='recurring')):
            cards,audit=self.render(forged)
            self.assertEqual(cards,[]);self.assertEqual(audit['reason'],'invalid_trigger_lifetime')

    def test_unknown_prerequisite_abstains_even_with_semantic_choice(self):
        text='If rain starts, I must use a cover.'
        entry=dict(source=dict(id='rain',role='user',content=text,session_id='s',timestamp=1),
                   draft=dict(source_id='rain',kind='conditional_constraint',condition_quote='If rain starts',
                              scope_quote='rain',action_quotes=['use a cover'],connecting_quote=text))
        self.sources['rain']=entry['source'];self.ids.append('rain')
        p=self.ledger.record('u',[entry],extraction_ref='synthetic:rain')[0]
        plan,audit=self.select([self.choice(p)])
        self.assertIsNone(plan);self.assertEqual(audit['reason'],'unknown_contingent_prerequisite')

    def test_malformed_choice_and_query_fall_back_without_rendering(self):
        plan,audit=self.select([dict(procedure_id=['invalid'])])
        self.assertIsNone(plan);self.assertEqual(audit['reason'],'selection_schema')
        plan,_=self.select();cards,audit=self.render(plan,query=None)
        self.assertEqual(cards,[]);self.assertEqual(audit['reason'],'current_query_required')


if __name__=='__main__':unittest.main(verbosity=2)
