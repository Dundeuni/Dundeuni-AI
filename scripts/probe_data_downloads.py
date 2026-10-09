import base64
import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    share = "https://1drv.ms/f/s!AggVhXcCj1FLhUUyUrqSpV_yI_GH"
    token = "u!" + base64.urlsafe_b64encode(share.encode()).decode().rstrip("=")
    probes = {
        "coverage_public_api": (f"https://api.onedrive.com/v1.0/shares/{token}/root?expand=children", {}),
        "coverage_public_page": (share, {}),
        "columbia_download": ("https://www.dropbox.com/sh/786qv3yhvc7s9ki/AACbEEzGPrD3_y38bpWHzgdqa?dl=1", {}),
        "synthbuster_range": ("https://zenodo.org/api/records/10066460/files/synthbuster.zip/content",
                              {"Range": "bytes=12372491690-12372557225"}),
    }
    records = {}
    folder = ROOT / "runs/20261001_baseline/source_access"
    for name, (url, headers) in probes.items():
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=40) as response:
                data = response.read(2*1024**2)
                record = {"status": response.status, "content_type": response.headers.get("Content-Type"),
                          "content_length": response.headers.get("Content-Length"),
                          "content_range": response.headers.get("Content-Range"), "read_bytes": len(data)}
            (folder / (name + ".response")).write_bytes(data)
            records[name] = record
        except Exception as error:
            records[name] = {"error": str(error)}
    (folder / "download_probes.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
    print(json.dumps(records, indent=2))


if __name__ == "__main__":
    main()
