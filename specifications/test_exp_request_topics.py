"""CPU authority,lifecycle,scope and fresh-source trigger contracts."""
from dataclasses import asdict,replace
import json,tempfile,unittest
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from cuetrail.experimental import request_topics as p


def source(text,role='user',ident='synthetic',timestamp=1):
    return dict(id=ident,role=role,session_id='synthetic-session',timestamp=timestamp,content=text)


class RequestProgramContracts(unittest.TestCase):
    def compile(self,text,**kwargs):
        original=source(text,**kwargs);value,reason=p.compile_view(original)
        self.assertEqual('valid',reason);self.assertIsNotNone(value)
        return value,original
    def request(self,programs,sources,query='Help me with testing updates.',mode='execute'):
        return dict(query=query,mode=mode,request_id='synthetic-request',source_loader=sources.__getitem__,native_ids=set(sources))
    def test_negative_action_and_original_citation_retained(self):
        value,original=self.compile('Never include sesame when I ask about lunch plans. ->-> 3,8')
        self.assertEqual('Never include sesame',value.actions[0].quote)
        self.assertEqual('when I ask about lunch plans',value.condition.quote)
        self.assertEqual('lunch plans',value.scope.quote);self.assertEqual(original['content'],value.evidence.quote)
        for item in (value.scope,value.condition,value.evidence,*value.actions):
            self.assertEqual(item.quote,original['content'][item.start:item.end])
    def test_source_window_offsets_are_absolute_and_revalidated(self):
        text='Unrelated paragraph.\n\nAlways provide diagrams when I ask about geometry.\n\nAnother paragraph.'
        original=source(text);start=text.index('Always');end=text.index('\n\nAnother')
        value,reason=p.compile_view(dict(original,window_start=start,window_content=text[start:end]))
        self.assertEqual('valid',reason);self.assertEqual(start,value.actions[0].start)
        self.assertEqual(p.digest([asdict(value)]),p.audit([value],{'synthetic':original}.__getitem__,{'synthetic'}))
        self.assertEqual('noncanonical_window',p.compile_view(dict(original,window_start=start+1,window_content=text[start:end]))[1])
    def test_user_constraint_is_not_claimed_as_confirmed_habit(self):
        value,_=self.compile('Always check the cache when I ask about testing updates.')
        self.assertEqual(('user_constraint','recurring','source_grounded'),(value.authority,value.lifetime,value.status))
        self.assertNotIn('habit',value.source_basis)
    def test_assistant_suggestion_never_executes_or_adopts(self):
        value,original=self.compile('Always check the cache when I ask about testing updates.',role='assistant')
        request=self.request([value],{value.source_id:original});receipt,audit=p.select([value],**request)
        self.assertFalse(audit['accepted']);self.assertEqual([],receipt['selected'])
        self.assertEqual(('assistant_suggestion','proposal','unconfirmed'),(value.authority,value.lifetime,value.status))
        self.assertFalse(receipt['adopts_long_term_rule'])
    def test_one_time_marker_overrides_always(self):
        value,original=self.compile('Always provide examples for this response when I ask about testing updates.')
        self.assertEqual('task_bound',value.lifetime)
        request=self.request([value],{value.source_id:original});receipt,audit=p.select([value],**request)
        self.assertFalse(audit['accepted'])
        request['mode']='historical_procedure';receipt,audit=p.select([value],**request)
        self.assertTrue(audit['accepted']);self.assertEqual('historical_only',receipt['selected'][0]['decision'])
    def test_statements_reports_exceptions_and_unresolved_qualifiers_abstain(self):
        for text in (
            'Always feel cheerful when I ask about music.',
            'My teacher said Always provide diagrams when I ask about geometry.',
            'Always provide examples unless restricted when I ask about geometry.',
            'Always provide diagrams when I ask about geometry. Only if approved.',
            'Always provide diagrams when I ask about geometry if authorized.',
            'Always provide diagrams when I ask about geometry?',
        ):
            with self.subTest(text=text):self.assertIsNone(p.compile_view(source(text))[0])
    def test_full_topic_tokens_required_not_word_bag_or_substring(self):
        value,_=self.compile('Always check the cache when I ask about testing updates.')
        self.assertIsNotNone(p.witness(value,'Can you help with TESTING updates?'))
        for query in ('Help with updates after testing.','Help with testing.','Help with pretesting updates.','Help me with updates testing.'):
            self.assertIsNone(p.witness(value,query))
    def test_negated_alternative_topic_abstains(self):
        value,_=self.compile('Always check the cache when I ask about testing updates.')
        for query in ('Not testing updates:help with budgeting.','Help with budgeting rather than testing updates.','Help without testing updates.'):
            self.assertIsNone(p.witness(value,query))
    def test_two_same_source_scopes_do_not_fill_unrelated_slot(self):
        first,s1=self.compile('Always check the cache when I ask about testing updates.',ident='test')
        other,s2=self.compile('Always use labels when I ask about shipping parcels.',ident='ship')
        values=[first,other];request=self.request(values,dict(test=s1,ship=s2));receipt,audit=p.select(values,**request)
        self.assertTrue(audit['accepted']);self.assertEqual([first.id],[row['procedure_id'] for row in receipt['selected']])
    def test_conflicting_user_actions_block_execution_and_preserve_versions(self):
        a,s1=self.compile('Always include examples when I ask about testing updates.',ident='one')
        b,s2=self.compile('Never include examples when I ask about testing updates.',ident='two',timestamp=2)
        c,s3=self.compile('Always include examples when I ask about testing updates.',ident='three',timestamp=3)
        values=p.govern_versions([a,b,c]);self.assertEqual([1,2,1],[value.version for value in values])
        self.assertTrue(all(value.status=='conflicting' for value in values))
        receipt,audit=p.select(values,**self.request(values,dict(one=s1,two=s2,three=s3)))
        self.assertFalse(audit['accepted']);self.assertEqual([],receipt['selected'])
    def test_suggestion_does_not_replace_or_conflict_user_constraint(self):
        a,s1=self.compile('Always include examples when I ask about testing updates.',ident='one')
        b,s2=self.compile('Never include examples when I ask about testing updates.',ident='two',role='assistant')
        values=p.govern_versions([a,b]);receipt,audit=p.select(values,**self.request(values,dict(one=s1,two=s2)))
        self.assertEqual(['source_grounded','unconfirmed'],[value.status for value in values])
        self.assertEqual([a.id],[row['procedure_id'] for row in receipt['selected']])
    def test_source_metadata_authority_or_quote_tampering_rejects(self):
        value,original=self.compile('Always check the cache when I ask about testing updates.')
        for changed in (dict(original,session_id='other'),dict(original,role='assistant'),dict(original,content=original['content'].replace('cache','logs'))):
            request=self.request([value],{value.source_id:changed});self.assertFalse(p.select([value],**request)[1]['accepted'])
        forged=replace(value,scope=p.Span(value.scope.start,value.scope.end,'other subject'))
        self.assertFalse(p.select([forged],**self.request([forged],{value.source_id:original}))[1]['accepted'])
    def test_request_and_native_scope_bound_receipt(self):
        value,original=self.compile('Always check the cache when I ask about testing updates.')
        request=self.request([value],{value.source_id:original});receipt,audit=p.select([value],**request)
        self.assertEqual([value],p.materialize(receipt,[value],**request)[0])
        for changed in (dict(request,request_id='another'),dict(request,query=request['query']+' Please.'),dict(request,native_ids=set())):
            self.assertEqual([],p.materialize(receipt,[value],**changed)[0])
    def test_duplicate_exact_evidence_does_not_confirm_or_add_slot(self):
        a,s1=self.compile('Always check the cache when I ask about testing updates.',ident='a')
        b,s2=self.compile('Always check the cache when I ask about testing updates.',ident='b')
        values=p.govern_versions([a,b]);receipt,audit=p.select(values,**self.request(values,dict(a=s1,b=s2)))
        self.assertEqual(1,len(receipt['selected']));self.assertTrue(all(value.authority=='user_constraint' for value in values))
    def test_at_most_two_current_programs_and_no_execution(self):
        values=[];sources={}
        for index,topic in enumerate(('testing updates','shipping parcels','cooking dinner')):
            value,original=self.compile('Always provide details when I ask about '+topic+'.',ident=str(index))
            values.append(value);sources[value.source_id]=original
        request=self.request(values,sources,query='Help with testing updates,shipping parcels and cooking dinner.')
        receipt,audit=p.select(values,**request);self.assertEqual(2,len(receipt['selected']))
        self.assertFalse(receipt['executes_steps']);self.assertFalse(receipt['adopts_long_term_rule'])


if __name__=='__main__':unittest.main()
