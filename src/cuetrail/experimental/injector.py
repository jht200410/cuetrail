"""Native-order injection of freshly verified structured source cards."""
from dataclasses import asdict
from . import renderer as r


def inject(native, plan, *, context_chars=24000, **request):
    if not native:
        return native, dict(applied=False, reason='no_native_evidence')
    cards, audit = r.render(plan, **request)
    if not audit['accepted'] or not cards:
        return native, dict(audit, applied=False)
    assert len(cards) == len(plan.procedures)
    if len(native[0]['content']) + sum(len(card) for card in cards) > context_chars:
        return native, dict(applied=False, reason='protected_first_budget', selected_ids=[])
    hits = []
    for text, p in zip(cards, plan.procedures):
        hits.append(dict(id=r.g.digest(['structured-procedure', p.id, p.version, request['mode'], audit['render_contract_sha256']]),
            content=text, score=native[0].get('score', 0), procedure=asdict(p), procedure_mode=request['mode']))
    output = [native[0], *hits]
    used = sum(len(hit['content']) for hit in output)
    for hit in native[1:]:
        if len(output) >= 100 or used + len(hit['content']) > context_chars:
            break
        output.append(hit)
        used += len(hit['content'])
    return output, dict(audit, applied=True, search_chars=used, native_prefix_retained=len(output)-len(hits))


def original_body_unit(hit, document):
    """Preserve contiguous source spans for unchanged native coverage metrics.

    Structured repetitions are in the header and gain no extra source coverage
    credit. The native packer can clip the original body as usual.
    """
    p = hit['procedure']
    quote = p['evidence_quote']
    if not quote or not hit['content'].endswith(quote):
        raise ValueError('Structured card lost its complete original evidence')
    if p['evidence_end'] - p['evidence_start'] != len(quote):
        raise ValueError('Original evidence range differs from body length')
    return dict(source_id=p['source_id'], doc_id=str(document['id']), session=document['session'],
        ordinal=document['ordinal'], start=p['evidence_start'], end=p['evidence_end'], body=quote,
        header=hit['content'][:-len(quote)], kind='procedure', procedure_id=p['id'])
