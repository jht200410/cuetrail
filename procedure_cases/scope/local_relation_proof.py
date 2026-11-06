"""A CPU-only opt-in proof;does not execute steps or alter an existing Ledger."""
from cuetrail.experimental import action_heads as relations

source=dict(id='example:report',role='user',session_id='example',timestamp=1,
    content='When writing reports, I must cite sources inline.')
view=relations.backend.view(source)
pointer=dict(view_id=view.id,condition_unit=view.units[0].id,scope_unit=view.units[0].id,
    action_units=[view.units[1].id],kind='conditional_constraint')
proof=relations.materialize(pointer,source)
draft=relations.revalidate(proof,source)
procedure,reason=relations.g.validate_draft(draft,source)
assert reason=='valid'
print('Authority:',procedure.authority)
print('Condition:',procedure.condition_quote)
print('Actions:',procedure.action_quotes)
print('Local authority evidence:',proof['authority_witness']['quote'])
print('Original source:',procedure.evidence_quote)
print('Automatic adoption:',proof['automatic_adoption'])
