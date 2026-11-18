"""Fire vs industry split since 2020, and the recovery clock.

Recovery clock: under the federal rule a fire counts for 40 years and then
ages out; human footprint counts until someone restores it. With no new
fire and no new industry, a range's undisturbed share climbs as fires age
out, up to a *ceiling* of 1 - (permanent share). If the ceiling clears the
threshold, the range recovers on its own in a computable year (fire-driven:
it needs time). If not, it never recovers without restoration
(industry-driven: it needs restoration of a computable area).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import config as C
from . import scenarios as S
from .pixels import load_table
from .prepare import read_interim

HORIZON = C.UPDATE_YEAR + C.FIRE_WINDOW_YEARS + 5   # every 2025 fire has aged out


def recovery_for_state(st: pd.DataFrame, thr: float, start: int = C.UPDATE_YEAR) -> dict:
    now = S.state_undisturbed(st, start)
    ceiling = 1.0 - st.loc[st["permanent"], "share"].sum()
    out = {"undisturbed_now": now, "ceiling": ceiling, "recovery_year": np.nan,
           "restore_share": max(0.0, thr - ceiling)}
    if now >= thr:
        out["recovery_class"] = "meets now"
        return out
    if ceiling < thr:
        out["recovery_class"] = "needs restoration"
        return out
    for y in range(start + 1, HORIZON + 1):
        if S.state_undisturbed(st, y) >= thr:
            out["recovery_year"] = y
            break
    out["recovery_class"] = "recovers with time"
    return out


def trajectory(st: pd.DataFrame, start: int = C.UPDATE_YEAR, end: int = HORIZON) -> pd.Series:
    years = np.arange(start, end + 1)
    return pd.Series([S.state_undisturbed(st, int(y)) for y in years], index=years)


def build_recovery(res: float = C.DEFAULT_RES, new_human: str | None = None,
                   rules=(S.HEADLINE_RULE, "rebuild_cnfdb"), tag: str = "") -> pd.DataFrame:
    """Recovery year per range under the headline rule and an alternative."""
    ranges = read_interim("ranges", read_geometry=False)
    rows, traj = [], {}
    for r in ranges.itertuples():
        d = load_table(r.CODE, res, tag)
        row = {"CODE": r.CODE, "name": r.name, "threshold": r.threshold,
               "area_km2": d["n"].sum() * res * res / 1e6}
        for rule in rules:
            st = S.state_table(d, rule, new_human)
            rec = recovery_for_state(st, r.threshold)
            row.update({f"{k}_{rule}": v for k, v in rec.items()})
            if rule == S.HEADLINE_RULE:
                traj[r.CODE] = trajectory(st)
        h = rules[0]
        row["restore_km2"] = row[f"restore_share_{h}"] * row["area_km2"]
        rows.append(row)
    rec = pd.DataFrame(rows)
    rec.to_csv(C.TABLES / f"recovery{tag}.csv", index=False)
    pd.DataFrame(traj).to_csv(C.TABLES / f"recovery_trajectories{tag}.csv", index_label="year")
    return rec


def build_split(scorecard: pd.DataFrame, new_human_share: pd.Series | None = None) -> pd.DataFrame:
    """Habitat lost since 2020, split into fire and industry, net of ageing out.

    ``new_fire``   ground newly disturbed by 2021-2025 fire (not disturbed in
                   the official 2020 footprint).
    ``industry``   new human footprint since 2020 (buffered 500 m) outside
                   fire perimeters: from the detector when available
                   (``new_human_share``), otherwise projected from the
                   official 2015->2020 growth (flagged ``industry_source``).
    ``aged_out``   ground returned to undisturbed as 1981-1985 fires aged out.
    """
    sp = scorecard[["CODE", "name", "area_km2", "new_fire", "aged_out",
                    "human_growth_2015_2020"]].copy()
    if new_human_share is None and "new_industry" in scorecard:
        new_human_share = scorecard.set_index("CODE")["new_industry"]
    if new_human_share is not None:
        sp["industry"] = sp["CODE"].map(new_human_share).fillna(0.0)
        sp["industry_source"] = "detector"
    else:
        sp["industry"] = sp["human_growth_2015_2020"]
        sp["industry_source"] = "projected from 2015-2020 official growth"
    sp["lost"] = sp["new_fire"] + sp["industry"]
    sp["fire_share_of_loss"] = np.where(sp["lost"] > 0, sp["new_fire"] / sp["lost"], np.nan)
    sp["net_change"] = sp["aged_out"] - sp["lost"]
    for c in ("new_fire", "industry", "aged_out", "lost"):
        sp[f"{c}_km2"] = sp[c] * sp["area_km2"]
    sp.to_csv(C.TABLES / ("split_det.csv" if sp["industry_source"].iat[0] == "detector"
                          else "split.csv"), index=False)
    return sp
