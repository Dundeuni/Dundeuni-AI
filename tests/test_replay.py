"""Check replay safety against existing results and altered reference inputs."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "prepare_replay", ROOT / "scripts/sharing/prepare_replay.py")
replay = importlib.util.module_from_spec(spec)
spec.loader.exec_module(replay)

class ReplayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.bundle = self.base / "bundle"
        records = {}
        for name in replay.INITIAL:
            rel = "reference/experiments/20261004_followup/" + name
            p = self.bundle / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("{}")
            records[rel] = {"sha256": replay.digest(p)}
        self.reference = self.bundle / rel
        (self.bundle / "inventory.json").write_text(json.dumps({"files": records}))
        self.target = self.base / "target"
        self.target.mkdir()

    def test_restore_only_initial_files(self):
        self.assertEqual(replay.restore(self.target, bundle=self.bundle), 4)
        files = list(self.target.rglob("*"))
        names = sorted(p.name for p in files if p.is_file())
        self.assertEqual(names, sorted(replay.INITIAL))

    def test_existing_result_is_preserved(self):
        run = self.target / "runs/20261004_followup"
        run.mkdir(parents=True)
        sentinel = run / "predictions.jsonl"
        sentinel.write_bytes(b"existing result")
        with self.assertRaises(FileExistsError):
            replay.restore(self.target, bundle=self.bundle)
        self.assertEqual(sentinel.read_bytes(), b"existing result")
        self.assertEqual(len(list(run.iterdir())), 1)

    def test_tampered_reference_fails_before_writing(self):
        self.reference.write_text('{"altered": true}')
        with self.assertRaises(ValueError):
            replay.restore(self.target, bundle=self.bundle)
        self.assertEqual(list(self.target.iterdir()), [])

if __name__ == "__main__":
    unittest.main()
