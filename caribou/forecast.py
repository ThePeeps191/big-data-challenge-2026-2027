"""Probability that each range is below its threshold in 2030.

A Monte Carlo simulation, not a trained model. For each range and run:

1. Start from the 2025 state table (share of range by permanent / last fire
   year) under the headline rule.
2. If the detector has not supplied post-2020 human footprint, add it for
   2021-2025 at the range's official 2015->2020 rate (catch-up years).
3. For each year 2026-2030: add new human footprint at that rate times a
   per-run multiplier (uniform 0.5-1.5, for rate uncertainty); then burn a
   share of the range drawn (bootstrap, with replacement) from the range's
   own annual NBAC burned share over a reference period.
4. In 2030, apply the 40-year window (fires before 1991 have aged out) and
   record the undisturbed share.

Assumptions, stated in the manuscript: fires and new footprint land at
random with respect to existing disturbance (recent burns are in reality
less likely to reburn, so this *understates* new loss), and years are
independent (no drought persistence).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import config as C
from . import scenarios as S
from .pixels import load_annual, load_table
from .prepare import read_interim


def annual_burn_shares(code: str, total_px: int, years: tuple[int, int],
                       res: float = C.DEFAULT_RES) -> np.ndarray:
    a = load_annual(code, res).set_index("year")["n"]
    ys = np.arange(years[0], years[1] + 1)
    return a.reindex(ys, fill_value=0).to_numpy() / total_px


def simulate(st: pd.DataFrame, burn_shares: np.ndarray, human_rate: float,
             start: int = C.UPDATE_YEAR, end: int = 2030, catchup_years: int = 0,
             n_runs: int = 20000, rate_spread=(0.5, 1.5), seed: int = 0) -> np.ndarray:
    """Return the simulated undisturbed share in ``end`` for each run."""
    rng = np.random.default_rng(seed)
    npst = st[~st["permanent"]]
    lf = npst["lastfire"].to_numpy()
    base = npst["share"].to_numpy()
    years = list(range(start + 1, end + 1))

    scale = np.ones(n_runs)               # common factor on existing categories
    new = np.zeros((n_runs, len(years)))  # share burned in each simulated year
    mult = rng.uniform(*rate_spread, n_runs)

    def add_human(rate):
        nonlocal scale
        npsh = scale * base.sum() + new.sum(axis=1)
        h = np.minimum(rate, npsh)
        f = np.where(npsh > 0, 1.0 - h / np.where(npsh > 0, npsh, 1), 0.0)
        scale = scale * f
        new[:] *= f[:, None]

    for _ in range(catchup_years):        # 2021-2025 footprint not yet mapped
        add_human(human_rate * mult)
    for j, _y in enumerate(years):
        add_human(human_rate * mult)
        b = rng.choice(burn_shares, n_runs, replace=True)
        npsh = scale * base.sum() + new.sum(axis=1)
        scale = scale * (1 - b)
        new[:] *= (1 - b)[:, None]
        new[:, j] = b * npsh
    ws = C.window_start(end)
    old_ok = (lf == 0) | (lf < ws)
    # every simulated burn is inside the window in `end`
    return scale * base[old_ok].sum()


def build_forecast(res: float = C.DEFAULT_RES, new_human: str | None = None,
                   new_human_rate: pd.Series | None = None,
                   ref_years: tuple[int, int] = (1986, C.UPDATE_YEAR),
                   alt_ref_years: tuple[int, int] = (2011, C.UPDATE_YEAR),
                   end: int = 2030, n_runs: int = 20000, tag: str = "") -> pd.DataFrame:
    ranges = read_interim("ranges", read_geometry=False)
    rows = []
    for i, r in enumerate(ranges.itertuples()):
        d = load_table(r.CODE, res, tag)
        total = int(d["n"].sum())
        st = S.state_table(d, S.HEADLINE_RULE, new_human)
        if new_human_rate is not None:
            rate, catchup = float(new_human_rate.get(r.CODE, 0.0)), 0
        else:
            rate = S.share(d, S.official_human(d) & ~S.official_human(d, 2015)) / 5.0
            catchup = C.UPDATE_YEAR - C.BASELINE_YEAR
        row = {"CODE": r.CODE, "name": r.name, "threshold": r.threshold,
               "undisturbed_2025": S.state_undisturbed(st, C.UPDATE_YEAR),
               "no_new_disturbance_2030": S.state_undisturbed(st, end),
               "human_rate_per_yr": rate}
        for label, yrs in (("", ref_years), ("_recent", alt_ref_years)):
            bs = annual_burn_shares(r.CODE, total, yrs, res)
            u = simulate(st, bs, rate, end=end, catchup_years=catchup, n_runs=n_runs, seed=i)
            row[f"mean_burn_per_yr{label}"] = bs.mean()
            row[f"p_below{label}"] = float((u < r.threshold).mean())
            row[f"median_2030{label}"] = float(np.median(u))
            row[f"p05_2030{label}"] = float(np.quantile(u, 0.05))
            row[f"p95_2030{label}"] = float(np.quantile(u, 0.95))
        rows.append(row)
    fc = pd.DataFrame(rows)
    fc.to_csv(C.TABLES / f"forecast{tag}.csv", index=False)
    return fc
