from __future__ import annotations

import hashlib
import io
import warnings
from dataclasses import dataclass

from PIL import Image, ImageOps, UnidentifiedImageError

from image_analysis.config import Settings
from image_analysis.errors import TransportError
from image_analysis.schemas import AnalysisImage


@dataclass
class NormalizedImage:
    image: Image.Image
    metadata: AnalysisImage
    alpha_composited: bool


def check_dimensions(width: int, height: int, settings: Settings) -> None:
    if max(width, height) > settings.max_side or width * height > settings.max_pixels:
        raise TransportError(413, "IMAGE_LIMIT_EXCEEDED")
    if min(width, height) < settings.min_side:
        raise TransportError(422, "IMAGE_TOO_SMALL")


def normalize_image(data: bytes, mime: str, settings: Settings) -> NormalizedImage:
    """Verify signature, decoder, one frame, bounds; orient once, white alpha, RGB."""
    if len(data) > settings.max_file_bytes:
        raise TransportError(413, "PAYLOAD_TOO_LARGE")
    if not data:
        raise TransportError(422, "INVALID_IMAGE")
    expected = (
        "PNG"
        if data.startswith(b"\x89PNG\r\n\x1a\n")
        else "JPEG"
        if data.startswith(b"\xff\xd8\xff")
        else None
    )
    if expected is None or mime != {"PNG": "image/png", "JPEG": "image/jpeg"}[expected]:
        raise TransportError(415, "UNSUPPORTED_IMAGE_FORMAT")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as source:
                if source.format != expected or getattr(source, "n_frames", 1) != 1:
                    raise TransportError(415, "UNSUPPORTED_IMAGE_FORMAT")
                check_dimensions(*source.size, settings)
                source.verify()
            with Image.open(io.BytesIO(data)) as source:
                source.load()
                oriented = ImageOps.exif_transpose(source)
                try:
                    check_dimensions(*oriented.size, settings)
                    alpha = (
                        "A" in oriented.getbands() or "transparency" in oriented.info
                    )
                    if alpha:
                        with oriented.convert("RGBA") as rgba:
                            with Image.new("RGBA", rgba.size, "white") as white:
                                with Image.alpha_composite(white, rgba) as composed:
                                    rgb = composed.convert("RGB")
                    else:
                        rgb = oriented.convert("RGB")
                finally:
                    oriented.close()
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise TransportError(413, "IMAGE_LIMIT_EXCEEDED") from exc
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError) as exc:
        raise TransportError(422, "INVALID_IMAGE") from exc
    # CuRe's official PNG-only JPEG96 step depends on decoder format, not filename.
    rgb.info["analysis_source_format"] = expected
    return NormalizedImage(
        image=rgb,
        metadata=AnalysisImage(
            width=rgb.width,
            height=rgb.height,
            inputSha256=hashlib.sha256(data).hexdigest(),
            normalizationVersion=settings.mode
            + "-normalization-v1-exif-rgb-white-alpha",
        ),
        alpha_composited=alpha,
    )
