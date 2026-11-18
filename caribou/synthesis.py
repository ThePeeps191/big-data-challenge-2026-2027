"""One table, and one figure, that bring the results together for the manuscript.

``outputs/tables/final_table.csv``, one row per range:

* 2020: published federal figure and our recomputation;
* 2025: headline (NBAC 2021-2025), band, status; the CNFDB fire-source rule
  where ``caribou.prelim`` computed it;
* 2026 (preliminary): burned share under the hotspot estimate, central value,
  band and status. Computed on the pixel grid for the ranges that
  ``caribou.prelim`` rasterized. For the rest it is *bounded*: the
  no-new-fire 2026 value from the recovery trajectory, minus between 0 and
  (highest calibration factor x burned share);
* recovery class / year and restoration need (from 2026 where computed);
* chance below the threshold in 2030 (from 2026 where computed);
* **triage**: what each range needs.

  ===================  ===========================================================
  needs restoration    below, and stays below after every fire ages out: only
                       restoring human footprint brings it back
  needs time           below, recovers as burns age out: protect it from new
                       disturbance until the recovery year
  at risk              meets (or straddles) now, but a 5% or higher chance of
                       being below in 2030: fire management and no new footprint
  secure               meets, under 5% chance of being below in 2030
  ===================  ===========================================================

``fig7_status_2020_2026`` adds the 2026 column to the slope chart for the
ranges that crossed.
"""

from __future__ import annotations

import pandas as pd
import shapely

from . import config as C
from .prepare import read_interim
from .scorecard import status

PRELIM_YEAR = C.UPDATE_YEAR + 1


def burned_2026_vector() -> pd.Series:
    """Share of each range inside the 2026 hotspot estimate (exact vector area)."""
    ranges = read_interim("ranges")
    est = read_interim(f"fires_prelim_{PRELIM_YEAR}")
    u = shapely.union_all(est.geometry.values)
    return pd.Series({r.CODE: shapely.intersection(r.geometry, u).area / r.geometry.area
                      for r in ranges.itertuples()})


def triage(row) -> str:
    st = row["status_2026"]
    if st == "below":
        return "needs restoration" if row["recovery_class"] == "needs restoration" else "needs time"
    p = row["p_below_2030"]
    return "at risk" if (st == "uncertain" or (pd.notna(p) and p >= 0.05)) else "secure"


def build_final_table() -> pd.DataFrame:
    t = C.TABLES
    sc = pd.read_csv(t / "scorecard.csv").set_index("CODE")
    rec = pd.read_csv(t / "recovery.csv").set_index("CODE")
    fc = pd.read_csv(t / "forecast.csv").set_index("CODE")
    traj = pd.read_csv(t / "recovery_trajectories.csv").set_index("year")
    pre = pd.read_csv(t / "prelim2026.csv").set_index("CODE")
    kt = pd.read_csv(t / "prelim2026_factors.csv").set_index("province")
    b26 = burned_2026_vector()
    h = "official_adj"
    rows = []
    for code, r in sc.iterrows():
        prov = code.rstrip("0123456789")
        row = {"CODE": code, "name": r["name"], "threshold": r["threshold"], "area_km2": r["area_km2"],
               "published_2020": r["report_undisturbed_2020"], "recomputed_2020": r["official_2020"],
               "meets_2020_published": bool(r["meets_2020"]),
               "u2025": r["central_2025"], "band_lo_2025": r["band_lo"], "band_hi_2025": r["band_hi"],
               "status_2025": r["status_2025"], "burned_2021_2025": r["burned_2021_2025"],
               "burned_2026_est": float(b26[code])}
        if code in pre.index:
            p = pre.loc[code]
            row.update({"u2025_cnfdb_post": p["u2025_cnfdb_post"],
                        "band_lo_2025": p["band_lo_2025_with_cnfdb"], "band_hi_2025": p["band_hi_2025_with_cnfdb"],
                        "status_2025": p["status_2025_with_cnfdb"],
                        "u2026": p["central_2026"], "band_lo_2026": p["band_lo_2026"],
                        "band_hi_2026": p["band_hi_2026"], "status_2026": p["status_2026"],
                        "method_2026": "pixel grid",
                        "ceiling": p["ceiling_from2026"],
                        "recovery_class": p["recovery_class_from2026"],
                        "recovery_year": p["recovery_year_from2026"],
                        "restore_km2": p["restore_share_from2026"] * r["area_km2"],
                        "p_below_2030": p["p_below_2030_from2026"], "outlook_from": PRELIM_YEAR})
        else:
            k_hi = float(kt.loc[prov, "hi"]) if prov in kt.index else float(kt.loc["national", "hi"])
            k_c = float(kt.loc[prov, "central"]) if prov in kt.index else float(kt.loc["national", "central"])
            nofire = float(traj.loc[PRELIM_YEAR, code])
            shift = nofire - float(traj.loc[C.UPDATE_YEAR, code])     # 1986 fires ageing out
            burn = float(b26[code])
            row.update({"u2026": nofire - k_c * burn * nofire,       # random placement on the range
                        "band_lo_2026": r["band_lo"] + shift - k_hi * burn,
                        "band_hi_2026": r["band_hi"] + shift,
                        "method_2026": "bounded" if burn > 0 else "trajectory (no 2026 fire)",
                        "ceiling": rec.loc[code, f"ceiling_{h}"],
                        "recovery_class": rec.loc[code, f"recovery_class_{h}"],
                        "recovery_year": rec.loc[code, f"recovery_year_{h}"],
                        "restore_km2": rec.loc[code, "restore_km2"],
                        "p_below_2030": fc.loc[code, "p_below"], "outlook_from": C.UPDATE_YEAR})
            row["status_2026"] = status(row["band_lo_2026"], row["band_hi_2026"], r["threshold"])
        rows.append(row)
    ft = pd.DataFrame(rows)
    ft["triage"] = ft.apply(triage, axis=1)
    ft["crossed_2025"] = ft["meets_2020_published"] & (ft["status_2025"] == "below")
    ft["crossed_by_2026"] = ft["meets_2020_published"] & (ft["status_2026"] == "below")
    ft.to_csv(t / "final_table.csv", index=False)
    return ft


def summary(ft: pd.DataFrame) -> dict:
    out = {
        "meets_2020_published": int(ft["meets_2020_published"].sum()),
        "meets_2025_whole_band": int((ft["status_2025"] == "meets").sum()),
        "meets_2025_band_reaches": int((ft["band_hi_2025"] >= ft["threshold"]).sum()),
        "meets_2026_whole_band": int((ft["status_2026"] == "meets").sum()),
        "meets_2026_band_reaches": int((ft["band_hi_2026"] >= ft["threshold"]).sum()),
        "crossed_2025": ft.loc[ft["crossed_2025"], "name"].tolist(),
        "crossed_by_2026": ft.loc[ft["crossed_by_2026"], "name"].tolist(),
        "uncertain_2026": ft.loc[ft["status_2026"] == "uncertain", "name"].tolist(),
        "triage_counts": ft["triage"].value_counts().to_dict(),
        "range_area_burned_2026_est_km2": float((ft["burned_2026_est"] * ft["area_km2"]).sum()),
    }
    for k in ("needs restoration", "needs time", "at risk", "secure"):
        out[f"triage_{k.replace(' ', '_')}"] = ft.loc[ft["triage"] == k, "name"].tolist()
    return out


def status_figure(ft: pd.DataFrame) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from .figures import CONTEXT, CRITICAL, INK, MUTED, WARNING_INK, _save
    d = ft[ft["threshold"] == C.DEFAULT_THRESHOLD]
    focus = d[d["meets_2020_published"] & (d["status_2026"] != "meets")]
    fig, ax = plt.subplots(figsize=(7.2, 5.6))
    xs = [0, 1, 2]
    for r in d.itertuples():
        if r.CODE in set(focus["CODE"]):
            continue
        ax.plot(xs, [100 * r.published_2020, 100 * r.u2025, 100 * r.u2026], color=CONTEXT, lw=0.8, zorder=1)
    for r in focus.itertuples():
        col = CRITICAL if r.status_2026 == "below" else WARNING_INK
        ys = [100 * r.published_2020, 100 * r.u2025, 100 * r.u2026]
        ax.plot(xs, ys, color=col, lw=2, zorder=3, marker="o", ms=4)
        ax.plot([2, 2], [100 * r.band_lo_2026, 100 * r.band_hi_2026], color=col, lw=5, alpha=0.3,
                solid_capstyle="round", zorder=2)
    lab = focus.sort_values("u2026")
    last = -1e9
    for r in lab.itertuples():
        y = max(100 * r.u2026, last + 2.4)
        last = y
        ax.text(2.14, y, f"{r.name}  {100 * r.published_2020:.0f} → {100 * r.u2025:.0f} → {100 * r.u2026:.0f}%",
                va="center", fontsize=8, color=INK)
    ax.axhline(65, color=INK, lw=1, ls=(0, (4, 3)), zorder=0)
    ax.text(-0.08, 64.6, "65% threshold", fontsize=8, color=INK, va="top",
            bbox=dict(facecolor="white", edgecolor="none", pad=1, alpha=0.8))
    ax.set_xticks(xs, ["2020\n(official)", "2025\n(NBAC, final)", "2026\n(preliminary)"])
    ax.set_xlim(-0.1, 2.1)
    ax.set_ylim(40, 90)
    ax.set_ylabel("Range undisturbed (%)")
    n20 = int(ft["meets_2020_published"].sum())
    n25 = int((ft["status_2025"] == "meets").sum())
    n26 = int((ft["status_2026"] == "meets").sum())
    n26b = int((ft["band_lo_2026"] >= ft["threshold"] - 0.0005).sum())   # band edge within 0.05 pt
    n26s = f"{n26}" if n26 == n26b else f"{n26}-{n26b}"
    ax.set_title(f"Ranges meeting their threshold (whole band): {n20} → {n25} → {n26s}", pad=10)
    ax.text(0, -0.16, "Ranges that met the 65% line in 2020 and no longer clearly do. Bar at 2026: "
            "uncertainty band (update rule × calibration of\nthe hotspot-based 2026 perimeters against NBAC "
            "2021-2025). Red: whole band below; amber: band straddles the line.",
            transform=ax.transAxes, fontsize=7, color=MUTED, va="top")
    _save(fig, "fig7_status_2020_2026")


def recovery_figure(ft: pd.DataFrame) -> None:
    """The recovery clock restarted from 2026 for the re-rasterized ranges
    (2025 state for the rest): fig3_recovery_clock_2026."""
    from .figures import recovery_chart
    h = "official_adj"
    rec = pd.DataFrame({"CODE": ft["CODE"], "name": ft["name"],
                        f"recovery_class_{h}": ft["recovery_class"],
                        f"recovery_year_{h}": ft["recovery_year"],
                        f"ceiling_{h}": ft["ceiling"],
                        f"restore_share_{h}": ft["restore_km2"] / ft["area_km2"]})
    sc = pd.DataFrame({"CODE": ft["CODE"], "official_2020": ft["recomputed_2020"], "crossing": ""})
    recovery_chart(rec, sc, name="fig3_recovery_clock_2026", start=C.UPDATE_YEAR)


def range_map(code: str = "ON4") -> None:
    """fig9: one range, its federal footprint, fires 1986-2020 still counting,
    NBAC 2021-2025 and the 2026 estimate."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch
    from .figures import FIRE, INDUSTRY, INK, MUTED, SURFACE, _save
    rr = read_interim("ranges", where=f"CODE = '{code}'")
    geom, herd, name = rr.geometry.iat[0], rr["HERD"].iat[0], rr["name"].iat[0]
    bb = tuple(geom.bounds)
    clip = lambda g: g.clip(geom)                                   # noqa: E731
    hum = clip(read_interim("fed2020_buffered", where=f"HERD = '{herd}'"))
    cn = read_interim("fires_cnfdb", bbox=bb)
    old = clip(cn[(cn["YEAR"] >= 1986) & (cn["YEAR"] <= 2020)])
    nb = read_interim("fires_nbac", bbox=bb)
    new = clip(nb[nb["YEAR"] > C.BASELINE_YEAR])
    e26 = clip(read_interim(f"fires_prelim_{PRELIM_YEAR}", bbox=bb))
    ft = pd.read_csv(C.TABLES / "final_table.csv").set_index("CODE").loc[code]
    fig, ax = plt.subplots(figsize=(6.4, 6.4 * (bb[3] - bb[1]) / (bb[2] - bb[0]) + 0.6))
    rr.plot(ax=ax, color="#eef3e8", edgecolor="none")
    if len(old):
        old.plot(ax=ax, color="#f6c9a8", edgecolor="none")
    if len(hum):
        hum.plot(ax=ax, color=INDUSTRY, alpha=0.55, edgecolor="none")
    if len(new):
        new.plot(ax=ax, color=FIRE, edgecolor="none")
    if len(e26):
        e26.plot(ax=ax, color="#8b1a1a", alpha=0.85, edgecolor="none")
    rr.boundary.plot(ax=ax, color=INK, linewidth=0.8)
    ax.set_axis_off()
    ax.set_title(f"{name}: {100 * ft.published_2020:.0f}% undisturbed (2020) → "
                 f"{100 * ft.u2025:.0f}% (2025) → {100 * ft.u2026:.0f}% (2026, preliminary)",
                 fontsize=10.5, loc="left")
    ax.legend(handles=[Patch(color=INDUSTRY, alpha=0.55, label="Human footprint + 500 m (federal 2020)"),
                       Patch(color="#f6c9a8", label="Fires 1986-2020 (still counting)"),
                       Patch(color=FIRE, label="Fires 2021-2025 (NBAC)"),
                       Patch(color="#8b1a1a", label="Fires 2026 (hotspot estimate, preliminary)")],
              loc="upper left", fontsize=7.5, frameon=True, facecolor=SURFACE, edgecolor="none")
    fig.text(0.01, 0.0, "Threshold: 65% undisturbed. 2026 perimeters overstate burned area by about a "
             "quarter (calibrated in the text).", fontsize=7, color=MUTED)
    fig.patch.set_facecolor(SURFACE)
    _save(fig, f"fig9_range_{code}", exts=("png",))   # detailed polygons: SVG would be ~10 MB


if __name__ == "__main__":
    import json
    ft = build_final_table()
    s = summary(ft)
    (C.TABLES / "final_summary.json").write_text(json.dumps(s, indent=2))
    print(json.dumps(s, indent=2))
    status_figure(ft)
    recovery_figure(ft)
    range_map("ON4")
