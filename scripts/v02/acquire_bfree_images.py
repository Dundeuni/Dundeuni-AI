"""Extract selected embedded image bytes via bounded official Parquet ranges."""
import collections,concurrent.futures,hashlib,io,json,time
from pathlib import Path
from PIL import Image
import pyarrow.parquet as pq
from common import ROOT,RUN,DATA,save_json,timestamp
from probe_parquet import BoundedRangeReader
def task(item):
    key,selected=item
    dataset,filename,group=key
    source_metadata="synthbuster_plus.json" if dataset=="synthbuster-plus" else "synthclic.json"
    repository=json.loads((RUN/"source_probe"/source_metadata).read_text())
    blob=next(x for x in repository["siblings"] if x["rfilename"]==filename)
    revision=repository["sha"]
    url=f"https://huggingface.co/datasets/marco-willi/{dataset}/resolve/{revision}/{filename}"
    reader=BoundedRangeReader(url,blob["size"],400*1024**2)
    parquet=pq.ParquetFile(reader)
    table=parquet.read_row_group(group,columns=["image"])
    results=[]
    for selected_row in selected:
        payload=table[selected_row["row_in_group"]][0].as_py() if False else table.column("image")[selected_row["row_in_group"]].as_py()
        data=payload["bytes"]
        expected=selected_row["image"]["path"]
        if payload["path"]!=expected:raise ValueError("Metadata/image row mismatch")
        with Image.open(io.BytesIO(data)) as image:
            image.verify()
        with Image.open(io.BytesIO(data)) as image:
            size=list(image.size);format=image.format
        suffix={"PNG":".png","JPEG":".jpg","TIFF":".tif"}.get(format)
        if suffix is None:raise ValueError("Unexpected original format: "+str(format))
        destination=DATA/"bfree"/dataset/selected_row["source"]/(selected_row["image_id"]+suffix)
        destination.parent.mkdir(parents=True,exist_ok=True)
        if destination.exists():
            if hashlib.sha256(destination.read_bytes()).digest()!=hashlib.sha256(data).digest():raise ValueError("Existing source differs")
        else:destination.write_bytes(data)
        results.append({**selected_row,"path":str(destination.relative_to(ROOT)),"bytes":len(data),"sha256":hashlib.sha256(data).hexdigest(),"size":size,"format":format})
    del table,parquet
    return {"dataset":dataset,"file":filename,"group":group,"transferred":reader.transferred,"images":results}
def main():
    plan=json.loads((RUN/"bfree_source_selection.json").read_text())
    grouped=collections.defaultdict(list)
    for row in plan["selected"]:grouped[(row["dataset"],row["upstream_file"],row["row_group"])].append(row)
    provenance=RUN/"bfree_chunks";provenance.mkdir(exist_ok=True)
    complete=[];tasks=[]
    for key,rows in grouped.items():
        marker=provenance/(key[0]+"_"+Path(key[1]).stem+"_"+str(key[2])+".json")
        if marker.exists():
            complete.append(json.loads(marker.read_text()))
        else:tasks.append((key,rows))
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        futures={pool.submit(task,item):item[0] for item in tasks}
        for future in concurrent.futures.as_completed(futures):
            value=future.result()
            marker=provenance/(value["dataset"]+"_"+Path(value["file"]).stem+"_"+str(value["group"])+".json")
            save_json(marker,value)
            complete.append(value)
            print("B-Free chunks",len(complete),"/",len(grouped),"images",sum(len(x["images"]) for x in complete),"transferred",sum(x["transferred"] for x in complete),flush=True)
    images=[row for chunk in complete for row in chunk["images"]]
    if len(images)!=400:raise ValueError("Incomplete 400-image acquisition")
    save_json(RUN/"bfree_images_provenance.json",{"created_at_utc":timestamp(),"images":images,"total_range_bytes":sum(x["transferred"] for x in complete),"original_embedded_bytes_preserved":True})
if __name__=="__main__":main()
