"""The scorecard: percent undisturbed per range, 2020 vs 2025.

Outputs (``outputs/tables``):

* ``reproduction.csv``  per range: official 2015 / 2020 shares (raster and exact
  vector), our rebuilds from parts, pixel agreement, unexplained share.
* ``scorecard.csv``     per range: 2020 official, 2025 under each update rule,
  uncertainty band, human-only rule, burned / newly disturbed / aged-out
  shares, status and crossing.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import shapely

from . import config as C
from . import scenarios as S
from .pixels import load_table, sql_quote
from .prepare import read_interim


# ---------------------------------------------------------------- exact vector shares
def vector_official(code: str) -> dict:
    """Exact (vector) undisturbed shares from the official layers for one range.

    Each official layer is one dissolved multipolygon per herd, so its parts
    do not overlap and the area inside the range is the sum of part-by-part
    intersections: no union needed.
    """
    rng = read_interim("ranges", where=f"CODE = {sql_quote(code)}")
    herd, geom = rng["HERD"].iat[0], rng.geometry.iat[0]
    shapely.prepare(geom)
    area = geom.area
    out = {"CODE": code}
    for col, src in (("l2", "fed2020_buffered"), ("l3", "fed2020_total"),
                     ("l2_15", "fed2015_buffered"), ("l3_15", "fed2015_total")):
        g = read_interim(src, where=f"HERD = {sql_quote(herd)}")
        parts = np.asarray(g.geometry.values, dtype=object)
        if g["FEATURE"].nunique() > 1:
            # several source features for one herd (NWT): they may overlap
            a = shapely.intersection(shapely.union_all(parts), geom).area
        else:
            inside = shapely.contains(geom, parts)
            a = shapely.area(parts[inside]).sum()
            rest = parts[~inside]
            if len(rest):
                a += shapely.area(shapely.intersection(rest, geom)).sum()
        out[f"vec_{col}"] = 1.0 - a / area
    return out


def vector_reproduction(workers: int = 6) -> pd.DataFrame:
    from concurrent.futures import ProcessPoolExecutor
    codes = read_interim("ranges", read_geometry=False)["CODE"].tolist()
    with ProcessPoolExecutor(max_workers=workers) as ex:
        rows = list(ex.map(vector_official, codes))
    df = pd.DataFrame(rows)
    df.to_csv(C.TABLES / "vector_official.csv", index=False)
    return df


# ---------------------------------------------------------------- per-range metrics
def status(lo: float, hi: float, thr: float) -> str:
    if lo >= thr:
        return "meets"
    if hi < thr:
        return "below"
    return "uncertain"


def range_metrics(d: pd.DataFrame, thr: float, res: float, new_human: str | None = None,
                  alt_centrals: list[float] | None = None) -> dict:
    m: dict = {}
    m["area_km2"] = d["n"].sum() * res * res / 1e6
    # reproduction
    m["official_2020"] = S.share_undisturbed(d, S.official(d, 2020))
    m["official_2015"] = S.share_undisturbed(d, S.official(d, 2015))
    m["rebuild_2020_cnfdb"] = S.share_undisturbed(d, S.rebuild(d, 2020, "cnfdb"))
    m["rebuild_2020_nbac"] = S.share_undisturbed(d, S.rebuild(d, 2020, "nbac"))
    m["rebuild_2015_cnfdb"] = S.share_undisturbed(d, S.rebuild(d, 2015, "cnfdb"))
    m["agree_2020_cnfdb"] = S.share(d, S.official(d) == S.rebuild(d, 2020, "cnfdb"))
    m["agree_2015_cnfdb"] = S.share(d, S.official(d, 2015) == S.rebuild(d, 2015, "cnfdb"))
    m["unexplained"] = S.share(d, S.unexplained(d))
    m["human_2015"] = S.share_undisturbed(d, S.official_human(d, 2015))
    m["human_2020"] = S.share_undisturbed(d, S.official_human(d, 2020))
    # update
    for rule in S.UPDATE_RULES:
        m[f"u2025_{rule}"] = S.share_undisturbed(d, S.disturbed(d, C.UPDATE_YEAR, rule, new_human))
    m["human_2025"] = S.share_undisturbed(d, S.human(d, new_human))
    m["central_2025"] = m[f"u2025_{S.HEADLINE_RULE}"]
    vals = [m[f"u2025_{r}"] for r in S.UPDATE_RULES] + list(alt_centrals or [])
    m["band_lo"], m["band_hi"] = min(vals), max(vals)
    # components of change
    post = d["lf_post"] > C.BASELINE_YEAR
    m["burned_2021_2025"] = S.share(d, post)
    m["new_fire"] = S.share(d, post & ~S.official(d))
    m["aged_out"] = S.share(d, S.aged_out(d, C.UPDATE_YEAR))
    m["human_growth_2015_2020"] = S.share(d, S.official_human(d) & ~S.official_human(d, 2015))
    if new_human and new_human in d:  # detector: new footprint on ground not already disturbed
        m["new_industry"] = S.share(d, (d[new_human] == 1) & ~S.official(d) & ~post)
    for y in range(C.BASELINE_YEAR + 1, C.UPDATE_YEAR + 1):
        m[f"burned_{y}"] = S.share(d, d["lf_post"] == y)  # last burn in y
    # 2020 components, as in the federal report's Figure 2
    fire20 = S.in_window(d["lf_c20"], C.BASELINE_YEAR)
    h20 = S.official_human(d)
    m["comp_fire_only_2020"] = S.share(d, fire20 & ~h20 & S.official(d))
    m["comp_overlap_2020"] = S.share(d, fire20 & h20)
    m["comp_human_only_2020"] = S.share(d, h20 & ~fire20)
    m["threshold"] = thr
    m["meets_2020_ours"] = m["official_2020"] >= thr
    m["status_2025"] = status(m["band_lo"], m["band_hi"], thr)
    m["change_pts"] = 100 * (m["central_2025"] - m["official_2020"])
    m["human_status_2025"] = "meets" if m["human_2025"] >= thr else "below"
    return m


def add_official_report(sc: pd.DataFrame) -> pd.DataFrame:
    """Join the federal report's published 2020 figures and set 2020 status.

    The 2020 status that the update is measured against is the *published*
    one (the legal baseline); our recomputed share is kept alongside, and a
    range whose two statuses disagree is flagged ``borderline_2020``.
    """
    ref = pd.read_csv(C.REFERENCE / "official_2020_disturbance.csv")
    ref = ref.rename(columns={c: f"report_{c}" for c in ref.columns if c != "CODE"})
    sc = sc.merge(ref, on="CODE", how="left")
    sc["report_undisturbed_2020"] = 1 - sc["report_total_pct"] / 100
    sc["meets_2020"] = sc["report_total_pct"] <= sc["report_max_disturbance_pct"]
    sc["diff_vs_report_pts"] = 100 * sc["official_2020"] - (100 - sc["report_total_pct"])
    sc["borderline_2020"] = sc["meets_2020"] != sc["meets_2020_ours"]
    return sc


def crossing(r) -> str:
    met, st, thr = bool(r.meets_2020), r.status_2025, r.threshold
    note = " (2020 status borderline)" if r.borderline_2020 else ""
    if met and st == "below":
        return "clear crossing" + note
    if met and st == "uncertain":
        return ("possible crossing" if r.central_2025 < thr else "at risk (band straddles)") + note
    if not met and st == "meets":
        return "recovered" + note
    return ""


def build_scorecard(res: float = C.DEFAULT_RES, alt_res: list[float] | None = None,
                    new_human: str | None = None, tag: str = "") -> pd.DataFrame:
    ranges = read_interim("ranges", read_geometry=False)
    rows = []
    for r in ranges.itertuples():
        d = load_table(r.CODE, res, tag)
        alts = []
        for ar in alt_res or []:
            try:
                da = load_table(r.CODE, ar, tag)
                alts.append(S.share_undisturbed(da, S.disturbed(da, C.UPDATE_YEAR,
                                                                S.HEADLINE_RULE, new_human)))
            except FileNotFoundError:
                pass
        m = range_metrics(d, r.threshold, res, new_human, alts)
        rows.append({"CODE": r.CODE, "HERD": r.HERD, "name": r.name, **m})
    sc = pd.DataFrame(rows)
    vec = C.TABLES / "vector_official.csv"
    if vec.exists():
        sc = sc.merge(pd.read_csv(vec), on="CODE", how="left")
    sc = add_official_report(sc)
    sc["crossing"] = [crossing(r) for r in sc.itertuples()]
    sc.to_csv(C.TABLES / f"scorecard{tag}.csv", index=False)
    return sc


def summarize(sc: pd.DataFrame) -> dict:
    """National headline numbers."""
    a = sc["area_km2"]
    out = {
        "ranges": len(sc),
        "meet_2020_report": int(sc["meets_2020"].sum()),
        "meet_2020_ours_raster": int(sc["meets_2020_ours"].sum()),
        "borderline_2020": sc.loc[sc["borderline_2020"], "name"].tolist(),
        "max_abs_diff_vs_report_pts": float(sc["diff_vs_report_pts"].abs().max()),
        "meet_2020_vector": int((sc["vec_l3"] >= sc["threshold"]).sum()) if "vec_l3" in sc else None,
        "meet_2015_official": int((sc["official_2015"] >= sc["threshold"]).sum()),
        "meet_2025_central": int((sc["central_2025"] >= sc["threshold"]).sum()),
        "meet_2025_clearly": int((sc["status_2025"] == "meets").sum()),
        "meet_2025_possibly": int((sc["band_hi"] >= sc["threshold"]).sum()),
        "below_2025_clearly": int((sc["status_2025"] == "below").sum()),
        "clear_crossings": sc.loc[sc["crossing"].str.startswith("clear"), "name"].tolist(),
        "possible_crossings": sc.loc[sc["crossing"].str.startswith("possible"), "name"].tolist(),
        "at_risk": sc.loc[sc["crossing"].str.startswith("at risk"), "name"].tolist(),
        "recovered": sc.loc[sc["crossing"] == "recovered", "name"].tolist(),
        "range_area_km2": float(a.sum()),
        "burned_2021_2025_km2": float((sc["burned_2021_2025"] * a).sum()),
        "burned_2021_2025_share": float((sc["burned_2021_2025"] * a).sum() / a.sum()),
        "new_fire_km2": float((sc["new_fire"] * a).sum()),
        "aged_out_km2": float((sc["aged_out"] * a).sum()),
        "ranges_burned_gt10pct": int((sc["burned_2021_2025"] > 0.10).sum()),
        "ranges_lost_gt10pts": int((sc["change_pts"] < -10).sum()),
        "meet_human_only_2020": int((sc["human_2020"] >= sc["threshold"]).sum()),
        "meet_human_only_2025": int((sc["human_2025"] >= sc["threshold"]).sum()),
        "median_abs_rebuild_error_2020_pts": float(
            100 * (sc["rebuild_2020_cnfdb"] - sc["official_2020"]).abs().median()),
        "max_abs_rebuild_error_2020_pts": float(
            100 * (sc["rebuild_2020_cnfdb"] - sc["official_2020"]).abs().max()),
        "median_abs_rebuild_error_2015_pts": float(
            100 * (sc["rebuild_2015_cnfdb"] - sc["official_2015"]).abs().median()),
    }
    for y in range(C.BASELINE_YEAR + 1, C.UPDATE_YEAR + 1):
        out[f"burned_last_{y}_share"] = float((sc[f"burned_{y}"] * a).sum() / a.sum())
    return out
