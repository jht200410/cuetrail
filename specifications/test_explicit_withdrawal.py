"""Synthetic authority/version/storage counterexamples; no benchmark or model."""
from dataclasses import asdict, replace
import json
import unittest

from cuetrail_governance import withdrawal as w

p, h = w.p, w.h
TEXT = '每当我询问「发布检查」时，请遵守以下步骤：\n1. 先核对版本号。\n2. 不要发布到生产，除非检查全部通过。\n3. 记录结果和来源。'


class WithdrawalContracts(unittest.TestCase):
    def setUp(self):
        self.direct = p.Source('direct', 'synthetic', 'u1', 's1', 'user', TEXT, 10)
        self.proposal = replace(self.direct, id='proposal', role='assistant', timestamp=11)
        self.confirmation = replace(self.direct, id='confirmation', session_id='s2', content=h.PREFIX+TEXT, timestamp=20)
        self.withdrawal = replace(self.direct, id='withdrawal', session_id='s3', content=w.PREFIX+TEXT, timestamp=30)
        self.sources = {v.id:v for v in (self.direct, self.proposal, self.confirmation, self.withdrawal)}
        self.native = set(self.sources)
        self.program = p.compile_source(self.direct)[0]
        self.advice = p.compile_source(self.proposal)[0]
        self.habit = h.compile_confirmation(self.advice, self.confirmation, self.load, self.native)[0]
        self.event = w.compile_withdrawal(self.program, self.withdrawal, self.load, self.native)[0]

    def load(self, identity):
        return self.sources[identity]

    def req(self, mode='execute', scope='发布检查'):
        query = f'请按既定程序处理「{scope}」。' if mode == 'execute' else f'回顾我关于「{scope}」的程序。'
        return p.parse_request(query, namespace='synthetic', subject_id='u1', request_id='r1')

    def choose(self, programs=None, habits=None, events=None, req=None):
        return w.select([self.program] if programs is None else programs, [] if habits is None else habits,
            [] if events is None else events, self.req() if req is None else req, self.load, self.native)

    def test_supported_withdrawal_preserves_complete_evidence_and_offsets(self):
        self.assertEqual(self.event.target_id, self.program.id)
        self.assertEqual(self.event.content_version, self.program.content_version)
        self.assertFalse(self.event.creates_replacement)
        for span in (self.event.explicit_intent, self.event.quoted_program):
            self.assertEqual(self.withdrawal.content[span.start:span.end], span.quote)
        self.assertEqual(self.event.quoted_program.quote, TEXT)

    def test_active_then_withdrawn_direct_constraint(self):
        self.assertTrue(self.choose()[1]['accepted'])
        receipt, decision = self.choose(events=[self.event])
        self.assertFalse(decision['accepted'])
        self.assertEqual(receipt.selected, ())
        self.assertEqual(decision['withdrawn_authorities'], [('procedure', self.program.id)])

    def test_confirmation_withdrawal_targets_confirmed_authority(self):
        event, reason = w.compile_withdrawal(self.habit, self.withdrawal, self.load, self.native)
        self.assertEqual(reason, 'valid')
        self.assertEqual(event.target_kind, 'confirmed_habit')
        receipt, decision = self.choose(programs=[self.advice], habits=[self.habit], events=[event])
        self.assertFalse(decision['accepted'])
        self.assertFalse(receipt.executes_steps)
        self.assertFalse(receipt.adopts_long_term_rule)
        self.assertEqual(self.advice.source.role, 'assistant')

    def test_habit_withdrawal_must_follow_confirmation_not_just_proposal(self):
        for timestamp in (None, True, 11, 15, 20):
            value = replace(self.withdrawal, timestamp=timestamp)
            self.sources[value.id] = value
            self.assertIsNone(w.compile_withdrawal(self.habit, value, self.load, self.native)[0])

    def test_direct_chronology_must_be_known_strictly_later(self):
        for timestamp in (None, True, 0, 10):
            value = replace(self.withdrawal, timestamp=timestamp)
            self.sources[value.id] = value
            self.assertIsNone(w.compile_withdrawal(self.program, value, self.load, self.native)[0])

    def test_unknown_original_timestamp_cannot_be_inferred(self):
        self.sources[self.direct.id] = replace(self.direct, timestamp=None)
        target = p.compile_source(self.sources[self.direct.id])[0]
        self.assertIsNone(w.compile_withdrawal(target, self.withdrawal, self.load, self.native)[0])

    def test_assistant_and_other_roles_cannot_withdraw(self):
        for role in ('assistant', 'tool', 'system'):
            value = replace(self.withdrawal, role=role)
            self.sources[value.id] = value
            self.assertIsNone(w.compile_withdrawal(self.program, value, self.load, self.native)[0])

    def test_namespace_subject_and_identity_boundaries(self):
        for field, value in [('namespace','foreign'), ('subject_id','u2'), ('session_id',''), ('namespace',''), ('subject_id','')]:
            source = replace(self.withdrawal, **{field:value})
            self.sources[source.id] = source
            self.assertIsNone(w.compile_withdrawal(self.program, source, self.load, self.native)[0])

    def test_unconfirmed_advice_and_task_cannot_be_withdrawal_targets(self):
        self.assertIsNone(w.compile_withdrawal(self.advice, self.withdrawal, self.load, self.native)[0])
        task_source = replace(self.direct, id='task', content='这次我询问「发布检查」时，请检查备份。')
        self.sources[task_source.id] = task_source
        self.native.add(task_source.id)
        task = p.compile_source(task_source)[0]
        self.assertIsNone(w.compile_withdrawal(task, self.withdrawal, self.load, self.native)[0])

    def test_bare_or_partial_or_quoted_or_changed_withdrawal_does_not_apply(self):
        for content in ('不用了。', '以后别这么做。', '他告诉我：'+w.PREFIX+TEXT, w.PREFIX+TEXT+'\n',
                        w.PREFIX+TEXT.splitlines()[0], w.PREFIX+TEXT.replace('不要', '可以'),
                        w.PREFIX+TEXT.replace('发布检查', '发布')):
            source = replace(self.withdrawal, content=content)
            self.sources[source.id] = source
            self.assertIsNone(w.compile_withdrawal(self.program, source, self.load, self.native)[0])

    def test_source_must_independently_match_canonical_store(self):
        fake = replace(self.withdrawal, session_id='fabricated')
        self.assertIsNone(w.compile_withdrawal(self.program, fake, self.load, self.native)[0])
        self.sources.pop(self.direct.id)
        self.assertIsNone(w.compile_withdrawal(self.program, self.withdrawal, self.load, self.native)[0])

    def test_native_source_inventory_required_for_target_and_withdrawal(self):
        for identity in (self.direct.id, self.withdrawal.id):
            native = self.native - {identity}
            self.assertIsNone(w.compile_withdrawal(self.program, self.withdrawal, self.load, native)[0])

    def test_forged_action_authority_or_version_cannot_withdraw(self):
        for target in (replace(self.program, content_version='forged'), replace(self.program, authority='user_confirmed_habit'),
                       replace(self.program, actions=(p.Span(0, 1, '改写'),)), replace(self.program, id='forged')):
            self.assertIsNone(w.compile_withdrawal(target, self.withdrawal, self.load, self.native)[0])

    def test_other_scope_unchanged(self):
        source = replace(self.direct, id='other-scope', content=TEXT.replace('发布检查', '备份检查'))
        self.sources[source.id] = source
        self.native.add(source.id)
        other = p.compile_source(source)[0]
        receipt, decision = self.choose(programs=[self.program, other], events=[self.event], req=self.req(scope='备份检查'))
        self.assertTrue(decision['accepted'])
        self.assertEqual(receipt.selected, (('procedure', other.id),))

    def conflicting_program(self):
        source = replace(self.direct, id='variant', timestamp=12, content=TEXT.replace('核对版本号', '检查备份'))
        self.sources[source.id] = source
        self.native.add(source.id)
        other = p.compile_source(source)[0]
        return p.govern_versions([self.program, other])

    def test_newer_action_variant_does_not_automatically_win(self):
        self.assertFalse(self.choose(programs=self.conflicting_program())[1]['accepted'])

    def test_explicit_withdrawal_resolves_only_bound_conflicting_variant(self):
        programs = self.conflicting_program()
        self.assertTrue(all(v.status == 'conflicting' for v in programs))
        receipt, decision = self.choose(programs=programs, events=[self.event])
        self.assertTrue(decision['accepted'])
        self.assertEqual(receipt.selected, (('procedure', programs[1].id),))
        text, _ = w.render(receipt, programs, [], [self.event], self.req(), self.load, self.native)
        self.assertEqual(json.loads(text)[0]['evidence']['status'], 'source_grounded')

    def test_withdrawal_does_not_resolve_other_conflicting_variants(self):
        programs = self.conflicting_program()
        third_source = replace(self.direct, id='third', timestamp=13, content=TEXT.replace('核对版本号', '核对哈希'))
        self.sources[third_source.id] = third_source
        self.native.add(third_source.id)
        programs = p.govern_versions(programs + [p.compile_source(third_source)[0]])
        self.assertFalse(self.choose(programs=programs, events=[self.event])[1]['accepted'])

    def test_habit_direct_conflict_only_resolved_by_correct_withdrawal(self):
        new_source = replace(self.direct, content=TEXT.replace('核对版本号', '检查备份'))
        self.sources[new_source.id] = new_source
        program = p.compile_source(new_source)[0]
        self.assertFalse(self.choose(programs=[program], habits=[self.habit])[1]['accepted'])
        event = w.compile_withdrawal(self.habit, self.withdrawal, self.load, self.native)[0]
        self.assertEqual(self.choose(programs=[program], habits=[self.habit], events=[event])[0].selected,
                         (('procedure', program.id),))

    def test_new_explicit_authority_is_separate_from_old_withdrawal(self):
        source = replace(self.direct, id='later-direct', timestamp=40)
        self.sources[source.id] = source
        self.native.add(source.id)
        later = p.compile_source(source)[0]
        receipt, decision = self.choose(programs=[self.program, later], events=[self.event])
        self.assertTrue(decision['accepted'])
        self.assertEqual(receipt.selected, (('procedure', later.id),))
        self.assertIsNone(w.compile_withdrawal(later, self.withdrawal, self.load, self.native)[0])

    def test_withdrawn_history_keeps_both_sources_and_no_applicability(self):
        req = self.req('historical')
        receipt, _ = self.choose(events=[self.event], req=req)
        text, decision = w.render(receipt, [self.program], [], [self.event], req, self.load, self.native)
        self.assertTrue(decision['accepted'])
        card = json.loads(text)[0]
        self.assertEqual(card['evidence']['source']['id'], self.direct.id)
        self.assertEqual(card['withdrawals'][0]['source']['id'], self.withdrawal.id)
        self.assertEqual(card['applicability'], 'withdrawn')
        self.assertEqual(card['display_mode'], 'historical_attribution_only')

    def test_old_receipt_rejected_when_withdrawal_added(self):
        old, _ = self.choose()
        text, decision = w.render(old, [self.program], [], [self.event], self.req(), self.load, self.native)
        self.assertEqual(text, '')
        self.assertFalse(decision['accepted'])

    def test_receipt_binds_withdrawal_even_for_unrelated_scope(self):
        req = self.req('historical')
        old, _ = self.choose(req=req)
        self.assertNotEqual(old, self.choose(events=[self.event], req=req)[0])

    def test_stale_source_or_event_fails_entire_ledger_closed(self):
        old, _ = self.choose(events=[self.event], req=self.req('historical'))
        self.sources[self.withdrawal.id] = replace(self.withdrawal, timestamp=31)
        receipt, decision = self.choose(events=[self.event], req=self.req('historical'))
        self.assertIsNone(receipt)
        self.assertFalse(decision['accepted'])
        self.assertEqual(w.render(old, [self.program], [], [self.event], self.req('historical'), self.load, self.native)[0], '')

    def test_missing_target_and_forged_event_rejected(self):
        for event in (replace(self.event, target_id='other'), replace(self.event, content_version='other'),
                      replace(self.event, creates_replacement=True), replace(self.event, target_kind='confirmed_habit'),
                      replace(self.event, quoted_program=p.Span(0,1,'改'))):
            self.assertIsNone(self.choose(events=[event])[0])
        self.assertIsNone(self.choose(programs=[], events=[self.event])[0])

    def test_duplicate_withdrawals_rejected(self):
        self.assertIsNone(self.choose(events=[self.event, self.event])[0])

    def test_request_mode_scope_identity_are_revalidated(self):
        old, _ = self.choose()
        for req in (replace(self.req(), mode='historical'), replace(self.req(), subject_id='u2'),
                    self.req(scope='备份检查'), replace(self.req(), id='r2')):
            self.assertEqual(w.render(old, [self.program], [], [], req, self.load, self.native)[0], '')

    def test_whole_card_budget_and_two_card_limit(self):
        req = self.req('historical')
        event = w.compile_withdrawal(self.habit, self.withdrawal, self.load, self.native)[0]
        receipt, decision = self.choose(programs=[self.program, self.advice], habits=[self.habit], events=[self.event, event], req=req)
        self.assertTrue(decision['accepted'])
        self.assertLessEqual(len(receipt.selected), 2)
        for budget in (0, True, 1, -1):
            self.assertEqual(w.render(receipt, [self.program, self.advice], [self.habit], [self.event, event], req,
                                     self.load, self.native, max_chars=budget)[0], '')

    def snapshot(self):
        event = w.compile_withdrawal(self.habit, self.withdrawal, self.load, self.native)[0]
        programs = [self.program, self.advice]
        return programs, [self.habit], [self.event, event], w.serialize(programs, [self.habit], [self.event, event], self.load, self.native)

    def test_durable_roundtrip_rebuilds_all_authority_sources(self):
        programs, habits, events, text = self.snapshot()
        self.assertEqual(w.deserialize(text, self.load, self.native), (programs, habits, events))
        self.assertEqual(json.loads(text)['withdrawals'][0]['source']['content'], w.PREFIX+TEXT)

    def test_durable_reopen_rejects_canonical_confirmation_change(self):
        *_, text = self.snapshot()
        self.sources[self.confirmation.id] = replace(self.confirmation, session_id='changed')
        with self.assertRaises(ValueError):
            w.deserialize(text, self.load, self.native)

    def test_durable_reopen_rejects_canonical_withdrawal_change(self):
        *_, text = self.snapshot()
        self.sources[self.withdrawal.id] = replace(self.withdrawal, content='不撤回。')
        with self.assertRaises(ValueError):
            w.deserialize(text, self.load, self.native)

    def test_serialized_tampering_and_duplicate_json_keys_rejected(self):
        *_, text = self.snapshot()
        for mutate in (lambda v:v['withdrawals'][0].update(content_version='forged'),
                       lambda v:v['withdrawals'][0]['source'].update(role='assistant'),
                       lambda v:v['withdrawals'][0].update(extra=True),
                       lambda v:v['withdrawals'].clear()):
            value = json.loads(text)
            mutate(value)
            with self.assertRaises(ValueError):
                w.deserialize(json.dumps(value,ensure_ascii=False), self.load, self.native)
        duplicate = text.replace('"schema_version":', '"schema_version":"duplicate","schema_version":', 1)
        with self.assertRaises(ValueError):
            w.deserialize(duplicate, self.load, self.native)

    def test_new_native_inventory_invalidates_persisted_ledger(self):
        *_, text = self.snapshot()
        with self.assertRaises(ValueError):
            w.deserialize(text, self.load, self.native | {'new-native-id'})


if __name__ == '__main__':
    unittest.main()
