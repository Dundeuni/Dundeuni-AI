"""Select source groups before any new scores; preserve upstream train/test."""
import csv,json,collections,re
from pathlib import Path
from common import ROOT,RUN,SEED,stable_key,save_json
SOURCES=("imagen3","FLUX.1-dev","FLUX.1-schnell","SD3-medium")
def main():
    previous=set()
    for p in list((ROOT/"data/manifests").glob("*.csv"))+[ROOT/"runs/20261002_bfree_raise/preparation/manifest.csv"]:
        with p.open(encoding="utf-8-sig",newline="") as f:
            for row in csv.DictReader(f):
                for value in row.values():
                    if value:previous.update(re.findall(r"r[0-9a-f]{8}t",value))
    selected=[];summaries=[]
    for dataset in ["synthbuster-plus","synthclic"]:
        real="raise1k" if dataset=="synthbuster-plus" else "clic2020"
        catalogs=[json.loads(p.read_text()) for p in sorted((RUN/"parquet_metadata").glob(dataset+"_*.json"))]
        by=collections.defaultdict(dict)
        for c in catalogs:
            for row in c["samples"]:by[row["image_id"]][row["source"]]=row
        for split,role in [("train","setting"),("test","validation")]:
            eligible=[id for id,g in by.items() if id not in previous and all(s in g and g[s]["upstream_split"]==split for s in (real,)+SOURCES)]
            chosen=sorted(eligible,key=lambda id:stable_key(dataset+":"+role+":"+id))[:20]
            if len(chosen)!=20:raise ValueError("Insufficient complete unexposed scene groups")
            for index,id in enumerate(chosen):
                for source in (real,)+SOURCES:
                    selected.append({**by[id][source],"role":role,"group_id":dataset+":"+id,
                                     "fold":index%5 if role=="setting" else None})
            summaries.append({"dataset":dataset,"role":role,"available_groups":len(eligible),"selected_groups":chosen})
    chunks={(x["dataset"],x["upstream_file"],x["row_group"]) for x in selected}
    network=0
    for cpath in (RUN/"parquet_metadata").glob("*.json"):
        c=json.loads(cpath.read_text())
        for i,size in enumerate(c["image_chunk_bytes"]):
            if (c["dataset"],c["filename"],i) in chunks:network+=size
    save_json(RUN/"bfree_source_selection.json",{"seed":SEED,"old_exposed_ids_excluded":sorted(previous),"selection":"Fixed seeded hash order, metadata only; upstream train setting and test validation",
       "groups":summaries,"selected":selected,"selected_count":len(selected),"required_image_chunks":len(chunks),"estimated_range_bytes":network})
    print("Selected",len(selected),"images;",len(chunks),"image chunks; estimated bytes",network,flush=True)
if __name__=="__main__":main()
