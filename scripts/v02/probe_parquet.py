"""Read only Parquet metadata columns; embedded image bytes remain unopened."""
import concurrent.futures
import io
import json
import urllib.request
from pathlib import Path
import pyarrow.parquet as pq
from common import ROOT, RUN, save_json, timestamp


class BoundedRangeReader(io.RawIOBase):
    def __init__(self, url, size, maximum):
        super().__init__()
        self.url, self.size, self.maximum = url, size, maximum
        self.position, self.transferred = 0, 0
    def seekable(self): return True
    def readable(self): return True
    def tell(self): return self.position
    def seek(self, offset, whence=0):
        value = offset if whence==0 else (self.position if whence==1 else self.size)+offset
        if value<0: raise ValueError("Negative seek")
        self.position=value
        return value
    def read(self, count=-1):
        if count<0: count=self.size-self.position
        count=min(count,self.size-self.position)
        if count<=0:return b""
        if self.transferred+count>self.maximum:raise ValueError("Range byte budget exceeded")
        start,end=self.position,self.position+count-1
        request=urllib.request.Request(self.url,headers={"Range":f"bytes={start}-{end}","User-Agent":"dundeuni-baseline-v02-research"})
        with urllib.request.urlopen(request,timeout=60) as response:
            if response.status!=206 or response.headers.get("Content-Range")!=f"bytes {start}-{end}/{self.size}":
                raise ValueError("Server did not honor exact range; full archive download refused")
            value=response.read(count+1)
        if len(value)!=count:raise ValueError("Truncated or oversized range")
        self.position+=count;self.transferred+=count
        return value


def inspect(item):
    dataset,revision,file=item
    filename=file["rfilename"]
    url=f"https://huggingface.co/datasets/marco-willi/{dataset}/resolve/{revision}/{filename}"
    reader=BoundedRangeReader(url,file["size"],4*1024**2)
    parquet=pq.ParquetFile(reader)
    records=[]
    for group in range(parquet.num_row_groups):
        table=parquet.read_row_group(group,columns=["label","image_id","ds_name","source","image.path"])
        for row_index,row in enumerate(table.to_pylist()):
            row.update(dataset=dataset,upstream_split=Path(filename).name.split("-")[0],
                       upstream_file=filename,row_group=group,row_in_group=row_index,
                       upstream_revision=revision)
            records.append(row)
    return {"dataset":dataset,"filename":filename,"revision":revision,
            "row_groups":parquet.num_row_groups,"rows":len(records),
            "row_group_sizes":[parquet.metadata.row_group(i).num_rows for i in range(parquet.num_row_groups)],
            "image_chunk_bytes":[parquet.metadata.row_group(i).column(0).total_compressed_size for i in range(parquet.num_row_groups)],
            "transferred_metadata_bytes":reader.transferred,"samples":records}


def main():
    tasks=[]
    for name,filename in [("synthbuster-plus","synthbuster_plus.json"),("synthclic","synthclic.json")]:
        metadata=json.loads((RUN/"source_probe"/filename).read_text())
        tasks.extend((name,metadata["sha"],f) for f in metadata["siblings"] if f["rfilename"].endswith(".parquet"))
    out=RUN/"parquet_metadata"
    out.mkdir(exist_ok=False)
    results=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        for count,result in enumerate(pool.map(inspect,tasks),1):
            path=out/(result["dataset"]+"_"+Path(result["filename"]).stem+".json")
            save_json(path,result)
            results.append({k:v for k,v in result.items() if k!="samples"})
            print(count,len(tasks),result["dataset"],result["filename"],result["rows"],"groups",result["row_groups"],"metadata bytes",result["transferred_metadata_bytes"],flush=True)
    save_json(RUN/"parquet_catalog_summary.json",{"created_at_utc":timestamp(),"files":results,
        "total_rows":sum(r["rows"] for r in results),"metadata_bytes":sum(r["transferred_metadata_bytes"] for r in results),"image_bytes_read":0})


if __name__=="__main__":main()
