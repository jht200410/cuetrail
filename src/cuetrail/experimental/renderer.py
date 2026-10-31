"""Request-bound extractive Procedure fields plus their complete original source.

This independent CPU prototype changes only card presentation, not retrieval or
Answer/Judge prompts. It is not connected to the frozen V8 input pilot.
"""
import hashlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND = HERE
PINS = {
    'evidence.py': '9afb80b62f3b309f42d8a8fc66d61a7ad6e17ecb1b998d5d10bd08d6f423e175',
    'ledger.py': '62ecd55b3f59838b29197e941c3f556ac1d0f20ebe542c73ad990e2a5326dc34',
    'trigger.py': 'a5a5ecd3e156ce167cfbd416e0c059e49655a9b3d09b5f5eea7067e5f1887f7f',
    'request_use.py': '5228a1692c4e3b93f1f880288779f1637da462a2e10c2ef6b724afc21a22b0f8',
}


def verify_backend():
    for name, expected in PINS.items():
        if hashlib.sha256((BACKEND / name).read_bytes()).hexdigest() != expected:
            raise ValueError('Structured renderer backend changed: ' + name)


verify_backend()
from . import evidence as g
from . import trigger
if Path(g.__file__).resolve() != BACKEND / 'evidence.py' or Path(trigger.__file__).resolve() != BACKEND / 'trigger.py':
    raise ValueError('A different evidence/trigger module was already loaded')


def render(plan, ledger, namespace, source_ids, source_loader, query, request_id, mode):
    """Return quoted data cards after fresh source/version/request verification."""
    verify_backend()
    _, audit = trigger.materialize(plan, ledger, namespace, source_ids, source_loader, query, request_id, mode)
    if not audit['accepted']:
        return [], audit
    cards = []
    for p in plan.procedures:
        meaning = ('Historical attribution; the quoted advice or plan was not thereby adopted.'
                   if mode == 'historical_procedure' else
                   'Conditional user evidence; use only within the quoted context and verified current request.')
        fields = [f'[Procedure v{p.version}; kind={p.kind}; authority={p.authority}; source_basis={p.source_basis}; lifetime={p.lifetime}]',
                  meaning,
                  'Quoted scope: ' + p.scope_quote,
                  'Quoted condition: ' + p.condition_quote]
        fields.extend(f'Quoted action {index}: {action}' for index, action in enumerate(p.action_quotes, 1))
        fields.extend([
            f'Original evidence source={p.source_id}:{p.evidence_start}-{p.evidence_end}; '
            f'role={p.source_role}; speaker={p.subject_quote or "user namespace"}; sha256={p.source_sha256}',
            p.evidence_quote,
        ])
        cards.append('\n'.join(fields))
    if sum(len(card) for card in cards) > g.MAX_CARD_CHARS:
        return [], dict(accepted=False, reason='structured_card_budget', chars=sum(len(card) for card in cards),
                        limit=g.MAX_CARD_CHARS, original_source_truncated=False)
    contract = g.digest(dict(renderer=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), backend=PINS))
    return cards, dict(audit, reason='source_verified_structured_cards', render_contract_sha256=contract,
        structured_fields_are_original_quotes=True, complete_original_evidence_retained=True,
        field_citations_reference_complete_original_span=True, extra_model_calls=0)
