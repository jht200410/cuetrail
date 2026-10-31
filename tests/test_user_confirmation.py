"""Synthetic source/authority/trigger contracts, never benchmark or model calls."""
from dataclasses import asdict, replace
import json
import unittest

from cuetrail_governance import confirmation as h

p = h.p
TEXT = '每当我询问「发布检查」时，请遵守以下步骤：\n1. 先核对版本号。\n2. 不要发布到生产，除非检查全部通过。\n3. 记录结果和来源。'


def source(text=TEXT, **fields):
    values = dict(id='proposal-1', namespace='synthetic', subject_id='user-1', session_id='s1', role='assistant', content=text, timestamp=1)
    values.update(fields)
    return p.Source(**values)


def request(mode='execute', **fields):
    query = '请按既定程序处理「发布检查」。' if mode == 'execute' else '回顾我关于「发布检查」的程序。'
    values = dict(namespace='synthetic', subject_id='user-1', request_id='r1')
    values.update(fields)
    return p.parse_request(query, **values)


class ConfirmationContracts(unittest.TestCase):
    def setUp(self):
        self.advice = source()
        self.confirm = source(h.PREFIX+TEXT, id='confirmation-1', role='user', session_id='s2', timestamp=2)
        self.sources = {self.advice.id:self.advice, self.confirm.id:self.confirm}
        self.native = set(self.sources)
        self.proposal = p.compile_source(self.advice)[0]
        self.habit, reason = self.compile()
        self.assertEqual(reason, 'valid')

    def compile(self, proposal=None, confirmation=None):
        return h.compile_confirmation(self.proposal if proposal is None else proposal,
            self.confirm if confirmation is None else confirmation, self.sources.__getitem__, self.native)

    def select(self, programs=None, habits=None, req=None):
        return h.select([self.proposal] if programs is None else programs, [self.habit] if habits is None else habits,
            request() if req is None else req, self.sources.__getitem__, self.native)

    def change_confirmation(self, **fields):
        self.confirm = replace(self.confirm, **fields)
        self.sources[self.confirm.id] = self.confirm

    def test_positive_proof_retains_both_sources_and_roles(self):
        self.assertEqual(self.habit.authority, 'user_confirmed_habit')
        self.assertEqual(self.habit.proposal.source.role, 'assistant')
        self.assertEqual(self.habit.confirmation_source.role, 'user')
        self.assertEqual(self.habit.content_version, self.proposal.content_version)
        self.assertFalse(self.habit.behavior_independently_observed)

    def test_confirmation_offsets_and_complete_exception(self):
        for span in (self.habit.explicit_intent, self.habit.quoted_program):
            self.assertEqual(self.confirm.content[span.start:span.end], span.quote)
        self.assertEqual(self.habit.quoted_program.quote, TEXT)
        self.assertIn('除非检查全部通过', self.habit.proposal.actions[1].quote)

    def test_short_agreement_does_not_confirm(self):
        for text in ('好的。', '是的。', '按上面做。', '我通常这么做。', '以后照旧。'):
            self.change_confirmation(content=text)
            self.assertIsNone(self.compile()[0])

    def test_partial_quoted_program_does_not_confirm(self):
        for text in (h.PREFIX+TEXT.splitlines()[0], h.PREFIX+TEXT.replace('不要', '可以'), h.PREFIX+TEXT+'\n',
                     '他告诉我：'+h.PREFIX+TEXT, h.PREFIX+TEXT.replace('发布检查','发布')):
            self.change_confirmation(content=text)
            self.assertIsNone(self.compile()[0])

    def test_assistant_cannot_confirm_itself(self):
        self.change_confirmation(role='assistant')
        self.assertIsNone(self.compile()[0])

    def test_tool_or_system_cannot_confirm(self):
        for role in ('tool', 'system'):
            self.change_confirmation(role=role)
            self.assertIsNone(self.compile()[0])

    def test_confirmation_owner_bound(self):
        self.change_confirmation(subject_id='user-2')
        self.assertIsNone(self.compile()[0])

    def test_confirmation_namespace_bound(self):
        self.change_confirmation(namespace='other')
        self.assertIsNone(self.compile()[0])

    def test_chronology_must_be_known_and_later(self):
        for timestamp in (None, True, 0, 1):
            self.change_confirmation(timestamp=timestamp)
            self.assertIsNone(self.compile()[0])

    def test_missing_proposal_chronology_rejected(self):
        self.advice = replace(self.advice, timestamp=None)
        self.sources[self.advice.id] = self.advice
        self.proposal = p.compile_source(self.advice)[0]
        self.assertIsNone(self.compile()[0])

    def test_one_time_advice_cannot_become_recurring(self):
        self.advice = source('这次我询问「发布检查」时，请检查备份。')
        self.sources[self.advice.id] = self.advice
        self.proposal = p.compile_source(self.advice)[0]
        self.change_confirmation(content=h.PREFIX+self.advice.content)
        self.assertEqual(self.compile()[1], 'one_time_proposal_not_recurring')

    def test_direct_user_instruction_keeps_its_type(self):
        self.advice = replace(self.advice, role='user')
        self.sources[self.advice.id] = self.advice
        self.proposal = p.compile_source(self.advice)[0]
        self.assertIsNone(self.compile()[0])
        self.assertEqual(self.proposal.authority, 'user_constraint')

    def test_both_sources_must_be_native(self):
        for identity in list(self.native):
            original = set(self.native)
            self.native.remove(identity)
            self.assertIsNone(self.compile()[0])
            self.native = original

    def test_forged_confirmation_object_rejected(self):
        forged = replace(self.confirm, timestamp=999)
        self.assertEqual(self.compile(confirmation=forged)[1], 'canonical_source_or_version_changed')

    def test_forged_proposal_version_or_authority_rejected(self):
        for fields in (dict(content_version='forged'), dict(authority='user_constraint'), dict(status='active')):
            self.assertIsNone(self.compile(proposal=replace(self.proposal, **fields))[0])

    def test_missing_canonical_source_rejected(self):
        del self.sources[self.confirm.id]
        self.assertIsNone(self.compile()[0])

    def test_duplicate_habit_rejected(self):
        with self.assertRaises(ValueError):
            h.audit_habits([self.habit,self.habit], self.sources.__getitem__, self.native)

    def test_forged_behavior_or_source_proof_rejected(self):
        for fields in (dict(behavior_independently_observed=True), dict(confirmation_sha256='fake'), dict(authority='user_constraint')):
            with self.assertRaises(ValueError):
                h.audit_habits([replace(self.habit, **fields)], self.sources.__getitem__, self.native)

    def test_confirmation_source_change_invalidates_habit(self):
        self.change_confirmation(timestamp=3)
        with self.assertRaises(ValueError):
            h.audit_habits([self.habit], self.sources.__getitem__, self.native)

    def test_json_reopen_revalidates_both_canonical_sources(self):
        text = h.serialize_habits([self.habit], self.sources.__getitem__, self.native)
        self.assertEqual(h.deserialize_habits(text, self.sources.__getitem__, self.native), [self.habit])
        self.sources[self.advice.id] = replace(self.advice, content=TEXT.replace('不要', '允许'))
        with self.assertRaises(ValueError):
            h.deserialize_habits(text, self.sources.__getitem__, self.native)

    def test_json_forgery_and_duplicate_fields_rejected(self):
        text = h.serialize_habits([self.habit], self.sources.__getitem__, self.native)
        value = json.loads(text)
        value['habits'][0]['authority'] = 'user_constraint'
        value['projection_sha256'] = p.digest(value['habits'])
        for stored in (json.dumps(value,ensure_ascii=False), '{"schema_version":"forged",'+text[1:]):
            with self.assertRaises(ValueError):
                h.deserialize_habits(stored, self.sources.__getitem__, self.native)

    def test_current_execution_selects_confirmed_not_unconfirmed(self):
        receipt, decision = self.select()
        self.assertTrue(decision['accepted'])
        self.assertEqual(receipt.selected, (('confirmed_habit',self.habit.id),))
        self.assertFalse(receipt.executes_steps)
        self.assertFalse(receipt.adopts_long_term_rule)

    def test_proposal_without_confirmation_does_not_apply(self):
        self.assertFalse(self.select(habits=[])[1]['accepted'])

    def test_historical_recall_preserves_distinct_authorities(self):
        receipt, decision = self.select(req=request('historical'))
        self.assertTrue(decision['accepted'])
        self.assertEqual(len(receipt.selected), 2)
        text, valid = h.render(receipt, [self.proposal], [self.habit], request('historical'), self.sources.__getitem__, self.native)
        self.assertTrue(valid['accepted'])
        self.assertIn('assistant_suggestion',text)
        self.assertIn('user_confirmed_habit',text)
        self.assertIn('historical_attribution_only',text)

    def test_owner_and_namespace_isolation_at_trigger(self):
        for fields in (dict(subject_id='user-2'),dict(namespace='other')):
            self.assertFalse(self.select(req=request(**fields))[1]['accepted'])

    def test_unrelated_scope_abstains(self):
        req = p.parse_request('请按既定程序处理「其他发布检查」。',namespace='synthetic',subject_id='user-1',request_id='r1')
        self.assertFalse(self.select(req=req)[1]['accepted'])

    def test_conflicting_direct_user_constraint_blocks_habit(self):
        direct = source(TEXT.replace('先核对版本号','先检查备份'),id='direct',role='user',timestamp=0)
        self.sources[direct.id] = direct
        self.native.add(direct.id)
        values = p.govern_versions([self.proposal,p.compile_source(direct)[0]])
        receipt, decision = self.select(programs=values)
        self.assertEqual(receipt.selected, ())
        self.assertTrue(any(row['reason']=='conflict_across_user_constraints_and_confirmed_habits' for row in decision['rejected']))

    def test_identical_direct_constraint_deduplicates_execution(self):
        direct = source(id='direct',role='user',timestamp=0)
        self.sources[direct.id] = direct
        self.native.add(direct.id)
        values = p.govern_versions([self.proposal,p.compile_source(direct)[0]])
        receipt, decision = self.select(programs=values)
        self.assertTrue(decision['accepted'])
        self.assertEqual(receipt.selected, (('procedure',values[1].id),))

    def test_latest_confirmed_variant_does_not_replace_old(self):
        other = source(TEXT.replace('先核对版本号','先检查备份'),id='proposal-2',timestamp=3)
        approval = source(h.PREFIX+other.content,id='confirmation-2',role='user',timestamp=4)
        self.sources.update({other.id:other,approval.id:approval})
        self.native.update((other.id,approval.id))
        second, reason = h.compile_confirmation(p.compile_source(other)[0],approval,self.sources.__getitem__,self.native)
        self.assertEqual(reason,'valid')
        receipt, decision = self.select(habits=[self.habit,second])
        self.assertFalse(decision['accepted'])
        self.assertEqual(receipt.selected,())
        self.assertEqual(len(self.select(programs=[],habits=[self.habit,second],req=request('historical'))[0].selected),2)

    def test_history_remains_bounded_to_two(self):
        habits = [self.habit]
        for i in (2,3):
            advice = source(TEXT.replace('先核对版本号','先检查备份'+str(i)),id=f'proposal-{i}',timestamp=i*2)
            approval = source(h.PREFIX+advice.content,id=f'confirmation-{i}',role='user',timestamp=i*2+1)
            self.sources.update({advice.id:advice,approval.id:approval})
            self.native.update((advice.id,approval.id))
            habits.append(h.compile_confirmation(p.compile_source(advice)[0],approval,self.sources.__getitem__,self.native)[0])
        receipt, decision = self.select(programs=[],habits=habits,req=request('historical'))
        self.assertEqual(len(receipt.selected),2)
        self.assertTrue(any(row['reason']=='at_most_two' for row in decision['rejected']))

    def test_request_mode_forgery_rejected(self):
        req = replace(request('historical'), mode='execute')
        self.assertIsNone(self.select(req=req)[0])

    def test_request_change_invalidates_receipt(self):
        receipt, _ = self.select()
        text, decision = h.render(receipt,[self.proposal],[self.habit],request(request_id='r2'),self.sources.__getitem__,self.native)
        self.assertFalse(decision['accepted'])
        self.assertEqual(text,'')

    def test_source_inventory_change_invalidates_receipt(self):
        receipt, _ = self.select()
        text, decision = h.render(receipt,[self.proposal],[self.habit],request(),self.sources.__getitem__,self.native|{'other'})
        self.assertFalse(decision['accepted'])
        self.assertEqual(text,'')

    def test_whole_card_budget_has_no_partial_source(self):
        receipt, _ = self.select()
        text, decision = h.render(receipt,[self.proposal],[self.habit],request(),self.sources.__getitem__,self.native,max_chars=20)
        self.assertFalse(decision['accepted'])
        self.assertEqual(text,'')

    def test_rendered_card_keeps_both_original_sources(self):
        receipt, _ = self.select()
        text, decision = h.render(receipt,[self.proposal],[self.habit],request(),self.sources.__getitem__,self.native)
        self.assertTrue(decision['accepted'])
        evidence = json.loads(text)[0]['evidence']
        self.assertEqual(evidence['proposal']['source']['content'],TEXT)
        self.assertEqual(evidence['confirmation_source']['content'],h.PREFIX+TEXT)
        self.assertFalse(evidence['behavior_independently_observed'])

    def test_forged_receipt_rejected(self):
        receipt, _ = self.select()
        forged = replace(receipt,selected=(('procedure',self.proposal.id),))
        self.assertFalse(h.render(forged,[self.proposal],[self.habit],request(),self.sources.__getitem__,self.native)[1]['accepted'])


if __name__ == '__main__':
    unittest.main()
