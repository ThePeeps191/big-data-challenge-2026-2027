import numpy as np
import pandas as pd
import pytest
import shapely
from shapely.geometry import box


def test_sample_in_stays_inside():
    from caribou.detector.labels import sample_in
    rng = np.random.default_rng(1)
    polys = np.array([box(0, 0, 10, 10), shapely.Point(50, 50).buffer(5)], dtype=object)
    pts, idx = sample_in(polys, 500, rng)
    assert len(pts) == 500
    assert shapely.contains(polys[idx], pts).all()
    # area-weighted: the 100 m2 box vs the ~78.5 m2 disc
    share_box = (idx == 0).mean()
    assert 0.48 < share_box < 0.64


def test_evaluate_held_out_ranges():
    from caribou.detector.train import evaluate
    rng = np.random.default_rng(0)
    rows = []
    for code in ["A1", "A2", "B1", "B2", "C1", "C2"]:
        for label, mu in ((0, 0.0), (1, 2.5), (2, -1.5)):
            n = 120
            rows.append(pd.DataFrame({"CODE": code, "label": label,
                                      "poly_id": np.where(label == 1, np.arange(n) // 3, -1),
                                      "f1": rng.normal(mu, 1, n), "f2": rng.normal(0, 1, n)}))
    df = pd.concat(rows, ignore_index=True)
    res, oof = evaluate(df, ["f1", "f2"], n_splits=3)
    assert res["folds"] == 3 and res["n_ranges"] == 6
    assert res["auc"] > 0.9
    a = res["at_fpr_0.01"]
    assert a["false_alarm_intact"] <= 0.03
    assert 0 < a["recall"] <= 1 and 0 < a["polygon_detection"] <= 1
    assert a["polygon_detection"] >= a["recall"] - 1e-9  # a polygon counts if any point hits
    assert set(res["per_range_auc"]) == {"A1", "A2", "B1", "B2", "C1", "C2"}
