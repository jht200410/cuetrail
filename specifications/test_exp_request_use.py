"""Synthetic tests of one-request authorization without proposal promotion."""
from dataclasses import replace
import unittest
from cuetrail.experimental import evidence as g
from cuetrail.experimental.request_use import authorize_once


def procedure():
    text='When preparing a deployment, first run tests, then create a backup.'
    source=dict(id='assistant-steps',role='assistant',content=text,session_id='s',timestamp=1)
    draft=dict(source_id=source['id'],kind='ordered_procedure',condition_quote='When preparing a deployment',
               scope_quote='deployment',action_quotes=['run tests','create a backup'],connecting_quote=text)
    p,reason=g.validate_draft(draft,source)
    assert reason=='valid'
    return p


class Contracts(unittest.TestCase):
    def setUp(self):
        self.p=procedure()
        self.q='For this deployment, follow the workflow you suggested earlier.'

    def test_explicit_request_creates_only_request_local_permission(self):
        use,reason=authorize_once(self.p,self.q,'request1',[self.p])
        self.assertEqual(reason,'explicit_request_only');self.assertTrue(use.matches('request1',self.q))
        self.assertFalse(use.adopts_standing_rule);self.assertEqual(use.source_authority,'assistant_suggestion')
        self.assertEqual(self.p.status,'unconfirmed');self.assertEqual(self.p.lifetime,'proposal')

    def test_permission_cannot_transfer_to_another_request_or_text(self):
        use,_=authorize_once(self.p,self.q,'request1',[self.p])
        self.assertFalse(use.matches('request2',self.q));self.assertFalse(use.matches('request1','another task'))

    def test_generic_task_or_denial_does_not_authorize_proposal(self):
        for q in ['Help me with a deployment.','For deployment, do not follow the workflow you suggested earlier.']:
            use,reason=authorize_once(self.p,q,'r',[self.p]);self.assertIsNone(use)

    def test_ambiguous_prior_plans_abstain(self):
        other=replace(self.p,id='other',action_quotes=('skip tests','create a backup'))
        use,reason=authorize_once(self.p,self.q,'r',[self.p,other])
        self.assertIsNone(use);self.assertEqual(reason,'ambiguous_proposal_reference')

    def test_known_user_constraint_cannot_be_overridden(self):
        binding=replace(self.p,id='binding',authority='user_constraint',status='source_grounded',lifetime='recurring')
        use,reason=authorize_once(self.p,self.q,'r',[self.p,binding])
        self.assertIsNone(use);self.assertEqual(reason,'binding_user_constraint_requires_joint_validation')

    def test_explicit_request_does_not_prove_unknown_if_condition(self):
        p=replace(self.p,condition_quote='If rain starts')
        use,reason=authorize_once(p,self.q,'r',[p]);self.assertIsNone(use)
        self.assertEqual(reason,'unknown_contingent_prerequisite')

    def test_question_about_adoption_is_not_permission_to_follow(self):
        q='For deployment, should I follow the workflow you suggested earlier?'
        self.assertIsNone(authorize_once(self.p,q,'r',[self.p])[0])

    def test_conditional_or_alternative_request_is_not_unconditional_permission(self):
        for q in ['If approval arrives, follow your workflow for deployment.',
                  'For deployment, follow a different workflow instead of the workflow you suggested earlier.']:
            self.assertIsNone(authorize_once(self.p,q,'r',[self.p])[0])

    def test_polite_direct_request_can_be_considered_without_adoption(self):
        q='Could you follow the workflow you suggested earlier for this deployment?'
        use,reason=authorize_once(self.p,q,'r',[self.p])
        self.assertEqual(reason,'explicit_request_only');self.assertFalse(use.adopts_standing_rule)


if __name__=='__main__':unittest.main(verbosity=2)
