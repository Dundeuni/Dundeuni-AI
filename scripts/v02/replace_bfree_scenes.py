"""Replace visually exposed/ambiguous validation scenes before inference."""
import json,collections,concurrent.futures
from pathlib import Path
from common import ROOT,RUN,stable_key,save_json,sha256
from acquire_bfree_images import task
EXCLUDE={"r1e9c8a5dt":"Same cow-costume parade/location as v0.1 review",
 "r1ca5a385t":"Same ornate clock object as previously exposed museum image",
 "r06d3ac60t":"Clock/instrument gallery possibly same museum family as prior clock",
 "r0f2c63d2t":"Possible shared autumn lake location with setting r1800ab47t",
 "r0a10fe29t":"Ornate gallery ceiling possibly same prior museum/gallery family"}
def main():
    previous=json.loads((RUN/"bfree_source_selection.json").read_text())
    rows=[r for r in previous["selected"] if not(r["dataset"]=="synthbuster-plus" and r["image_id"] in EXCLUDE)]
    excluded=set(previous["old_exposed_ids_excluded"])|{r["image_id"] for r in previous["selected"] if r["dataset"]=="synthbuster-plus"}|set(EXCLUDE)
    by=collections.defaultdict(dict)
    for p in (RUN/"parquet_metadata").glob("synthbuster-plus_*.json"):
        for row in json.loads(p.read_text())["samples"]:by[row["image_id"]][row["source"]]=row
    sources=["raise1k","imagen3","FLUX.1-dev","FLUX.1-schnell","SD3-medium"]
    eligible=[id for id,g in by.items() if id not in excluded and all(s in g and g[s]["upstream_split"]=="test" for s in sources)]
    chosen=sorted(eligible,key=lambda id:stable_key("synthbuster-plus:validation:"+id))[:len(EXCLUDE)]
    if len(chosen)!=len(EXCLUDE):raise ValueError("Insufficient replacement candidates")
    for id in chosen:
        for source in sources:rows.append({**by[id][source],"role":"validation","group_id":"synthbuster-plus:"+id,"fold":None})
    plan={**previous,"selected":rows,"content_review_exclusions":EXCLUDE,"replacement_groups":chosen,"scores_used":False}
    save_json(RUN/"bfree_source_selection_v2.json",plan)
    acquired=json.loads((RUN/"bfree_images_provenance.json").read_text())
    index={(r["dataset"],r["source"],r["image_id"]):r for r in acquired["images"]}
    images=[];tasks=collections.defaultdict(list)
    for row in rows:
        key=(row["dataset"],row["source"],row["image_id"])
        if key in index:
            old=index[key]
            if sha256(ROOT/old["path"])!=old["sha256"]:raise ValueError("Existing acquired image changed")
            images.append({**old,"role":row["role"],"fold":row["fold"]})
        else:tasks[(row["dataset"],row["upstream_file"],row["row_group"])].append(row)
    extra=[]
    print("Source-only replacements",chosen,"new images",sum(map(len,tasks.values())),"chunks",len(tasks),flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        for value in pool.map(task,tasks.items()):
            extra.append(value);images.extend(value["images"])
            print("Replacement acquisition",len(images),"/400",flush=True)
    save_json(RUN/"bfree_replacement_chunk_provenance.json",extra)
    save_json(RUN/"bfree_images_provenance_v2.json",{"images":images,"original_embedded_bytes_preserved":True,
       "additional_range_bytes":sum(r["transferred"] for r in extra),"previous_provenance":str(RUN/"bfree_images_provenance.json")})
if __name__=="__main__":main()
