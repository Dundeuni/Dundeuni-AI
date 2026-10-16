"""Real localization adapter; never substitutes a generated map for model output."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import tempfile
from dataclasses import replace
from pathlib import Path

from PIL import Image

from image_analysis.adapters import ManipulationOutput
from image_analysis.config import Settings
from image_analysis.cure import digest
from image_analysis.errors import ModelFailure
from image_analysis.schemas import ModelKind

WEIGHT_SHA256 = "ac1d90e329a72e0d66e8665e123a19e94bfae3209c3ef8a4f9ca3b91578c7844"


def dual_settings() -> Settings:
    return replace(
        Settings(),
        mode="CURE_TRUFOR",
        generation_only=False,
        hold_enabled=True,
        model_timeout_seconds=120,
        response_reserve_seconds=1,
    )


class TruForAdapter:
    kind: ModelKind = "manipulation"
    model_name = "TruFor"

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.python = self.root / ".venv/trufor/Scripts/python.exe"
        self.worker = Path(__file__).with_name("trufor_worker.py")
        self.process: asyncio.subprocess.Process | None = None
        source = self.root / "third_party/TruFor/TruFor_train_test"
        weight = source / "pretrained_models/weights/trufor.pth.tar"
        if not self.python.is_file() or digest(weight) != WEIGHT_SHA256:
            raise ValueError("TruFor runtime or weight integrity unavailable")
        manifest = {"weight": WEIGHT_SHA256, "worker": digest(self.worker)}
        for path in sorted(source.rglob("*.py")):
            manifest[str(path.relative_to(source))] = digest(path)
        manifest["config"] = digest(source / "lib/config/trufor_ph3.yaml")
        manifest["environment"] = digest(self.root / ".venv/trufor/pyvenv.cfg")
        binding = json.dumps(manifest, sort_keys=True).encode()
        self.model_version = "TruFor-ph3-" + hashlib.sha256(binding).hexdigest()[:20]
        self.ready = True

    async def infer(self, image: Image.Image) -> ManipulationOutput:
        if self.process is not None:
            raise ModelFailure("MODEL_RUNTIME_UNAVAILABLE")
        with tempfile.TemporaryDirectory(prefix="dundeuni_trufor_") as temp:
            folder = Path(temp)
            path, output = folder / "normalized.png", folder / "result.json"
            image.save(path, format="PNG")
            env = dict(os.environ)
            env.pop("DUNDEUNI_AI_SERVICE_TOKEN", None)
            self.process = await asyncio.create_subprocess_exec(
                str(self.python),
                "-X",
                "utf8",
                str(self.worker),
                "--root",
                str(self.root),
                "--input",
                str(path),
                "--output",
                str(output),
                env=env,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                _, stderr = await self.process.communicate()
                if self.process.returncode or not output.is_file():
                    lines = stderr.decode("utf-8", errors="replace").splitlines()
                    code = lines[-1] if lines else "MODEL_EXECUTION_FAILED"
                    if code not in ("MODEL_OUTPUT_INVALID", "MODEL_OUT_OF_MEMORY"):
                        code = "MODEL_EXECUTION_FAILED"
                    raise ModelFailure(code)
                result = json.loads(output.read_text("utf-8"))
                with Image.open(folder / "map.tiff") as raw_map:
                    map_image = raw_map.convert("F")
                try:
                    with Image.open(folder / "conf.tiff") as raw_conf:
                        conf_image = raw_conf.convert("F")
                    return ManipulationOutput(
                        score=result["score"],
                        map=map_image,
                        conf=conf_image,
                        imgsize=tuple(result["imgsize"]),
                    )
                except Exception:
                    map_image.close()
                    raise
            finally:
                await self.recover()

    async def recover(self) -> bool:
        process = self.process
        if process is not None:
            if process.returncode is None:
                try:
                    if os.name == "nt":
                        cleanup = await asyncio.create_subprocess_exec(
                            "taskkill",
                            "/PID",
                            str(process.pid),
                            "/T",
                            "/F",
                            stdout=asyncio.subprocess.DEVNULL,
                            stderr=asyncio.subprocess.DEVNULL,
                        )
                        await cleanup.wait()
                    else:
                        process.kill()
                except ProcessLookupError:
                    pass
            await process.wait()
            self.process = None
        return True
