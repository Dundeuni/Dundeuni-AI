from __future__ import annotations

import io
from datetime import timedelta
from uuid import uuid4

import pytest
from PIL import Image

from image_analysis.service import timestamp, utc_now


def image_bytes(
    mode="RGB",
    size=(64, 48),
    color=None,
    format="PNG",
    **kwargs,
):
    with Image.new(mode, size, color) as image:
        output = io.BytesIO()
        image.save(output, format=format, **kwargs)
        return output.getvalue()


def request_parts(data=None, mime="image/png", fields=None):
    values = {
        "analysisId": "8c1b24c0-3186-4ee5-a679-74acb055b001",
        "elementId": "a65d2da5-8ec3-4f89-b066-0f24ce940001",
        "sourceType": "IMAGE",
        "deadlineAt": timestamp(utc_now() + timedelta(seconds=30)),
    }
    if fields:
        values.update(fields)
    parts = [(key, (None, value)) for key, value in values.items() if value is not None]
    parts.append(
        ("file", ("synthetic.png", data if data is not None else image_bytes(), mime))
    )
    return parts


def request_headers():
    return {
        "Authorization": "Bearer MOCK_ONLY_NOT_A_SECRET",
        "X-Request-ID": str(uuid4()),
    }


@pytest.fixture
def headers():
    return request_headers()
