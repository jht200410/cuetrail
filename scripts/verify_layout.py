"""Verify the development tree and unchanged historical release files."""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--frozen-only', action='store_true')
    args = parser.parse_args()
    record = json.loads((ROOT/'DEVELOPMENT_LAYOUT.json').read_text(encoding='utf-8'))
    expected = record['protected_files'] if args.frozen_only else record['files_sha256']
    for name, digest in expected.items():
        path = (ROOT/name).resolve()
        if not path.is_relative_to(ROOT) or not path.is_file():
            raise SystemExit('Missing or invalid file: '+name)
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise SystemExit('File hash differs: '+name)
    print(json.dumps(dict(verified=True, files=len(expected), protected_files=len(record['protected_files']),
                         original_commit=record['before_commit'], official_submission=False)))

if __name__ == '__main__':
    main()
