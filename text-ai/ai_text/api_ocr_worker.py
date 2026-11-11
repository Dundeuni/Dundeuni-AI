"""Paddle-only process: identical RGB preparation and body policy to the CLI."""
import argparse
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    from PIL import Image, ImageOps
    from ai_text.pipeline import RiskAnalyzer
    from ai_text.message_body_v2 import extract_message_body
    parser = argparse.ArgumentParser()
    parser.add_argument('--image', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    path = Path(args.image).resolve()
    with tempfile.TemporaryDirectory(dir=path.parent) as temporary:
        prepared = Path(temporary) / 'input.png'
        with Image.open(path) as source:
            ImageOps.exif_transpose(source).convert('RGB').save(prepared)
        lines = RiskAnalyzer().extract(prepared)
    body = extract_message_body(path, lines)
    body['ocr_lines'] = lines
    Path(args.output).write_text(json.dumps(body, ensure_ascii=False), encoding='utf-8')


if __name__ == '__main__':
    main()
