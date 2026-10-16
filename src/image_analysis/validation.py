from __future__ import annotations

import re
from datetime import datetime, timezone
from uuid import UUID

from starlette.datastructures import FormData, UploadFile

from image_analysis.errors import TransportError
from image_analysis.schemas import ModelKind

UUID_PATTERN = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\Z")
DEADLINE_PATTERN = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?Z\Z")
REQUIRED = {"file", "analysisId", "elementId", "sourceType", "deadlineAt"}
ALLOWED = REQUIRED | {"models"}


def valid_uuid(value: str, *, v4: bool = False) -> bool:
    if not UUID_PATTERN.fullmatch(value):
        return False
    parsed = UUID(value)
    return not v4 or parsed.version == 4


def validate_form(
    form: FormData,
    now: datetime,
    generation_only: bool = False,
) -> tuple[dict[str, str], UploadFile, list[ModelKind], datetime]:
    fields: dict[str, str] = {}
    seen: set[str] = set()
    upload = None
    for key, value in form.multi_items():
        if key not in ALLOWED or key in seen:
            raise TransportError(400, "INVALID_REQUEST")
        seen.add(key)
        if key == "file":
            if not isinstance(value, UploadFile):
                raise TransportError(400, "INVALID_REQUEST")
            upload = value
        else:
            if not isinstance(value, str) or len(value.encode("utf-8")) > 128:
                raise TransportError(400, "INVALID_REQUEST")
            fields[key] = value
    if not REQUIRED <= seen or upload is None:
        raise TransportError(400, "INVALID_REQUEST")
    if any(not valid_uuid(fields[key]) for key in ("analysisId", "elementId")):
        raise TransportError(400, "INVALID_REQUEST")
    if fields["sourceType"] not in ("IMAGE", "SCREEN_CROP"):
        raise TransportError(400, "INVALID_REQUEST")
    choice = fields.get("models", "GENERATION" if generation_only else "ALL")
    if generation_only and choice != "GENERATION":
        raise TransportError(400, "INVALID_REQUEST")
    selected: list[ModelKind] = []
    if choice in ("ALL", "GENERATION"):
        selected.append("generation")
    if choice in ("ALL", "MANIPULATION"):
        selected.append("manipulation")
    if not selected:
        raise TransportError(400, "INVALID_REQUEST")
    if not DEADLINE_PATTERN.fullmatch(fields["deadlineAt"]):
        raise TransportError(400, "INVALID_REQUEST")
    try:
        deadline = datetime.fromisoformat(fields["deadlineAt"][:-1] + "+00:00")
    except ValueError as exc:
        raise TransportError(400, "INVALID_REQUEST") from exc
    if deadline <= now.astimezone(timezone.utc):
        raise TransportError(422, "DEADLINE_EXPIRED")
    return fields, upload, selected, deadline
