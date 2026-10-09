import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from policies import auroc, decide, metrics, probability


class PolicyTests(unittest.TestCase):
    def test_official_binary_boundaries(self):
        self.assertEqual(decide("bfree", 0, "A")["decision"], 0)
        self.assertEqual(decide("trufor", .5, "A")["decision"], 1)

    def test_abstention_boundaries_and_display(self):
        for value in (.4, .5, .6):
            result = decide("trufor", value, "B")
            self.assertIsNone(result["decision"])
            self.assertIsNone(result["display_score"])
        self.assertEqual(decide("trufor", .399999, "B")["decision"], 0)
        self.assertEqual(decide("trufor", .600001, "B")["decision"], 1)
        # Rounding must not change the decision at the displayed boundary.
        self.assertEqual(decide("trufor", .600001, "B")["display_score"], 60)

    def test_extreme_logits_and_invalid_scores(self):
        self.assertEqual(probability("bfree", -10000), 0)
        self.assertEqual(probability("bfree", 10000), 1)
        for raw in (float("nan"), float("inf"), -0.1, 1.1):
            with self.assertRaises(ValueError):
                probability("trufor", raw)

    def test_auroc_ties_and_missing_class(self):
        self.assertEqual(auroc([0, 1, 0, 1], [1, 1, 1, 1]), .5)
        self.assertEqual(auroc([0, 0, 1, 1], [0, 1, 2, 3]), 1)
        self.assertEqual(auroc([0, 0, 1, 1], [3, 2, 1, 0]), 0)
        self.assertIsNone(auroc([1], [1]))

    def test_failures_and_abstentions_keep_denominators(self):
        rows = [{"model": "trufor", "label": label, "raw_score": raw, "status": status}
                for label, raw, status in [(0, .9, "success"), (0, .5, "success"),
                                           (1, .1, "success"), (1, .5, "success"),
                                           (1, None, "failed")]]
        result = metrics(rows, "B")
        self.assertEqual(result["false_positive_rate"], .5)
        self.assertEqual(result["false_negative_rate"], .5)
        self.assertEqual(result["abstain_rate"], .5)
        self.assertEqual(result["failure_rate"], .2)
        self.assertEqual(result["valid"], 4)


if __name__ == "__main__":
    unittest.main()
