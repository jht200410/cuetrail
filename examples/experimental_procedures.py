"""Synthetic draft/choice demonstration; no model, network or tool execution."""
import json
from cuetrail.experimental import Ledger, select
from cuetrail.experimental.injector import inject, original_body_unit


def main():
    source = dict(id='synthetic-source', role='user', session_id='synthetic', timestamp=1,
        content='Before every deployment, I usually first run tests, then create a backup.')
    draft = dict(source_id=source['id'], condition_quote='Before every deployment', scope_quote='deployment',
        action_quotes=['run tests','create a backup'], connecting_quote=source['content'], kind='ordered_procedure')
    # Hand-authored JSON illustrates the model interface; it is not model output.
    ledger = Ledger(':memory:')
    try:
        procedure = ledger.record('demo',[dict(source=source,draft=draft)],extraction_ref='hand-authored-demo')[0]
        query = 'Help me prepare a deployment.'
        args = dict(ledger=ledger,namespace='demo',source_ids=[source['id']],source_loader=lambda _:source,
            query=query,request_id='demo-request',mode='execute')
        selection = [dict(procedure_id=procedure.id,query_evidence_quote=query,decision='apply')]
        plan, selected = select(**args,selection=selection)
        native = [dict(id='native-first',content='Protected original evidence.',score=1.0)]
        hits,audit = inject(native,plan,**args)
        unit = original_body_unit(hits[1],dict(id='synthetic-document',session='synthetic',ordinal=0))
        print(json.dumps(dict(synthetic_only=True,model_calls=0,semantic_choice='hand-authored, not learned',
            stored_authority=procedure.authority,source_basis=procedure.source_basis,
            selection_accepted=selected['accepted'],injected=audit['applied'],
            raw_original_body=unit['body'],card=hits[1]['content'],
            executes_steps=audit['executes_steps'],adopts_standing_rule=audit['adopts_standing_rule']),ensure_ascii=False,indent=2))
    finally:
        ledger.close()


if __name__=='__main__':main()
