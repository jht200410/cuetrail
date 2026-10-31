"""Standard-library, synthetic source-ledger/reopen/complete-inventory demo."""
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from cuetrail_governance import inventory as i

p,h,w=i.p,i.h,i.w
text='每当我询问「恢复检查」时，请始终先核对备份，不要删除副本，除非检查全部通过。'
proposal=p.Source('proposal','demo','user','s1','assistant',text,1)
confirmation=p.Source('confirmation','demo','user','s2','user',h.PREFIX+text,2)
withdrawal=p.Source('withdrawal','demo','user','s3','user',w.PREFIX+text,3)
query='请按既定程序处理「恢复检查」。'
fields=dict(namespace='demo',subject_id='user',request_id='r1')
with TemporaryDirectory(prefix='cuetrail-inventory-',dir=Path.cwd()) as folder:
    path=Path(folder)/'procedures.sqlite3'
    store=i.Inventory(path)
    # Ingestion order is not historical authority order.
    store.add(confirmation)
    store.add(proposal)
    old,before=store.select(query,**fields)
    assert before['accepted']
    reopened=i.Inventory(path)
    assert reopened.select(query,**fields)[0]==old
    reopened.add(withdrawal)
    current,after=store.select(query,**fields)
    assert not after['accepted']
    assert store.render(old,query,**fields)[0]==''
    history='回顾我关于「恢复检查」的程序。'
    historical,_=store.select(history,**fields)
    rendered,history_result=store.render(historical,history,**fields)
    assert history_result['accepted']
    cards=json.loads(rendered)
    confirmed=[v for v in cards if v['kind']=='confirmed_habit']
    assert len(confirmed)==1 and confirmed[0]['applicability']=='withdrawn'
    print(json.dumps(dict(before_withdrawal_applies=before['accepted'],reopen_same_receipt=True,
        automatically_discovered_withdrawals=after['inventory']['withdrawals'],after_withdrawal_applies=after['accepted'],
        stale_receipt_rejected=True,caller_supplied_program_subset=False,canonical_sources=after['inventory']['canonical_sources'],
        complete_within_stored_partition=after['inventory']['complete_within_stored_partition'],
        external_corpus_completeness_proven=False,model_calls=0),ensure_ascii=False,indent=2))
