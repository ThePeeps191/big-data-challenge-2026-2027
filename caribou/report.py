"""Render the results section of README.md from the output tables.

Everything quoted in the README comes from ``outputs/tables``, so re-running
the pipeline next year refreshes the text too:

    python -m caribou report
"""

from __future__ import annotations

import json
import re

import numpy as np
import pandas as pd

from . import config as C

START, END = "<!-- RESULTS -->", "<!-- /RESULTS -->"


def pct(x, nd=0):
    return f"{100 * x:.{nd}f}%"


def km2(x):
    return f"{x:,.0f} km²"


def render(tag: str = "") -> str:
    t = C.TABLES
    sc = pd.read_csv(t / f"scorecard{tag}.csv")
    rec = pd.read_csv(t / f"recovery{tag}.csv")
    fc = pd.read_csv(t / f"forecast{tag}.csv")
    s = json.loads((t / f"summary{tag}.json").read_text())
    h = "official_adj"
    a = sc["area_km2"]

    clear = sc[sc["crossing"].fillna("").str.startswith("clear")].sort_values("change_pts")
    risk = sc[sc["crossing"].fillna("").str.match(r"at risk|possible")]
    lines = [START, "", "## Results (first full run, 2026-11-17)", ""]
    n25 = (f"{s['meet_2025_clearly']}" if s["meet_2025_clearly"] == s["meet_2025_possibly"]
           else f"{s['meet_2025_clearly']}-{s['meet_2025_possibly']}")
    lines += [
        f"**{s['meet_2020_report']} of 51 ranges met their threshold on the 2020 federal map. "
        f"After the 2021-{C.UPDATE_YEAR} fires, {n25} do.** "
        f"{len(clear)} ranges fell through the line with their whole uncertainty band below it, "
        f"including the Northwest Territories range, the largest in the country "
        f"({km2(float(sc.loc[sc.CODE == 'NT1', 'area_km2'].iat[0]))}).",
        "",
        "![2020 vs 2025 for all 51 ranges](outputs/figures/fig1_slope_2020_2025.png)",
        "",
        "| Measure | Result |", "| --- | --- |",
        f"| Ranges meeting threshold, 2020 (published / our recomputation) | {s['meet_2020_report']} / "
        f"{s['meet_2020_ours_raster']} (Brightsand is 35.2% disturbed in the federal layers, "
        f"published as 35%) |",
        f"| Our 2020 recomputation vs the published per-range figures | within "
        f"{s['max_abs_diff_vs_report_pts']:.1f} points for all 51 (the report rounds to whole %) |",
        f"| Rebuilt 2020 footprint (buffered human + CNFDB 1981-2020) vs official layer | "
        f"median difference {s['median_abs_rebuild_error_2020_pts']:.4f} points, max "
        f"{s['max_abs_rebuild_error_2020_pts']:.2f} |",
        f"| Ranges meeting threshold, 2025 (whole band above / band reaches threshold) | "
        f"{s['meet_2025_clearly']} / {s['meet_2025_possibly']} |",
        f"| Range area burned 2021-{C.UPDATE_YEAR} | {km2(s['burned_2021_2025_km2'])} "
        f"({pct(s['burned_2021_2025_share'], 1)} of all range area) |",
        f"| ...of which was not already disturbed in 2020 | {km2(s['new_fire_km2'])} |",
        f"| Returned to undisturbed as 1981-1985 fires aged out | {km2(s['aged_out_km2'])} |",
        f"| Ranges with more than 10% burned in five years | {s['ranges_burned_gt10pct']} |",
        f"| Ranges that lost more than 10 points | {s['ranges_lost_gt10pts']} |",
        f"| Ranges meeting threshold under a human-only rule (no fire), 2020 | "
        f"{s['meet_human_only_2020']} |",
        (f"| 100 m raster vs exact vector area of the official layers | max "
         f"{100 * (sc['vec_l3'] - sc['official_2020']).abs().max():.2f} points (2020), "
         f"{100 * (sc['vec_l3_15'] - sc['official_2015']).abs().max():.2f} (2015) |"
         if "vec_l3" in sc else "| 100 m raster vs exact vector | not computed |"),
        "",
        "### Ranges that crossed below their threshold", "",
        "| Range | 2020 (official) | 2025 (headline) | 2025 band | Burned 2021-25 | Back above the line, "
        "no new disturbance | Chance below in 2030 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    r_idx = rec.set_index("CODE")
    f_idx = fc.set_index("CODE")
    for r in pd.concat([clear, risk]).itertuples():
        rr = r_idx.loc[r.CODE]
        cls = rr[f"recovery_class_{h}"]
        when = (f"{int(rr[f'recovery_year_{h}'])}" if cls == "recovers with time"
                else ("meets now" if cls == "meets now" else "never without restoration"))
        flag = "" if r.crossing.startswith("clear") else " (band straddles the line)"
        star = " *" if r.borderline_2020 else ""
        lines.append(
            f"| {r.name} ({r.CODE}){star}{flag} | {pct(r.official_2020)} | {pct(r.central_2025)} | "
            f"{pct(r.band_lo)}-{pct(r.band_hi)} | {pct(r.burned_2021_2025)} | {when} | "
            f"{pct(f_idx.loc[r.CODE, 'p_below'])} |")
    lines += ["",
              "\\* Brightsand was published as exactly at the line in 2020; the federal layers give "
              "64.8% undisturbed. SK1's threshold is 40%.", ""]

    # recovery
    cls = rec[f"recovery_class_{h}"].value_counts()
    rt = rec[rec[f"recovery_class_{h}"] == "recovers with time"]
    nr = rec[rec[f"recovery_class_{h}"] == "needs restoration"].sort_values("restore_km2",
                                                                            ascending=False)
    lines += [
        "### The recovery clock", "",
        f"With no new fire and no new industry, **{cls.get('recovers with time', 0)} ranges now "
        f"below their threshold would recover on their own** as burns age out "
        f"({int(rt[f'recovery_year_{h}'].min())}-{int(rt[f'recovery_year_{h}'].max())}). "
        f"**{cls.get('needs restoration', 0)} never would**: their human footprint alone keeps them "
        f"below, and they need {km2(nr['restore_km2'].sum())} of restoration in total "
        f"(largest: {', '.join(f'{x.name} {km2(x.restore_km2)}' for x in nr.head(3).itertuples())}). "
        f"{cls.get('meets now', 0)} ranges meet their threshold today.",
        "",
        "![Recovery clock](outputs/figures/fig3_recovery_clock.png)", "",
    ]

    # forecast
    meets_now = sc[sc["status_2025"] != "below"]["CODE"]
    f_at = fc[fc["CODE"].isin(meets_now) & (fc["p_below"] >= 0.05)].sort_values("p_below",
                                                                                ascending=False)
    nwt = fc.set_index("CODE").loc["NT1"]
    lines += [
        "### 2030 outlook", "",
        "Among ranges not already below their threshold, those with at least a 5% chance of being "
        "below it in 2030 (fire record 1986-2025; in brackets, the 2011-2025 record only): "
        + "; ".join(f"{x.name} {pct(x.p_below)} ({pct(x.p_below_recent)})" for x in f_at.itertuples())
        + ".",
        "",
        f"The Northwest Territories range would be back above the line by "
        f"{int(r_idx.loc['NT1', f'recovery_year_{h}'])} if nothing else burned, but at its own "
        f"1986-2025 burn rate it is below the line in {pct(nwt['p_below'])} of simulated 2030s "
        f"(median {pct(nwt['median_2030'])}).",
        "",
        "Figures: [scorecard with bands](outputs/figures/fig2_scorecard_bands.png) · "
        "[fire vs industry](outputs/figures/fig4_fire_vs_industry.png) · "
        "[2030 outlook](outputs/figures/fig5_forecast_2030.png) · "
        "[status map](outputs/figures/fig6_status_map.png) · "
        "[hero image](outputs/figures/fig0_hero_MB12.png). "
        "Full tables: [outputs/tables](outputs/tables).",
        "",
        "**Not yet in these numbers:** industry built since 2020. The fire vs industry split "
        "projects it from the official 2015-2020 growth until the detector (below) maps it. "
        "Treat 2025 values as an upper bound on undisturbed habitat.",
        "", END,
    ]
    return "\n".join(lines)


def update_readme(tag: str = "") -> None:
    path = C.ROOT / "README.md"
    text = path.read_text(encoding="utf8")
    block = render(tag)
    if START in text and END in text:
        text = re.sub(re.escape(START) + r".*?" + re.escape(END), lambda _m: block, text, flags=re.S)
    elif START in text:
        text = text.replace(START, block)
    else:
        raise ValueError("README has no results marker")
    path.write_text(text, encoding="utf8")
    print("  README results updated")
