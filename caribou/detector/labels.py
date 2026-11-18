"""Training labels for the new-disturbance detector, sampled locally.

Three classes, sampled as points so they can be sent to Earth Engine cheaply:

* ``1 cleared``  inside federal polygonal disturbances with ``Year_added = 2020``
                 (cutblocks, harvest, well sites, mines, ...: visible on 2020
                 imagery, absent in 2015), shrunk by one Landsat pixel so
                 points sit inside the clearing.
* ``2 burned``   inside NBAC perimeters of 2016-2020 and outside the official
                 buffered human footprint.
* ``0 intact``   inside the range, outside the official buffered human
                 footprint, and in no fire since 1981 (CNFDB or NBAC).

Each point carries its range ``CODE`` (for held-out-range validation) and,
for cleared points, the id of its source polygon (for polygon-level
detection rates).
"""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely

from .. import config as C
from ..pixels import sql_quote
from ..prepare import read_interim

CLEARED_CLASSES = ("Cutblock", "Harvest", "Well site", "Mine", "Oil/Gas", "Settlement",
                   "Agriculture", "Unknown")
LABELS = {0: "intact", 1: "cleared", 2: "burned"}


def sample_in(geoms: np.ndarray, n: int, rng: np.random.Generator,
              weights: np.ndarray | None = None, max_iter: int = 50) -> tuple[np.ndarray, np.ndarray]:
    """Uniform random points inside polygons; returns (points, index of polygon).

    Polygons are chosen with probability proportional to area (or ``weights``),
    then points are drawn in each polygon's bounding box by rejection.
    """
    geoms = np.asarray(geoms, dtype=object)
    area = shapely.area(geoms) if len(geoms) else np.array([])
    keep = area > 0                       # drop line/point slivers from overlays
    orig = np.flatnonzero(keep)           # map back to the caller's indices
    geoms = geoms[keep]
    if weights is not None:
        weights = np.asarray(weights, float)[keep]
    if len(geoms) == 0 or n == 0:
        return np.array([], dtype=object), np.array([], dtype=int)
    w = area[keep] if weights is None else weights
    w = w / w.sum()
    pick = rng.choice(len(geoms), size=n, p=w)
    pts = np.empty(n, dtype=object)
    todo = np.arange(n)
    shapely.prepare(geoms)
    b = shapely.bounds(geoms)
    for _ in range(max_iter):
        if len(todo) == 0:
            break
        gi = pick[todo]
        x = rng.uniform(b[gi, 0], b[gi, 2])
        y = rng.uniform(b[gi, 1], b[gi, 3])
        cand = shapely.points(x, y)
        ok = shapely.contains_xy(geoms[gi], x, y) if hasattr(shapely, "contains_xy") \
            else shapely.contains(geoms[gi], cand)
        pts[todo[ok]] = cand[ok]
        todo = todo[~ok]
    ok = np.array([p is not None for p in pts])
    return pts[ok], orig[pick[ok]]


def range_labels(code: str, n_per_class: int = 300, seed: int = 0) -> gpd.GeoDataFrame:
    rng = np.random.default_rng(seed)
    rr = read_interim("ranges", where=f"CODE = {sql_quote(code)}")
    herd, geom = rr["HERD"].iat[0], rr.geometry.iat[0]
    bbox = tuple(geom.bounds)
    human = shapely.union_all(read_interim("fed2020_buffered",
                                           where=f"HERD = {sql_quote(herd)}").geometry.values)
    frames = []

    # cleared: polygons first identified in 2020
    pol = read_interim("fed2020_polygons", bbox=bbox)
    pol = pol[(pol["Year_added"] == 2020) & pol["Class"].isin(CLEARED_CLASSES)].copy()
    pol["poly_id"] = pol.index.astype(int)
    pol["geometry"] = pol.buffer(-30)
    pol = pol[~pol.is_empty & pol.intersects(geom)]
    if len(pol):
        p, i = sample_in(pol.geometry.values, n_per_class, rng)
        frames.append(gpd.GeoDataFrame({"geometry": p, "label": 1, "poly_id": pol["poly_id"].to_numpy()[i],
                                        "Class": pol["Class"].to_numpy()[i]}, crs=C.AREA_CRS))

    # burned: NBAC 2016-2020, outside the human footprint
    nb = read_interim("fires_nbac", bbox=bbox)
    fires_recent = nb[(nb["YEAR"] >= 2016) & (nb["YEAR"] <= 2020)]
    if len(fires_recent):
        burn = shapely.intersection(shapely.union_all(fires_recent.geometry.values), geom)
        burn = shapely.difference(burn, human)
        parts = shapely.get_parts(burn)
        if len(parts):
            p, _ = sample_in(parts, n_per_class, rng)
            frames.append(gpd.GeoDataFrame({"geometry": p, "label": 2, "poly_id": -1, "Class": "Burn"},
                                           crs=C.AREA_CRS))

    # intact: no human footprint within 500 m, no fire since 1981
    cn = read_interim("fires_cnfdb", bbox=bbox)
    old = pd.concat([cn[cn["YEAR"] >= 1981].geometry, nb[nb["YEAR"] >= 1981].geometry])
    p, _ = sample_in(shapely.get_parts(geom), n_per_class * 4, rng)
    if len(p):
        ok = ~shapely.intersects(p, human)
        if len(old):
            tree = shapely.STRtree(old.values)
            hit = np.zeros(len(p), bool)
            hit[np.unique(tree.query(p, predicate="intersects")[0])] = True
            ok &= ~hit
        p = p[ok][:n_per_class]
        frames.append(gpd.GeoDataFrame({"geometry": p, "label": 0, "poly_id": -1, "Class": "Intact"},
                                       crs=C.AREA_CRS))
    out = pd.concat(frames, ignore_index=True)
    out["CODE"] = code
    return gpd.GeoDataFrame(out, crs=C.AREA_CRS)


def build_labels(codes: list[str] | None = None, n_per_class: int = 300, seed: int = 0,
                 min_cleared_polygons: int = 20) -> gpd.GeoDataFrame:
    """Labels for every range that has enough 2020 clearings to learn from."""
    ranges = read_interim("ranges", read_geometry=False)
    codes = codes or ranges["CODE"].tolist()
    pol = read_interim("fed2020_polygons", read_geometry=False)
    n2020 = pol[pol["Year_added"] == 2020].groupby("HERD").size()
    herd_of = dict(zip(ranges["CODE"], ranges["HERD"]))
    frames = []
    for i, c in enumerate(codes):
        if n2020.get(herd_of[c], 0) < min_cleared_polygons:
            continue
        frames.append(range_labels(c, n_per_class, seed + i))
        print(f"  labels {c}: {frames[-1]['label'].value_counts().to_dict()}")
    lab = gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), crs=C.AREA_CRS)
    lab["pid"] = np.arange(len(lab))
    out = C.INTERIM / "detector"
    out.mkdir(exist_ok=True)
    lab.to_file(out / "labels.gpkg", driver="GPKG", engine="pyogrio")
    return lab
