"""Untrusted metadata must not redirect source acquisition outside official TIFF IDs."""
import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import probe_raise_csv


class RaiseMetadataTests(unittest.TestCase):
    def fixture(self, root, change=None):
        scenes = ["r%08xt" % index for index in range(1000)]
        source = root / "runs/20261001_original"
        source.mkdir(parents=True)
        (source / "bfree_synthbuster_acquisition.json").write_text(json.dumps({"samples": [{"scene_id": scene} for scene in scenes[:40]]}), encoding="utf-8")
        rows = [{"File": scene, "TIFF": "http://193.205.194.113/RAISE/TIFF/" + scene + ".TIF", "NEF": ""} for scene in scenes]
        if change:
            change(rows)
        metadata = root / "metadata.csv"
        with metadata.open("w", encoding="utf-8", newline="") as target:
            writer = csv.DictWriter(target, fieldnames=["File", "TIFF", "NEF"])
            writer.writeheader()
            writer.writerows(rows)
        return metadata

    def test_selects_prespecified_ids_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            metadata = self.fixture(root)
            with patch.object(probe_raise_csv, "ROOT", root):
                rows, selected = probe_raise_csv.selected_rows(metadata)
            self.assertEqual(len(rows), 1000)
            self.assertEqual([row["scene_id"] for row in selected], ["r%08xt" % index for index in range(40)])

    def test_foreign_host_rejected_before_network(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            metadata = self.fixture(root, lambda rows: rows[0].update(TIFF="http://example.com/RAISE/TIFF/r00000000t.TIF"))
            with patch.object(probe_raise_csv, "ROOT", root), self.assertRaisesRegex(ValueError, "Unexpected official TIFF URL"):
                probe_raise_csv.selected_rows(metadata)

    def test_tiff_for_wrong_source_id_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            metadata = self.fixture(root, lambda rows: rows[0].update(TIFF=rows[1]["TIFF"]))
            with patch.object(probe_raise_csv, "ROOT", root), self.assertRaisesRegex(ValueError, "Unexpected official TIFF URL"):
                probe_raise_csv.selected_rows(metadata)


if __name__ == "__main__":
    unittest.main()
