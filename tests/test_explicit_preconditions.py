"""Synthetic literal-prerequisite, authority and canonical-request adversaries."""
from dataclasses import asdict, replace
import json
import unittest

from cuetrail_governance import guarded as g

p=g.p
PROGRAM='每当我询问「恢复检查」且「环境=测试；备份=已验证」时，请遵守以下步骤：\n1. 先核对版本号。\n2. 不要删除副本，除非恢复验证全部通过。'
QUERY='在「环境=测试；备份=已验证」条件下，请按既定程序处理「恢复检查」。'


class PreconditionContracts(unittest.TestCase):
    def setUp(self):
        self.source=p.Source('program','synthetic','u1','s1','user',PROGRAM,10)
        self.current=p.Source('current','synthetic','u1','s2','user',QUERY,20)
        self.sources={v.id:v for v in (self.source,self.current)}
        self.native=set(self.sources)
        self.program,self.reason=g.compile_source(self.source)
        self.request=g.parse_request(self.current)

    def load(self,identity):
        return self.sources[identity]

    def select(self,programs=None,request=None,native=None):
        return g.select([self.program] if programs is None else programs,self.request if request is None else request,
                        self.load,self.native if native is None else native)

    def change_query(self,text):
        self.current=replace(self.current,content=text)
        self.sources[self.current.id]=self.current
        return g.parse_request(self.current)

    def test_full_representation_has_original_prerequisite_spans_and_step_order(self):
        self.assertEqual(self.reason,'valid')
        self.assertEqual(self.program.authority,'user_constraint')
        spans=[self.program.scope,self.program.condition,self.program.evidence,*self.program.actions]
        spans += [s for guard in self.program.prerequisites for s in (guard.field,guard.value,guard.evidence)]
        for span in spans:
            self.assertEqual(self.source.content[span.start:span.end],span.quote)
        self.assertEqual([v.field.quote for v in self.program.prerequisites],['环境','备份'])
        self.assertIn('除非恢复验证全部通过',self.program.actions[1].quote)

    def test_satisfied_literal_conditions_are_user_assertions_only(self):
        receipt,audit=self.select()
        self.assertTrue(audit['accepted'])
        self.assertFalse(audit['external_state_verified'])
        self.assertEqual(audit['evidence_basis'],'current_user_assertion_only')
        text,result=g.render(receipt,[self.program],self.request,self.load,self.native)
        self.assertTrue(result['accepted'])
        card=json.loads(text)[0]
        self.assertTrue(card['preconditions_witnessed_in_request'])
        self.assertFalse(card['external_state_verified'])
        self.assertFalse(card['executes_steps'])
        self.assertFalse(card['adopts_long_term_rule'])
        self.assertEqual(card['current_request']['source']['id'],'current')

    def test_missing_and_different_required_fact_abstain(self):
        for text in (QUERY.replace('；备份=已验证',''),QUERY.replace('已验证','未验证'),QUERY.replace('环境=测试','环境=生产')):
            req=self.change_query(text)
            receipt,audit=self.select(request=req)
            self.assertFalse(audit['accepted'])
            self.assertEqual(receipt.selected,())
            self.assertEqual(audit['rejected'][0]['reason'],'missing_or_different_prerequisite_witness')

    def test_topic_match_without_prerequisite_grammar_is_unsupported(self):
        for text in ('请按既定程序处理「恢复检查」。','在测试环境恢复备份。',QUERY+'不必检查备份。'):
            self.assertIsNone(self.change_query(text))

    def test_predicate_order_does_not_change_matching_but_changes_request_binding(self):
        old,_=self.select()
        req=self.change_query(QUERY.replace('环境=测试；备份=已验证','备份=已验证；环境=测试'))
        fresh,audit=self.select(request=req)
        self.assertTrue(audit['accepted'])
        self.assertEqual(old.selected,fresh.selected)
        self.assertNotEqual(old.request_binding,fresh.request_binding)
        self.assertEqual(g.render(old,[self.program],req,self.load,self.native)[0],'')

    def test_extra_nonconflicting_assertion_is_allowed_and_source_bound(self):
        req=self.change_query(QUERY.replace('备份=已验证','备份=已验证；区域=本地'))
        receipt,audit=self.select(request=req)
        self.assertTrue(audit['accepted'])
        text,_=g.render(receipt,[self.program],req,self.load,self.native)
        self.assertEqual(json.loads(text)[0]['current_request']['assertions'][2]['evidence']['quote'],'区域=本地')

    def test_duplicate_empty_alternative_and_uncertain_assertions_rejected(self):
        facts=('环境=测试；环境=测试','环境=测试；环境=生产','环境=测试；','环境=测试；；备份=已验证',
               '环境=测试或生产；备份=已验证','环境=测试；备份=未知','环境=测试；备份=未确认',
               '环境 =测试；备份=已验证','环境= 测试；备份=已验证','环境==测试；备份=已验证')
        for value in facts:
            self.assertIsNone(self.change_query('在「'+value+'」条件下，请按既定程序处理「恢复检查」。'))

    def test_unsupported_program_prerequisites_not_partial_programs(self):
        for text in (PROGRAM.replace('环境=测试；备份=已验证','环境=测试；环境=生产'),
                     PROGRAM.replace('已验证','可能已验证'),PROGRAM.replace('；备份=已验证','；'),
                     PROGRAM.replace('1.','2.',1),PROGRAM+'\n'):
            self.assertIsNone(g.compile_source(replace(self.source,content=text))[0])

    def test_one_time_and_reported_habit_do_not_create_programs(self):
        for text in (PROGRAM.replace('每当','这次',1),'我通常这么做：'+PROGRAM,'他说：'+PROGRAM):
            self.assertIsNone(g.compile_source(replace(self.source,content=text))[0])

    def test_assistant_proposal_stays_unconfirmed_despite_current_scope_match(self):
        self.source=replace(self.source,role='assistant')
        self.sources[self.source.id]=self.source
        self.program=g.compile_source(self.source)[0]
        receipt,audit=self.select()
        self.assertFalse(audit['accepted'])
        self.assertEqual(self.program.authority,'assistant_suggestion')
        self.assertEqual(self.program.lifetime,'proposal')
        self.assertFalse(receipt.adopts_long_term_rule)

    def test_current_assertion_must_be_native_canonical_user_source(self):
        self.assertIsNone(self.select(native=self.native-{'current'})[0])
        self.sources[self.current.id]=replace(self.current,session_id='forged')
        self.assertIsNone(self.select()[0])
        for role in ('assistant','tool','system'):
            self.assertIsNone(g.parse_request(replace(self.current,role=role)))

    def test_source_user_and_namespace_boundaries(self):
        for key,value in (('subject_id','u2'),('namespace','other')):
            source=replace(self.source,**{key:value})
            self.sources[source.id]=source
            program=g.compile_source(source)[0]
            self.assertFalse(self.select(programs=[program])[1]['accepted'])

    def test_exact_scope_not_substring_or_synonym(self):
        for topic in ('恢复','恢复检查扩展','备份检查'):
            req=self.change_query(QUERY.replace('恢复检查',topic))
            self.assertFalse(self.select(request=req)[1]['accepted'])

    def test_guard_value_not_substring_or_case_insensitive(self):
        for value in ('测试环境','TEST','test','测试2'):
            req=self.change_query(QUERY.replace('环境=测试','环境='+value))
            self.assertFalse(self.select(request=req)[1]['accepted'])

    def test_unknown_or_future_program_chronology_cannot_apply(self):
        for timestamp in (None,20,30):
            source=replace(self.source,timestamp=timestamp)
            self.sources[source.id]=source
            program=g.compile_source(source)[0]
            self.assertFalse(self.select(programs=[program])[1]['accepted'])
        self.assertIsNone(g.parse_request(replace(self.current,timestamp=None)))
        self.assertIsNone(g.parse_request(replace(self.current,timestamp=True)))

    def test_specific_matching_variant_does_not_override_other_matching_actions(self):
        general=replace(self.source,id='general',content=PROGRAM.replace('；备份=已验证','').replace('核对版本号','检查备份'),timestamp=9)
        self.sources[general.id]=general
        self.native.add(general.id)
        program=g.compile_source(general)[0]
        receipt,audit=self.select(programs=[self.program,program])
        self.assertFalse(audit['accepted'])
        self.assertEqual(receipt.selected,())
        self.assertEqual(audit['reason'],'conflicting_applicable_actions')
        self.assertEqual(set(audit['conflicting_program_ids']),{self.program.id,program.id})

    def test_nonmatching_variant_does_not_create_false_current_conflict(self):
        other=replace(self.source,id='production',content=PROGRAM.replace('环境=测试','环境=生产').replace('核对版本号','检查备份'))
        self.sources[other.id]=other
        self.native.add(other.id)
        program=g.compile_source(other)[0]
        receipt,audit=self.select(programs=[self.program,program])
        self.assertTrue(audit['accepted'])
        self.assertEqual(receipt.selected,(self.program.id,))

    def test_history_preserves_attribution_without_precondition_truth_claim(self):
        source=replace(self.source,id='advice',role='assistant',content=PROGRAM.replace('核对版本号','检查备份'))
        self.sources[source.id]=source
        self.native.add(source.id)
        advice=g.compile_source(source)[0]
        req=self.change_query('回顾我关于「恢复检查」的条件程序。')
        receipt,audit=self.select(programs=[self.program,advice],request=req)
        self.assertTrue(audit['accepted'])
        text,_=g.render(receipt,[self.program,advice],req,self.load,self.native)
        cards=json.loads(text)
        self.assertEqual(len(cards),2)
        self.assertEqual({v['program']['source']['role'] for v in cards},{'user','assistant'})
        self.assertTrue(all(v['display_mode']=='historical_attribution_only' and not v['preconditions_witnessed_in_request'] for v in cards))

    def test_changed_program_or_request_invalidates_existing_receipt(self):
        old,_=self.select()
        self.sources[self.current.id]=replace(self.current,timestamp=21)
        self.assertEqual(g.render(old,[self.program],self.request,self.load,self.native)[0],'')
        self.sources[self.current.id]=self.current
        self.sources[self.source.id]=replace(self.source,content=PROGRAM.replace('备份=已验证','备份=待验证'))
        self.assertIsNone(self.select()[0])

    def test_forged_guard_action_version_and_request_metadata_rejected(self):
        for program in (replace(self.program,content_version='forged'),replace(self.program,authority='user_confirmed_habit'),
                        replace(self.program,prerequisites=()),replace(self.program,actions=())):
            self.assertIsNone(self.select(programs=[program])[0])
        req=replace(self.request,external_state_verified=True)
        self.assertIsNone(self.select(request=req)[0])

    def test_duplicate_sources_budget_and_maximum_two_cards(self):
        self.assertIsNone(self.select(programs=[self.program,self.program])[0])
        receipt,_=self.select()
        for budget in (0,True,1,-1):
            self.assertEqual(g.render(receipt,[self.program],self.request,self.load,self.native,max_chars=budget)[0],'')
        self.assertLessEqual(len(receipt.selected),2)

    def test_durable_roundtrip_reconstructs_guards_from_canonical_sources(self):
        text=g.serialize([self.program],self.load,self.native)
        self.assertEqual(g.deserialize(text,self.load,self.native),[self.program])
        self.sources[self.source.id]=replace(self.source,content=PROGRAM.replace('环境=测试','环境=生产'))
        with self.assertRaises(ValueError):
            g.deserialize(text,self.load,self.native)

    def test_stored_forgery_and_duplicate_json_fields_rejected(self):
        text=g.serialize([self.program],self.load,self.native)
        value=json.loads(text)
        value['programs'][0]['prerequisites'][0]['value']['quote']='生产'
        with self.assertRaises(ValueError):
            g.deserialize(json.dumps(value,ensure_ascii=False),self.load,self.native)
        duplicate=text.replace('"schema_version":','"schema_version":"forged","schema_version":',1)
        with self.assertRaises(ValueError):
            g.deserialize(duplicate,self.load,self.native)

    def test_unicode_topics_keep_scope_and_literal_condition_witnesses(self):
        topics=['恢复🧪','发布/检查','Résumé','项目甲','デプロイ','배포','مشروع','αβγ']
        for topic in topics:
            source=replace(self.source,content=PROGRAM.replace('恢复检查',topic))
            current=replace(self.current,content=QUERY.replace('恢复检查',topic))
            self.sources.update({source.id:source,current.id:current})
            program=g.compile_source(source)[0]
            req=g.parse_request(current)
            receipt,audit=self.select(programs=[program],request=req)
            self.assertTrue(audit['accepted'])
            self.assertEqual(program.scope.quote,topic)
            self.assertEqual(req.scope.quote,topic)
            self.assertFalse(receipt.executes_steps)


if __name__=='__main__':
    unittest.main()
