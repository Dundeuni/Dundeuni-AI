"""Portable byte-integrity and failure-path checks; no real weights or GPU."""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from check_package import validate_model_assets, validate_repository


class PackageCheckTests(unittest.TestCase):
    """Verify newline tolerance without tolerating content or asset changes."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def write_manifest(
        self,
        name: str,
        expected: bytes,
        hash_mode: str = "lf",
    ) -> dict[str, Any]:
        """Write a minimal integrity manifest for a single test fixture."""
        entry = {
            "path": name,
            "bytes": len(expected),
            "sha256": hashlib.sha256(expected).hexdigest(),
            "hash_mode": hash_mode,
        }
        manifest = {"schema_version": 2, "files": [entry]}
        (self.root / "PACKAGE_MANIFEST.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        return manifest

    def test_lf_and_crlf_match_the_same_canonical_hash(self) -> None:
        content = b"VALUE = 1\n"
        self.write_manifest("sample.py", content)
        for actual in (content, b"VALUE = 1\r\n"):
            with self.subTest(actual=actual):
                (self.root / "sample.py").write_bytes(actual)
                self.assertEqual(validate_repository(self.root), [])

    def test_content_mutation_is_rejected(self) -> None:
        self.write_manifest("sample.py", b"VALUE = 1\n")
        (self.root / "sample.py").write_bytes(b"VALUE = 2\n")
        self.assertTrue(validate_repository(self.root))

    def test_missing_file_is_rejected(self) -> None:
        self.write_manifest("missing.py", b"VALUE = 1\n")
        self.assertIn("missing.py: missing", validate_repository(self.root))

    def test_raw_asset_newline_change_is_rejected(self) -> None:
        self.write_manifest("config.json", b"{}\r\n", "raw")
        (self.root / "config.json").write_bytes(b"{}\n")
        self.assertTrue(validate_repository(self.root))

    def test_raw_asset_bytes_are_accepted(self) -> None:
        self.write_manifest("config.json", b"{}\r\n", "raw")
        (self.root / "config.json").write_bytes(b"{}\r\n")
        self.assertEqual(validate_repository(self.root), [])

    def test_unknown_hash_mode_is_rejected(self) -> None:
        self.write_manifest("sample.txt", b"value\n", "unknown")
        (self.root / "sample.txt").write_bytes(b"value\n")
        self.assertTrue(validate_repository(self.root))

    def test_invalid_utf8_is_rejected(self) -> None:
        self.write_manifest("sample.txt", b"\xff\n")
        (self.root / "sample.txt").write_bytes(b"\xff\n")
        self.assertTrue(validate_repository(self.root))

    def test_duplicate_paths_are_rejected(self) -> None:
        manifest = self.write_manifest("sample.py", b"VALUE = 1\n")
        manifest["files"].append(dict(manifest["files"][0]))
        (self.root / "PACKAGE_MANIFEST.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        (self.root / "sample.py").write_bytes(b"VALUE = 1\n")
        self.assertIn(
            "sample.py: duplicate manifest entry", validate_repository(self.root)
        )

    def test_invalid_python_is_rejected_even_with_matching_hash(self) -> None:
        self.write_manifest("sample.py", b"def broken(\n")
        (self.root / "sample.py").write_bytes(b"def broken(\n")
        self.assertTrue(validate_repository(self.root))

    def test_missing_final_newline_changes_the_hash(self) -> None:
        self.write_manifest("sample.txt", b"value\n")
        (self.root / "sample.txt").write_bytes(b"value")
        self.assertTrue(validate_repository(self.root))

    def test_rooted_and_parent_paths_are_rejected(self) -> None:
        names = ("/outside.py", "\\outside.py", "C:outside.py", "../outside.py")
        for name in names:
            with self.subTest(name=name):
                self.write_manifest(name, b"VALUE = 1\n")
                errors = validate_repository(self.root)
                self.assertTrue(any("inside the package" in error for error in errors))

    def test_lfs_pointer_is_not_accepted_as_model_weights(self) -> None:
        manifest = self.write_manifest("model.safetensors", b"actual weights")
        (self.root / "model.safetensors").write_bytes(
            b"version https://git-lfs.github.com/spec/v1\n"
        )
        errors = validate_model_assets(self.root, manifest)
        self.assertTrue(any("received a pointer" in error for error in errors))

    def test_model_rooted_and_parent_paths_are_rejected(self) -> None:
        names = ("/outside.bin", "\\outside.bin", "C:outside.bin", "../outside.bin")
        for name in names:
            with self.subTest(name=name):
                manifest = self.write_manifest(name, b"actual weights", "raw")
                errors = validate_model_assets(self.root, manifest)
                self.assertTrue(any("inside the package" in error for error in errors))

    def test_symlink_to_outside_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as other:
            outside = Path(other) / "outside.py"
            outside.write_bytes(b"VALUE = 1\n")
            linked = self.root / "linked.py"
            try:
                linked.symlink_to(outside)
            except OSError:
                self.skipTest("Creating symbolic links is unavailable on this host")
            manifest = self.write_manifest("linked.py", b"VALUE = 1\n")
            code_errors = validate_repository(self.root)
            asset_errors = validate_model_assets(self.root, manifest)
            for errors in (code_errors, asset_errors):
                self.assertTrue(any("inside the package" in error for error in errors))

    def test_valid_separate_assets_are_accepted(self) -> None:
        content = b"test model asset"
        manifest = self.write_manifest("model.safetensors", content)
        (self.root / "model.safetensors").write_bytes(content)
        self.assertEqual(validate_model_assets(self.root, manifest), [])


if __name__ == "__main__":
    unittest.main()
