"""Record the completed source-only visual review and conservative scene families."""
import datetime
import json
from run_inference import ROOT, sha256


def main():
    base = ROOT / "runs/20261002_bfree_raise"
    imported = json.loads((base / "scene_inputs/audit.json").read_text(encoding="utf-8"))["imported"]
    groups = {row["scene_id"]: "raise_scene_" + row["scene_id"] for row in imported}
    # All 40 originals and all 24 closest-pair panels were inspected before model scores.
    # Suspected shared locations are kept together even when exact duplication is absent.
    families = [
        {"name": "raise_suspected_brick_fortification", "scenes": ["r01a31693t", "r02189767t"],
            "reason": "brick passage and brick crenellated walkway; conservative possible shared fortification, not proven identical view"},
        {"name": "raise_suspected_city_monument_square", "scenes": ["r01b3f004t", "r01cf60c7t"],
            "reason": "monument/column and historic square in snow and street-level views; conservative possible shared square"},
        {"name": "raise_suspected_lake_landscape", "scenes": ["r02508493t", "r02897203t", "r029afdb0t"],
            "reason": "lake/village landscape and two mountain-lake views; conservative possible shared location, exact location not asserted"},
        {"name": "raise_suspected_town_parade", "scenes": ["r0207a52ct", "r0287344at"],
            "reason": "public parades in historic streets; conservative shared event/location family, not proven same occasion"}]
    for family in families:
        for scene in family["scenes"]:
            if scene not in groups:
                raise ValueError("Review scene absent from import")
            groups[scene] = family["name"]
    similarity = json.loads((base / "scene_similarity/similarity.json").read_text(encoding="utf-8"))
    if len(imported) != 40 or similarity["pairs_compared"] != 780:
        raise ValueError("Incomplete source-only review inputs")
    record = {"review_status": "verified", "reviewed_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "review_code_sha256": sha256(__file__), "group_by_scene": groups,
        "input_sha256_by_scene": {row["scene_id"]: row["input_sha256"] for row in imported},
        "source_import_sha256": sha256(base / "scene_inputs/audit.json"),
        "similarity_sha256": sha256(base / "scene_similarity/similarity.json"),
        "all_40_original_contact_panels_visually_reviewed": True, "closest_24_pairs_visually_reviewed": True,
        "exact_duplicate_pairs": sum(row["same_rgb_png_hash"] for row in similarity["pairs"]),
        "minimum_phash_hamming_63": min(row["phash_hamming_63"] for row in similarity["pairs"]),
        "conservative_possible_scene_families": families, "inference_scores_used": False,
        "limitations": "Visual/source-only review of 40 selected originals; group families include uncertainty; no exhaustive pretraining or full-RAISE comparison"}
    with (base / "scene_review.json").open("x", encoding="utf-8") as target:
        json.dump(record, target, indent=2)
    print("Recorded visual source review: 40 images", len(set(groups.values())), "conservative scene groups")


if __name__ == "__main__":
    main()
