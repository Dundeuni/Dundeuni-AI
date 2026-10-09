"""Read-only preflight for v0.2 replication; no inference or downloads."""
import pathlib,json,hashlib,sys
ROOT=pathlib.Path(__file__).resolve().parents[2]
BUNDLE=pathlib.Path(__file__).resolve().parent
def sha256(path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(4*1024*1024),b""):h.update(b)
    return h.hexdigest()
def check(path,expected):
    if not path.is_file():raise FileNotFoundError(path)
    if sha256(path)!=expected:raise ValueError("SHA-256 mismatch: "+str(path))
def main():
    for rel,expected in json.loads((BUNDLE/"code_sha256.json").read_text(encoding="utf-8")).items():
        check(ROOT/rel,expected)
    for record in json.loads((BUNDLE/"model_reference.json").read_text(encoding="utf-8")).values():
        check(ROOT/record["weights_path"],record["weights_sha256"])
    for rel,record in json.loads((BUNDLE/"required_data_files.json").read_text(encoding="utf-8")).items():
        check(ROOT/rel,record["sha256"])
    run=ROOT/"runs/20261004_followup";ref=BUNDLE/"reference/experiments/20261004_followup"
    for name in ("approved_protocol.json","scope_adjustment.json","bfree_manifest.json","tampering_manifest.json"):
        check(run/name,sha256(ref/name))
    sys.path.insert(0,str(ROOT/"scripts/v02"))
    from build_inputs import verify_rows
    from collections import Counter
    for task,count,roles in [("bfree",2400,{"setting":1200,"validation":1200}),
        ("tampering",1440,{"setting":480,"validation":480,"comparison":480})]:
        rows=json.loads((run/(task+"_manifest.json")).read_text(encoding="utf-8"))["rows"]
        if len(rows)!=count or dict(Counter(r["role"] for r in rows))!=roles:
            raise ValueError("Request/role count mismatch")
        verify_rows(rows)
        if task=="tampering" and any(r["dataset"]=="Columbia" and r["role"]!="comparison" for r in rows):
            raise ValueError("Columbia leaked into independent data")
    print("PASS: frozen code, weights, inputs/masks, protocol, roles, and source-group separation")
    print("Preflight only: GPU compatibility and inference completion are not certified.")
if __name__=="__main__":main()
