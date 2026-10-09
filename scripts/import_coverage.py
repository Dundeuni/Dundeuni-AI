"""Validate the official OneDrive COVERAGE archive and preserve source hashes."""
import argparse
import json
import zipfile
from pathlib import Path
from run_inference import ROOT, sha256


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("archive",type=Path)
    parser.add_argument("--out",type=Path,default=ROOT/"data/coverage")
    args=parser.parse_args()
    args.archive=args.archive.resolve()
    with zipfile.ZipFile(args.archive) as packed:
        for item in packed.infolist():
            target=(args.out/item.filename).resolve()
            if not target.is_relative_to(args.out.resolve()) or (item.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError("Unsafe archive member")
        if packed.testzip():
            raise ValueError("Archive CRC mismatch")
        for item in packed.infolist():
            destination=args.out/item.filename
            if destination.exists():
                if not item.is_dir() and destination.read_bytes() != packed.read(item):
                    raise ValueError("Existing file differs; preserve it: "+item.filename)
            else:
                packed.extract(item,args.out)
    root=args.out/"COVERAGE"
    readme=(root/"readme.txt").read_text(encoding="latin-1")
    if "Update Sep 27, 2017" not in readme:
        raise ValueError("Missing corrected-label README version")
    images={p.name:p for p in (root/"image").glob("*.tif")}
    masks={p.name:p for p in (root/"mask").glob("*.tif")}
    expected_images={str(i)+suffix+".tif" for i in range(1,101) for suffix in ("","t")}
    expected_masks={str(i)+suffix+".tif" for i in range(1,101) for suffix in ("copy","paste","forged")}
    if set(images) != expected_images or set(masks) != expected_masks:
        raise ValueError("Incomplete COVERAGE image/mask set")
    record={"official_repository":"https://github.com/wenbihan/coverage",
            "official_share":"https://1drv.ms/f/s!AggVhXcCj1FLhUUyUrqSpV_yI_GH",
            "acquisition":"public browser folder download; no account or upload",
            "archive_path":str(args.archive.relative_to(ROOT)),"archive_bytes":args.archive.stat().st_size,
            "archive_sha256":sha256(args.archive),"archive_crc_verified":True,
            "label_version":"official Sep 27 2017 corrected original/tampered labels",
            "license":"non-commercial research and publication attribution",
            "images":200,"masks":300,"files":[{"path":str(p.relative_to(ROOT)),"sha256":sha256(p),
                "bytes":p.stat().st_size} for p in sorted(root.rglob("*")) if p.is_file()]}
    out=ROOT/"runs/20261001_original/coverage_source.json"
    with out.open("x",encoding="utf-8") as target:
        json.dump(record,target,indent=2)
    print("COVERAGE images 200 / masks 300 / CRC verified / SHA256",record["archive_sha256"])


if __name__ == "__main__":
    main()
