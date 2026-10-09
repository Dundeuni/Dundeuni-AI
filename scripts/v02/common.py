"""Shared integrity, acquisition and manifest helpers."""
import datetime
import hashlib
import json
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
RUN = ROOT / "runs/20261004_followup"
DATA = ROOT / "data/v02"
SEED = 20261004
CONDITIONS = ("original", "jpeg_q75", "half_png", "messenger_proxy_512_q80", "screen_720x1280", "screen_photo_crop")


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(4*1024*1024), b""):
            h.update(block)
    return h.hexdigest()


def save_json(path, record, exclusive=True):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x" if exclusive else "w", encoding="utf-8") as stream:
        json.dump(record, stream, ensure_ascii=False, indent=2)


def get_json(url, maximum=8*1024**2):
    request = urllib.request.Request(url, headers={"User-Agent": "dundeuni-baseline-v02-research/1.0"})
    with urllib.request.urlopen(request, timeout=45) as response:
        data = response.read(maximum+1)
    if len(data) > maximum:
        raise ValueError("Metadata byte budget exceeded")
    return json.loads(data)


def acquire(url, destination, maximum, expected_sha256=None):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if expected_sha256 and sha256(destination) != expected_sha256:
            raise ValueError("Existing downloaded source hash differs")
        return {"path": str(destination.relative_to(ROOT)), "bytes": destination.stat().st_size, "sha256": sha256(destination), "reused": True}
    partial = destination.with_name(destination.name+".partial")
    if partial.exists():
        raise FileExistsError("Preserve incomplete download: " + str(partial))
    request = urllib.request.Request(url, headers={"User-Agent": "dundeuni-baseline-v02-research/1.0"})
    size = 0
    with urllib.request.urlopen(request, timeout=60) as response, partial.open("xb") as stream:
        if response.status != 200:
            raise ValueError("Unexpected download response")
        for block in iter(lambda: response.read(1024*1024), b""):
            size += len(block)
            if size > maximum:
                raise ValueError("Download byte budget exceeded")
            stream.write(block)
    result_hash = sha256(partial)
    if expected_sha256 and result_hash != expected_sha256:
        raise ValueError("Downloaded source hash differs")
    partial.replace(destination)
    return {"path": str(destination.relative_to(ROOT)), "bytes": size, "sha256": result_hash, "reused": False}


def timestamp():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def stable_key(value):
    return hashlib.sha256((str(SEED)+":"+value).encode("utf-8")).hexdigest()
