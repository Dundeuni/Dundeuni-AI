"""One real CuRe/Node HTTP call on a synthetic image; not an accuracy evaluation."""

from __future__ import annotations

import asyncio
import json
import socket
import tempfile
from pathlib import Path

import uvicorn
from PIL import Image

from image_analysis.app import create_app
from image_analysis.cure import CureAdapter, cure_settings


async def main() -> None:
    root = Path(__file__).resolve().parents[1]
    adapter = CureAdapter()
    app = create_app(cure_settings(), {"generation": adapter})
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, access_log=False, log_level="error"))
    task = asyncio.create_task(server.serve(sockets=[sock]))
    process = None
    try:
        while not server.started:
            if task.done():
                await task
                raise RuntimeError("Server did not start")
            await asyncio.sleep(0.01)
        with tempfile.TemporaryDirectory(prefix="cure-be-check-") as temp:
            path = Path(temp) / "synthetic.png"
            with Image.new("RGB", (64, 64), (30, 100, 170)) as image:
                image.save(path)
            process = await asyncio.create_subprocess_exec(
                "node",
                str(root / "integration/live-provider-check.mjs"),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            config = {
                "origin": f"http://127.0.0.1:{port}",
                "path": str(path),
                "mime": "image/png",
            }
            out, _ = await asyncio.wait_for(
                process.communicate(json.dumps(config).encode()), timeout=145
            )
            if process.returncode:
                raise RuntimeError("Node BE provider live check failed")
            result = json.loads(out)
            assert adapter.process is None
            report = {
                "passed": True,
                "input": "synthetic RGB PNG 64x64",
                "purpose": "BE provider contract, not model accuracy",
                "result": result,
                "workerCleaned": True,
            }
            (root / "validation/be-provider-live-20261012.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print("Real GPU / Node BE provider: passed; worker cleaned")
    finally:
        if process is not None and process.returncode is None:
            process.kill()
            await process.wait()
        server.should_exit = True
        await task


if __name__ == "__main__":
    asyncio.run(main())
