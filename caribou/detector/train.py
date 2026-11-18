"""Train and evaluate the detector on held-out ranges (scikit-learn).

Validation is by range: ``GroupKFold`` over range codes, so every score is
for ranges the model never saw. Reported per feature set:

* ROC AUC and average precision for "cleared" vs everything else;
* at the threshold giving a 1% false-alarm rate on intact + burned points:
  pixel recall and the share of 2020 polygons with at least one detected point;
* the same at the F1-optimal threshold;
* per-range AUC.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.metrics import average_precision_score, precision_recall_curve, roc_auc_score
from sklearn.model_selection import GroupKFold

from .. import config as C


def make_model(kind: str = "rf", seed: int = 0):
    if kind == "rf":
        return RandomForestClassifier(n_estimators=300, min_samples_leaf=2, n_jobs=-1,
                                      class_weight="balanced", random_state=seed)
    if kind == "gbt":
        return HistGradientBoostingClassifier(max_iter=300, learning_rate=0.05,
                                              class_weight="balanced", random_state=seed)
    raise ValueError(kind)


def threshold_at_fpr(p_neg: np.ndarray, fpr: float) -> float:
    return float(np.quantile(p_neg, 1 - fpr)) if len(p_neg) else 0.5


def evaluate(df: pd.DataFrame, features: list[str], model: str = "rf", n_splits: int = 5,
             fpr: float = 0.01, seed: int = 0) -> tuple[dict, pd.DataFrame]:
    d = df.dropna(subset=features).reset_index(drop=True)
    X = d[features].to_numpy(np.float32)
    y = (d["label"] == 1).astype(int).to_numpy()
    groups = d["CODE"].to_numpy()
    k = min(n_splits, len(np.unique(groups)))
    oof = np.zeros(len(d))
    for tr, te in GroupKFold(n_splits=k).split(X, y, groups):
        m = make_model(model, seed).fit(X[tr], y[tr])
        oof[te] = m.predict_proba(X[te])[:, 1]
    d = d.assign(p=oof)
    neg = d["label"] != 1
    t1 = threshold_at_fpr(d.loc[neg, "p"].to_numpy(), fpr)
    prec, rec, thr = precision_recall_curve(y, oof)
    f1 = 2 * prec * rec / np.maximum(prec + rec, 1e-9)
    tf1 = float(thr[np.argmax(f1[:-1])]) if len(thr) else 0.5

    def at(t):
        det = d["p"] >= t
        pos = d["label"] == 1
        # poly_id is only unique within a range (labels.py), so group by both
        polys = d[pos & (d["poly_id"] >= 0)].groupby(["CODE", "poly_id"])["p"].max()
        return {"threshold": t,
                "recall": float((det & pos).sum() / max(pos.sum(), 1)),
                "false_alarm_intact": float((det & (d["label"] == 0)).sum() / max((d["label"] == 0).sum(), 1)),
                "false_alarm_burned": float((det & (d["label"] == 2)).sum() / max((d["label"] == 2).sum(), 1)),
                "precision_sample": float((det & pos).sum() / max(det.sum(), 1)),
                "polygon_detection": float((polys >= t).mean()) if len(polys) else np.nan}

    per_range = {}
    for code, g in d.groupby("CODE"):
        yy = (g["label"] == 1).astype(int)
        if yy.nunique() == 2:
            per_range[code] = float(roc_auc_score(yy, g["p"]))
    res = {"n_points": int(len(d)), "n_ranges": int(len(np.unique(groups))), "folds": k,
           "model": model, "n_features": len(features),
           "auc": float(roc_auc_score(y, oof)), "average_precision": float(average_precision_score(y, oof)),
           f"at_fpr_{fpr:g}": at(t1), "at_best_f1": at(tf1), "per_range_auc": per_range}
    return res, d


def compare(samples: dict[str, tuple[pd.DataFrame, list[str]]], model: str = "rf",
            out_name: str = "detector_eval") -> pd.DataFrame:
    """Evaluate several feature sets on the same held-out-range protocol."""
    rows, full = [], {}
    for name, (df, feats) in samples.items():
        res, _ = evaluate(df, feats, model)
        full[name] = res
        a = res["at_fpr_0.01"]
        rows.append({"features": name, "auc": res["auc"], "avg_precision": res["average_precision"],
                     "recall_at_1pct_fa": a["recall"], "polygon_det_at_1pct_fa": a["polygon_detection"],
                     "burned_false_alarm_at_1pct_fa": a["false_alarm_burned"],
                     "n_points": res["n_points"], "n_ranges": res["n_ranges"]})
    tab = pd.DataFrame(rows)
    tab.to_csv(C.TABLES / f"{out_name}.csv", index=False)
    (C.TABLES / f"{out_name}.json").write_text(json.dumps(full, indent=2))
    return tab
