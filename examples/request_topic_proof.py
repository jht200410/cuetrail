"""Run a literal request-topic proof with no model,network or dataset."""
from dataclasses import asdict
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from cuetrail.experimental import request_topics as p


def main():
    user=dict(id='user-rule',role='user',session_id='demo',timestamp=1,
        content='Always include rollback checks when I ask about deployment plans.')
    advice=dict(id='assistant-advice',role='assistant',session_id='demo',timestamp=2,
        content='Always avoid backup checks when I ask about deployment plans.')
    sources={value['id']:value for value in (user,advice)}
    values=[]
    for source in sources.values():
        value,reason=p.compile_view(source);assert reason=='valid';values.append(value)
    values=p.govern_versions(values)
    request=dict(query='Help me with deployment plans.',mode='execute',request_id='demo-current-request',
        source_loader=sources.__getitem__,native_ids=set(sources))
    receipt,audit=p.select(values,**request);selected,materialized=p.materialize(receipt,values,**request)
    assert len(selected)==1 and selected[0].source_role=='user'
    assert not receipt['executes_steps'] and not receipt['adopts_long_term_rule']
    print(json.dumps(dict(selected=[dict(condition=asdict(value.condition),actions=[asdict(span) for span in value.actions],
        authority=value.authority,lifetime=value.lifetime,version=value.version) for value in selected],
        query_scope_receipts=receipt['selected'],assistant_proposals_adopted=0,executes_steps=False,
        model_calls=0,network_calls=0),ensure_ascii=False,indent=2))
    changed=dict(request,query='Help me plan a hiking trip.')
    assert p.materialize(receipt,values,**changed)[0]==[]


if __name__=='__main__':main()
