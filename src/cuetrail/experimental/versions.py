"""Conservative source-bound Procedure replacement proofs;CPU prototype only.

No facts,history expansion,semantic inference or advice adoption. Only an entire
single user sentence that literally replaces one quoted action with another can
create a replacement link. All other changed-action variants remain unresolved.
This deliberately supports a narrow grammar,not general natural-language edits.
"""
from dataclasses import asdict,replace
import hashlib
from pathlib import Path
import re
import sys

from . import evidence as g
PIN='9afb80b62f3b309f42d8a8fc66d61a7ad6e17ecb1b998d5d10bd08d6f423e175'
if hashlib.sha256(Path(g.__file__).read_bytes()).hexdigest()!=PIN:
    raise ValueError('Pinned Procedure validator changed')


def originals(procedures,drafts,source_loader):
    seen=set();sources={}
    for p in procedures:
        if p.id in seen:raise ValueError('Duplicate original Procedure')
        seen.add(p.id)
        source=source_loader(p.source_id)
        fresh,reason=g.validate_draft(drafts[p.id],source)
        if fresh!=p:raise ValueError('Procedure derivation or source changed: '+reason)
        sources[p.id]=source
    if set(drafts)!=seen:raise ValueError('Missing or extra original derivations')
    return sources


def replacement_proof(new,old_active,draft,source):
    """Require an exact complete sentence,explicit quotes,and a unique old action."""
    if new.source_role!='user' or new.authority=='assistant_suggestion':return None,'proposal_cannot_replace'
    if new.timestamp is None or any(old.timestamp is None or new.timestamp<=old.timestamp for old in old_active):
        return None,'replacement_order_unknown'
    old_actions={old.action_quotes for old in old_active}
    if len(old_actions)!=1 or len(next(iter(old_actions)))!=1 or len(new.action_quotes)!=1:
        return None,'replacement_target_not_unique_single_action'
    old_action=next(iter(old_actions))[0];new_action=new.action_quotes[0]
    if any('"' in value or '\n' in value or '\r' in value for value in (old_action,new_action,new.condition_quote)):
        return None,'replacement_quote_grammar_unsupported'
    # Whole canonical source equality prevents a shorter relation from hiding
    # surrounding attribution,negation,exceptions or a separate replacement.
    text=source['content']
    if new.evidence_start!=0 or new.evidence_end!=len(text) or new.evidence_quote!=text or draft['connecting_quote']!=text:
        return None,'replacement_requires_complete_canonical_source'
    prefix=re.escape(new.condition_quote)
    # Only grammar keywords ignore case. Quoted action targets remain byte-for-
    # byte Python-string literals;case-folding a quote is not source evidence.
    pattern=(prefix+r',\s*(?i:(?:please\s+)?replace)\s+"'+re.escape(old_action)+
             r'"\s+(?i:with)\s+"'+re.escape(new_action)+r'"\s*\.')
    if not re.fullmatch(pattern,text):return None,'no_explicit_literal_replacement_sentence'
    prior_ids=tuple(old.id for old in old_active)
    proof=dict(kind='explicit-quoted-action-replacement-v2-literal-targets',new_procedure_id=new.id,prior_ids=prior_ids,
        source_id=new.source_id,source_role=new.source_role,source_sha256=new.source_sha256,
        evidence_start=0,evidence_end=len(text),evidence_quote=text,
        old_action_quotes=next(iter(old_actions)),new_action_quotes=new.action_quotes,
        subject_quote=new.subject_quote,condition_quote=new.condition_quote,scope_quote=new.scope_quote,
        validator_sha256=PIN,governor_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    return proof,'explicit_source_bound_replacement'


def govern(procedures,drafts,source_loader):
    procedures=list(procedures);sources=originals(procedures,drafts,source_loader)
    output=[];groups={};audits=[]
    ordered=sorted(enumerate(procedures),key=lambda item:(item[1].timestamp is None,
        item[1].timestamp if item[1].timestamp is not None else item[0],item[0]))
    for _,p in ordered:
        key=p.subject_quote.casefold(),p.signature
        prior=groups.setdefault(key,[])
        active=[i for i in prior if output[i].status!='superseded']
        different=[i for i in active if output[i].action_quotes!=p.action_quotes]
        audit=dict(procedure_id=p.id,reason='initial_or_same_action',replacement_link=None,automatic_adoption=False)
        if different:
            p=replace(p,version=1+max(output[i].version for i in prior))
            proof,reason=replacement_proof(p,[output[i] for i in active],drafts[p.id],sources[p.id])
            audit.update(reason=reason,replacement_link=proof)
            if proof is not None:
                p=replace(p,supersedes_ids=tuple(output[i].id for i in active),version_evidence_quote=proof['evidence_quote'])
                for i in active:output[i]=replace(output[i],status='superseded')
            elif p.authority!='assistant_suggestion':
                p=replace(p,status='conflicting')
                for i in active:output[i]=replace(output[i],status='conflicting')
        elif active:
            p=replace(p,version=max(output[i].version for i in active))
        prior.append(len(output));output.append(p);audits.append(audit)
    return output,audits
