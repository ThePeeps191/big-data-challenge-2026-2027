"""Detector pipeline.

    python -m caribou.detector labels                   # local: sample label points
    python -m caribou.detector sample --kind emb        # Earth Engine: features at points (2020)
    python -m caribou.detector sample --kind ls
    python -m caribou.detector evaluate                 # local: held-out-range scores
    python -m caribou.detector apply --kind emb         # Earth Engine: 2025 probability rasters
    python -m caribou.detector postprocess --threshold 0.8   # local: new clearings, buffered

Then add the detections to the scorecard:

    python -m caribou pixels analyze figures --new-human detector_new_buffered

``--window minlon minlat maxlon maxlat`` restricts sampling to a pilot window
(the IDEA's Quebec pilot: -76.2 49.62 -75.8 49.88).
"""

from __future__ import annotations

import argparse
import json

import geopandas as gpd
import pandas as pd

from .. import config as C

DET = C.INTERIM / "detector"


def labels_wgs84(window=None) -> pd.DataFrame:
    lab = gpd.read_file(DET / "labels.gpkg").to_crs("EPSG:4326")
    lab["lon"], lab["lat"] = lab.geometry.x, lab.geometry.y
    if window:
        x0, y0, x1, y1 = window
        lab = lab[(lab["lon"] >= x0) & (lab["lon"] <= x1) & (lab["lat"] >= y0) & (lab["lat"] <= y1)]
    return pd.DataFrame(lab.drop(columns="geometry"))


def main(argv=None):
    p = argparse.ArgumentParser(prog="caribou.detector", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("step", choices=["labels", "sample", "evaluate", "apply", "postprocess"])
    p.add_argument("--kind", default="emb", choices=["emb", "ls", "both"])
    p.add_argument("--kinds", nargs="*", default=["emb", "ls", "both"])
    p.add_argument("--year", type=int, default=None)
    p.add_argument("--n", type=int, default=300, help="points per class per range")
    p.add_argument("--codes", nargs="*")
    p.add_argument("--window", type=float, nargs=4)
    p.add_argument("--project", default=None, help="Earth Engine cloud project")
    p.add_argument("--threshold", type=float, default=None)
    p.add_argument("--model", default="rf", choices=["rf", "gbt"])
    a = p.parse_args(argv)
    DET.mkdir(parents=True, exist_ok=True)
    win = f"_win" if a.window else ""

    if a.step == "labels":
        from .labels import build_labels
        lab = build_labels(a.codes, a.n)
        print(lab["label"].value_counts().rename({0: "intact", 1: "cleared", 2: "burned"}))

    elif a.step == "sample":
        from . import ee_features as F
        F.init(a.project)
        year = a.year or C.BASELINE_YEAR
        lab = labels_wgs84(a.window)
        kinds = ["emb", "ls"] if a.kind == "both" else [a.kind]
        for k in kinds:
            s = F.sample_points(lab[["pid", "lon", "lat"]], k, year)
            s = lab.merge(s, on="pid", how="inner")
            s.to_csv(DET / f"samples_{k}_{year}{win}.csv", index=False)
            print(f"  {k}: {len(s)} sampled points")

    elif a.step == "evaluate":
        from . import ee_features as F
        from .train import compare
        year = a.year or C.BASELINE_YEAR
        sets = {}
        loaded = {k: pd.read_csv(DET / f"samples_{k}_{year}{win}.csv")
                  for k in ("emb", "ls") if (DET / f"samples_{k}_{year}{win}.csv").exists()}
        for k in a.kinds:
            if k == "both":
                if {"emb", "ls"} <= set(loaded):
                    keep = ["pid"] + F.ls_feature_names()
                    sets["both"] = (loaded["emb"].merge(loaded["ls"][keep], on="pid"),
                                    F.feature_names("both"))
            elif k in loaded:
                sets[k] = (loaded[k], F.feature_names(k))
        if "ls" in loaded:  # the IDEA's one-feature pilot baseline: NBR drop alone
            sets["dNBR only"] = (loaded["ls"], ["dNBR"])
        tab = compare(sets, a.model, out_name=f"detector_eval{win}")
        print(tab.to_string(index=False))

    elif a.step == "apply":
        from . import ee_features as F
        from .apply import detect_range, latest_embedding_year, train_ee
        from ..prepare import read_interim
        F.init(a.project)
        year = a.year or C.UPDATE_YEAR
        if a.kind in ("emb", "both"):
            last = latest_embedding_year()
            if year > last:
                print(f"  embeddings end in {last}; applying at {last} instead of {year}")
                year = last
        clf = train_ee(labels_wgs84(), a.kind, C.BASELINE_YEAR)
        codes = a.codes or read_interim("ranges", read_geometry=False)["CODE"].tolist()
        for c in codes:
            print(f"  detect {c} ({year})")
            detect_range(c, clf, a.kind, year)
        (DET / "apply_year.json").write_text(json.dumps({"year": year, "kind": a.kind}))

    elif a.step == "postprocess":
        from .apply import postprocess
        meta = json.loads((DET / "apply_year.json").read_text())
        t = a.threshold
        if t is None:
            ev = json.loads((C.TABLES / "detector_eval.json").read_text())
            t = ev[meta["kind"]]["at_fpr_0.01"]["threshold"]
            print(f"  threshold from held-out evaluation (1% false alarms): {t:.3f}")
        new = postprocess(t, meta["year"])
        print(f"  {len(new)} new clearings, {new['area_ha'].sum():,.0f} ha")


if __name__ == "__main__":
    main()
