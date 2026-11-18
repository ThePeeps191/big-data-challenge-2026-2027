"""Apply the detector to 2025 and turn detections into a buffered footprint.

1. ``train_ee`` trains an Earth Engine random forest (cleared vs not) on the
   same label points used for the held-out evaluation, sampled server-side
   at the training year (2020).
2. ``detect_range`` classifies the assessment-year stack (2025) and pulls the
   cleared-probability raster over a range tile by tile (``computePixels``)
   into ``data/interim/detector/prob_<CODE>.tif`` (uint8, 0-255, 30 m,
   Canada Albers).
3. ``postprocess`` (local, no Earth Engine) thresholds the rasters, keeps
   clearings of at least 2 ha (the federal minimum mapping unit), drops any
   that touch a federal 2020 polygon (already mapped) or fall mostly inside a
   2016-2025 fire perimeter (burns, not clearings), and buffers the rest by
   500 m into ``detector_new_buffered.gpkg``: the extra mask the pixel engine
   adds to the scorecard as post-2020 industry.
"""

from __future__ import annotations

import math
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import shapely
from pyproj import CRS
from rasterio.features import shapes
from rasterio.transform import from_origin

from .. import config as C
from ..pixels import sql_quote
from ..prepare import read_interim, write
from . import ee_features as F

DET = C.INTERIM / "detector"


def _points_fc(lab_wgs84: pd.DataFrame):
    ee = F.ee
    return ee.FeatureCollection([
        ee.Feature(ee.Geometry.Point([float(x), float(y)]), {"cleared": int(l == 1)})
        for x, y, l in zip(lab_wgs84["lon"], lab_wgs84["lat"], lab_wgs84["label"])])


def train_ee(lab_wgs84: pd.DataFrame, kind: str = "emb", year: int = 2020,
             n_trees: int = 200, scale: float = 30):
    ee = F.ee
    names = F.feature_names(kind)
    samples = F.stack(kind, year).sampleRegions(collection=_points_fc(lab_wgs84),
                                                properties=["cleared"], scale=scale, tileScale=4)
    clf = (ee.Classifier.smileRandomForest(numberOfTrees=n_trees, minLeafPopulation=2, seed=0)
           .setOutputMode("PROBABILITY")
           .train(features=samples, classProperty="cleared", inputProperties=names))
    return clf


def latest_embedding_year() -> int:
    ee = F.ee
    d = ee.ImageCollection(F.EMBEDDING).aggregate_max("system:time_start").getInfo()
    return int(pd.Timestamp(d, unit="ms").year)


def detect_range(code: str, clf, kind: str = "emb", year: int = C.UPDATE_YEAR,
                 res: float = 30.0, tile: int = 1024) -> Path:
    DET.mkdir(parents=True, exist_ok=True)
    out = DET / f"prob_{code}_{year}.tif"
    if out.exists():
        return out
    rr = read_interim("ranges", where=f"CODE = {sql_quote(code)}")
    geom = rr.geometry.iat[0]
    minx, miny, maxx, maxy = geom.bounds
    x0, y1 = math.floor(minx / res) * res, math.ceil(maxy / res) * res
    W, H = math.ceil((maxx - x0) / res), math.ceil((y1 - miny) / res)
    img = (F.stack(kind, year).classify(clf).multiply(255).toByte()
           .updateMask(F.water_mask().Not()).unmask(0))
    wkt = CRS(C.AREA_CRS).to_wkt()
    shapely.prepare(geom)
    profile = dict(driver="GTiff", width=W, height=H, count=1, dtype="uint8", crs=C.AREA_CRS,
                   transform=from_origin(x0, y1, res, res), compress="deflate", tiled=True,
                   blockxsize=256, blockysize=256, nodata=0)
    tmp = out.with_suffix(".part.tif")
    with rasterio.open(tmp, "w", **profile) as dst:
        tiles = [(r, c) for r in range(0, H, tile) for c in range(0, W, tile)]
        for i, (r, c) in enumerate(tiles):
            h, w = min(tile, H - r), min(tile, W - c)
            tb = shapely.box(x0 + c * res, y1 - (r + h) * res, x0 + (c + w) * res, y1 - r * res)
            if not geom.intersects(tb):
                continue
            arr = F.compute_tile(img, x0 + c * res, y1 - r * res, w, h, res, wkt)
            dst.write(arr.astype(np.uint8), 1, window=rasterio.windows.Window(c, r, w, h))
            if i % 20 == 0:
                print(f"    {code}: tile {i + 1}/{len(tiles)}")
    tmp.replace(out)
    return out


def postprocess(threshold: float, year: int = C.UPDATE_YEAR, min_ha: float = 2.0,
                fire_overlap_max: float = 0.5) -> gpd.GeoDataFrame:
    t8 = int(round(threshold * 255))
    fed = read_interim("fed2020_polygons")
    fed_tree = shapely.STRtree(fed.geometry.values)
    frames = []
    for tif in sorted(DET.glob(f"prob_*_{year}.tif")):
        code = tif.stem.split("_")[1]
        rr = read_interim("ranges", where=f"CODE = {sql_quote(code)}")
        geom = rr.geometry.iat[0]
        with rasterio.open(tif) as src:
            a = src.read(1)
            m = (a >= t8).astype(np.uint8)
            polys = [shapely.geometry.shape(g) for g, v in shapes(m, mask=m.astype(bool),
                                                                   transform=src.transform) if v == 1]
        if not polys:
            continue
        g = gpd.GeoDataFrame({"CODE": code}, geometry=polys, crs=C.AREA_CRS)
        g = g[g.area >= min_ha * 1e4]
        g = g[g.intersects(geom)]
        if not len(g):
            continue
        hit = np.zeros(len(g), bool)
        hit[np.unique(fed_tree.query(g.geometry.values, predicate="intersects")[0])] = True
        g = g[~hit]
        fires = read_interim("fires_nbac", bbox=tuple(geom.bounds))
        fires = fires[(fires["YEAR"] >= 2016) & (fires["YEAR"] <= year)]
        if len(fires) and len(g):
            burn = shapely.union_all(fires.geometry.values)
            frac = shapely.area(shapely.intersection(g.geometry.values, burn)) / g.area.to_numpy()
            g = g[frac <= fire_overlap_max]
        g["area_ha"] = g.area / 1e4
        g["mean_prob"] = np.nan
        frames.append(g)
        print(f"  {code}: {len(g)} new clearings, {g['area_ha'].sum():,.0f} ha")
    new = gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), crs=C.AREA_CRS)
    new["year"] = year
    write(new, "detector_new")
    buf = new.copy()
    buf["geometry"] = new.buffer(C.BUFFER_M)
    write(buf, "detector_new_buffered")
    return new
