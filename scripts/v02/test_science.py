"""Scientific guard and metric tests; no model scores or evaluation inputs."""
import unittest,tempfile,json,sys
from pathlib import Path
import numpy as np
from common import CONDITIONS
from policy_selection import candidates,decision,select,cross_validate
from inference import location_metrics,verify_validation_guard
TARGETS={"false_positive_rate":.05,"false_negative_rate":.1,"abstain_rate":.2}
def data():
    return [{"image_id":f"{c}_{fold}_{label}","group_id":str(fold),"fold":fold,"role":"setting","condition":c,
         "label":label,"status":"success","scores":{"official":.05 if label==0 else .95},"raw_score":-3 if label==0 else 3}
         for c in CONDITIONS for fold in range(5) for label in [0,1]]
class ScienceTests(unittest.TestCase):
    def test_inclusive_abstention_and_original_A(self):
        b=next(c for c in candidates("bfree") if c["id"]=="B")
        for p,d in [(.399,0),(.4,None),(.5,None),(.6,None),(.601,1)]:
            self.assertEqual(decision({"status":"success","scores":{"official":p}},b),d)
        a=candidates("bfree")[0]
        self.assertEqual(decision({"status":"success","scores":{"official":.5},"raw_score":0},a),0)
    def test_selection_failure_not_fallback(self):
        rows=data()
        for r in rows:r["scores"]["official"]=.5;r["raw_score"]=0
        result=select(rows,"bfree",TARGETS)
        self.assertEqual(result["status"],"selection_failed");self.assertIsNone(result["selected"])
    def test_missing_condition_and_failure_reject(self):
        self.assertEqual(select([r for r in data() if r["condition"]!="original"],"bfree",TARGETS)["status"],"selection_failed")
        rows=data();rows[0]["status"]="failed"
        self.assertEqual(select(rows,"bfree",TARGETS)["status"],"selection_failed")
    def test_validation_cannot_fit_or_cv(self):
        rows=data();rows[0]["role"]="validation"
        with self.assertRaises(ValueError):select(rows,"bfree",TARGETS)
        with self.assertRaises(ValueError):cross_validate(rows,"bfree",TARGETS)
        with self.assertRaises(ValueError):verify_validation_guard(Path("unused"),"bfree",None)
    def test_group_cv_isolation(self):
        result=cross_validate(data(),"bfree",TARGETS)
        self.assertTrue(all(r["selection_status"]=="selected" and r["fit_groups"]==4 and r["held_groups"]==1 for r in result["folds"]))
        rows=data();rows[0]["fold"]=1
        with self.assertRaises(ValueError):cross_validate(rows,"bfree",TARGETS)
    def test_location_alignment_perfect_miss_and_false_area(self):
        truth=np.array([[1,0],[0,0]],dtype=bool)
        result=location_metrics(truth.astype(float),truth,1)
        self.assertEqual(result["F1"],1);self.assertEqual(result["IoU"],1)
        self.assertEqual(location_metrics(np.zeros((2,2)),truth,1)["F1"],0)
        self.assertEqual(location_metrics(np.array([[.5,0],[0,0]]),np.zeros((2,2)),0)["false_positive_area_fraction"],.25)
        self.assertIsNone(location_metrics(np.ones((2,2)),np.zeros((2,2)),1)["F1"])
        with self.assertRaises(ValueError):location_metrics(np.ones((2,2)),np.zeros((3,3)),1)
if __name__=="__main__":unittest.main()
