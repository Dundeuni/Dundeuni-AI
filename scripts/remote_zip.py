"""Bounded HTTP Range ZIP reader. Never silently downloads the full archive."""
import io
import urllib.request


class RangeReader(io.RawIOBase):
    def __init__(self, url, size, max_bytes=200*1024**2):
        self.url = url
        self.size = size
        self.position = 0
        self.transferred = 0
        self.max_bytes = max_bytes

    def seekable(self):
        return True

    def readable(self):
        return True

    def tell(self):
        return self.position

    def seek(self, offset, whence=0):
        position = offset if whence == 0 else (self.position if whence == 1 else self.size) + offset
        if position < 0:
            raise ValueError("Negative seek")
        self.position = position
        return position

    def read(self, count=-1):
        if count < 0:
            count = self.size-self.position
        count = min(count, self.size-self.position)
        if count <= 0:
            return b""
        if self.transferred + count > self.max_bytes:
            raise RuntimeError("Partial download byte budget exceeded")
        start, end = self.position, self.position+count-1
        request = urllib.request.Request(self.url, headers={"Range": f"bytes={start}-{end}"})
        with urllib.request.urlopen(request, timeout=60) as response:
            expected = f"bytes {start}-{end}/{self.size}"
            if response.status != 206 or response.headers.get("Content-Range") != expected:
                raise RuntimeError("Server did not honor exact byte range")
            result = response.read(count+1)
        if len(result) != count:
            raise RuntimeError("Truncated or oversized range response")
        self.position += count
        self.transferred += count
        return result
