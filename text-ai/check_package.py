"""Check code or separately supplied model assets; no network or Git operations."""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--code-only', action='store_true', help='Check repository files without model weights')
    parser.add_argument('--model-dir', type=Path, help='Directory received separately; alternatively set AI_TEXT_MODEL_DIR')
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    if args.code_only:
        manifest = json.loads((root / 'PACKAGE_MANIFEST.json').read_text(encoding='utf-8'))
        errors = []
        for entry in manifest['files']:
            path = root / entry['path']
            if not path.is_file():
                errors.append(entry['path'] + ': missing')
            elif path.suffix == '.py':
                try:
                    ast.parse(path.read_text(encoding='utf-8-sig'))
                except (SyntaxError, UnicodeError) as error:
                    errors.append(entry['path'] + ': invalid Python source: ' + type(error).__name__)
        if errors:
            print('FAILED: repository code check');print('\n'.join(errors));return 1
        print('PASS: repository files and Python syntax checked. Model weights were NOT checked; they are delivered separately.')
        return 0

    manifest = json.loads((root / 'MODEL_ASSETS.json').read_text(encoding='utf-8'))
    configured = args.model_dir or os.environ.get('AI_TEXT_MODEL_DIR')
    folder = Path(configured) if configured else root / 'models' / manifest['model_version']
    errors = []
    for entry in manifest['files']:
        path = folder / entry['path']
        if not path.is_file():
            errors.append(entry['path'] + ': missing');continue
        if path.suffix == '.safetensors':
            with path.open('rb') as stream:
                if stream.read(180).startswith(b'version https://git-lfs.github.com/spec/v1'):
                    errors.append(entry['path'] + ': received a pointer, not the actual separately supplied weights');continue
        if path.stat().st_size != entry['bytes'] or digest(path) != entry['sha256']:
            errors.append(entry['path'] + ': size/SHA-256 mismatch')
    if errors:
        print('FAILED: model asset check');print('\n'.join(errors))
        print('Weights are not stored in Git. Obtain the exact trained model assets separately and set AI_TEXT_MODEL_DIR, or use --model-dir.')
        return 1
    print('PASS: separately supplied model files match MODEL_ASSETS.json. No accuracy, OCR, or BE test was run.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
