"""Synthetic polarity contracts; no datasets or models."""
import unittest
from cuetrail.experimental import evidence as g


class ActionGovernance(unittest.TestCase):
    def check(self,text,actions,expected,condition='When packing lunches',scope='packing lunches',kind='conditional_constraint'):
        source=dict(id='synthetic',role='user',content=text,session_id='synthetic',timestamp=1)
        draft=dict(source_id='synthetic',condition_quote=condition,scope_quote=scope,
            action_quotes=actions,connecting_quote=text,kind=kind)
        obj,reason=g.validate_draft(draft,source)
        self.assertEqual(expected,obj is not None,reason)
        if obj:self.assertIn(text,g.card(obj,'execute'))
        return obj,reason

    def test_omitted_not_rejected(self):
        self.assertEqual('action_polarity_omitted',self.check('When packing lunches, I must not include sesame.',['include sesame'],False)[1])

    def test_preserved_not_accepted(self):
        self.check('When packing lunches, I must not include sesame.',['not include sesame'],True)

    def test_omitted_avoid_rejected(self):
        self.assertEqual('action_governor_omitted',self.check('When packing lunches, I must avoid peanuts.',['peanuts'],False)[1])

    def test_preserved_avoid_then_positive_action(self):
        self.check('When packing lunches, I must avoid peanuts and use clean utensils.',['avoid peanuts','use clean utensils'],True)

    def test_omitted_never_rejected(self):
        self.check('When packing lunches, I must never include sesame.',['include sesame'],False)

    def test_preserved_never_accepted(self):
        self.check('When packing lunches, I must never include sesame.',['never include sesame'],True)

    def test_omitted_cannot_rejected(self):
        self.check('When packing lunches, I cannot include sesame.',['include sesame'],False)

    def test_ordered_dont_rejected_if_omitted(self):
        self.check("Before a release, I usually first check the license, then don't publish private keys.",
            ['check the license','publish private keys'],False,'Before a release','release','ordered_procedure')

    def test_ordered_dont_preserved(self):
        self.check("Before a release, I usually first check the license, then don't publish private keys.",
            ['check the license',"don't publish private keys"],True,'Before a release','release','ordered_procedure')

    def test_negated_condition_is_not_negated_action(self):
        self.check('If the lid is not closed, I must check the seal.',['check the seal'],True,
            'If the lid is not closed','lid')

    def test_ordinary_word_notebook_is_not_negation(self):
        self.check('When packing lunches, I must use my notebook.',['use my notebook'],True)

    def test_schema5_identity(self):
        obj,_=self.check('When packing lunches, I must avoid peanuts.',['avoid peanuts'],True)
        self.assertEqual(5,obj.schema_version)

    def test_chinese_action_polarity(self):
        self.check('当准备午餐时，我必须不要加入芝麻。',['加入芝麻'],False,'当准备午餐时','准备午餐')
        self.check('当准备午餐时，我必须不要加入芝麻。',['不要加入芝麻'],True,'当准备午餐时','准备午餐')

    def test_chinese_negated_context_does_not_negate_action(self):
        self.check('当我不能联网时，我必须使用离线手册。',['使用离线手册'],True,'当我不能联网时','不能联网')


if __name__=='__main__':unittest.main()
