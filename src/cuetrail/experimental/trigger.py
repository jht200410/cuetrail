"""Request-bound selection receipts over audited stored Procedures.

The caller supplies a semantic selector's IDs/quotes. Code checks provenance,
authority, known prerequisites and current versions; it does not prove semantic
relevance or execute steps. No model, benchmark or frozen-candidate integration.
"""
from dataclasses import asdict,dataclass
import hashlib
import json
from pathlib import Path
import sqlite3

from . import evidence as g
from .request_use import query_sha


@dataclass(frozen=True)
class TriggerPlan:
    namespace:str
    request_id:str
    query_sha256:str
    mode:str
    contract_sha256:str
    procedures:tuple[g.Procedure,...]
    selection_json:str
    lifetime:str='current_request_only'
    executes_steps:bool=False


def contract(ledger):
    files=(Path(__file__),ledger.code_path,ledger.ledger_path)
    return g.digest([(p.name,hashlib.sha256(p.read_bytes()).hexdigest()) for p in files])


def failure(reason,**details):return None,dict(accepted=False,reason=reason,**details)


def select(ledger,namespace,source_ids,source_loader,query,request_id,mode,selection):
    """Bind at most two validated semantic choices to one audited request.

    Any invalid choice rejects the whole selection. No partial selection is
    silently promoted, and no assistant suggestion obtains execution authority.
    Historical evidence can include old/proposed versions, retaining labels.
    """
    if not isinstance(request_id,str) or not request_id.strip():return failure('request_identity_required')
    if not isinstance(namespace,str) or not namespace.strip():return failure('namespace_required')
    if not isinstance(query,str) or not query.strip():return failure('current_query_required')
    if mode not in ('execute','historical_procedure'):return failure('procedural_intent_required')
    if not isinstance(selection,list) or len(selection)>2:return failure('at_most_two_choices')
    if not selection:return failure('no_semantic_selection')
    try:
        visible,audit=ledger.verified_visible(namespace,source_ids,source_loader,historical=True)
    except (ValueError,TypeError,KeyError,OSError,sqlite3.Error) as error:
        return failure('source_or_version_audit_failed',error_type=type(error).__name__)
    lookup={p.id:p for p in visible};chosen=[];seen=set()
    for item in selection:
        if not isinstance(item,dict):return failure('selection_schema')
        if not isinstance(item.get('procedure_id'),str):return failure('selection_schema')
        p=lookup.get(item.get('procedure_id'))
        if p is None:return failure('procedure_not_in_native_scope')
        key=p.signature,p.subject_quote.casefold()
        if key in seen:return failure('duplicate_or_ambiguous_procedure')
        valid,reason=g.validate_selection(item,p,query,mode)
        if not valid:return failure(reason,procedure_id=p.id)
        seen.add(key);chosen.append(p)
    plan=TriggerPlan(namespace,request_id,query_sha(query),mode,contract(ledger),tuple(chosen),
                     json.dumps(selection,ensure_ascii=False,sort_keys=True))
    return plan,dict(accepted=True,reason='audited_request_bound_selection',procedures=len(chosen),
                     semantic_relevance_is_model_decision=True,source_audit=audit,
                     request_id=request_id,query_sha256=plan.query_sha256,
                     sources=[dict(id=p.id,source_id=p.source_id,version=p.version,authority=p.authority,
                         status=p.status,source_sha256=p.source_sha256,evidence_start=p.evidence_start,
                         evidence_end=p.evidence_end) for p in chosen])


def materialize(plan,ledger,namespace,source_ids,source_loader,query,request_id,mode):
    """Revalidate immediately before rendering evidence cards, never actions.

    On any mismatch the caller must keep its native output unchanged. A valid
    plan grants no persistent adoption, tool execution or extra retrieval.
    """
    if not isinstance(plan,TriggerPlan):return [],dict(accepted=False,reason='missing_trigger_plan')
    if not isinstance(query,str):return [],dict(accepted=False,reason='current_query_required')
    if (plan.namespace,plan.request_id,plan.query_sha256,plan.mode)!=(namespace,request_id,query_sha(query),mode):
        return [],dict(accepted=False,reason='request_binding_changed')
    if plan.contract_sha256!=contract(ledger):
        return [],dict(accepted=False,reason='trigger_contract_changed')
    if plan.lifetime!='current_request_only' or plan.executes_steps:
        return [],dict(accepted=False,reason='invalid_trigger_lifetime')
    try:selection=json.loads(plan.selection_json)
    except (TypeError,ValueError):return [],dict(accepted=False,reason='invalid_selection_receipt')
    fresh,audit=select(ledger,namespace,source_ids,source_loader,query,request_id,mode,selection)
    if fresh is None:return [],audit
    if fresh!=plan:return [],dict(accepted=False,reason='procedure_or_version_changed')
    cards=[g.card(p,mode) for p in plan.procedures]
    if sum(len(card) for card in cards)>g.MAX_CARD_CHARS:
        return [],dict(accepted=False,reason='procedure_card_budget')
    return cards,dict(accepted=True,reason='revalidated_evidence_cards',executes_steps=False,
                     adopts_standing_rule=False,selected_ids=[p.id for p in plan.procedures],
                     request_id=request_id,query_sha256=plan.query_sha256,
                     procedure_receipt_sha256=g.digest([asdict(p) for p in plan.procedures]))
