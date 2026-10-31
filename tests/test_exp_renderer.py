"""Synthetic renderer provenance/lifecycle tests, without models or datasets."""
import unittest
from dataclasses import replace
from cuetrail.experimental import renderer as r
from cuetrail.experimental.ledger import Ledger


class Contracts(unittest.TestCase):
    def setUp(self):
        self.source = dict(id='synthetic', role='user', session_id='synthetic', timestamp=1,
            content='When packing lunches, I must avoid peanuts and use clean utensils.')
        self.draft = dict(source_id='synthetic', condition_quote='When packing lunches', scope_quote='packing lunches',
            action_quotes=['avoid peanuts', 'use clean utensils'], connecting_quote=self.source['content'], kind='conditional_constraint')
        self.ledger = Ledger(':memory:')
        self.p = self.ledger.record('test', [dict(source=self.source, draft=self.draft)], extraction_ref='synthetic')[0]
        self.query = 'Help me with packing lunches.'
        self.args = dict(ledger=self.ledger, namespace='test', source_ids=['synthetic'], source_loader=lambda _: self.source,
                         query=self.query, request_id='request', mode='execute')
        self.plan, _ = r.trigger.select(**self.args, selection=[dict(procedure_id=self.p.id, query_evidence_quote=self.query, decision='apply')])

    def tearDown(self):
        self.ledger.close()

    def test_fields_and_full_source_are_both_retained(self):
        cards, audit = r.render(self.plan, **self.args)
        self.assertTrue(audit['accepted'])
        self.assertEqual(1, len(cards))
        for quote in [self.p.scope_quote, self.p.condition_quote, *self.p.action_quotes, self.source['content']]:
            self.assertIn(quote, cards[0])
        self.assertIn('Quoted action 1: avoid peanuts', cards[0])
        self.assertIn(self.p.source_sha256, cards[0])
        self.assertFalse(audit['adopts_standing_rule'])
        self.assertFalse(audit['executes_steps'])

    def test_different_query_cannot_reuse_cards(self):
        args = dict(self.args, query='Help me with a different task.')
        self.assertFalse(r.render(self.plan, **args)[1]['accepted'])

    def test_different_request_cannot_reuse_cards(self):
        self.assertFalse(r.render(self.plan, **dict(self.args, request_id='different'))[1]['accepted'])

    def test_changed_source_cannot_render(self):
        self.source = dict(self.source, content=self.source['content'] + ' This was revoked.')
        self.assertFalse(r.render(self.plan, **self.args)[1]['accepted'])

    def test_forged_action_is_not_rendered(self):
        forged = replace(self.plan, procedures=(replace(self.p, action_quotes=('include peanuts',)),))
        self.assertFalse(r.render(forged, **self.args)[1]['accepted'])

    def test_unconfirmed_assistant_is_history_only(self):
        source = dict(self.source, id='assistant', role='assistant',
            content='Before rehearsals, first check the sheet music, then tune the instrument.')
        draft = dict(source_id='assistant', condition_quote='Before rehearsals', scope_quote='rehearsals',
            action_quotes=['check the sheet music', 'tune the instrument'], connecting_quote=source['content'], kind='ordered_procedure')
        p = self.ledger.record('history', [dict(source=source, draft=draft)], extraction_ref='synthetic-advice')[0]
        query = 'What steps did you suggest before rehearsals?'
        args = dict(ledger=self.ledger, namespace='history', source_ids=['assistant'], source_loader=lambda _: source,
                    query=query, request_id='history', mode='historical_procedure')
        plan, _ = r.trigger.select(**args, selection=[dict(procedure_id=p.id, query_evidence_quote=query, decision='historical_only')])
        cards, audit = r.render(plan, **args)
        self.assertTrue(audit['accepted'])
        self.assertIn('was not thereby adopted', cards[0])
        self.assertIn('authority=assistant_suggestion', cards[0])
        args['mode'] = 'execute'
        self.assertFalse(r.render(plan, **args)[1]['accepted'])

    def test_structured_budget_falls_back_without_truncation(self):
        entries = []
        for index, scope in enumerate(['packing lunches', 'preparing dinners']):
            text = f'When {scope}, I must avoid peanuts and use clean utensils.'
            text += ' ' + 'x' * (1189 - len(text))
            source = dict(self.source, id='budget' + str(index), content=text)
            draft = dict(self.draft, source_id=source['id'], condition_quote='When ' + scope,
                         scope_quote=scope, connecting_quote=text)
            entries.append(dict(source=source, draft=draft))
        sources = {entry['source']['id']: entry['source'] for entry in entries}
        objects = self.ledger.record('budget', entries, extraction_ref='synthetic-budget')
        query = 'Help me with packing lunches and preparing dinners.'
        args = dict(ledger=self.ledger, namespace='budget', source_ids=list(sources), source_loader=sources.__getitem__,
                    query=query, request_id='budget', mode='execute')
        plan, _ = r.trigger.select(**args, selection=[dict(procedure_id=p.id, query_evidence_quote=query, decision='apply') for p in objects])
        raw, raw_audit = r.trigger.materialize(plan, **args)
        self.assertTrue(raw_audit['accepted'])
        self.assertEqual(2, len(raw))
        cards, audit = r.render(plan, **args)
        self.assertFalse(cards)
        self.assertEqual('structured_card_budget', audit['reason'])
        self.assertFalse(audit['original_source_truncated'])


if __name__ == '__main__':unittest.main()
