"""Preliminary 2026 update, and a federal-consistent fire-source check.

NBAC for a fire season is published about eight months after it ends (the
2025 layers are version 20260513), so the 2026 season, over since
2026-10-15, has no NBAC yet. CWFIS does publish an in-season *Fire Perimeter
Estimate* (buffered satellite hotspots, ``downloads/hotspots/perimeters.shp``,
with past seasons in ``hotspots/archive/<year>_perimeters.zip``). Hotspot
buffers overstate burned area, so this module

1. **calibrates** the estimates against NBAC for 2021-2025 inside the ranges:
   by range and year, the ratio of NBAC burned area to estimated area, plus
   how much of each the other covers. A range's 2026 estimate is scaled by
   the pooled ratio of its province (central) and by the lowest and highest
   ratio of any sizeable range-year in that province (band);
2. **rasterizes** the 2026 estimate as an extra mask (``f26``) on the same
   100 m grid as the main pipeline, for the ranges where it can matter, and
   scores 2026 under every update rule with the scaled estimate;
3. adds a **CNFDB 2021-2024** mask (``c2124``): the federal footprint was built
   from CNFDB perimeters, while the main update uses NBAC after 2020. This
   rule swaps in CNFDB for 2021-2024 (NBAC for 2025), the fire source the
   federal method itself used, and joins the 2025 band;
4. restarts the **recovery clock** and the **2030 forecast** from 2026 for those
   ranges, with the 2026 estimate at face value (an upper bound on the 2026
   burn; the main forecast still draws 2026 from the fire record).

Nothing here overwrites the main pipeline's tables. Outputs, all in
``outputs/tables``: ``prelim2026.csv``, ``prelim2026_calibration.csv``,
``cnfdb_vs_nbac_2021_2024.csv``.

    python -m caribou.prelim fetch prepare calibrate
    python -m caribou.prelim pixels --codes ON4 NT1 MB8 ON5 SK1
    python -m caribou.prelim analyze
"""

from __future__ import annotations

import argparse
import datetime as dt
import zipfile
from concurrent.futures import ProcessPoolExecutor, as_completed

import geopandas as gpd
import numpy as np
import pandas as pd
import pyogrio
import shapely

from . import config as C
from . import scenarios as S
from .fetch import _download
from .forecast import simulate
from .pixels import annual_path, range_pixel_table, table_path
from .prepare import _shp_in_zip, _touching_ranges, polygonal, read_interim, write
from .recovery import recovery_for_state
from .scorecard import status

PRELIM_YEAR = C.UPDATE_YEAR + 1                  # 2026
HOTSPOTS = "https://cwfis.cfs.nrcan.gc.ca/downloads/hotspots/"
RAW = C.RAW / "prelim"
TAG = "_prelim"
EXTRAS = {"f26": f"fires_prelim_{PRELIM_YEAR}", "c2124": "fires_cnfdb_post"}
CAL_YEARS = range(C.BASELINE_YEAR + 1, C.UPDATE_YEAR + 1)    # 2021-2025
CNFDB_POST = (C.BASELINE_YEAR + 1, 2024)                       # years in the CNFDB post-2020 file


# ---------------------------------------------------------------- fetch
def fetch_prelim() -> None:
    """Current-season perimeter estimate (dated copy) and the 2021-2025 archive."""
    cur = RAW / str(PRELIM_YEAR)
    cur.mkdir(parents=True, exist_ok=True)
    if not (cur / "_FETCHED").exists():
        for ext in ("shp", "shx", "dbf", "prj", "cpg"):
            _download(HOTSPOTS + f"perimeters.{ext}", cur / f"perimeters.{ext}")
        (cur / "_FETCHED").write_text(dt.datetime.now(dt.timezone.utc).isoformat())
    print(f"[prelim] {PRELIM_YEAR} perimeters fetched {(cur / '_FETCHED').read_text()}")
    for y in CAL_YEARS:
        _download(HOTSPOTS + f"archive/{y}_perimeters.zip", RAW / "archive" / f"{y}_perimeters.zip")
    print(f"[prelim] archive {CAL_YEARS.start}-{CAL_YEARS.stop - 1}")


# ---------------------------------------------------------------- prepare
def _estimate_layer(src: str, year: int, ranges: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    g = pyogrio.read_dataframe(src)
    g = g[["geometry"]].to_crs(C.AREA_CRS)
    g["geometry"] = polygonal(g.geometry.values)
    g = g[g.geometry.notna()]
    g = _touching_ranges(g, ranges)
    g["YEAR"] = year
    return g


def prepare_prelim() -> None:
    ranges = read_interim("ranges")
    print(f"[prelim] prepare {PRELIM_YEAR} estimate")
    cur = _estimate_layer(str(RAW / str(PRELIM_YEAR) / "perimeters.shp"), PRELIM_YEAR, ranges)
    # the current-season file is replaced in place each year: refuse a wrong season
    first = pd.to_datetime(pyogrio.read_dataframe(str(RAW / str(PRELIM_YEAR) / "perimeters.shp"),
                                                  read_geometry=False)["FIRSTDATE"])
    assert (first.dt.year == PRELIM_YEAR).all(), "perimeters.shp is not the expected season"
    write(cur, f"fires_prelim_{PRELIM_YEAR}")
    for y in CAL_YEARS:
        z = RAW / "archive" / f"{y}_perimeters.zip"
        write(_estimate_layer(_shp_in_zip(z), y, ranges), f"fires_prelim_{y}")
    print("[prelim] prepare CNFDB 2021-2024")
    names = [n for n in zipfile.ZipFile(C.RAW / "cnfdb" / "NFDB_poly.zip").namelist()
             if n.lower().endswith(".shp") and "to2020" not in n]
    if len(names) != 1:
        raise ValueError(f"expected one post-2020 CNFDB shapefile, found {names}")
    src = f"zip://{(C.RAW / 'cnfdb' / 'NFDB_poly.zip').as_posix()}!{names[0]}"
    fields = pyogrio.read_info(src)["fields"]
    cols = [c for c in ("YEAR", "SRC_AGENCY", "FIRE_ID", "SIZE_HA", "CAUSE") if c in fields]
    g = pyogrio.read_dataframe(src, columns=cols)
    g = g[(g["YEAR"] >= CNFDB_POST[0]) & (g["YEAR"] <= CNFDB_POST[1])].to_crs(C.AREA_CRS)
    g["geometry"] = polygonal(g.geometry.values)
    g = _touching_ranges(g[g.geometry.notna()], ranges)
    g["YEAR"] = g["YEAR"].astype(int)
    write(g, "fires_cnfdb_post")


# ---------------------------------------------------------------- calibration
def _area_in(geoms: np.ndarray, rng_geom) -> tuple[float, object]:
    if len(geoms) == 0:
        return 0.0, None
    u = shapely.intersection(shapely.union_all(geoms), rng_geom)
    return float(u.area), u


def _range_calibration(code: str) -> list[dict]:
    rng = read_interim("ranges", where=f"CODE = '{code}'")
    geom, bbox = rng.geometry.iat[0], tuple(rng.geometry.iat[0].bounds)
    nb = read_interim("fires_nbac", bbox=bbox)
    cn = read_interim("fires_cnfdb_post", bbox=bbox)
    rows = []
    for y in CAL_YEARS:
        est = read_interim(f"fires_prelim_{y}", bbox=bbox)
        a_est, u_est = _area_in(est.geometry.values, geom)
        a_nb, u_nb = _area_in(nb.loc[nb["YEAR"] == y].geometry.values, geom)
        a_both = float(shapely.intersection(u_est, u_nb).area) if u_est is not None and u_nb is not None else 0.0
        a_cn, u_cn = (_area_in(cn.loc[cn["YEAR"] == y].geometry.values, geom)
                      if y <= CNFDB_POST[1] else (np.nan, None))
        a_cn_nb = (float(shapely.intersection(u_cn, u_nb).area)
                   if u_cn is not None and u_nb is not None else 0.0)
        rows.append({"CODE": code, "year": y, "est_km2": a_est / 1e6, "nbac_km2": a_nb / 1e6,
                     "est_and_nbac_km2": a_both / 1e6, "cnfdb_km2": a_cn / 1e6,
                     "cnfdb_and_nbac_km2": a_cn_nb / 1e6})
    return rows


def calibrate(workers: int = 6) -> pd.DataFrame:
    """Hotspot estimate vs NBAC (and CNFDB vs NBAC), by range and year."""
    codes = read_interim("ranges", read_geometry=False)["CODE"].tolist()
    rows = []
    with ProcessPoolExecutor(max_workers=workers) as ex:
        for r in ex.map(_range_calibration, codes):
            rows += r
    by = pd.DataFrame(rows)
    by.to_csv(C.TABLES / "prelim2026_calibration_by_range.csv", index=False)
    tot = by.groupby("year")[["est_km2", "nbac_km2", "est_and_nbac_km2", "cnfdb_km2",
                              "cnfdb_and_nbac_km2"]].sum().reset_index()
    tot["nbac_over_est"] = tot["nbac_km2"] / tot["est_km2"]
    tot["est_precision"] = tot["est_and_nbac_km2"] / tot["est_km2"]     # est area NBAC confirms
    tot["est_recall"] = tot["est_and_nbac_km2"] / tot["nbac_km2"]       # NBAC area est covers
    tot["cnfdb_over_nbac"] = tot["cnfdb_km2"] / tot["nbac_km2"]
    tot["cnfdb_covered_by_nbac"] = tot["cnfdb_and_nbac_km2"] / tot["cnfdb_km2"]
    tot.to_csv(C.TABLES / "prelim2026_calibration.csv", index=False)
    print(tot.round(3).to_string(index=False))
    return tot


def cnfdb_completeness() -> pd.DataFrame:
    """CNFDB 2021-2024 vs NBAC area inside ranges, by year and source agency."""
    ranges = read_interim("ranges")
    cn = read_interim("fires_cnfdb_post")
    nb = read_interim("fires_nbac")
    nb = nb[(nb["YEAR"] >= CNFDB_POST[0]) & (nb["YEAR"] <= CNFDB_POST[1])]
    rows = []
    prov = ranges["CODE"].str.rstrip("0123456789")
    for p in sorted(prov.unique()):
        rg = shapely.union_all(ranges.loc[prov == p].geometry.values)
        shapely.prepare(rg)
        for y in range(CNFDB_POST[0], CNFDB_POST[1] + 1):
            c = cn[(cn["YEAR"] == y)]
            n = nb[(nb["YEAR"] == y)]
            c = c[shapely.intersects(c.geometry.values, rg)]
            n = n[shapely.intersects(n.geometry.values, rg)]
            a_c = shapely.intersection(shapely.union_all(c.geometry.values), rg).area / 1e6 if len(c) else 0.0
            a_n = shapely.intersection(shapely.union_all(n.geometry.values), rg).area / 1e6 if len(n) else 0.0
            agencies = ",".join(sorted(c["SRC_AGENCY"].astype(str).unique())) if "SRC_AGENCY" in c else ""
            rows.append({"province": p, "year": y, "cnfdb_km2": a_c, "nbac_km2": a_n,
                         "cnfdb_over_nbac": a_c / a_n if a_n else np.nan,
                         "cnfdb_polygons": len(c), "cnfdb_agencies": agencies})
    out = pd.DataFrame(rows)
    out.to_csv(C.TABLES / "cnfdb_vs_nbac_2021_2024.csv", index=False)
    print(out.round(3).to_string(index=False))
    return out


# ---------------------------------------------------------------- pixels
def _pixel_job(code: str, res: float) -> str:
    df, ann = range_pixel_table(code, res, extras=EXTRAS)
    df.to_csv(table_path(code, res, TAG), index=False)
    if not annual_path(code, res).exists():
        ann.to_csv(annual_path(code, res), index=False)
    return code


def build_pixels(codes: list[str], res: float = C.DEFAULT_RES, workers: int = 6,
                 overwrite: bool = False) -> None:
    todo = [c for c in codes if overwrite or not table_path(c, res, TAG).exists()]
    print(f"[prelim] pixels for {len(todo)} ranges at {res:g} m")
    with ProcessPoolExecutor(max_workers=max(1, min(workers, len(todo)))) as ex:
        for f in as_completed([ex.submit(_pixel_job, c, res) for c in todo]):
            f.result()


# ---------------------------------------------------------------- analysis
def cnfdb_post_rule(d: pd.DataFrame, year: int) -> pd.Series:
    """Headline rule with CNFDB perimeters for 2021-2024 and NBAC for 2025."""
    base = (d["l3"] == 1) & ~S.aged_out(d, year)
    return base | S.human(d) | (d["c2124"] == 1) | (d["lf_post"] == C.UPDATE_YEAR)


def with_2026(d: pd.DataFrame) -> pd.DataFrame:
    """Treat the 2026 estimate as a post-2020 fire (face value, k = 1)."""
    d = d.copy()
    d["lf_post"] = np.where(d["f26"] == 1, PRELIM_YEAR, d["lf_post"])
    return d


def score(code: str, thr: float, k: dict[str, float], res: float = C.DEFAULT_RES,
          ref_years=(1986, C.UPDATE_YEAR), n_runs: int = 20000, seed: int = 0) -> dict:
    d = pd.read_csv(table_path(code, res, TAG))
    out = {"CODE": code, "threshold": thr}
    # 2025 again, from these tables (reproduction check) + the CNFDB fire-source rule
    for rule in S.UPDATE_RULES:
        out[f"u2025_{rule}"] = S.share_undisturbed(d, S.disturbed(d, C.UPDATE_YEAR, rule))
    out["u2025_cnfdb_post"] = S.share_undisturbed(d, cnfdb_post_rule(d, C.UPDATE_YEAR))
    out["burned_2026_est"] = S.share(d, d["f26"] == 1)
    # 2026: no-fire baseline (1986 fires age out) minus k x new ground under the estimate
    vals = []
    for rule in (*S.UPDATE_RULES, "cnfdb_post"):
        base = (cnfdb_post_rule(d, PRELIM_YEAR) if rule == "cnfdb_post"
                else S.disturbed(d, PRELIM_YEAR, rule))
        u0 = S.share_undisturbed(d, base)
        new = S.share(d, (d["f26"] == 1) & ~base)
        out[f"u2026_nofire_{rule}"] = u0
        out[f"new2026_est_{rule}"] = new
        for name, kk in k.items():
            out[f"u2026_{rule}_{name}"] = u0 - kk * new
            vals.append(u0 - kk * new)
    out["central_2026"] = out[f"u2026_{S.HEADLINE_RULE}_central"]
    out["band_lo_2026"], out["band_hi_2026"] = min(vals), max(vals)
    out["status_2026"] = status(out["band_lo_2026"], out["band_hi_2026"], thr)
    # recovery clock and 2030 outlook restarted from 2026 (estimate at face value)
    d6 = with_2026(d)
    st = S.state_table(d6, S.HEADLINE_RULE, year=PRELIM_YEAR)
    rec = recovery_for_state(st, thr, start=PRELIM_YEAR)
    out.update({f"{key}_from2026": v for key, v in rec.items()})
    total = int(d["n"].sum())
    a = pd.read_csv(annual_path(code, res)).set_index("year")["n"]
    ys = np.arange(ref_years[0], ref_years[1] + 1)
    bs = a.reindex(ys, fill_value=0).to_numpy() / total
    rate = S.share(d, S.official_human(d) & ~S.official_human(d, 2015)) / 5.0
    u = simulate(st, bs, rate, start=PRELIM_YEAR, end=2030,
                 catchup_years=PRELIM_YEAR - C.BASELINE_YEAR, n_runs=n_runs, seed=seed)
    out["p_below_2030_from2026"] = float((u < thr).mean())
    out["median_2030_from2026"] = float(np.median(u))
    return out


MIN_CAL_KM2 = 100.0   # range-years with less estimated burn are too small to calibrate on


def province(code: str) -> str:
    return code.rstrip("0123456789")


def calibration_factors() -> pd.DataFrame:
    """NBAC / estimate ratio per province: pooled (central), min and max over
    range-years with at least ``MIN_CAL_KM2`` of estimated burn (band).
    Provinces with fewer than three such range-years use the national values."""
    by = pd.read_csv(C.TABLES / "prelim2026_calibration_by_range.csv")
    by["prov"] = by["CODE"].map(province)
    big = by[by["est_km2"] >= MIN_CAL_KM2].assign(r=lambda x: x["nbac_km2"] / x["est_km2"])

    def summarize(g):
        return pd.Series({"central": g["nbac_km2"].sum() / g["est_km2"].sum(),
                          "lo": g["r"].min(), "hi": g["r"].max(), "n": len(g)})
    nat = summarize(big)
    rows = {}
    for p in sorted(by["prov"].unique()):
        g = big[big["prov"] == p]
        rows[p] = {**(summarize(g) if len(g) >= 3 else nat).to_dict(),
                   "source": "province" if len(g) >= 3 else "national"}
    rows["national"] = {**nat.to_dict(), "source": "national"}
    k = pd.DataFrame(rows).T
    k[["central", "lo", "hi", "n"]] = k[["central", "lo", "hi", "n"]].astype(float)
    k.to_csv(C.TABLES / "prelim2026_factors.csv", index_label="province")
    return k


def analyze(res: float = C.DEFAULT_RES) -> pd.DataFrame:
    kt = calibration_factors()
    print("[prelim] calibration factors NBAC/estimate by province:")
    print(kt.to_string())
    ranges = read_interim("ranges", read_geometry=False).set_index("CODE")
    codes = [c for c in ranges.index if table_path(c, res, TAG).exists()]
    rows = []
    for i, c in enumerate(codes):
        kp = kt.loc[province(c)]
        k = {"central": float(kp["central"]), "lo": float(kp["lo"]), "hi": float(kp["hi"])}
        rows.append({"name": ranges.loc[c, "name"], "k_central": k["central"], "k_lo": k["lo"],
                     "k_hi": k["hi"], **score(c, float(ranges.loc[c, "threshold"]), k, res, seed=i)})
    out = pd.DataFrame(rows)
    sc = pd.read_csv(C.TABLES / "scorecard.csv").set_index("CODE")
    out["committed_central_2025"] = out["CODE"].map(sc["central_2025"])
    out["repro_diff_pts"] = 100 * (out[f"u2025_{S.HEADLINE_RULE}"] - out["committed_central_2025"])
    out["status_2025"] = out["CODE"].map(sc["status_2025"])
    out["band_lo_2025_with_cnfdb"] = np.minimum(out["CODE"].map(sc["band_lo"]), out["u2025_cnfdb_post"])
    out["band_hi_2025_with_cnfdb"] = np.maximum(out["CODE"].map(sc["band_hi"]), out["u2025_cnfdb_post"])
    out["status_2025_with_cnfdb"] = [status(lo, hi, t) for lo, hi, t in
                                     zip(out["band_lo_2025_with_cnfdb"], out["band_hi_2025_with_cnfdb"],
                                         out["threshold"])]
    out.to_csv(C.TABLES / "prelim2026.csv", index=False)
    show = ["CODE", "name", "committed_central_2025", "repro_diff_pts", "u2025_cnfdb_post",
            "status_2025", "status_2025_with_cnfdb", "burned_2026_est", "central_2026",
            "band_lo_2026", "band_hi_2026", "status_2026", "recovery_class_from2026",
            "recovery_year_from2026", "p_below_2030_from2026"]
    print(out[show].round(4).to_string(index=False))
    return out


def main(argv=None):
    p = argparse.ArgumentParser(prog="caribou.prelim", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("steps", nargs="+", choices=["fetch", "prepare", "calibrate", "completeness",
                                                 "pixels", "analyze"])
    p.add_argument("--codes", nargs="*")
    p.add_argument("--res", type=float, default=C.DEFAULT_RES)
    p.add_argument("--workers", type=int, default=6)
    p.add_argument("--overwrite", action="store_true")
    a = p.parse_args(argv)
    for step in a.steps:
        print(f"=== prelim {step}")
        if step == "fetch":
            fetch_prelim()
        elif step == "prepare":
            prepare_prelim()
        elif step == "calibrate":
            calibrate(a.workers)
        elif step == "completeness":
            cnfdb_completeness()
        elif step == "pixels":
            codes = a.codes or read_interim("ranges", read_geometry=False)["CODE"].tolist()
            build_pixels(codes, a.res, a.workers, a.overwrite)
        elif step == "analyze":
            analyze(a.res)


if __name__ == "__main__":
    main()
