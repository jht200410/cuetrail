"""Request-local permission to consider an explicitly requested old proposal.

This never adopts a proposal, changes a Procedure, executes steps or substitutes
for semantic applicability. It is not integrated into the frozen V3 candidate.
"""
from dataclasses import dataclass
import hashlib
import re
from . import evidence as g

FOLLOW=re.compile(r'\b(?:follow|use|repeat|reuse|adopt)\b',re.I)
DIRECTIVE=re.compile(r'(?:^|[,;.!]\s*)(?:please\s+)?(?:follow|use|repeat|reuse|adopt)\b|\b(?:can|could|would|will)\s+you\s+(?:please\s+)?(?:follow|use|repeat|reuse|adopt)\b|\bI\s+(?:want|need|would like)\s+you\s+to\s+(?:follow|use|repeat|reuse|adopt)\b',re.I)
REFERENCE=re.compile(r'\b(?:your\s+(?:previous\s+|earlier\s+)?(?:steps|procedure|workflow|plan)|(?:steps|procedure|workflow|plan)\s+(?:that\s+)?you\s+(?:suggested|recommended|gave))\b',re.I)
DENIAL=re.compile(r"\b(?:do not|don't|never|avoid|shouldn't|mustn't)\s+(?:follow|use|repeat|reuse|adopt)\b",re.I)
ALTERNATIVE=re.compile(r'\binstead of\b|\b(?:different|another|alternative)\b[^.!?]{0,80}\b(?:steps|procedure|workflow|plan)\b',re.I)


def query_sha(query):return hashlib.sha256(query.encode()).hexdigest()


@dataclass(frozen=True)
class RequestUse:
    procedure_id:str
    source_authority:str
    source_id:str
    evidence_start:int
    evidence_end:int
    request_id:str
    query_sha256:str
    request_quote:str
    lifetime:str='current_request_only'
    state:str='permission_only_not_applicability'
    adopts_standing_rule:bool=False

    def matches(self,request_id,query):
        return self.request_id==request_id and self.query_sha256==query_sha(query)


def authorize_once(p,query,request_id,procedures):
    if not request_id or not isinstance(request_id,str):return None,'explicit_request_identity_required'
    if p.authority!='assistant_suggestion' or p.status!='unconfirmed':return None,'not_an_unconfirmed_proposal'
    if p.kind!='ordered_procedure' or len(p.action_quotes)<2:return None,'not_a_multistep_proposal'
    if not FOLLOW.search(query) or not DIRECTIVE.search(query) or not REFERENCE.search(query) or DENIAL.search(query) or ALTERNATIVE.search(query):
        return None,'no_explicit_current_request'
    if g.CONTINGENT_ANY.search(query):return None,'conditional_request_requires_state_validation'
    if p.scope_quote.casefold() not in query.casefold():return None,'quoted_scope_not_requested'
    alternatives={x.id for x in procedures if x.authority=='assistant_suggestion' and x.status=='unconfirmed'
                  and x.scope_quote.casefold()==p.scope_quote.casefold() and x.condition_quote.casefold()==p.condition_quote.casefold()}
    if alternatives!={p.id}:return None,'ambiguous_proposal_reference'
    if any(x.authority=='user_constraint' and x.status=='source_grounded' and x.lifetime!='task_bound'
           and x.scope_quote.casefold()==p.scope_quote.casefold() for x in procedures):
        return None,'binding_user_constraint_requires_joint_validation'
    if g.CONTINGENT.match(p.condition_quote):
        if not g.terms(p.condition_quote)<=g.terms(query):return None,'unknown_contingent_prerequisite'
        neg=lambda text:bool(re.search(r"\b(?:not|never|without|don't|cannot|can't)\b|没有|不是",text,re.I))
        if neg(p.condition_quote)!=neg(query):return None,'contingent_polarity_conflict'
    return RequestUse(p.id,p.authority,p.source_id,p.evidence_start,p.evidence_end,
                      request_id,query_sha(query),query),'explicit_request_only'
