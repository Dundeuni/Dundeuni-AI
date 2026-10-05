"""Select unseen RAISE/Synthbuster scene pairs before detector inference.

Downloading here only fetches public Synthbuster ZIP entries. RAISE acquisition
must follow its official application; this script never calls its gated endpoint.
Splits remain provisional until real source scenes and near duplicates are reviewed.
"""
import argparse
import json
import zipfile
from pathlib import Path
from collections import Counter
from acquire_evaluation_data import URL, SIZE
from remote_zip import RangeReader
from run_inference import ROOT, sha256


def selection():
    index_path=ROOT/"runs/20261001_baseline/source_access/synthbuster_index.json"
    entries=json.loads(index_path.read_text(encoding="utf-8"))
    old=json.loads((ROOT/"runs/20261001_baseline/synthbuster_samples.json").read_text(encoding="utf-8"))
    exposed={Path(item["path"]).stem for item in old["samples"]}
    groups={}
    for entry in entries:
        path=Path(entry["path"])
        if path.suffix.lower()==".png":
            groups.setdefault(path.parent.name,{})[path.stem]=entry
    common=sorted(set.intersection(*(set(items) for items in groups.values()))-exposed)
    if len(common)<40:
        raise ValueError("Insufficient unexposed scene IDs")
    generators=sorted(groups)
    samples=[]
    for index,scene in enumerate(common[:40]):
        generator=generators[index%len(generators)]
        entry=groups[generator][scene]
        samples.append({"scene_id":scene,"generator":generator,"source_entry":entry["path"],
            "bytes":entry["bytes"],"compressed_bytes":entry["compressed_bytes"],"crc32":entry["crc32"],
            "group_id":"raise_"+scene,"provisional_split":"tune" if index%2==0 else "final",
            "required_real_original":"RAISE-1k TIFF for "+scene})
    return {"selection":"first 40 sorted shared IDs absent from the exposed supplementary set; generator round robin",
        "source_index_sha256":sha256(index_path),"prior_exposed_scene_ids":sorted(exposed),
        "raw_detector_scores_read":False,"split_provisional":True,"real_scene_review_pending":True,
        "real_sources_acquired":False,"license":"CC-BY-NC-SA-4.0",
        "expected_sample_bytes":sum(s["bytes"] for s in samples),
        "expected_compressed_bytes":sum(s["compressed_bytes"] for s in samples),
        "generator_counts":dict(Counter(s["generator"] for s in samples)),"samples":samples}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--download",action="store_true")
    parser.add_argument("--out",type=Path,default=ROOT/"runs/20261001_original/bfree_selection.json")
    args=parser.parse_args()
    if args.out.exists():
        record=json.loads(args.out.read_text(encoding="utf-8"))
        if record["samples"] != selection()["samples"]:
            raise ValueError("Existing pre-score selection changed")
    else:
        record=selection()
        args.out.parent.mkdir(parents=True,exist_ok=True)
        with args.out.open("x",encoding="utf-8") as target:
            json.dump(record,target,indent=2)
    print("Selected fresh scenes",len(record["samples"]),"compressed bytes",record["expected_compressed_bytes"],flush=True)
    if not args.download:
        return
    acquired=args.out.with_name("bfree_synthbuster_acquisition.json")
    if acquired.exists():
        raise FileExistsError("Acquisition already recorded; preserve it")
    stream=RangeReader(URL,SIZE)
    records=[]
    with zipfile.ZipFile(stream) as packed:
        for item in record["samples"]:
            info=packed.getinfo(item["source_entry"])
            if info.file_size!=item["bytes"] or "%08x"%info.CRC!=item["crc32"]:
                raise ValueError("Remote archive entry changed")
            destination=ROOT/"data/synthbuster"/info.filename
            if not destination.resolve().is_relative_to((ROOT/"data/synthbuster").resolve()):
                raise ValueError("Unsafe ZIP entry")
            contents=packed.read(info)  # zipfile checks the entry CRC.
            destination.parent.mkdir(parents=True,exist_ok=True)
            if destination.exists() and destination.read_bytes()!=contents:
                raise ValueError("Existing source image differs")
            if not destination.exists():
                destination.write_bytes(contents)
            records.append({**item,"path":str(destination.relative_to(ROOT)),"sha256":sha256(destination)})
            print(item["scene_id"],item["generator"],info.file_size,flush=True)
    with acquired.open("x",encoding="utf-8") as target:
        json.dump({"url":URL,"selection_sha256":sha256(args.out),"transferred_bytes":stream.transferred,
            "entry_crc_verified":True,"whole_archive_md5_verified":False,"samples":records},target,indent=2)
    print("Acquired 40; transferred",stream.transferred,"RAISE pending",flush=True)


if __name__ == "__main__":
    main()
