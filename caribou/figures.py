"""Poster and manuscript figures (PNG at 200 dpi + SVG).

Colour roles (validated reference palette): ink and greys for context,
status colours only for a range's state - *critical* red for a clear
crossing, *warning* amber for a crossing inside the uncertainty band,
*good* green for meeting the threshold - always paired with a text label.
Fire and industry use categorical slots 2 (orange) and 1 (blue).
"""

from __future__ import annotations

import json

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from . import config as C  # noqa: E402

INK, INK2, MUTED = "#0b0b0b", "#52514e", "#898781"
GRID, AXIS, SURFACE = "#e1e0d9", "#c3c2b7", "#fcfcfb"
CRITICAL, WARNING, GOOD, SERIOUS = "#d03b3b", "#fab219", "#0ca30c", "#ec835a"
WARNING_INK = "#b07a00"   # darker amber for text/lines on light surface
FIRE, INDUSTRY = "#eb6834", "#2a78d6"
CONTEXT = "#c3c2b7"

plt.rcParams.update({
    "font.family": ["Segoe UI", "DejaVu Sans", "sans-serif"],
    "font.size": 10, "axes.edgecolor": AXIS, "axes.labelcolor": INK2,
    "xtick.color": MUTED, "ytick.color": MUTED, "axes.grid": False,
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "axes.spines.top": False, "axes.spines.right": False, "axes.titlesize": 12,
    "axes.titleweight": "bold", "axes.titlecolor": INK, "axes.titlelocation": "left",
})


def _save(fig, name, exts=("png", "svg")):
    for ext in exts:
        fig.savefig(C.FIGURES / f"{name}.{ext}", dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"  figure {name}")


def _load(tag=""):
    t = C.TABLES
    sc = pd.read_csv(t / f"scorecard{tag}.csv")
    rec = pd.read_csv(t / f"recovery{tag}.csv")
    fc = pd.read_csv(t / f"forecast{tag}.csv")
    sp = pd.read_csv(t / ("split_det.csv" if tag else "split.csv"))
    return sc, rec, fc, sp


# ---------------------------------------------------------------- 1. slope chart
def slope_chart(sc: pd.DataFrame):
    """All 51 ranges, 2020 official -> 2025 updated, against the 65% line."""
    fig, ax = plt.subplots(figsize=(6.2, 7.2))
    d = sc[sc["threshold"] == C.DEFAULT_THRESHOLD]
    def role(cr):
        cr = cr if isinstance(cr, str) else ""
        if cr.startswith("clear"):
            return CRITICAL, 2.2, 3
        if cr.startswith("possible") or cr.startswith("at risk"):
            return WARNING_INK, 1.8, 2
        return CONTEXT, 0.9, 1

    for r in d.itertuples():
        col, lw, z = role(r.crossing)
        ax.plot([0, 1], [100 * r.official_2020, 100 * r.central_2025], color=col, lw=lw,
                zorder=z, solid_capstyle="round")
        ax.scatter([0, 1], [100 * r.official_2020, 100 * r.central_2025], s=14, color=col,
                   zorder=z + 0.5, edgecolor=SURFACE, linewidth=0.8)
    ax.axhline(65, color=INK, lw=1, ls=(0, (4, 3)), zorder=0)
    ax.text(-0.075, 65.8, "65% threshold", va="bottom", ha="left", color=INK, fontsize=8.5)
    # direct labels for crossings, de-overlapped
    lab = d[d["crossing"].fillna("").str.match(r"clear|possible|at risk")].sort_values("central_2025")
    ys, last = [], -1e9
    for v in 100 * lab["central_2025"]:
        y = max(v, last + 2.6)
        ys.append(y)
        last = y
    for (r, y) in zip(lab.itertuples(), ys):
        star = "*" if r.borderline_2020 else ""
        ax.text(1.04, y, f"{r.name}{star}  {100 * r.official_2020:.0f}% → {100 * r.central_2025:.0f}%",
                va="center", fontsize=8.5, color=INK)
    ax.set_xticks([0, 1], ["2020\n(official map)", "2025\n(updated, this study)"])
    ax.set_xlim(-0.08, 1.0)
    ax.set_ylim(0, 100)
    ax.set_ylabel("Range undisturbed (%)")
    ax.spines["bottom"].set_visible(False)
    ax.tick_params(axis="x", length=0, colors=INK2)
    n20 = int(sc["meets_2020"].sum())
    n25c = int((sc["status_2025"] == "meets").sum())
    n25p = int((sc["band_hi"] >= sc["threshold"]).sum())
    n25 = f"{n25c}" if n25c == n25p else f"{n25c}-{n25p}"
    ax.set_title(f"Ranges meeting their threshold: {n20} in 2020, {n25} in 2025", pad=14)
    from matplotlib.lines import Line2D
    handles = [Line2D([], [], color=CRITICAL, lw=2.2, label="Fell below the line (outside uncertainty)"),
               Line2D([], [], color=WARNING_INK, lw=1.8, label="At the line: uncertainty band straddles it"),
               Line2D([], [], color=CONTEXT, lw=1, label="Other ranges")]
    ax.legend(handles=handles, loc="lower left", frameon=False, fontsize=8)
    ax.text(0, -0.12, "SK1 (40% threshold) shown in the scorecard figure. "
            "2025 = official 2020 footprint, fires aged out\nafter 40 years, plus NBAC fires "
            "2021-2025. * Published as exactly at the line in 2020 (35%\ndisturbed); the federal "
            "layers give 35.2%.",
            transform=ax.transAxes, fontsize=7.5, color=MUTED, va="top")
    _save(fig, "fig1_slope_2020_2025")


# ---------------------------------------------------------------- 2. scorecard bands
def scorecard_chart(sc: pd.DataFrame):
    d = sc.assign(margin=sc["central_2025"] - sc["threshold"]).sort_values("margin")
    fig, ax = plt.subplots(figsize=(7.2, 11))
    y = np.arange(len(d))
    stat_col = {"meets": GOOD, "below": CRITICAL, "uncertain": WARNING_INK}
    for yi, r in zip(y, d.itertuples()):
        t = 100 * r.threshold
        c = stat_col[r.status_2025]
        ax.plot([100 * r.band_lo - t, 100 * r.band_hi - t], [yi, yi], color=c, lw=4,
                alpha=0.35, solid_capstyle="round")
        ax.scatter(100 * r.official_2020 - t, yi, s=22, facecolor=SURFACE, edgecolor=INK2,
                   lw=1, zorder=3)
        ax.scatter(100 * r.central_2025 - t, yi, s=26, color=c, zorder=4)
    ax.axvline(0, color=INK, lw=1)
    names = [f"{r.name} ({r.CODE})" + ("  [40%]" if r.threshold != C.DEFAULT_THRESHOLD else "")
             for r in d.itertuples()]
    ax.set_yticks(y, names, fontsize=7.5, color=INK2)
    ax.tick_params(axis="y", length=0)
    ax.set_ylim(-1, len(d))
    ax.set_xlabel("Points above (+) or below (−) the range's threshold")
    ax.xaxis.grid(True, color=GRID, lw=0.6)
    ax.set_axisbelow(True)
    ax.set_title("Boreal caribou scorecard, 2025 update", pad=10)
    from matplotlib.lines import Line2D
    h = [Line2D([], [], marker="o", ls="", mfc=SURFACE, mec=INK2, label="2020 official"),
         Line2D([], [], marker="o", ls="", color=INK2, label="2025 updated (headline rule)"),
         Line2D([], [], lw=4, alpha=0.35, color=INK2, label="2025 uncertainty band"),
         Line2D([], [], lw=4, color=GOOD, label="Meets (whole band above)"),
         Line2D([], [], lw=4, color=WARNING_INK, label="Uncertain (band straddles)"),
         Line2D([], [], lw=4, color=CRITICAL, label="Below (whole band below)")]
    ax.legend(handles=h, loc="lower right", fontsize=7.5, frameon=True, facecolor=SURFACE,
              edgecolor=GRID)
    _save(fig, "fig2_scorecard_bands")


# ---------------------------------------------------------------- 3. recovery clock
def recovery_chart(rec: pd.DataFrame, sc: pd.DataFrame):
    h = "official_adj"
    d = rec[rec[f"recovery_class_{h}"] != "meets now"].copy()
    d = d.merge(sc[["CODE", "official_2020", "crossing"]], on="CODE")
    d["sortkey"] = np.where(d[f"recovery_class_{h}"] == "recovers with time",
                            d[f"recovery_year_{h}"], 3000 - 100 * d[f"ceiling_{h}"])
    d = d.sort_values("sortkey", ascending=False)
    fig, ax = plt.subplots(figsize=(7.4, 0.24 * len(d) + 1.6))
    y = np.arange(len(d))
    end = C.UPDATE_YEAR + C.FIRE_WINDOW_YEARS + 2
    for yi, r in zip(y, d.itertuples()):
        cls = getattr(r, f"recovery_class_{h}")
        if cls == "recovers with time":
            yr = getattr(r, f"recovery_year_{h}")
            ax.plot([C.UPDATE_YEAR, yr], [yi, yi], color=FIRE, lw=5, solid_capstyle="butt")
            ax.text(yr + 0.6, yi, f"{int(yr)}", va="center", fontsize=7.5, color=INK2)
        else:
            gap = 100 * getattr(r, f"restore_share_{h}")
            ax.plot([C.UPDATE_YEAR, end], [yi, yi], color=INDUSTRY, lw=5, alpha=0.25,
                    solid_capstyle="butt")
            ax.text(end + 0.6, yi, f"never: restore {gap:.0f}% of range", va="center",
                    fontsize=7.5, color=INDUSTRY)
    ax.set_yticks(y, [f"{r.name}" for r in d.itertuples()], fontsize=7.5, color=INK2)
    ax.tick_params(axis="y", length=0)
    ax.set_xlim(C.UPDATE_YEAR, end + 22)
    ax.xaxis.grid(True, color=GRID, lw=0.6)
    ax.set_axisbelow(True)
    ax.set_xlabel("Year the range would be back above its threshold, with no new fire or industry")
    ax.set_title("The recovery clock: which herds need time, which need restoration", pad=10)
    from matplotlib.patches import Patch
    ax.legend(handles=[Patch(color=FIRE, label="Fire-driven: recovers as burns age out (40 yr)"),
                       Patch(color=INDUSTRY, alpha=0.35,
                             label="Industry-driven: below the line even after every fire ages out")],
              loc="upper right", fontsize=7.5, frameon=True, facecolor=SURFACE, edgecolor=GRID)
    _save(fig, "fig3_recovery_clock")


# ---------------------------------------------------------------- 4. fire vs industry
def split_chart(sp: pd.DataFrame, top: int = 25):
    d = sp.assign(tot=sp["new_fire_km2"] + sp["industry_km2"]).nlargest(top, "tot")
    d = d.sort_values("tot")
    fig, ax = plt.subplots(figsize=(7, 0.26 * len(d) + 1.4))
    y = np.arange(len(d))
    ax.barh(y, d["new_fire_km2"], color=FIRE, height=0.7, label="Newly disturbed by fire 2021-2025")
    ax.barh(y, d["industry_km2"], left=d["new_fire_km2"] + d["tot"].max() * 0.003,
            color=INDUSTRY, height=0.7, label=f"New industry ({d['industry_source'].iat[0]})")
    ax.set_yticks(y, d["name"], fontsize=7.5, color=INK2)
    ax.tick_params(axis="y", length=0)
    ax.xaxis.grid(True, color=GRID, lw=0.6)
    ax.set_axisbelow(True)
    ax.set_xlabel("Habitat newly disturbed since 2020 (km²)")
    ax.set_title(f"Fire vs industry: habitat lost since 2020 (top {top} ranges)", pad=10)
    ax.legend(loc="lower right", fontsize=7.5, frameon=False)
    _save(fig, "fig4_fire_vs_industry")


# ---------------------------------------------------------------- 5. forecast
def forecast_chart(fc: pd.DataFrame, sc: pd.DataFrame):
    d = fc.merge(sc[["CODE", "status_2025"]], on="CODE")
    d = d[((d["p_below"] > 0.005) | (d["p_below_recent"] > 0.005)) & (d["p_below"] < 0.999)
          | ((d["status_2025"] != "below") & (d["p_below"] > 0.005))]
    d = d.sort_values("p_below")
    fig, ax = plt.subplots(figsize=(7, 0.24 * len(d) + 1.4))
    y = np.arange(len(d))
    ax.barh(y, 100 * d["p_below"], color=SERIOUS, height=0.65, label="Fire record 1986-2025")
    ax.scatter(100 * d["p_below_recent"], y, marker="|", s=90, color=INK, zorder=3,
               label="Fire record 2011-2025 only")
    ax.set_yticks(y, d["name"], fontsize=7.5, color=INK2)
    ax.tick_params(axis="y", length=0)
    ax.set_xlim(0, 100)
    ax.xaxis.grid(True, color=GRID, lw=0.6)
    ax.set_axisbelow(True)
    ax.set_xlabel("Chance the range is below its threshold in 2030 (%)")
    ax.set_title("2030 outlook (ranges not already certain to be below)", pad=10)
    ax.legend(loc="lower right", fontsize=7.5, frameon=False)
    _save(fig, "fig5_forecast_2030")


# ---------------------------------------------------------------- 6. map
def status_map(sc: pd.DataFrame):
    from .prepare import read_interim
    g = read_interim("ranges").merge(sc[["CODE", "status_2025", "crossing", "meets_2020"]], on="CODE")
    g["geometry"] = g.simplify(1000)  # display only: keeps the SVG small
    col = {"meets": GOOD, "uncertain": WARNING, "below": CRITICAL}
    fig, ax = plt.subplots(figsize=(9, 5.6))
    for st, c in col.items():
        sub = g[g["status_2025"] == st]
        if len(sub):
            sub.plot(ax=ax, color=c, edgecolor=SURFACE, linewidth=0.4, alpha=0.85)
    cr = g[g["crossing"].fillna("").str.startswith("clear")]
    if len(cr):
        cr.boundary.plot(ax=ax, color=INK, linewidth=1.2)
        import matplotlib.patheffects as pe
        halo = [pe.withStroke(linewidth=3, foreground=SURFACE)]
        pts = sorted(((r.geometry.representative_point(), C.display_name(r.HERD))
                      for r in cr.itertuples()), key=lambda t: t[0].x)
        for k, (p, name) in enumerate(pts):
            dy = 28 if k % 2 == 0 else -28        # stagger neighbours above / below
            ax.annotate(name, (p.x, p.y), xytext=(14, dy), textcoords="offset points",
                        fontsize=8, color=INK, path_effects=halo,
                        arrowprops=dict(arrowstyle="-", color=INK, lw=0.6))
    ax.set_axis_off()
    from matplotlib.patches import Patch
    ax.legend(handles=[Patch(color=GOOD, label="Meets threshold (whole band)"),
                       Patch(color=WARNING, label="Uncertain (band straddles threshold)"),
                       Patch(color=CRITICAL, label="Below threshold (whole band)"),
                       Patch(facecolor="none", edgecolor=INK, label="Crossed below since 2020")],
              loc="lower left", fontsize=8, frameon=False)
    ax.set_title("Boreal caribou ranges, status after the 2021-2025 fires", pad=6)
    _save(fig, "fig6_status_map")


def make_all(tag: str = ""):
    sc, rec, fc, sp = _load(tag)
    slope_chart(sc)
    scorecard_chart(sc)
    recovery_chart(rec, sc)
    split_chart(sp)
    forecast_chart(fc, sc)
    status_map(sc)
    s = C.TABLES / f"summary{tag}.json"
    if s.exists():
        print(json.dumps(json.loads(s.read_text()), indent=1)[:400])
