"""Synthetic source/request proof demo; no model, network, or benchmark score."""
import json
from cuetrail_scope import compile_view,govern_versions,choose,materialize


class FixtureScopeClient:
    def complete(self,kind,messages,schema):
        request=json.loads(messages[-1]['content'])['CURRENT_REQUEST']
        return dict(relation='within_scope',query_quote=request),'synthetic-fixture-receipt'


def main():
    source=dict(id='demo-constraint',role='user',session_id='demo',timestamp=1,
        content='Always include a rollback plan when I ask about deployment.')
    value,reason=compile_view(source);assert reason=='valid'
    programs=govern_versions([value]);lookup={source['id']:source}
    request=dict(query='Help me prepare for deployment.',mode='execute',request_id='demo-current-request',source_loader=lookup.__getitem__,native_ids=set(lookup))
    plan,_=choose(programs,FixtureScopeClient(),**request)
    selected,audit=materialize(plan,programs,**request)
    print(json.dumps(dict(synthetic_fixture=True,model_calls=0,source_ids=[value.source_id for value in selected],
        original_conditions=[value.condition.quote for value in selected],original_actions=[[span.quote for span in value.actions] for value in selected],
        executes_steps=audit['executes_steps'],adopts_long_term_rule=audit['adopts_long_term_rule']),indent=2))


if __name__=='__main__':main()
