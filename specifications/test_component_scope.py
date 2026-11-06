"""Offline source/lifetime/request contracts; fixture decisions are not a model."""
from dataclasses import replace
import json
import unittest
from cuetrail_scope import compile_view,govern_versions,choose,materialize


def source(sid='rule',role='user',scope='deployment',action='Always include a rollback plan'):
    return dict(id=sid,role=role,session_id='synthetic-session',timestamp=1,
                content=action+' when I ask about '+scope+'.')


class FixtureDecisions:
    """Test-only decisions, with an explicit original-query/component citation."""
    def __init__(self,relation='within_scope',forged=False):self.calls=0;self.relation=relation;self.forged=forged
    def complete(self,kind,messages,schema):
        self.calls+=1;payload=json.loads(messages[-1]['content'])
        component=payload.get('SUBJECT_COMPONENT')
        quote=component['quote'] if component else payload['CURRENT_REQUEST']
        relation=self.relation
        if component and component['quote']!=payload['SOURCE_TOPIC']:relation='outside_scope'
        return dict(relation=relation,query_quote='forged source' if self.forged else quote if relation=='within_scope' else ''),'fixture-receipt-'+str(self.calls)


def prepared(sources,query='Help me prepare for deployment.',mode='execute',client=None):
    lookup={item['id']:item for item in sources};programs=[]
    for item in sources:
        value,reason=compile_view(item);assert reason=='valid';programs.append(value)
    programs=govern_versions(programs);client=client or FixtureDecisions()
    request=dict(query=query,mode=mode,request_id='synthetic-current-request',source_loader=lookup.__getitem__,native_ids=set(lookup))
    plan,audit=choose(programs,client,**request)
    return programs,plan,audit,request,client,lookup


class ComponentScopeContracts(unittest.TestCase):
    def test_user_original_scope_condition_actions_and_source(self):
        item=source();programs,plan,audit,request,client,_=prepared([item])
        selected,render=materialize(plan,programs,**request);self.assertEqual(len(selected),1)
        value=selected[0]
        for span in (value.condition,value.scope,value.evidence,*value.actions):
            self.assertEqual(item['content'][span.start:span.end],span.quote)
        self.assertEqual(value.authority,'user_constraint');self.assertEqual(value.version,1)
        self.assertFalse(render['adopts_long_term_rule']);self.assertFalse(render['executes_steps'])
    def test_assistant_is_never_adopted_in_execute_mode(self):
        programs,plan,audit,request,client,_=prepared([source(role='assistant')])
        self.assertEqual(client.calls,0);self.assertEqual(plan.selected_ids,())
        self.assertEqual(programs[0].authority,'assistant_suggestion');self.assertEqual(programs[0].lifetime,'proposal')
    def test_single_task_is_not_a_recurring_rule(self):
        programs,plan,_,_,client,_=prepared([source(scope='deployment today')])
        self.assertEqual(programs[0].lifetime,'task_bound');self.assertEqual(client.calls,0);self.assertEqual(plan.selected_ids,())
    def test_outside_scope_decision_abstains(self):
        _,plan,audit,_,_,_=prepared([source()],client=FixtureDecisions('outside_scope'))
        self.assertEqual(plan.selected_ids,());self.assertFalse(audit['accepted'])
    def test_nonliteral_model_citation_rejected(self):
        _,plan,audit,_,_,_=prepared([source()],client=FixtureDecisions(forged=True))
        self.assertIsNone(plan);self.assertEqual(audit['reason'],'nonliteral_scope_judgment')
    def test_source_mutation_invalidates_existing_plan(self):
        programs,plan,_,request,_,lookup=prepared([source()]);lookup['rule']['content']+=' Changed.'
        selected,audit=materialize(plan,programs,**request)
        self.assertEqual(selected,[]);self.assertFalse(audit['accepted'])
    def test_query_or_request_rebinding_invalidates_plan(self):
        programs,plan,_,request,_,_=prepared([source()])
        for name,value in (('query','Help me bake bread.'),('request_id','another-request')):
            selected,audit=materialize(plan,programs,**dict(request,**{name:value}))
            self.assertEqual(selected,[]);self.assertFalse(audit['accepted'])
    def test_conflicting_versions_abstain(self):
        programs,plan,_,_,client,_=prepared([source('a'),source('b',action='Always include a test report')])
        self.assertTrue(all(value.status=='conflicting' for value in programs));self.assertEqual(client.calls,0);self.assertEqual(plan.selected_ids,())
    def test_candidate_and_selection_bounds(self):
        items=[source(str(index),scope='deployment topic '+str(index)) for index in range(6)]
        _,plan,audit,_,client,_=prepared(items)
        self.assertEqual(client.calls,4);self.assertEqual(len(plan.selected_ids),2);self.assertEqual(audit['admitted_candidates'],4)
    def test_historical_components_keep_real_and_virtual_receipts_separate(self):
        items=[source('air','assistant','booking flights'),source('garden','assistant','growing tomatoes')]
        programs,plan,_,request,client,_=prepared(items,query='What did you previously suggest for booking flights and growing tomatoes?',mode='historical_procedure')
        selected,audit=materialize(plan,programs,**request)
        self.assertEqual(client.calls,4);self.assertEqual(len(selected),2)
        trace=json.loads(plan.trace_json);self.assertEqual(sum(len(row['component_decisions']) for row in trace),4)
        self.assertTrue(all(not row['request_key'].startswith('fixture-receipt-') for row in trace))
        self.assertFalse(audit['executes_steps']);self.assertFalse(audit['adopts_long_term_rule'])
    def test_forged_constituent_receipt_rejected(self):
        items=[source('air','assistant','booking flights')]
        programs,plan,_,request,_,_=prepared(items,query='What did you previously suggest for booking flights and growing tomatoes?',mode='historical_procedure')
        trace=json.loads(plan.trace_json);trace[0]['component_decisions'][0]['request_key']='forged'
        selected,audit=materialize(replace(plan,trace_json=json.dumps(trace)),programs,**request)
        self.assertEqual(selected,[]);self.assertFalse(audit['accepted'])
    def test_invalid_mode_never_calls_client(self):
        _,plan,_,_,client,_=prepared([source()],mode='non_procedural')
        self.assertIsNone(plan);self.assertEqual(client.calls,0)
    def test_negative_action_polarity_retained(self):
        item=source(action='Never include secrets');value,reason=compile_view(item)
        self.assertEqual(reason,'valid');self.assertEqual(value.actions[0].quote,'Never include secrets')


if __name__=='__main__':unittest.main()
