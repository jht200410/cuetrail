"""Current native server entry retaining the original auth/Add/Search contract."""
import hashlib
import json
import os
from pathlib import Path

from fastapi import Depends
from adaptive_evidence import api as native

from . import __version__
from .integration import memory_store_class


def verify_source_manifest():
    root=Path(__file__).resolve().parent.parent
    manifest=root/'cuetrail-source-manifest.json'
    if not manifest.exists():
        if os.getenv('CUETRAIL_REQUIRE_MANIFEST')=='1':
            raise RuntimeError('Current source manifest required before production startup')
        return 'local-unfrozen-contract'
    raw=manifest.read_bytes()
    expected=json.loads(raw)
    if expected.get('candidate')!='CueTrail-v77-current-native':
        raise RuntimeError('Unexpected current candidate manifest')
    required={'cuetrail_native/__init__.py','cuetrail_native/integration.py','cuetrail_native/server.py',
              'adaptive_evidence/__init__.py','adaptive_evidence/api.py','adaptive_evidence/core.py'}
    files=expected.get('files_sha256',{})
    if not required.issubset(files):
        raise RuntimeError('Incomplete current runtime manifest')
    actual={str(path.relative_to(root)).replace('\\','/') for package in
            ('adaptive_evidence','cuetrail_native','cuetrail_scope','cuetrail_governance')
            for path in (root/package).rglob('*.py')}
    if actual!={name for name in files if name.endswith('.py') and name.split('/')[0] in
                ('adaptive_evidence','cuetrail_native','cuetrail_scope','cuetrail_governance')}:
        raise RuntimeError('Unlisted or missing current runtime module')
    for name,digest in files.items():
        target=(root/name).resolve()
        if not target.is_relative_to(root) or hashlib.sha256(target.read_bytes()).hexdigest()!=digest:
            raise RuntimeError('Current native source integrity failure')
    return hashlib.sha256(raw).hexdigest()


SOURCE_BUILD_ID=verify_source_manifest()
native.MemoryStore=memory_store_class(native.MemoryStore)
app=native.app
app.title='CueTrail'
app.version=__version__
# Keep the original API routes, schemas, auth, errors, timing and lifespan.
# Replace only health so official receipts identify the actual current code.
app.router.routes=[route for route in app.router.routes if getattr(route,'path',None)!='/health']


@app.get('/health')
def health(store=Depends(native.get_store)):
    result=native.health(store)
    result.update(system_name='CueTrail',version=__version__,baseline_source_version=result['version'],
        source_build_id=SOURCE_BUILD_ID,current_procedural_code=True,
        procedural_features=['canonical_native_sources','explicit_user_scoped_programs','two_source_confirmation',
                             'bound_withdrawal','literal_prerequisite_witnesses'],
        procedural_searches=store.procedural_searches,procedural_injections=store.procedural_injections,
        procedural_audit_failures=store.procedural_audit_failures)
    return result
