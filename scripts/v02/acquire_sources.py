"""Acquire exact official Mesorch source and CocoGlide without editing v0.1."""
import concurrent.futures,hashlib,json,zipfile
from pathlib import Path
from common import ROOT,RUN,DATA,acquire,save_json,timestamp

def mesorch():
    tree=json.loads((RUN/"source_probe/mesorch_tree.json").read_text())
    revision=tree["sha"]
    dest=ROOT/"third_party/Mesorch"
    results=[]
    for blob in tree["tree"]:
        if blob["type"]!="blob" or blob["path"].startswith("images/"):continue
        url=f'https://raw.githubusercontent.com/scu-zjz/Mesorch/{revision}/{blob["path"]}'
        path=dest/blob["path"]
        result=acquire(url,path,1024**2)
        data=path.read_bytes()
        actual=hashlib.sha1(b"blob "+str(len(data)).encode()+b"\0"+data).hexdigest()
        if actual!=blob["sha"]:raise ValueError("Git blob integrity differs: "+blob["path"])
        result.update(git_blob_sha1=actual)
        results.append(result)
        print("Mesorch source verified",blob["path"],flush=True)
    save_json(RUN/"mesorch_source_provenance.json",{"revision":revision,"files":results,"created_at_utc":timestamp()})

def coco():
    url="https://www.grip.unina.it/download/prog/TruFor/CocoGlide.zip"
    archive=ROOT/"artifacts/downloads/v02/CocoGlide.zip"
    result=acquire(url,archive,130*1024**2)
    if result["bytes"]!=123161479:raise ValueError("Official archive changed size")
    print("CocoGlide downloaded",result["bytes"],flush=True)
    dest=DATA/"cocoglide_upstream"
    dest.mkdir(parents=True,exist_ok=False)
    with zipfile.ZipFile(archive) as z:
        bad=z.testzip()
        if bad:raise ValueError("CRC failure: "+bad)
        for member in z.infolist():
            target=(dest/member.filename).resolve()
            if dest.resolve() not in target.parents and target!=dest.resolve():raise ValueError("Unsafe ZIP member")
            if (member.external_attr>>16)&0o170000==0o120000:raise ValueError("Symlink ZIP member refused")
        z.extractall(dest)
        names=z.namelist()
    save_json(RUN/"cocoglide_source_provenance.json",{"url":url,"download":result,"members":names,"crc_checked":True,"created_at_utc":timestamp()})
    print("CocoGlide CRC checked and extracted",len(names),flush=True)

if __name__=="__main__":
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(mesorch),pool.submit(coco)]
        for f in futures:f.result()
