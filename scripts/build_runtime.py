"""Build the documented runtime from tracked source, without loading a model."""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    output = Path(args.output).resolve()
    if output.exists():raise ValueError('Output directory must not already exist')
    raw = (ROOT / 'runtime/manifest.json').read_bytes()
    manifest = json.loads(raw)
    output.mkdir(parents=True)
    for name, expected in manifest['files_sha256'].items():
        relative = Path(name)
        if relative.is_absolute() or '..' in relative.parts:raise ValueError('Invalid runtime path')
        source = (ROOT / ('src' if name.startswith(('cuetrail_native/', 'cuetrail_scope/', 'cuetrail_governance/'))
                         else 'vendor/context-weave-exact32') / relative).resolve()
        if not source.is_relative_to(ROOT):raise ValueError('Source path escapes checkout')
        content = source.read_bytes()
        if hashlib.sha256(content).hexdigest() != expected:raise ValueError('Source hash differs: ' + name)
        destination = (output / relative).resolve()
        if not destination.is_relative_to(output):raise ValueError('Destination escapes runtime')
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
    (output / 'cuetrail-source-manifest.json').write_bytes(raw)
    print(json.dumps(dict(source_build_id=hashlib.sha256(raw).hexdigest(), files=len(manifest['files_sha256']), output=str(output))))


if __name__ == '__main__':main()
