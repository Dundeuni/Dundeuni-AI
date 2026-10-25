"""Verify repository files or separately supplied model assets without network I/O."""

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
from typing import Any


def digest(path: Path) -> str:
    """Return the SHA-256 of the exact file bytes without loading large weights."""
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def _canonical_bytes(data: bytes, hash_mode: str) -> bytes:
    if hash_mode == "raw":
        return data
    if hash_mode == "lf":
        data.decode("utf-8")
        return data.replace(b"\r\n", b"\n")
    raise ValueError(f"Unsupported hash mode: {hash_mode}")


def _load_manifest(path: Path) -> dict[str, Any]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("Manifest must be a JSON object")
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise ValueError("Manifest must list at least one file")
    return manifest


def _package_member(root: Path, relative: str) -> Path:
    relative_path = Path(relative)
    windows_path = PureWindowsPath(relative)
    if (
        relative_path.anchor
        or windows_path.anchor
        or ".." in relative_path.parts
        or ".." in windows_path.parts
    ):
        raise ValueError("Path must stay inside the package")
    path = root / relative_path
    path.resolve().relative_to(root.resolve())
    return path


def validate_repository(root: Path) -> list[str]:
    """Check listed paths, canonical sizes/hashes, and Python syntax.

    LF mode changes only CRLF byte pairs into LF. Raw mode preserves model and
    upstream notice bytes. The manifest itself is intentionally not self-hashed.
    """
    try:
        manifest = _load_manifest(root / "PACKAGE_MANIFEST.json")
    except (OSError, ValueError) as error:
        return [f"PACKAGE_MANIFEST.json: {type(error).__name__}"]

    errors: list[str] = []
    seen: set[str] = set()
    for entry in manifest["files"]:
        relative = entry["path"]
        try:
            path = _package_member(root, relative)
        except (OSError, RuntimeError, ValueError):
            errors.append(f"{relative}: path must stay inside the package")
            continue
        if relative in seen:
            errors.append(f"{relative}: duplicate manifest entry")
            continue
        seen.add(relative)
        if not path.is_file():
            errors.append(f"{relative}: missing")
            continue
        try:
            data = _canonical_bytes(path.read_bytes(), entry["hash_mode"])
        except (OSError, ValueError, KeyError) as error:
            error_type = type(error).__name__
            errors.append(f"{relative}: invalid bytes/hash mode ({error_type})")
            continue
        if (
            len(data) != entry["bytes"]
            or hashlib.sha256(data).hexdigest() != entry["sha256"]
        ):
            errors.append(f"{relative}: size/SHA-256 mismatch")
        if path.suffix == ".py":
            try:
                ast.parse(data.decode("utf-8"))
            except (SyntaxError, UnicodeError) as error:
                errors.append(f"{relative}: invalid Python ({type(error).__name__})")
    return errors


def validate_model_assets(folder: Path, manifest: dict[str, Any]) -> list[str]:
    """Check the exact bytes of the separately delivered model and tokenizer."""
    errors: list[str] = []
    for entry in manifest["files"]:
        relative = entry["path"]
        try:
            path = _package_member(folder, relative)
        except (OSError, RuntimeError, ValueError):
            errors.append(f"{relative}: path must stay inside the package")
            continue
        if not path.is_file():
            errors.append(f"{relative}: missing")
            continue
        if path.suffix == ".safetensors":
            with path.open("rb") as stream:
                pointer = b"version https://git-lfs.github.com/spec/v1"
                if stream.read(180).startswith(pointer):
                    errors.append(f"{relative}: received a pointer, not model weights")
                    continue
        if path.stat().st_size != entry["bytes"] or digest(path) != entry["sha256"]:
            errors.append(f"{relative}: size/SHA-256 mismatch")
    return errors


def main() -> int:
    """Select code-only or model verification and return a process exit code."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--code-only",
        action="store_true",
        help="Check repository hashes/syntax without model weights",
    )
    parser.add_argument(
        "--model-dir",
        type=Path,
        help="Separately received model folder; alternatively use AI_TEXT_MODEL_DIR",
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    if args.code_only:
        errors = validate_repository(root)
        if errors:
            print("FAILED: repository code check")
            print("\n".join(errors))
            return 1
        print(
            "PASS: repository paths, canonical hashes and Python syntax checked. "
            "Model weights were NOT checked; they are delivered separately."
        )
        return 0

    try:
        manifest = _load_manifest(root / "MODEL_ASSETS.json")
    except (OSError, ValueError) as error:
        print(f"FAILED: MODEL_ASSETS.json ({type(error).__name__})")
        return 1
    configured = args.model_dir or os.environ.get("AI_TEXT_MODEL_DIR")
    folder = (
        Path(configured)
        if configured
        else root / "models" / manifest["model_version"]
    )
    errors = validate_model_assets(folder, manifest)
    if errors:
        print("FAILED: model asset check")
        print("\n".join(errors))
        print(
            "Weights are not stored in Git. Obtain the exact trained assets "
            "separately and set AI_TEXT_MODEL_DIR, or use --model-dir."
        )
        return 1
    print(
        "PASS: separate model files match MODEL_ASSETS.json. "
        "No accuracy, OCR, or BE test was run."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
