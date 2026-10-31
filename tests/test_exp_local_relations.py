"""Standalone synthetic checks for opt-in local Procedure relationship proofs."""
from copy import deepcopy
import unittest
from cuetrail.experimental import action_heads as r


def source(text,role='user'):
    return dict(id='synthetic-proof',role=role,session_id='example',timestamp=1,content=text)


def pointer(s,context,actions,kind='conditional_constraint'):
    view=r.backend.view(s)
    def unit(text):
        ids=[u.id for u in view.units if text in u.text]
        assert len(ids)==1
        return ids[0]
    return dict(view_id=view.id,condition_unit=unit(context),scope_unit=unit(context),
        action_units=[unit(text) for text in actions],kind=kind)


class LocalRelationProofs(unittest.TestCase):
    def test_discourse_example_is_not_applicability(self):
        s=source('For instance, we explored films that I never considered previously.')
        with self.assertRaisesRegex(r.backend.PointerError,'discourse_marker_not_applicability_scope'):
            r.materialize(pointer(s,'For instance',['we explored']),s)

    def test_past_mental_state_is_not_constraint(self):
        s=source('Before this experience, I had never appreciated the influence of a review.')
        with self.assertRaisesRegex(r.backend.PointerError,'constraint_not_at_action_head'):
            r.materialize(pointer(s,'Before this experience',['I had never appreciated']),s)

    def test_tail_make_sure_is_not_an_action_head(self):
        s=source('Before a bike ride, I plug in a drive to make sure the pictures are saved.')
        with self.assertRaisesRegex(r.backend.PointerError,'constraint_not_at_action_head'):
            r.materialize(pointer(s,'Before a bike ride',['I plug in']),s)

    def test_second_independent_action_cannot_borrow_first_modal(self):
        s=source('When preparing reports, I must cite sources, then I enjoy music.')
        with self.assertRaisesRegex(r.backend.PointerError,'constraint_not_at_action_head'):
            r.materialize(pointer(s,'When preparing reports',['I must cite','then I enjoy']),s)

    def test_must_admit_does_not_declare_constraint(self):
        s=source('When reviewing drafts, I must admit that the story is engaging.')
        with self.assertRaisesRegex(r.backend.PointerError,'discourse_modal_not_action_constraint'):
            r.materialize(pointer(s,'When reviewing drafts',['I must admit']),s)

    def test_local_constraint_keeps_complete_source_and_authority_witness(self):
        s=source('When packing lunches, I must not include sesame.')
        proof=r.materialize(pointer(s,'When packing lunches',['I must not include']),s)
        obj,reason=r.g.validate_draft(r.revalidate(proof,s),s)
        self.assertEqual('valid',reason);self.assertEqual(s['content'],obj.evidence_quote)
        w=proof['authority_witness'];self.assertEqual(w['quote'],s['content'][w['start']:w['end']])
        self.assertEqual('user_constraint',obj.authority);self.assertFalse(proof['automatic_adoption'])

    def test_unrelated_constraint_cannot_authorize_another_action(self):
        s=source('When preparing reports, I enjoy the weather. I must save source files.')
        p=pointer(s,'When preparing reports',['I enjoy the weather'])
        self.assertIsNotNone(r.backend.materialize(p,s))
        with self.assertRaisesRegex(r.backend.PointerError,'constraint_not_governing'):r.materialize(p,s)

    def test_unrelated_habit_cannot_authorize_another_action(self):
        s=source('When exercising, I feel alert. I usually read books.')
        p=pointer(s,'When exercising',['I feel alert'],kind='habit')
        with self.assertRaisesRegex(r.backend.PointerError,'habit_not_reported'):r.materialize(p,s)

    def test_incidental_preposition_is_not_a_condition(self):
        s=source('My notes for the meeting are ready. I must check the references.')
        with self.assertRaisesRegex(r.backend.PointerError,'condition_not_explicit'):r.materialize(pointer(s,'My notes for',['I must check']),s)

    def test_context_and_action_cannot_skip_a_sentence(self):
        s=source('When preparing reports, I enjoy the weather. I must cite sources.')
        with self.assertRaisesRegex(r.backend.PointerError,'actions_not_adjacent'):r.materialize(pointer(s,'When preparing reports',['I must cite']),s)

    def test_constraint_list_retains_governed_objects(self):
        s=source('When running backups, I must not copy private folders, public folders, or caches.')
        proof=r.materialize(pointer(s,'When running backups',['I must not copy']),s)
        self.assertIn('private folders, public folders, or caches',proof['draft']['action_quotes'][0])

    def test_chinese_constraints_keep_original_negation(self):
        s=source('当准备午餐时，我必须不要加入芝麻。')
        proof=r.materialize(pointer(s,'当准备午餐时',['我必须不要']),s)
        self.assertIn('不要',proof['draft']['action_quotes'][0])

    def test_assistant_ordered_steps_remain_unconfirmed(self):
        s=source('When deploying, first run tests, then create a backup.','assistant')
        proof=r.materialize(pointer(s,'When deploying',['first run tests','then create'],kind='ordered_procedure'),s)
        obj,_=r.g.validate_draft(proof['draft'],s)
        self.assertEqual('unconfirmed',obj.status);self.assertEqual('assistant_suggestion',obj.authority)

    def test_one_time_request_stays_task_bound(self):
        s=source('For this one response, please first list tools, then explain how to use them.')
        proof=r.materialize(pointer(s,'For this one response',['please first list','then explain'],kind='ordered_procedure'),s)
        self.assertEqual('task_bound',proof['lifetime'])

    def test_modified_source_or_offsets_cannot_reuse_proof(self):
        s=source('When writing reports, I must cite sources.')
        proof=r.materialize(pointer(s,'When writing reports',['I must cite']),s)
        modified=deepcopy(proof);modified['local_relation']['end']-=1
        with self.assertRaises(r.backend.PointerError):r.revalidate(modified,s)
        with self.assertRaises(r.backend.PointerError):r.revalidate(proof,dict(s,content=s['content']+' Changed.'))
