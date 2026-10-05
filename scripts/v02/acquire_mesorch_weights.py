"""Download final checkpoints through official anonymous download forms."""
import concurrent.futures,html.parser,urllib.parse,json,zipfile
from common import ROOT,RUN,acquire,save_json,timestamp
class Form(html.parser.HTMLParser):
    def __init__(self):super().__init__();self.inputs={};self.action=None
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=="form" and a.get("id")=="download-form":self.action=a.get("action")
        if tag=="input" and a.get("type")=="hidden":self.inputs[a.get("name")]=a.get("value")
def download(item):
    name,filename,file_id=item
    parser=Form();parser.feed((RUN/(name+"_public_download_form.html")).read_text())
    if parser.action!="https://drive.usercontent.google.com/download" or parser.inputs.get("id")!=file_id:
        raise ValueError("Unexpected official anonymous download form")
    url=parser.action+"?"+urllib.parse.urlencode(parser.inputs)
    path=ROOT/"third_party/Mesorch/weights"/filename
    result=acquire(url,path,1200*1024**2)
    if not zipfile.is_zipfile(path):raise ValueError("Checkpoint is not a PyTorch ZIP archive")
    with zipfile.ZipFile(path) as z:
        if not any(x.endswith("data.pkl") for x in z.namelist()):raise ValueError("Checkpoint payload missing")
    result.update(model=name,official_file_id=file_id,source="Official Mesorch README public Google Drive folder")
    save_json(RUN/(name+"_weights_provenance.json"),result)
    print(name,result["bytes"],result["sha256"],flush=True)
if __name__=="__main__":
    items=[("mesorch","mesorch-98.pth","1PJxKteinMyaAYokKy0JhuzBnBc6bGsau"),("mesorch_p","mesorch_p-118.pth","1uDu-wJLUA18xX0xiRoSgq2EtRm5KP4h5")]
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        for value in pool.map(download,items):pass
