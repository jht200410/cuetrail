"""Prospective synthetic contracts; no benchmark inputs, models or dependencies."""
from dataclasses import asdict, replace
import hashlib
import json
import unittest

from cuetrail_governance import procedure_zh as p

ONE = '每当我询问「数据库部署」时，请始终先检查备份，再验证恢复步骤，不要直接覆盖生产数据。'
MULTI = '每当我询问「发布检查」时，请遵守以下步骤：\n1. 先核对版本号。\n2. 不要发布到生产，除非检查全部通过。\n3. 记录结果和来源。'


def source(text=ONE, **kwargs):
    fields = dict(id='source-1', namespace='synthetic', subject_id='user-1', session_id='session-1', role='user', content=text, timestamp=1)
    fields.update(kwargs)
    return p.Source(**fields)


def programs(*sources):
    values = [p.compile_source(s)[0] for s in sources]
    assert all(v is not None for v in values)
    return p.govern_versions(values)


def request(topic='数据库部署', mode='execute', **kwargs):
    query = f'请按既定程序处理「{topic}」。' if mode == 'execute' else f'回顾我关于「{topic}」的程序。'
    fields = dict(namespace='synthetic', subject_id='user-1', request_id='request-1')
    fields.update(kwargs)
    return p.parse_request(query, **fields)


class SourceContracts(unittest.TestCase):
    def test_condition_and_negative_action_remain_literal(self):
        value, reason = p.compile_source(source())
        self.assertEqual(reason, 'valid')
        self.assertEqual(value.condition.quote, '每当我询问「数据库部署」时')
        self.assertEqual(value.scope.quote, '数据库部署')
        self.assertEqual(value.actions[0].quote, '先检查备份，再验证恢复步骤，不要直接覆盖生产数据')
        for span in (value.condition, value.scope, value.evidence, *value.actions):
            self.assertEqual(ONE[span.start:span.end], span.quote)
        self.assertEqual(value.source_sha256, hashlib.sha256(ONE.encode('utf8')).hexdigest())

    def test_numbered_whole_actions_and_exception_retained(self):
        value, reason = p.compile_source(source(MULTI))
        self.assertEqual(reason, 'valid')
        self.assertEqual([a.quote for a in value.actions], MULTI.splitlines()[1:])
        self.assertIn('除非检查全部通过', value.actions[1].quote)
        for action in value.actions:
            self.assertEqual(MULTI[action.start:action.end], action.quote)

    def test_crlf_offsets_preserved(self):
        text = MULTI.replace('\n', '\r\n')
        value, _ = p.compile_source(source(text))
        self.assertIsNotNone(value)
        self.assertTrue(all(text[a.start:a.end] == a.quote for a in value.actions))

    def test_discontinuous_or_extra_steps_rejected(self):
        for text in (MULTI.replace('2. ', '3. '), MULTI.replace('2. ', '1. '), MULTI+'\n', MULTI.replace('\n2.', '\n\n2.'),
                     MULTI.replace('3. 记录结果和来源。', '其他：保留日志。'), MULTI.split('\n1.')[0]+'\n1. 记录一次。'):
            with self.subTest(text=text):
                self.assertIsNone(p.compile_source(source(text))[0])

    def test_more_than_six_steps_rejected(self):
        text = MULTI.split('\n1.')[0] + '\n' + '\n'.join(f'{i}. 检查来源。' for i in range(1, 8))
        self.assertIsNone(p.compile_source(source(text))[0])

    def test_quoted_report_or_narrative_rejected(self):
        for text in ('助手建议：'+ONE, '「'+ONE+'」', '他告诉我：'+ONE, '例如：'+ONE, ONE+'这是他的话。'):
            self.assertIsNone(p.compile_source(source(text))[0])

    def test_self_report_and_confirmation_not_adopted(self):
        for text in ('我通常部署前检查备份。', '好的。', '是的，就这样。', '我上次用了这个步骤。', '以后照旧。'):
            self.assertIsNone(p.compile_source(source(text))[0])

    def test_assistant_stays_suggestion(self):
        value, _ = p.compile_source(source(role='assistant'))
        self.assertEqual((value.authority, value.status, value.lifetime), ('assistant_suggestion', 'unconfirmed', 'proposal'))

    def test_task_stays_task_bound(self):
        value, _ = p.compile_source(source('这次我询问「数据库部署」时，请检查备份。'))
        self.assertEqual(value.lifetime, 'task_bound')

    def test_metadata_validation(self):
        for fields in (dict(role='system'), dict(role='tool'), dict(id=''), dict(namespace=''), dict(subject_id=''), dict(session_id=''), dict(timestamp=True)):
            self.assertIsNone(p.compile_source(source(**fields))[0])

    def test_long_or_partial_source_rejected(self):
        self.assertIsNone(p.compile_source(source('提示：'+ONE))[0])
        self.assertIsNone(p.compile_source(source('每当我询问「范围」时，请始终记录'+'字'*1200+'。'))[0])

    def test_unicode_without_normalization(self):
        for i in range(32):
            topic = f'项目🧪-{i}-Ｘé'
            text = f'每当我询问「{topic}」时，请始终保留原文，不要去掉否定词。'
            value, _ = p.compile_source(source(text, id=f'unicode-{i}'))
            self.assertIsNotNone(value)
            self.assertEqual(value.scope.quote, topic)
            self.assertEqual(text[value.scope.start:value.scope.end], topic)

    def test_versions_stable_under_source_order(self):
        one, two = source(), source(ONE.replace('先检查备份', '先核对环境'), id='source-2', timestamp=10)
        left, right = programs(one, two), programs(two, one)
        self.assertEqual({v.id: v.content_version for v in left}, {v.id: v.content_version for v in right})
        self.assertTrue(all(v.status == 'conflicting' for v in left))

    def test_metadata_changes_bind_identity(self):
        value, _ = p.compile_source(source())
        for fields in (dict(role='assistant'), dict(subject_id='other'), dict(namespace='other'), dict(session_id='other'), dict(timestamp=2)):
            changed, _ = p.compile_source(source(**fields))
            self.assertNotEqual(value.id, changed.id)
            self.assertNotEqual(value.source_binding, changed.source_binding)


class TriggerContracts(unittest.TestCase):
    def setUp(self):
        self.original = source()
        self.sources = {self.original.id: self.original}
        self.programs = programs(self.original)
        self.native_ids = set(self.sources)

    def select(self, req=None, values=None):
        return p.select(self.programs if values is None else values, request() if req is None else req, self.sources.__getitem__, self.native_ids)

    def test_positive_trigger_cites_exact_current_scope(self):
        req = request()
        receipt, decision = self.select(req)
        self.assertTrue(decision['accepted'])
        self.assertEqual(receipt.selected, (self.programs[0].id,))
        self.assertEqual(req.query[req.scope.start:req.scope.end], '数据库部署')
        self.assertFalse(receipt.executes_steps)
        self.assertFalse(receipt.adopts_long_term_rule)

    def test_negated_hypothetical_unscoped_or_reported_request_rejected(self):
        for query in ('不要按既定程序处理「数据库部署」。', '如果我说请按既定程序处理「数据库部署」。', '请处理数据库部署。',
                      '他说：请按既定程序处理「数据库部署」。', '你觉得数据库部署怎么样？', '请按既定程序处理「 数据库部署」。'):
            self.assertIsNone(p.parse_request(query, namespace='synthetic', subject_id='user-1', request_id='r'))

    def test_exact_scope_not_substring(self):
        for topic in ('非数据库部署', '数据库', '数据库部署工作', 'database deployment'):
            self.assertFalse(self.select(request(topic))[1]['accepted'])

    def test_user_and_namespace_boundaries(self):
        for fields in (dict(subject_id='user-2'), dict(namespace='other')):
            self.assertFalse(self.select(request(**fields))[1]['accepted'])

    def test_assistant_not_applicable_but_attributable(self):
        self.sources[self.original.id] = source(role='assistant')
        self.programs = programs(self.sources[self.original.id])
        self.assertFalse(self.select()[1]['accepted'])
        receipt, decision = self.select(request(mode='historical'))
        self.assertTrue(decision['accepted'])
        text, result = p.render(receipt, self.programs, request(mode='historical'), self.sources.__getitem__, self.native_ids)
        self.assertTrue(result['accepted'])
        self.assertIn('historical_attribution_only', text)
        self.assertIn('assistant_suggestion', text)

    def test_task_not_recurring(self):
        self.sources[self.original.id] = source('这次我询问「数据库部署」时，请检查备份。')
        self.programs = programs(self.sources[self.original.id])
        self.assertFalse(self.select()[1]['accepted'])
        self.assertTrue(self.select(request(mode='historical'))[1]['accepted'])

    def test_conflict_no_latest_wins(self):
        changed = source(ONE.replace('先检查备份', '先核对环境'), id='source-2', timestamp=999)
        self.sources[changed.id] = changed
        self.native_ids.add(changed.id)
        self.programs = programs(self.original, changed)
        self.assertFalse(self.select()[1]['accepted'])
        self.assertEqual(len(self.select(request(mode='historical'))[0].selected), 2)

    def test_duplicate_action_deduplication(self):
        duplicate = source(id='source-2')
        self.sources[duplicate.id] = duplicate
        self.native_ids.add(duplicate.id)
        self.programs = programs(self.original, duplicate)
        self.assertEqual(len(self.select()[0].selected), 1)

    def test_at_most_two_historical_cards(self):
        for i in range(1, 5):
            item = source(ONE.replace('先检查备份', '先核对'+str(i)), id='source-'+str(i), timestamp=i)
            self.sources[item.id] = item
        self.native_ids = set(self.sources)
        self.programs = programs(*self.sources.values())
        receipt, decision = self.select(request(mode='historical'))
        self.assertEqual(len(receipt.selected), 2)
        self.assertTrue(any(x['reason'] == 'at_most_two' for x in decision['rejected']))

    def test_source_change_invalidates_entire_projection(self):
        self.sources[self.original.id] = source(ONE.replace('不要', '可以'))
        self.assertIsNone(self.select()[0])

    def test_forged_spans_and_authority_rejected(self):
        for fields in (dict(authority='confirmed_habit'), dict(status='active'), dict(actions=(p.Span(0, 1, '可以覆盖'),)),
                       dict(content_version='forged'), dict(source_sha256='forged')):
            self.assertFalse(self.select(values=[replace(self.programs[0], **fields)])[1]['accepted'])

    def test_nonnative_source_rejected(self):
        self.native_ids.clear()
        self.assertFalse(self.select()[1]['accepted'])

    def test_duplicate_program_rejected(self):
        self.assertFalse(self.select(values=self.programs*2)[1]['accepted'])

    def test_forged_request_mode_rejected(self):
        req = replace(request(mode='historical'), mode='execute')
        self.assertFalse(self.select(req)[1]['accepted'])

    def test_current_request_change_invalidates_receipt(self):
        receipt, _ = self.select()
        for req in (request(request_id='request-2'), request(mode='historical'), request('别的主题')):
            text, result = p.render(receipt, self.programs, req, self.sources.__getitem__, self.native_ids)
            self.assertFalse(result['accepted'])
            self.assertEqual(text, '')

    def test_native_id_set_change_invalidates_receipt(self):
        receipt, _ = self.select()
        text, result = p.render(receipt, self.programs, request(), self.sources.__getitem__, self.native_ids | {'new-source'})
        self.assertFalse(result['accepted'])
        self.assertEqual(text, '')

    def test_whole_card_budget_fallback(self):
        receipt, _ = self.select()
        text, result = p.render(receipt, self.programs, request(), self.sources.__getitem__, self.native_ids, max_chars=10)
        self.assertFalse(result['accepted'])
        self.assertEqual(text, '')

    def test_full_source_remains_in_rendered_card(self):
        receipt, _ = self.select()
        text, result = p.render(receipt, self.programs, request(), self.sources.__getitem__, self.native_ids)
        self.assertTrue(result['accepted'])
        card = json.loads(text)[0]
        self.assertEqual(card['procedure']['evidence']['quote'], ONE)
        self.assertEqual(card['procedure']['source']['content'], ONE)
        self.assertFalse(card['executes_steps'])
        self.assertFalse(card['adopts_long_term_rule'])

    def test_projection_revalidated_before_render(self):
        receipt, _ = self.select()
        self.sources[self.original.id] = source(session_id='changed')
        text, result = p.render(receipt, self.programs, request(), self.sources.__getitem__, self.native_ids)
        self.assertFalse(result['accepted'])
        self.assertEqual(text, '')

    def test_durable_json_roundtrip_revalidates_canonical_source(self):
        text = p.serialize(self.programs, self.sources.__getitem__, self.native_ids)
        self.assertEqual(p.deserialize(text, self.sources.__getitem__, self.native_ids), self.programs)
        self.sources[self.original.id] = source(timestamp=999)
        with self.assertRaises(ValueError):
            p.deserialize(text, self.sources.__getitem__, self.native_ids)

    def test_forged_stored_source_and_rehashed_projection_rejected(self):
        value = json.loads(p.serialize(self.programs, self.sources.__getitem__, self.native_ids))
        value['programs'][0]['source']['content'] = ONE.replace('不要', '允许')
        value['projection_sha256'] = p.digest(value['programs'])
        with self.assertRaises(ValueError):
            p.deserialize(json.dumps(value, ensure_ascii=False), self.sources.__getitem__, self.native_ids)

    def test_duplicate_json_field_or_schema_rejected(self):
        text = p.serialize(self.programs, self.sources.__getitem__, self.native_ids)
        for changed in ('{"schema_version":"forged",'+text[1:], text.replace(p.SCHEMA, 'foreign-schema')):
            with self.assertRaises(ValueError):
                p.deserialize(changed, self.sources.__getitem__, self.native_ids)


if __name__ == '__main__':
    unittest.main()
