"""Synthetic source/version proofs only;no database migration or model calls."""
from dataclasses import replace
import json
from pathlib import Path
import unittest
from cuetrail.experimental import versions as v


def item(sid,action,time,text=None,old=None,role='user'):
    condition='Before rehearsals'
    content=text or (f'{condition}, please replace "{old}" with "{action}".' if old else f'{condition}, {action}.')
    source=dict(id=sid,role=role,session_id='synthetic',timestamp=time,content=content)
    draft=dict(source_id=sid,condition_quote=condition,scope_quote='rehearsals',action_quotes=[action],
               connecting_quote=content,kind='conditional_constraint')
    p,reason=v.g.validate_draft(draft,source)
    assert p is not None,reason
    return p,draft,source


def govern(items):
    sources={source['id']:source for _,_,source in items}
    return v.govern([p for p,_,_ in items],{p.id:draft for p,draft,_ in items},sources.__getitem__)


class VersionProofContracts(unittest.TestCase):
    def test_old_target_case_variants_cannot_replace_literal_action(self):
        old=item('a','I must lock the case',1)
        for target in ('I MUST LOCK THE CASE','i must lock the case'):
            with self.subTest(target=target):
                new=item('b','I must check the bow',2,old=target)
                result,audits=govern([old,new])
                self.assertTrue(all(p.status=='conflicting' for p in result))
                self.assertIsNone(audits[-1]['replacement_link'])

    def test_only_grammar_keywords_may_ignore_case(self):
        old=item('a','I must lock the case',1)
        text='Before rehearsals, PLEASE REPLACE "I must lock the case" WITH "I must check the bow".'
        new=item('b','I must check the bow',2,text=text)
        result,audits=govern([old,new])
        self.assertEqual(['superseded','source_grounded'],[p.status for p in result])
        self.assertIsNotNone(audits[-1]['replacement_link'])

    def test_unicode_case_folding_cannot_substitute_for_literal_target(self):
        old=item('a','I must keep the K case',1)
        new=item('b','I must check the bow',2,old='I must keep the K case')
        result,audits=govern([old,new])
        self.assertTrue(all(p.status=='conflicting' for p in result))
        self.assertIsNone(audits[-1]['replacement_link'])

    def test_unrelated_markers_cannot_replace_either_side_of_relation(self):
        old=item('a','I must lock the case',1)
        for text in ('From now on, I use a blue notebook. Before rehearsals, I must check the bow.',
                     'Before rehearsals, I must check the bow. I will replace the notebook.'):
            new=item('b','I must check the bow',2,text=text)
            result,audits=govern([old,new])
            self.assertEqual(['conflicting','conflicting'],[p.status for p in result])
            self.assertIsNone(audits[-1]['replacement_link']);self.assertFalse(result[-1].supersedes_ids)

    def test_exact_quoted_replacement_has_complete_source_bound_link(self):
        old=item('a','I must lock the case',1)
        new=item('b','I must check the bow',2,old=old[0].action_quotes[0])
        result,audits=govern([old,new]);link=audits[-1]['replacement_link']
        self.assertEqual(['superseded','source_grounded'],[p.status for p in result])
        self.assertEqual((old[0].id,),result[-1].supersedes_ids);self.assertEqual(2,result[-1].version)
        self.assertEqual(new[2]['content'],link['evidence_quote']);self.assertEqual(new[0].source_sha256,link['source_sha256'])
        self.assertFalse(audits[-1]['automatic_adoption'])

    def test_unknown_or_equal_timestamp_cannot_prove_replacement(self):
        old=item('a','I must lock the case',1)
        for time in (None,1):
            result,audits=govern([old,item('b','I must check the bow',time,old=old[0].action_quotes[0])])
            self.assertTrue(all(p.status=='conflicting' for p in result))
            self.assertEqual('replacement_order_unknown',audits[-1]['reason'])

    def test_partial_old_action_is_not_a_target_proof(self):
        old=item('a','I must never open the case',1)
        new=item('b','I must check the bow',2,old='open the case')
        result,audits=govern([old,new]);self.assertTrue(all(p.status=='conflicting' for p in result))
        self.assertIsNone(audits[-1]['replacement_link'])

    def test_negated_or_reported_replacement_sentence_is_not_executed(self):
        old=item('a','I must lock the case',1)
        for prefix in ('Do not follow this: ','A friend suggested: '):
            text=prefix+'Before rehearsals, please replace "I must lock the case" with "I must check the bow".'
            result,audits=govern([old,item('b','I must check the bow',2,text=text)])
            self.assertTrue(all(p.status=='conflicting' for p in result));self.assertIsNone(audits[-1]['replacement_link'])

    def test_ambiguous_old_variants_require_resolution_of_every_target(self):
        a=item('a','I must lock the case',1);b=item('b','I must tune the cello',2)
        c=item('c','I must check the bow',3,old=a[0].action_quotes[0])
        result,audits=govern([a,b,c]);self.assertTrue(all(p.status=='conflicting' for p in result))
        self.assertEqual('replacement_target_not_unique_single_action',audits[-1]['reason'])

    def test_known_explicit_chain_does_not_reactivate_old_superseded_versions(self):
        a=item('a','I must lock the case',1)
        b=item('b','I must check the bow',2,old=a[0].action_quotes[0])
        c=item('c','I must tune the cello',3,old=b[0].action_quotes[0])
        result,audits=govern([c,a,b])
        self.assertEqual([1,2,3],[p.version for p in result])
        self.assertEqual(['superseded','superseded','source_grounded'],[p.status for p in result])
        self.assertEqual((b[0].id,),result[-1].supersedes_ids)

    def test_source_draft_or_projection_change_rejected_before_governance(self):
        a=item('a','I must lock the case',1)
        with self.assertRaisesRegex(ValueError,'derivation or source changed'):
            govern([(replace(a[0],version=99),a[1],a[2])])
        with self.assertRaisesRegex(ValueError,'derivation or source changed'):
            govern([(a[0],a[1],dict(a[2],role='assistant'))])

    def test_identical_action_evidence_does_not_increment_or_adopt(self):
        result,audits=govern([item('a','I must lock the case',1),item('b','I must lock the case',2)])
        self.assertEqual([1,1],[p.version for p in result]);self.assertTrue(all(not p.supersedes_ids for p in result))
        self.assertTrue(all(not audit['automatic_adoption'] for audit in audits))

    def test_assistant_suggestions_never_replace_or_promote(self):
        a=item('a','I must lock the case',1,role='assistant')
        b=item('b','I must check the bow',2,old=a[0].action_quotes[0],role='assistant')
        result,audits=govern([a,b]);self.assertTrue(all(p.status=='unconfirmed' for p in result))
        self.assertTrue(all(p.authority=='assistant_suggestion' for p in result))
        self.assertIsNone(audits[-1]['replacement_link'])
