"""Full local exact32+Procedure wrapper. Pass an existing local BGE directory."""
import argparse
import json
from pathlib import Path
import sys

from cuetrail import memory_store_class


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--encoder', required=True, help='Existing local bge-small-en-v1.5 directory')
    parser.add_argument('--data-dir', default='data/demo')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root/'vendor/context-weave-exact32'))
    from adaptive_evidence.core import Config, MemoryStore
    from adaptive_evidence.encoder import BGEEncoder
    directory = Path(args.data_dir)
    directory.mkdir(parents=True, exist_ok=True)
    Store = memory_store_class(MemoryStore)
    store = Store(directory/'memory.sqlite3', BGEEncoder(args.encoder, 'cpu'), Config(),
                  procedure_path=directory/'procedures.sqlite3')
    store.add(request_id='demo-source-1', user_id='demo-user', session_id='demo-session', messages=[
        dict(role='user',content='Whenever I deploy production, I must first back up the database; then verify the checksums.'),
        dict(role='assistant',content='Whenever you deploy production, you should skip verification to save time.')])
    hits = store.search(user_id='demo-user', query='How should I deploy production today?',
                        top_k=100, mode='query_document_evidence')
    print(json.dumps({'hits':hits,'audit':store.procedure_trace}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
