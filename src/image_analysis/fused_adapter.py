from __future__ import annotations

import asyncio
from pathlib import Path

from PIL import Image

from image_analysis.adapters import ManipulationOutput
from image_analysis.cure import digest
from image_analysis.schemas import ModelKind


class FusedAdapter:
    kind: ModelKind = "manipulation"
    model_name = "FUSED"

    def __init__(self, weights: Path) -> None:
        import torch  # type: ignore[import-not-found]

        from image_analysis.fused_inference import FusedEnsemble

        if not torch.cuda.is_available():
            raise ValueError("FUSED requires CUDA")
        torch.set_num_threads(4)
        self.model = FusedEnsemble(weights, "cuda")
        self.model_version = (
            "FUSED-20-80-" + digest(Path(__file__).with_name("fused_inference.py"))[:20]
        )
        self.ready = True

    def _predict(self, image: Image.Image) -> ManipulationOutput:
        (open_score, open_map), (so_score, so_map) = self.model.predict(image)
        with Image.fromarray(0.2 * open_map + 0.8 * so_map) as combined:
            localization = combined.resize(image.size, Image.Resampling.BILINEAR)
        return ManipulationOutput(
            score=0.2 * open_score + 0.8 * so_score,
            map=localization,
            conf=None,
            imgsize=(image.height, image.width),
        )

    async def infer(self, image: Image.Image) -> ManipulationOutput:
        worker = asyncio.create_task(asyncio.to_thread(self._predict, image))
        try:
            return await asyncio.shield(worker)
        except asyncio.CancelledError:
            # Keep ownership of the image and CUDA until the thread returns.
            try:
                output = await worker
            except Exception:
                pass
            else:
                output.map.close()
            raise

    async def recover(self) -> bool:
        # Any failed CUDA request is quarantined until the local server restarts.
        return False
