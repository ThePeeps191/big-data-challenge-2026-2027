"""Rasterize every input once per range into a *pixel-class table*.

Each in-range pixel gets a key made of

* bit flags   ``l2``     official 2020 buffered human footprint (layer 2)
              ``l3``     official 2020 total footprint (layer 3)
              ``l2_15``  official 2015 buffered human footprint
              ``l3_15``  official 2015 total footprint
              ``x*``     optional extra masks (e.g. detector clearings)
* last-fire years (0 = no fire on record in that source and period)
              ``lf_c20``  last CNFDB fire up to 2020
              ``lf_c15``  last CNFDB fire up to 2015
              ``lf_n20``  last NBAC fire up to 2020
              ``lf_post`` last NBAC fire 2021-2025

Counting pixels per unique key gives a table of a few thousand rows per
range. Because only the *last* fire matters for a 40-year window, every
scenario in the project (official 2020, 2025 variants, human-only rule,
recovery clock, forecast start state) is an aggregation over this table:
no re-rasterizing.

Pixels are assigned by centre (``all_touched=False``) on a grid snapped to
multiples of the resolution in Canada Albers Equal Area, so pixel area is
exactly ``res**2``. Tiles keep memory bounded at any resolution.
"""

from __future__ import annotations

import math
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
import shapely
from rasterio.enums import MergeAlg
from rasterio.features import rasterize
from rasterio.transform import from_origin

from . import config as C
from .prepare import read_interim

BIT_LAYERS = [
    ("l2", "fed2020_buffered"),
    ("l3", "fed2020_total"),
    ("l2_15", "fed2015_buffered"),
    ("l3_15", "fed2015_total"),
]
# (column, source, first year, last year)
YEAR_LAYERS = [
    ("lf_c20", "fires_cnfdb", None, 2020),
    ("lf_c15", "fires_cnfdb", None, 2015),
    ("lf_n20", "fires_nbac", None, 2020),
    ("lf_post", "fires_nbac", 2021, C.UPDATE_YEAR),
]
MAX_EXTRA = 4


def sql_quote(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def table_path(code: str, res: float, tag: str = "") -> Path:
    d = C.INTERIM / "pixels"
    d.mkdir(exist_ok=True)
    return d / f"{code}_{int(res)}m{tag}.csv"


def annual_path(code: str, res: float) -> Path:
    d = C.INTERIM / "annual"
    d.mkdir(exist_ok=True)
    return d / f"{code}_{int(res)}m.csv"


@dataclass
class Layer:
    """Polygons with an STRtree, ready to be burned into tiles."""

    geoms: np.ndarray
    values: np.ndarray
    tree: shapely.STRtree = field(init=False)

    def __post_init__(self):
        self.tree = shapely.STRtree(self.geoms)

    @classmethod
    def from_gdf(cls, gdf, values=None, sort_by=None):
        if sort_by is not None:  # burn order matters for 'replace': oldest first
            gdf = gdf.sort_values(sort_by, kind="stable")
        geoms = gdf.geometry.values.to_numpy() if hasattr(gdf.geometry.values, "to_numpy") \
            else np.asarray(gdf.geometry.values)
        vals = np.ones(len(gdf), dtype=np.uint8) if values is None else np.asarray(values(gdf))
        return cls(np.asarray(geoms, dtype=object), vals)

    def burn(self, bounds, shape, transform, res) -> np.ndarray:
        out = np.zeros(shape, dtype=np.uint8)
        if len(self.geoms) == 0:
            return out
        idx = self.tree.query(shapely.box(*bounds))
        if len(idx) == 0:
            return out
        idx.sort()  # keep original (year-sorted) burn order
        pad = 2 * res
        g = shapely.clip_by_rect(self.geoms[idx], bounds[0] - pad, bounds[1] - pad,
                                 bounds[2] + pad, bounds[3] + pad)
        keep = ~(shapely.is_empty(g) | shapely.is_missing(g))
        if not keep.any():
            return out
        return rasterize(zip(g[keep], self.values[idx][keep].tolist()), out_shape=shape,
                         transform=transform, fill=0, all_touched=False,
                         merge_alg=MergeAlg.replace, dtype=np.uint8)


def _year_code(gdf):
    return (gdf["YEAR"].astype(int) - C.YEAR0).astype(np.uint8)


def load_range_layers(code: str, extras: dict[str, str] | None = None):
    """Read everything that touches one range (bbox / HERD filtered reads)."""
    rng = read_interim("ranges", where=f"CODE = {sql_quote(code)}")
    assert len(rng) == 1, code
    herd = rng["HERD"].iat[0]
    geom = rng.geometry.iat[0]
    bbox = tuple(geom.bounds)

    layers: dict[str, Layer] = {}
    parts = shapely.get_parts(geom)
    layers["inr"] = Layer(np.asarray(parts, dtype=object), np.ones(len(parts), np.uint8))
    for col, src in BIT_LAYERS:
        g = read_interim(src, where=f"HERD = {sql_quote(herd)}")
        layers[col] = Layer.from_gdf(g)
    fires = {s: read_interim(s, bbox=bbox) for s in {y[1] for y in YEAR_LAYERS}}
    for col, src, y0, y1 in YEAR_LAYERS:
        g = fires[src]
        sel = (g["YEAR"] <= y1) & (g["YEAR"] >= (y0 or 0))
        layers[col] = Layer.from_gdf(g[sel], values=_year_code, sort_by="YEAR")
    annual = {int(y): Layer.from_gdf(g) for y, g in fires["fires_nbac"].groupby("YEAR")}
    xl = {}
    for i, (name, src) in enumerate((extras or {}).items()):
        assert i < MAX_EXTRA
        xl[name] = Layer.from_gdf(read_interim(src, bbox=bbox))
    return herd, geom, layers, annual, xl


def range_pixel_table(code: str, res: float = C.DEFAULT_RES, tile_px: int = C.TILE_PX,
                      extras: dict[str, str] | None = None, verbose: bool = True):
    """Return (pixel-class table, annual NBAC burned pixels) for one range."""
    t0 = time.time()
    herd, geom, layers, annual, xl = load_range_layers(code, extras)
    minx, miny, maxx, maxy = geom.bounds
    x0 = math.floor(minx / res) * res
    y1 = math.ceil(maxy / res) * res
    W = math.ceil((maxx - x0) / res)
    H = math.ceil((y1 - miny) / res)

    keys, counts = [], []
    annual_px: dict[int, int] = {}
    n_tiles = 0
    for r0 in range(0, H, tile_px):
        for c0 in range(0, W, tile_px):
            th, tw = min(tile_px, H - r0), min(tile_px, W - c0)
            tx0, ty1 = x0 + c0 * res, y1 - r0 * res
            bounds = (tx0, ty1 - th * res, tx0 + tw * res, ty1)
            tr = from_origin(tx0, ty1, res, res)
            shape = (th, tw)
            inr = layers["inr"].burn(bounds, shape, tr, res).astype(bool)
            if not inr.any():
                continue
            n_tiles += 1
            k = np.zeros(int(inr.sum()), dtype=np.uint64)
            for bit, (col, _) in enumerate(BIT_LAYERS):
                k |= layers[col].burn(bounds, shape, tr, res)[inr].astype(np.uint64) << np.uint64(bit)
            for j, name in enumerate(xl):
                k |= xl[name].burn(bounds, shape, tr, res)[inr].astype(np.uint64) << np.uint64(4 + j)
            for j, (col, *_rest) in enumerate(YEAR_LAYERS):
                k |= layers[col].burn(bounds, shape, tr, res)[inr].astype(np.uint64) << np.uint64(8 * (j + 1))
            u, n = np.unique(k, return_counts=True)
            keys.append(u)
            counts.append(n)
            for y, lyr in annual.items():
                m = lyr.burn(bounds, shape, tr, res)
                c = int(m[inr].sum()) if m.any() else 0
                if c:
                    annual_px[y] = annual_px.get(y, 0) + c

    k = np.concatenate(keys)
    n = np.concatenate(counts)
    u, inv = np.unique(k, return_inverse=True)
    n = np.bincount(inv, weights=n).astype(np.int64)
    df = decode_keys(u, list(xl))
    df["n"] = n
    ann = pd.DataFrame(sorted(annual_px.items()), columns=["year", "n"])
    if verbose:
        print(f"  {code:5s} {herd[:28]:28s} {W}x{H}px {n_tiles} tiles "
              f"{df['n'].sum() * res * res / 1e6:10,.0f} km2  {time.time() - t0:6.1f}s", flush=True)
    return df, ann


def decode_keys(u: np.ndarray, extra_names: list[str]) -> pd.DataFrame:
    df = pd.DataFrame()
    for bit, (col, _) in enumerate(BIT_LAYERS):
        df[col] = ((u >> np.uint64(bit)) & np.uint64(1)).astype(np.uint8)
    for j, name in enumerate(extra_names):
        df[name] = ((u >> np.uint64(4 + j)) & np.uint64(1)).astype(np.uint8)
    for j, (col, *_rest) in enumerate(YEAR_LAYERS):
        y = ((u >> np.uint64(8 * (j + 1))) & np.uint64(255)).astype(np.int32)
        df[col] = np.where(y > 0, y + C.YEAR0, 0).astype(np.int32)
    return df


# ---------------------------------------------------------------- driver
def _job(code, res, tile_px, extras, tag):
    df, ann = range_pixel_table(code, res, tile_px, extras)
    df.to_csv(table_path(code, res, tag), index=False)
    if not tag:
        ann.to_csv(annual_path(code, res), index=False)
    return code


def build_all(res: float = C.DEFAULT_RES, workers: int = 6, codes: list[str] | None = None,
              tile_px: int = C.TILE_PX, extras: dict[str, str] | None = None, tag: str = "",
              overwrite: bool = False) -> None:
    ranges = read_interim("ranges", read_geometry=False)
    # largest first so the long jobs start early
    order = ranges.sort_values("area_km2", ascending=False)["CODE"].tolist()
    codes = [c for c in order if codes is None or c in codes]
    if not overwrite:
        codes = [c for c in codes if not table_path(c, res, tag).exists()]
    print(f"[pixels] {len(codes)} ranges at {res:g} m with {workers} workers")
    if workers <= 1:
        for c in codes:
            _job(c, res, tile_px, extras, tag)
        return
    with ProcessPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(_job, c, res, tile_px, extras, tag) for c in codes]
        for f in as_completed(futs):
            f.result()


def load_table(code: str, res: float = C.DEFAULT_RES, tag: str = "") -> pd.DataFrame:
    return pd.read_csv(table_path(code, res, tag))


def load_annual(code: str, res: float = C.DEFAULT_RES) -> pd.DataFrame:
    return pd.read_csv(annual_path(code, res))
