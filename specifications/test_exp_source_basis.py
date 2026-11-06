"""Synthetic source authority regressions, independent of model-selected kind."""
from dataclasses import asdict
import unittest
from cuetrail.experimental import evidence as g


def compile_fixture(text,actions,role='user',kind='ordered_procedure'):
    source=dict(id='synthetic',role=role,session_id='s',timestamp=1,content=text)
    draft=dict(source_id='synthetic',kind=kind,condition_quote='Before every deployment',scope_quote='deployment',
               action_quotes=actions,connecting_quote=text)
    p,reason=g.validate_draft(draft,source)
    assert p is not None,reason
    return p,draft,source


class Contracts(unittest.TestCase):
    def test_explicit_routine_is_reported_despite_verb_or_nested_adverb(self):
        for clause,action in [('I usually first run tests','run tests'),
                              ('I usually first check tests','check tests'),
                              ('I usually check tests first','check tests')]:
            p,_,_=compile_fixture('Before every deployment, '+clause+', then create a backup.',
                                  [action,'create a backup'])
            self.assertEqual(p.authority,'user_reported_procedure')
            self.assertEqual(p.source_basis,'explicit_routine_self_report')
            self.assertEqual(p.lifetime,'recurring');self.assertEqual(p.schema_version,5)

    def test_reported_habit_basis_survives_model_kind_choice(self):
        text='Before every deployment, I usually check tests first, then create a backup.'
        ordered,_,_=compile_fixture(text,['check tests','create a backup'])
        habit,_,_=compile_fixture(text,['check tests','create a backup'],kind='habit')
        self.assertEqual(ordered.source_basis,habit.source_basis)
        self.assertEqual(habit.authority,'user_reported_habit')
        self.assertNotEqual(ordered.kind,habit.kind)

    def test_assistant_self_report_words_never_obtain_user_authority(self):
        p,_,_=compile_fixture('Before every deployment, I usually check tests first, then create a backup.',
                             ['check tests','create a backup'],role='assistant')
        self.assertEqual(p.authority,'assistant_suggestion');self.assertEqual(p.source_basis,'assistant_proposal')
        self.assertEqual(p.status,'unconfirmed');self.assertEqual(p.lifetime,'proposal')

    def test_personal_future_statement_does_not_prove_habit(self):
        p,_,_=compile_fixture('Before every deployment, I will first check tests, then create a backup.',
                             ['check tests','create a backup'])
        self.assertEqual(p.source_basis,'personal_procedure_statement')
        self.assertEqual(p.authority,'user_reported_procedure');self.assertEqual(p.lifetime,'task_bound')

    def test_polite_current_request_keeps_request_provenance(self):
        p,_,_=compile_fixture('Before every deployment, please first check tests, then create a backup.',
                             ['check tests','create a backup'])
        self.assertEqual(p.source_basis,'user_request');self.assertEqual(p.authority,'user_requested_procedure')
        self.assertEqual(p.lifetime,'task_bound')

    def test_explicit_constraint_keeps_its_own_basis(self):
        p,_,_=compile_fixture('Before every deployment, I must check tests first, then create a backup.',
                             ['check tests','create a backup'],kind='conditional_constraint')
        self.assertEqual(p.authority,'user_constraint');self.assertEqual(p.source_basis,'explicit_user_constraint')

    def test_schema_revision_changes_identity_even_for_unchanged_authority(self):
        p,draft,source=compile_fixture('Before every deployment, I usually check tests first, then create a backup.',
                                       ['check tests','create a backup'])
        old_id=g.digest([source['id'],p.evidence_start,p.evidence_quote,p.signature,draft['action_quotes'],draft['kind']])
        self.assertNotEqual(p.id,old_id)
        self.assertIn('source_basis=explicit_routine_self_report',g.card(p,'execute'))
        self.assertEqual(asdict(p)['source_basis'],'explicit_routine_self_report')


if __name__=='__main__':unittest.main(verbosity=2)
