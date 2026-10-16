from __future__ import annotations

import asyncio
import hashlib
import json
import os
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Any

from PIL import Image

from image_analysis.adapters import GenerationOutput
from image_analysis.config import Settings
from image_analysis.errors import ModelFailure
from image_analysis.schemas import ModelKind

EXPECTED_WEIGHTS = {
    "third_party/CuRe/weights/cure_adapter.pt": (
        "17cabb334563c15abc8827db87dc272a4aef10f4279025faee1ef8d32c444ae1"
    ),
    "weights/CuRe/PE-Core-L14-336.pt": (
        "0cdab5b338cbaa1e7a5dcd1b2fb4c9f4d5df1abd289564658edbab64a650e7e8"
    ),
}


def resolve_cure_root(root: Path | None = None) -> Path:
    """Prefer an explicit asset root, otherwise require the environment setting."""
    value = root if root is not None else os.environ.get("DUNDEUNI_CURE_ROOT")
    if value is None or not str(value).strip():
        raise ValueError("Set --cure-root or DUNDEUNI_CURE_ROOT")
    return Path(value).expanduser().resolve()


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def cure_settings(settings: Settings | None = None) -> Settings:
    configured = settings is not None and settings.mode == "CURE"
    return replace(
        settings or Settings(),
        mode="CURE",
        generation_only=True,
        hold_enabled=settings.hold_enabled if configured and settings else True,
        generation_threshold=settings.generation_threshold
        if configured and settings
        else 0.5,
        model_timeout_seconds=settings.model_timeout_seconds
        if configured and settings
        else 120.0,
        response_reserve_seconds=settings.response_reserve_seconds
        if configured and settings
        else 1.0,
    )


class CureAdapter:
    """One isolated worker per inference; cancellation reaps its GPU process."""

    kind: ModelKind = "generation"
    model_name = "CuRe"

    def __init__(self, root: Path | None = None, reference: Path | None = None) -> None:
        self.root = resolve_cure_root(root)
        self.python = self.root / ".venv/cure/Scripts/python.exe"
        self.worker = Path(__file__).with_name("cure_worker.py")
        self.process: asyncio.subprocess.Process | None = None
        self.reference = reference
        self.last_metrics: dict[str, Any] = {}
        if not self.python.is_file():
            raise ValueError("Existing CuRe environment unavailable")
        sources = {name: digest(self.root / name) for name in EXPECTED_WEIGHTS}
        if sources != EXPECTED_WEIGHTS:
            raise ValueError("CuRe weight integrity mismatch")
        for source in sorted((self.root / "third_party/CuRe/cure").glob("*.py")):
            sources[str(source.relative_to(self.root))] = digest(source)
        sources["api_worker"] = digest(self.worker)
        # Bind critical metadata from the existing isolated environment.
        metadata_root = self.root / ".venv/cure/Lib/site-packages"
        packages = (
            "torch",
            "torchvision",
            "timm",
            "pillow",
            "albumentations",
            "opencv_python_headless",
        )
        for package in packages:
            for metadata in sorted(
                metadata_root.glob(package + "-*.dist-info/METADATA")
            ):
                sources["environment/" + metadata.parent.name] = digest(metadata)
        sources["environment/python"] = digest(self.root / ".venv/cure/pyvenv.cfg")
        self.manifest = sources
        binding = json.dumps(sources, sort_keys=True).encode()
        self.model_version = (
            "CuRe-pe-core-l14-336-" + hashlib.sha256(binding).hexdigest()[:20]
        )
        self.ready = True

    async def infer(self, image: Image.Image) -> GenerationOutput:
        if self.process is not None:
            raise ModelFailure("MODEL_RUNTIME_UNAVAILABLE")
        with tempfile.TemporaryDirectory(prefix="dundeuni_cure_") as directory:
            folder = Path(directory)
            input_path, output_path = folder / "normalized.png", folder / "result.json"
            image.save(
                input_path, format="PNG"
            )  # lossless transport to isolated worker
            source_format = image.info.get("analysis_source_format")
            if source_format not in ("PNG", "JPEG"):
                raise ModelFailure("MODEL_OUTPUT_INVALID")
            command = [
                str(self.python),
                "-X",
                "utf8",
                str(self.worker),
                "--root",
                str(self.root),
                "--input",
                str(input_path),
                "--source-format",
                str(source_format),
                "--output",
                str(output_path),
            ]
            if self.reference:
                command.extend(["--reference", str(self.reference)])
            environment = dict(os.environ)
            environment.pop("DUNDEUNI_AI_SERVICE_TOKEN", None)
            environment.update(
                HF_HUB_OFFLINE="1",
                TRANSFORMERS_OFFLINE="1",
                PYTHONUTF8="1",
                PYTHONDONTWRITEBYTECODE="1",
            )
            self.process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
                env=environment,
            )
            try:
                _, stderr = await self.process.communicate()
                if self.process.returncode != 0 or not output_path.is_file():
                    messages = stderr.decode("utf-8", errors="replace").splitlines()
                    message = messages[-1].strip() if messages else ""
                    code = (
                        message
                        if message in ("MODEL_OUT_OF_MEMORY", "MODEL_OUTPUT_INVALID")
                        else "MODEL_EXECUTION_FAILED"
                    )
                    raise ModelFailure(code)
                result = json.loads(output_path.read_text(encoding="utf-8"))
                self.last_metrics = result
                return GenerationOutput(score=result["score"])
            finally:
                await self._stop()

    async def _stop(self) -> None:
        if self.process is not None:
            if self.process.returncode is None:
                try:
                    if os.name == "nt":
                        # Windows venv launcher spawns a child interpreter.
                        # Kill only this owned worker tree, then wait for its handles.
                        cleanup = await asyncio.create_subprocess_exec(
                            "taskkill",
                            "/PID",
                            str(self.process.pid),
                            "/T",
                            "/F",
                            stdout=asyncio.subprocess.DEVNULL,
                            stderr=asyncio.subprocess.DEVNULL,
                        )
                        await cleanup.wait()
                    else:
                        self.process.kill()
                except ProcessLookupError:
                    pass
            await self.process.wait()
            self.process = None

    async def recover(self) -> bool:
        await self._stop()
        return True
