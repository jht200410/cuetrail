"""Synthetic native-order and contiguous-evidence integration checks."""
from dataclasses import asdict
import unittest
from cuetrail.experimental import injector as i
from cuetrail.experimental.ledger import Ledger


class Contracts(unittest.TestCase):
    def setUp(self):
        self.source = dict(id='synthetic', role='user', session_id='synthetic', timestamp=1,
            content='Before rehearsals, I usually first tune the cello, then check the bow.')
        draft = dict(source_id='synthetic', condition_quote='Before rehearsals', scope_quote='rehearsals',
            action_quotes=['tune the cello','check the bow'], connecting_quote=self.source['content'], kind='ordered_procedure')
        self.ledger = Ledger(':memory:')
        self.p = self.ledger.record('test',[dict(source=self.source,draft=draft)],extraction_ref='synthetic')[0]
        self.query = 'Help me prepare for rehearsals.'
        self.args = dict(ledger=self.ledger, namespace='test', source_ids=['synthetic'], source_loader=lambda _: self.source,
            query=self.query, request_id='request', mode='execute')
        self.plan,_ = i.r.trigger.select(**self.args,selection=[dict(procedure_id=self.p.id,query_evidence_quote=self.query,decision='apply')])
        self.native = [dict(id='first',content='Protected original evidence.',score=1.0),dict(id='second',content='Other native evidence.',score=0.5)]

    def tearDown(self):
        self.ledger.close()

    def test_native_order_and_structured_fields(self):
        hits,audit = i.inject(self.native,self.plan,**self.args)
        self.assertTrue(audit['applied'])
        self.assertEqual(self.native[0],hits[0])
        self.assertEqual(self.native[1],hits[-1])
        self.assertIn('Quoted condition: Before rehearsals',hits[1]['content'])
        self.assertEqual(asdict(self.p),hits[1]['procedure'])

    def test_body_span_is_original_and_fields_are_header_only(self):
        hits,_ = i.inject(self.native,self.plan,**self.args)
        unit = i.original_body_unit(hits[1],dict(id='original-doc',session='synthetic',ordinal=0))
        self.assertEqual(self.source['content'],unit['body'])
        self.assertEqual(self.p.evidence_start,unit['start'])
        self.assertEqual(self.p.evidence_end,unit['end'])
        self.assertIn('Quoted action 1: tune the cello',unit['header'])
        self.assertEqual(hits[1]['content'],unit['header']+unit['body'])

    def test_query_mismatch_keeps_exact_native_object(self):
        hits,audit = i.inject(self.native,self.plan,**dict(self.args,query='A different query'))
        self.assertIs(self.native,hits)
        self.assertFalse(audit['applied'])

    def test_protected_first_budget_keeps_exact_native_object(self):
        hits,audit = i.inject(self.native,self.plan,context_chars=len(self.native[0]['content']),**self.args)
        self.assertIs(self.native,hits)
        self.assertEqual('protected_first_budget',audit['reason'])

    def test_body_cannot_be_silently_rewritten(self):
        hits,_ = i.inject(self.native,self.plan,**self.args)
        forged = dict(hits[1],content=hits[1]['content']+' changed')
        with self.assertRaisesRegex(ValueError,'complete original'):
            i.original_body_unit(forged,dict(id='original-doc',session='synthetic',ordinal=0))


if __name__ == '__main__':unittest.main()
