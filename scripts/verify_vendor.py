"""Verify all vendored official0.32 source files without modifying them."""
import hashlib
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
manifest = json.loads((root/'vendor/manifest.json').read_text(encoding='utf-8'))
for name, expected in manifest['files'].items():
    path = root/'vendor/context-weave-exact32'/name
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise SystemExit('Source integrity failure: '+name)
print(f"Verified {len(manifest['files'])} original files; baseline {manifest['baseline_version']}.")
