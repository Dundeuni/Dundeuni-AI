import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import run_inference
import freeze_protocol
from audit_columbia import colors
from import_original_raise import split_groups


class ProtocolTests(unittest.TestCase):
    def test_raise_scene_partition_keeps_large_groups_together(self):
        samples=[{"scene_id":"scene%d"%i} for i in range(40)]
        reviewed={"review_status":"verified","group_by_scene":{
            "scene%d"%i: "scene_family_%d"%(i//10) for i in range(40)}}
        result=split_groups(samples,reviewed)
        self.assertEqual(sum(split=="tune" for _,split in result.values()),20)
        for family in reviewed["group_by_scene"].values():
            self.assertEqual(len({split for group,split in result.values() if group==family}),1)
        reviewed["group_by_scene"]={"scene%d"%i: "large" if i<21 else "small" for i in range(40)}
        with self.assertRaisesRegex(ValueError,"without breaking groups"):
            split_groups(samples,reviewed)

    def test_camera_mask_colors_do_not_overflow_or_reverse(self):
        mask=np.array([[[255,0,0],[0,255,0]],[[198,2,1],[2,198,1]]],dtype=np.uint8)
        regions,ambiguous=colors(mask)
        np.testing.assert_array_equal(regions,[[0,1],[0,1]])
        self.assertFalse(ambiguous.any())

    def test_source_group_and_exact_duplicate_leakage_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/"a.png").write_bytes(b"camera-original")
            (root/"b.png").write_bytes(b"different-derived-file")
            rows=[dict(image_id="a",model="trufor",label="0",path="a.png",split="tune",group_id="scene",label_review="verified"),
                  dict(image_id="b",model="trufor",label="1",path="b.png",split="final",group_id="scene",label_review="verified")]
            manifest=root/"manifest.csv"
            def write():
                with manifest.open("w",newline="") as target:
                    writer=csv.DictWriter(target,fieldnames=list(rows[0]))
                    writer.writeheader(); writer.writerows(rows)
            write()
            with patch.object(run_inference,"ROOT",root):
                with self.assertRaisesRegex(ValueError,"crosses splits"):
                    run_inference.read_manifest(manifest,"trufor")
                rows[1]["group_id"]="other"
                (root/"b.png").write_bytes(b"camera-original")
                write()
                with self.assertRaisesRegex(ValueError,"crosses splits"):
                    run_inference.read_manifest(manifest,"trufor")

    def test_final_protocol_detects_manifest_and_weight_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            manifest=root/"manifest.csv"; manifest.write_text("frozen-list")
            weight=root/"weight.pth"; weight.write_bytes(b"final-official")
            record={"model":"trufor","manifest_sha256":run_inference.sha256(manifest),
                    "protocol_files":{"runner":"unchanged"},"policy_version":freeze_protocol.VERSION,
                    "model_files":{"weight.pth":run_inference.sha256(weight)}}
            frozen=root/"protocol.json"; frozen.write_text(json.dumps(record))
            with patch.object(freeze_protocol,"ROOT",root),patch.object(freeze_protocol,"protocol_files",return_value={"runner":"unchanged"}):
                freeze_protocol.verify_freeze(manifest,"trufor",frozen)
                weight.write_bytes(b"wrong-intermediate-checkpoint")
                with self.assertRaisesRegex(ValueError,"weight changed"):
                    freeze_protocol.verify_freeze(manifest,"trufor",frozen)
                manifest.write_text("reselected-after-final-score")
                with self.assertRaisesRegex(ValueError,"manifest changed"):
                    freeze_protocol.verify_freeze(manifest,"trufor",frozen)


if __name__ == "__main__":
    unittest.main()
