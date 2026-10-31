"""Extractive, scoped procedural memory; no benchmark identities or labels.

All text-bearing fields are original source spans. The module never invents a
rule, promotes assistant advice, or treats a matching intent as proof of an
unmentioned prerequisite. Storage is a separate, append-only audit artifact.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import re
import sqlite3

SCHEMA_VERSION = 1
MAX_PROCEDURES = 2
MAX_CARD_CHARS = 3200
TASK = re.compile(r"\b(?:how|should|recommend\w*|suggest\w*|plan\w*|help|create|write|design|prepare|organize|cook|choose|select|steps?|procedure|routine|workflow|approach|advice|best way|what (?:would|can|could))\b|怎么|如何|步骤|建议|计划|帮我", re.I)
CONDITIONAL = re.compile(r"\b(?:whenever|every time|when|while|before|after|if)\b[^.!?\n]{3,220}?(?=,|:|;|\bthen\b)|(?:当|如果|每当)[^。！？\n]{3,100}?(?=，|：|就)", re.I)
NORM = re.compile(r"\b(?:must|need to|have to|please|make sure|ensure|avoid|never|do not|don't|cannot|can't|only|remember to|be sure)\b|必须|请|不要|避免|务必", re.I)
HABIT = re.compile(r"\bI\s+(?:(?:always|usually|typically|normally|routinely)\b|(?:tend|make sure|have learned)\s+to\b)|我(?:总是|通常|习惯)", re.I)
REUSABLE = re.compile(r"\b(?:whenever|every time|always|usually|typically|normally|routinely|from now on|in future|going forward)\b|每次|每当|总是|通常|以后", re.I)
PERSONAL = re.compile(r"\b(?:I|my|me|we|our)\b|我|我们", re.I)
HYPOTHETICAL = re.compile(r"\b(?:if I were|if I could|imagine|hypothetical|for example|suppose)\b", re.I)
STOP = set("a an the i me my we our you your they their he she it its this that these those to of for in on at with by from is are was were be been being and or but so as then than when whenever while before after if every time usually always typically normally routinely would could should can may will shall must need please make sure ensure do does did not don t have has had what how which where who about help some any all also just use using get got want like now going forward".split())


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def terms(text: str) -> set[str]:
    words = re.findall(r"[a-zA-Z][a-zA-Z'-]{2,}|[\u4e00-\u9fff]{2,}", text.casefold())
    # Small language-only normalization, not a topic/benchmark dictionary.
    def stem(word: str) -> str:
        for suffix in ('ing', 'ies', 'es', 's'):
            if len(word) > len(suffix) + 3 and word.endswith(suffix):
                return word[:-len(suffix)] + ('y' if suffix == 'ies' else '')
        return word
    return {stem(w) for w in words if w not in STOP}


@dataclass(frozen=True)
class SourceRef:
    source_id: str
    role: str
    session_id: str
    timestamp: int | None
    start: int
    end: int
    quote: str
    quote_sha256: str


@dataclass(frozen=True)
class Procedure:
    procedure_id: str
    signature: str
    version: int
    schema_version: int
    status: str
    authority: str
    scope: str
    condition: str
    condition_kind: str
    steps: tuple[str, ...]
    sources: tuple[SourceRef, ...]
    supersedes: str | None = None


def extract(source: dict) -> list[Procedure]:
    """Compile one source turn; no answer, options, annotation or query input."""
    text = source['content']
    output = []
    # No whole-history user-fact expansion: only explicit conditional clauses.
    # Preserve adjacent ordered steps by keeping the original source sentence.
    for sentence in re.finditer(r'[^.!?。！？\n]+(?:[.!?。！？]+|$)', text):
        raw = sentence.group()
        quote = raw.strip()
        if not quote or len(quote) > 1800:
            continue
        match = CONDITIONAL.search(quote)
        if not match:
            continue
        condition = match.group().strip()
        start = sentence.start() + len(raw) - len(raw.lstrip())
        role = source['role'].casefold()
        # Advice is retained as a proposal for audit, never selected.
        if role == 'assistant':
            authority, status = 'assistant_suggestion', 'proposal'
        elif role == 'user' and PERSONAL.search(quote) and HABIT.search(quote):
            authority, status = 'confirmed_habit', 'active'
        elif role == 'user' and NORM.search(quote) and not HYPOTHETICAL.search(quote):
            authority, status = 'user_constraint', 'active' if REUSABLE.search(quote) else 'source_session_only'
        else:
            continue
        # A bare preference never creates a procedure. Require content outside
        # the applicability clause: the action is not the trigger itself.
        remainder = (quote[:match.start()] + quote[match.end():]).strip(' ,;:')
        if len(terms(remainder)) < 2 or not terms(condition):
            continue
        ref = SourceRef(str(source['id']), role, str(source['session_id']),
                        source.get('timestamp'), start, start + len(quote), quote,
                        hashlib.sha256(quote.encode()).hexdigest())
        signature = digest([authority, sorted(terms(condition))])
        pid = digest([signature, source['id'], start, quote])
        # Use the entire exact sentence as a step so pronouns, negatives and
        # exceptions are never separated from the action they qualify.
        kind = 'contingent' if re.match(r'if\b|如果', condition, re.I) else 'task_scope'
        output.append(Procedure(pid, signature, 1, SCHEMA_VERSION, status,
                                authority, condition, condition, kind, (quote,), (ref,)))
    return output


class ProcedureIndex:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else None

    def compile(self, sources: list[dict]) -> list[Procedure]:
        procedures = [p for s in sources for p in extract(s)]
        # Repeated identical evidence is corroboration, not a new version.
        # Different actions with the exact same condition stay ambiguous rather
        # than inventing a latest-wins rule or silently overwriting evidence.
        grouped: dict[str, list[Procedure]] = {}
        for p in procedures:
            grouped.setdefault(p.signature, []).append(p)
        result = []
        for siblings in grouped.values():
            actions = {p.steps for p in siblings}
            revisions = {}
            for p in siblings:
                data = asdict(p)
                data['sources'] = p.sources
                revisions.setdefault(p.steps, len(revisions) + 1)
                data['version'] = revisions[p.steps]
                if len(actions) > 1 and p.status == 'active':
                    data['status'] = 'ambiguous'
                result.append(Procedure(**data))
        return result

    def persist(self, namespace: str, procedures: list[Procedure]) -> None:
        if not self.path:
            return
        with sqlite3.connect(self.path) as db:
            db.execute('CREATE TABLE IF NOT EXISTS procedures(namespace TEXT,id TEXT,version INTEGER,value TEXT, PRIMARY KEY(namespace,id))')
            for p in procedures:
                value = json.dumps(asdict(p), ensure_ascii=False, sort_keys=True)
                old = db.execute('SELECT value FROM procedures WHERE namespace=? AND id=?', (namespace, p.procedure_id)).fetchone()
                if old and old[0] != value:
                    raise ValueError('Procedure audit identity changed')
                db.execute('INSERT OR IGNORE INTO procedures VALUES(?,?,?,?)', (namespace, p.procedure_id, p.version, value))

    def select(self, procedures: list[Procedure], query: str) -> tuple[list[Procedure], dict]:
        trace = {'triggered': bool(TASK.search(query)), 'intent': 'task' if TASK.search(query) else 'non_task',
                 'compiled': len(procedures), 'decisions': [], 'selected_ids': []}
        if not trace['triggered']:
            return [], trace
        query_terms = terms(query)
        hits = []
        for p in procedures:
            condition_terms = terms(p.condition)
            overlap = condition_terms & query_terms
            ratio = len(overlap) / len(condition_terms)
            reason = 'scope_mismatch'
            if p.status != 'active':
                reason = p.status
            elif p.authority == 'assistant_suggestion':
                reason = 'unconfirmed_suggestion'
            elif p.condition_kind == 'contingent' and ratio < 1:
                reason = 'prerequisite_unknown'
            elif (len(overlap) >= 2 and ratio >= .5) or (len(condition_terms) == 1 and ratio == 1):
                # Opposite polarity is not proof of applicability.
                qneg = bool(re.search(r"\b(?:not|never|without|don't|avoid)\b", query, re.I))
                cneg = bool(re.search(r"\b(?:not|never|without|don't|avoid)\b", p.condition, re.I))
                if qneg != cneg:
                    reason = 'polarity_uncertain'
                else:
                    reason = 'applicable'
                    hits.append((ratio, len(overlap), p))
            trace['decisions'].append({'id': p.procedure_id, 'version': p.version, 'authority': p.authority,
                                        'status': p.status, 'condition_kind': p.condition_kind,
                                        'overlap_count': len(overlap), 'scope_terms': len(condition_terms), 'reason': reason})
        hits.sort(key=lambda h: (-h[0], -h[1], h[2].procedure_id))
        selected = []
        seen = set()
        for _, _, p in hits:
            if p.steps in seen:
                continue
            selected.append(p)
            seen.add(p.steps)
            if len(selected) == MAX_PROCEDURES:
                break
        trace['selected_ids'] = [p.procedure_id for p in selected]
        return selected, trace


def card(p: Procedure) -> str:
    # The only new text is explicit representation metadata; quote is verbatim.
    s = p.sources[0]
    return (f'[Procedure v{p.version}; {p.authority}; scope={p.scope}; '
            f'source={s.source_id}:{s.start}-{s.end}; role={s.role}]\n' + s.quote)


def inject(hits: list[dict], selected: list[Procedure], render, context_chars: int = 24000) -> tuple[list[dict], dict]:
    """Inject objects with evidence, without reordering native retrieval hits."""
    cards, used = [], 0
    for p in selected:
        text = card(p)
        if used + len(text) > MAX_CARD_CHARS:
            continue
        cards.append({'id': 'procedure:' + p.procedure_id, 'content': text,
                      'score': 1.0, 'procedure': asdict(p)})
        used += len(text)
    if not cards or not hits:
        return hits, {'applied': False, 'cards': 0, 'reason': 'no_applicable_procedure'}
    # Original first evidence is protected. Remaining evidence retains its order
    # and metadata; only a tail can be removed to honor the original char budget.
    result = [hits[0], *cards]
    used += len(hits[0]['content'])
    if used > context_chars:
        return hits, {'applied': False, 'cards': 0, 'reason': 'protected_anchor_budget'}
    for hit in hits[1:]:
        if len(result) == 100 or used + len(hit['content']) > context_chars:
            break
        result.append(hit)
        used += len(hit['content'])
    return result, {'applied': True, 'cards': len(cards), 'chars': used,
                    'reason': 'condition_and_intent_match', 'native_relative_order_preserved': True}
