"""Disturbance rules, written as boolean expressions over a pixel-class table.

A pixel-class table (see :mod:`caribou.pixels`) has one row per unique
combination of footprint flags and last-fire years, with a pixel count
``n``. Every function here returns a boolean Series ("disturbed") aligned
with the table, for an *assessment year* ``year``; the share undisturbed is
then ``1 - n[disturbed].sum() / n.sum()``.

Rules for the update (``year >= 2025``), in the words of the manuscript:

``official_adj``  (headline) Start from the official 2020 total footprint
                  (layer 3). Remove pixels whose only reason for being in it
                  was a CNFDB fire that has aged out of the 40-year window
                  (not under the buffered human footprint, last CNFDB fire
                  older than ``year - 39``). Add NBAC fires of 2021-``year``.
``rebuild_cnfdb`` Rebuild from parts: official buffered human footprint
                  (layer 2) plus every fire in the window, CNFDB to 2020 and
                  NBAC after.
``rebuild_nbac``  Same with NBAC for every year.
``no_ageout``     Official 2020 total plus new fires, nothing ages out
                  (an upper bound on disturbance; not the federal rule).

The human-only rule drops fire entirely.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import config as C

UPDATE_RULES = ("official_adj", "rebuild_cnfdb", "rebuild_nbac", "no_ageout")
HEADLINE_RULE = "official_adj"


def in_window(lastfire: pd.Series, year: int, window: int = C.FIRE_WINDOW_YEARS) -> pd.Series:
    """True where the last fire falls inside the window ending in ``year``."""
    return (lastfire >= C.window_start(year, window)) & (lastfire <= year) & (lastfire > 0)


def human(d: pd.DataFrame, new_human: str | None = None) -> pd.Series:
    h = d["l2"] == 1
    if new_human and new_human in d:
        h = h | (d[new_human] == 1)
    return h


def post_fire(d: pd.DataFrame, year: int) -> pd.Series:
    """Last NBAC fire after the baseline, falling in the window of ``year``."""
    return in_window(d["lf_post"], year) & (d["lf_post"] > C.BASELINE_YEAR)


# ------------------------------------------------------------- reproduction
def official(d: pd.DataFrame, edition: int = 2020) -> pd.Series:
    return d["l3" if edition == 2020 else "l3_15"] == 1


def official_human(d: pd.DataFrame, edition: int = 2020) -> pd.Series:
    return d["l2" if edition == 2020 else "l2_15"] == 1


def rebuild(d: pd.DataFrame, edition: int = 2020, source: str = "cnfdb") -> pd.Series:
    """Buffered human footprint + fires in the window, for a federal edition."""
    h = official_human(d, edition)
    col = {("cnfdb", 2020): "lf_c20", ("cnfdb", 2015): "lf_c15",
           ("nbac", 2020): "lf_n20"}[(source, edition)]
    return h | in_window(d[col], edition)


# ------------------------------------------------------------- update rules
def aged_out(d: pd.DataFrame, year: int) -> pd.Series:
    """Official-total pixels whose only cause was a CNFDB fire now out of window."""
    lf = d["lf_c20"]
    return (d["l3"] == 1) & (d["l2"] == 0) & (lf >= C.window_start(C.BASELINE_YEAR)) \
        & (lf < C.window_start(year))


def unexplained(d: pd.DataFrame) -> pd.Series:
    """Official-total pixels with no human footprint and no CNFDB fire in the
    1981-2020 window: cause unknown to us, so they are never aged out."""
    return (d["l3"] == 1) & (d["l2"] == 0) & ~in_window(d["lf_c20"], C.BASELINE_YEAR)


def disturbed(d: pd.DataFrame, year: int = C.UPDATE_YEAR, rule: str = HEADLINE_RULE,
              new_human: str | None = None, fire: bool = True) -> pd.Series:
    """Disturbed mask in assessment year ``year`` (>= 2020) under ``rule``.

    For years after the last fire season the table knows about, this is the
    "no new fire, no new industry" trajectory used by the recovery clock.
    """
    h = human(d, new_human)
    if not fire:
        return h
    if rule == "official_adj":
        base = (d["l3"] == 1) & ~aged_out(d, year)
        return base | h | post_fire(d, year)
    if rule == "rebuild_cnfdb":
        return h | in_window(d["lf_c20"], year) | post_fire(d, year)
    if rule == "rebuild_nbac":
        return h | in_window(d["lf_n20"], year) | post_fire(d, year)
    if rule == "no_ageout":
        return (d["l3"] == 1) | h | post_fire(d, year)
    raise ValueError(rule)


def share_undisturbed(d: pd.DataFrame, mask: pd.Series) -> float:
    n = d["n"].to_numpy()
    return 1.0 - n[mask.to_numpy()].sum() / n.sum()


def share(d: pd.DataFrame, mask: pd.Series) -> float:
    n = d["n"].to_numpy()
    return n[mask.to_numpy()].sum() / n.sum()


def state_table(d: pd.DataFrame, rule: str = HEADLINE_RULE, new_human: str | None = None,
                year: int = C.UPDATE_YEAR) -> pd.DataFrame:
    """Collapse a pixel table to (permanent, lastfire) -> share of range.

    ``permanent`` marks pixels disturbed for a reason that never ages out on
    its own (human footprint; and, under ``official_adj``/``no_ageout``,
    official-total pixels we cannot attribute to a dated fire).
    ``lastfire`` is the last fire year that still matters (0 = none).
    This is the start state for the recovery clock and the forecast.
    """
    h = human(d, new_human)
    if rule == "official_adj":
        perm = h | unexplained(d)
        lf = np.where(d["lf_post"] > C.BASELINE_YEAR, d["lf_post"],
                      np.where((d["l3"] == 1) & (d["l2"] == 0), d["lf_c20"], 0))
    elif rule == "no_ageout":
        perm = h | (d["l3"] == 1)
        lf = np.where(d["lf_post"] > C.BASELINE_YEAR, d["lf_post"], 0)
    elif rule == "rebuild_cnfdb":
        perm = h
        lf = np.maximum(d["lf_c20"], d["lf_post"])
    elif rule == "rebuild_nbac":
        perm = h
        lf = np.maximum(d["lf_n20"], d["lf_post"])
    else:
        raise ValueError(rule)
    lf = np.where(lf > year, 0, lf)
    st = pd.DataFrame({"permanent": perm.to_numpy().astype(bool), "lastfire": lf.astype(int),
                       "n": d["n"].to_numpy()})
    st = st.groupby(["permanent", "lastfire"], as_index=False)["n"].sum()
    st["share"] = st["n"] / st["n"].sum()
    return st


def state_undisturbed(st: pd.DataFrame, year: int, window: int = C.FIRE_WINDOW_YEARS) -> float:
    """Share undisturbed in ``year`` for a state table, with no new disturbance."""
    fire_on = (st["lastfire"] >= C.window_start(year, window)) & (st["lastfire"] > 0)
    dist = st["permanent"] | fire_on
    return float(1.0 - st.loc[dist, "share"].sum())
