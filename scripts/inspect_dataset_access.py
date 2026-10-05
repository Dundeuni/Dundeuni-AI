"""Public metadata only; does not submit personal data or request forms."""
import json
import re
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.links += [v for k, v in attrs if k == "href"]


def main():
    directory = ROOT / "runs/20261001_baseline/source_access"
    directory.mkdir(parents=True, exist_ok=True)
    urls = {
        "raise": "https://loki.disi.unitn.it/RAISE/confirm.php?package=1k",
        "coverage": "https://raw.githubusercontent.com/wenbihan/coverage/master/README.md",
        "synthbuster": "https://zenodo.org/api/records/10066460",
    }
    records = {}
    for name, url in urls.items():
        try:
            with urllib.request.urlopen(url, timeout=30) as response:
                content = response.read()
            (directory / (name + ".txt")).write_bytes(content)
            text = content.decode()
            if name == "raise":
                parser = Links()
                parser.feed(text)
                info = parser.links
            elif name == "coverage":
                info = re.findall(r"https://1drv\.ms/[^)\s]+", text)
            else:
                data = json.loads(text)
                info = {"files": [{k: f[k] for k in ("key", "size", "checksum", "links")}
                                  for f in data["files"]],
                        "license": data["metadata"].get("license")}
            records[name] = {"url": url, "status": "accessible", "info": info}
        except Exception as error:
            records[name] = {"url": url, "status": "failed", "error": str(error)}
    (directory / "metadata.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
    print(json.dumps(records, indent=2))


if __name__ == "__main__":
    main()
