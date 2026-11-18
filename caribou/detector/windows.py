"""The detector on open data, in a random sample of windows (no Earth Engine account).

Google's Satellite Embedding V1 annual layers (AlphaEarth Foundations) are also
published as Cloud-Optimized GeoTIFFs on Source Cooperative, CC-BY 4.0:
"The AlphaEarth Foundations Satellite Embedding dataset is produced by Google
and Google DeepMind." Reading them wall-to-wall over 2.4 million km² of range is
not practical on a laptop (about 15 MB per 10 km block per year), so the
detector is trained and tested in a **seeded random sample of windows**.

Window
    One internal block of an embedding tile: 1024 x 1024 pixels at 10 m
    (10.24 km square, 105 km²) in the tile's UTM grid. The COGs are stored
    bottom-up (positive y pixel size; Source Cooperative README). Blocks are
    read from the .tiff and flipped north-up; the orientation was checked by
    overlaying federal 2020 cutblocks on 2017->2020 embedding change.

Population and draw (fixed before any result was seen)
    Blocks lying wholly inside one range, counted only in the UTM zone that
    holds their centre (neighbouring zones' tiles overlap), and holding at least
    ``MIN_POLYGONS`` federal polygons first mapped in 2020: the landscapes
    where new clearing happens, and where the detector can be tested. Drawn
    at random (seed ``SEED``), ``N_PER_PROVINCE`` per province, plus the blocks
    covering the IDEA's Quebec pilot window. A burn stratum adds one block per
    province at least 20% burned in 2016-2020 (seed ``SEED + 1``): fresh burns
    are the main look-alike of a clearing, and the industrial windows hold few.
    Burn blocks are used for training and false alarms, not for application.

Features at assessment year Y (as in the Earth Engine design, plus one)
    emb(Y) (64), emb(Y) - emb(Y-3) (64) and the cosine change
    1 - emb(Y)·emb(Y-3). Values are de-quantized as Google documents:
    (x / 127.5)² · sign(x), then renormalized to unit length.

Labels at Y = 2020 (pixel level, window grid)
    1 cleared  inside a federal polygon first mapped in 2020 (cutblocks,
               well sites, mines, ...), eroded by one pixel;
    2 burned   NBAC fire 2016-2020, outside the 2020 buffered footprint;
    0 intact   outside the 2020 buffered footprint, no fire since 1981.

Evaluation (held-out ranges, ``GroupKFold`` by range as in ``train.py``)
    pixel AUC / average precision / recall at a 1% false-alarm rate on a
    class-balanced sample; then, wall-to-wall in each held-out window,
    post-processed detections (>= 2 ha, the federal minimum mapping unit):
    share of 2020 polygons hit, detections that match no federal polygon and
    no fire ("unconfirmed"), and the 500 m-buffered footprint they imply
    against the official 2015->2020 growth.

Independent check (not used in training)
    NRCan's CA Forest Harvest 1985-2022 (Landsat, 30 m, year of harvest;
    Hermosilla et al. 2016): how many unconfirmed 2020 detections are mapped
    harvests the federal footprint lacks; how many 2021-2022 harvest patches
    the 2020-2025 detections find (recall); what share of new 2020-2023
    detections fall on a 2020-2022 harvest (a floor on precision, since
    2023 harvests are real but not in the layer).

Baseline without AI
    dNBR = NBR(2017) - NBR(2020) from Sentinel-2 L2A summer medians
    (Planetary Computer), scored with the same samples and post-processing.

Application
    The out-of-fold model of each window at Y = 2023 (change 2020->2023) and
    Y = 2025 (2022->2025), the same 3-year lag as training. Detections that
    touch no federal polygon, lie mostly outside 2016-2025 fires and were not
    already "unconfirmed" in 2020 are new clearings since 2020. Their 500 m
    buffer outside the 2020 footprint is compared with the official
    2015->2020 growth in the same window, and with the 2020 false-new rate as
    a noise floor. Window results test whether industry kept its 2015-2020
    pace in sampled industrial landscapes; they are **not** per-range
    estimates and are not fed into the national scorecard.

    python -m caribou.detector.windows select download labels samples run dnbr baseline
"""

from __future__ import annotations

import argparse
import json
import math
import time
from concurrent.futures import ThreadPoolExecutor

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import shapely
from pyproj import Transformer
from rasterio.features import rasterize
from rasterio.transform import Affine
from scipy import ndimage
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.model_selection import GroupKFold

from .. import config as C
from ..fetch import _download
from ..prepare import read_interim
from .labels import CLEARED_CLASSES
from .train import make_model, threshold_at_fpr

AEF_INDEX_URL = "https://data.source.coop/tge-labs/aef/v1/annual/aef_index.parquet"
S3_PREFIX, HTTP_BASE = "s3://us-west-2.opendata.source.coop/", "https://data.source.coop/"
BLOCK, RES, LAG = 1024, 10.0, 3
TRAIN_YEAR, APPLY_YEARS = C.BASELINE_YEAR, (2023, C.UPDATE_YEAR)
YEARS = sorted({TRAIN_YEAR, TRAIN_YEAR - LAG, *APPLY_YEARS, *(y - LAG for y in APPLY_YEARS)})
MIN_POLYGONS, N_PER_PROVINCE, SEED = 10, 3, 2026
PILOT_WGS84 = (-76.2, 49.62, -75.8, 49.88)       # IDEA.md Quebec pilot window
PILOT_MIN_OVERLAP = 0.5
BURN_MIN_SHARE = 0.2                              # burn-stratum blocks: >= 20% burned 2016-2020
SAMPLES_PER_CLASS = 4000                         # per window, for training / pixel metrics
MIN_PX = int(2e4 / RES**2)                       # 2 ha
BUFFER_PX = int(C.BUFFER_M / RES)
FPR = 0.01

RAW = C.RAW / "aef"
DET = C.INTERIM / "detector" / "windows"
EMB_NAMES = [f"A{i:02d}" for i in range(64)]
FEATURES = {"embedding_rf": EMB_NAMES + [f"d{b}" for b in EMB_NAMES] + ["cos_change"],
            "cos_change_only": ["cos_change"],
            # added after the first two were run: the full model also sees what a pixel
            # looks like now, so old clearings and regrowing burns read as "cleared";
            # change features alone ask "did this pixel change in the last 3 years?"
            "embedding_change_rf": [f"d{b}" for b in EMB_NAMES] + ["cos_change"]}


# ---------------------------------------------------------------- index and windows
def aef_index() -> pd.DataFrame:
    """Embedding tile index (path, year, UTM bounds), cut to the ranges' extent."""
    small = RAW / "aef_index_ranges.parquet"
    if small.exists():
        return pd.read_parquet(small)
    full = _download(AEF_INDEX_URL, RAW / "aef_index.parquet")
    cols = ["path", "year", "crs", "utm_west", "utm_south", "utm_east", "utm_north",
            "wgs84_west", "wgs84_south", "wgs84_east", "wgs84_north"]
    idx = pd.read_parquet(full, columns=cols)
    rng = read_interim("ranges").to_crs("EPSG:4326").total_bounds
    idx = idx[(idx["wgs84_east"] > rng[0]) & (idx["wgs84_west"] < rng[2])
              & (idx["wgs84_north"] > rng[1]) & (idx["wgs84_south"] < rng[3])].reset_index(drop=True)
    idx.to_parquet(small)
    return idx


def candidate_blocks() -> gpd.GeoDataFrame:
    """Every embedding block wholly inside one range, with its count of
    federal polygons first mapped in 2020."""
    idx = aef_index()
    t20 = idx[idx["year"] == TRAIN_YEAR]
    ranges = read_interim("ranges")
    pol = read_interim("fed2020_polygons")
    pol = pol[(pol["Year_added"] == 2020) & pol["Class"].isin(CLEARED_CLASSES)]
    cent = pol.geometry.representative_point()
    out = []
    size = BLOCK * RES
    for crs, tiles in t20.groupby("crs"):
        r_utm = ranges.to_crs(crs)
        pts = gpd.GeoSeries(cent, crs=C.AREA_CRS).to_crs(crs).values
        ptree = shapely.STRtree(np.asarray(pts, dtype=object))
        bx, rows = [], []
        for t in tiles.itertuples():
            nbx = int(math.floor((t.utm_east - t.utm_west) / size + 1e-9))
            nby = int(math.floor((t.utm_north - t.utm_south) / size + 1e-9))
            for bc in range(nbx):
                for br in range(nby):
                    x0, y0 = t.utm_west + bc * size, t.utm_south + br * size
                    bx.append(shapely.box(x0, y0, x0 + size, y0 + size))
                    rows.append((crs, t.utm_west, t.utm_south, bc, br, x0, y0))
        bx = np.asarray(bx, dtype=object)
        # tiles of neighbouring UTM zones overlap: keep a block only in the zone
        # whose 6-degree band holds its centre, so no ground is counted twice
        zone = int(crs.split(":")[1]) % 100
        cx, cy = shapely.get_coordinates(shapely.centroid(bx)).T
        lon, _ = Transformer.from_crs(crs, "EPSG:4326", always_xy=True).transform(cx, cy)
        native = (lon >= -180 + 6 * (zone - 1)) & (lon < -180 + 6 * zone)
        code = np.full(len(bx), "", dtype=object)
        for r in r_utm.itertuples():
            shapely.prepare(r.geometry)
            code[shapely.contains(r.geometry, bx)] = r.CODE
        keep = (code != "") & native
        if not keep.any():
            continue
        q_blocks, q_pts = ptree.query(bx[keep], predicate="contains")
        n = np.bincount(q_blocks, minlength=int(keep.sum()))
        df = pd.DataFrame([rows[i] for i in np.flatnonzero(keep)],
                          columns=["crs", "utm_west", "utm_south", "bc", "br", "x0", "y0"])
        df["CODE"], df["n2020"] = code[keep], n
        g = gpd.GeoDataFrame(df, geometry=list(bx[keep]), crs=crs).to_crs(C.AREA_CRS)
        out.append(g)
    cand = gpd.GeoDataFrame(pd.concat(out, ignore_index=True), crs=C.AREA_CRS)
    cand["prov"] = cand["CODE"].str.rstrip("0123456789")
    # share of each block burned 2016-2020 (NBAC), for the burn stratum
    nb = read_interim("fires_nbac")
    nb = nb[(nb["YEAR"] >= 2016) & (nb["YEAR"] <= TRAIN_YEAR)]
    ftree = shapely.STRtree(nb.geometry.values)
    bi, fi = ftree.query(cand.geometry.values, predicate="intersects")
    burned = np.zeros(len(cand))
    for b in np.unique(bi):
        u = shapely.union_all(nb.geometry.values[fi[bi == b]])
        burned[b] = shapely.intersection(u, cand.geometry.values[b]).area
    cand["burned_16_20"] = burned / cand.area.to_numpy()
    cand["wid"] = [f"{r.CODE}_{r.crs.split(':')[1]}_{int(r.x0)}_{int(r.y0)}" for r in cand.itertuples()]
    return cand


def select_windows(seed: int = SEED) -> gpd.GeoDataFrame:
    cand = candidate_blocks()
    pool = cand[cand["n2020"] >= MIN_POLYGONS]
    rng = np.random.default_rng(seed)
    picks = []
    for p in sorted(pool["prov"].unique()):
        sub = pool[pool["prov"] == p]
        k = min(N_PER_PROVINCE, len(sub))
        picks.append(sub.iloc[np.sort(rng.choice(len(sub), k, replace=False))].assign(kind="random"))
    # burn stratum: fresh burns are the main look-alike of a clearing, and the
    # industrial windows hold few; one block per province, at least
    # BURN_MIN_SHARE burned 2016-2020, used for training and false alarms only
    rng_b = np.random.default_rng(seed + 1)
    taken = set(pd.concat(picks)["wid"])
    bpool = cand[(cand["burned_16_20"] >= BURN_MIN_SHARE) & ~cand["wid"].isin(taken)]
    for p in sorted(bpool["prov"].unique()):
        sub = bpool[bpool["prov"] == p]
        picks.append(sub.iloc[[int(rng_b.integers(len(sub)))]].assign(kind="burn"))
    # the IDEA's Quebec pilot: blocks covering at least half of their area inside the window
    tf = Transformer.from_crs("EPSG:4326", C.AREA_CRS, always_xy=True)
    xs, ys = tf.transform([PILOT_WGS84[0], PILOT_WGS84[2], PILOT_WGS84[0], PILOT_WGS84[2]],
                          [PILOT_WGS84[1], PILOT_WGS84[1], PILOT_WGS84[3], PILOT_WGS84[3]])
    pilot = shapely.Polygon([(xs[0], ys[0]), (xs[1], ys[1]), (xs[3], ys[3]), (xs[2], ys[2])])
    ov = shapely.area(shapely.intersection(cand.geometry.values, pilot)) / cand.area.to_numpy()
    pil = cand[(ov >= PILOT_MIN_OVERLAP)].assign(kind="pilot")
    win = pd.concat([*picks, pil], ignore_index=True).drop_duplicates("wid", keep="last")
    win = gpd.GeoDataFrame(win, crs=C.AREA_CRS).reset_index(drop=True)
    DET.mkdir(parents=True, exist_ok=True)
    win.to_file(DET / "windows.gpkg", driver="GPKG", engine="pyogrio")
    summary = pool.groupby("prov").size().rename("population").to_frame()
    summary["candidates_all"] = cand.groupby("prov").size()
    summary["drawn"] = win[win["kind"] == "random"].groupby("prov").size()
    summary["burn_pool"] = cand[cand["burned_16_20"] >= BURN_MIN_SHARE].groupby("prov").size()
    summary["burn_drawn"] = win[win["kind"] == "burn"].groupby("prov").size()
    summary.to_csv(C.TABLES / "detector_windows_population.csv")
    print(summary.to_string())
    print(win[["wid", "CODE", "kind", "n2020"]].to_string(index=False))
    return win


def load_windows() -> gpd.GeoDataFrame:
    return gpd.read_file(DET / "windows.gpkg", engine="pyogrio")


# ---------------------------------------------------------------- embeddings
def _tile_url(idx: pd.DataFrame, w, year: int) -> str:
    t = idx[(idx["year"] == year) & (idx["crs"] == w.crs) & (idx["utm_west"] == w.utm_west)
            & (idx["utm_south"] == w.utm_south)]
    if len(t) != 1:
        raise LookupError(f"{w.wid}: {len(t)} tiles for {year}")
    return "/vsicurl/" + t["path"].iat[0].replace(S3_PREFIX, HTTP_BASE)


def block_path(wid: str, year: int):
    return DET / "emb" / f"{wid}_{year}.npy"


def download_block(w, year: int, idx: pd.DataFrame) -> str:
    out = block_path(w.wid, year)
    if out.exists():
        return str(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    url = _tile_url(idx, w, year)
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", GDAL_HTTP_MAX_RETRY="5",
                      GDAL_HTTP_RETRY_DELAY="3"):
        with rasterio.open(url) as s:
            # bottom-up COG: origin at the south-west corner, positive y pixel size
            assert s.transform.e > 0 and s.transform.c == w.utm_west and s.transform.f == w.utm_south
            a = s.read(window=rasterio.windows.Window(int(w.bc) * BLOCK, int(w.br) * BLOCK,
                                                      BLOCK, BLOCK))
    a = np.ascontiguousarray(a[:, ::-1, :])        # north-up
    tmp = out.with_suffix(".tmp.npy")
    np.save(tmp, a)
    tmp.replace(out)
    return str(out)


def download_all(workers: int = 6) -> None:
    win, idx = load_windows(), aef_index()
    jobs = [(w, y) for w in win.itertuples()
            for y in (YEARS if w.kind != "burn" else (TRAIN_YEAR - LAG, TRAIN_YEAR))]
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for i, _ in enumerate(ex.map(lambda j: download_block(j[0], j[1], idx), jobs), 1):
            if i % 10 == 0 or i == len(jobs):
                print(f"  embeddings {i}/{len(jobs)} ({time.time() - t0:.0f}s)", flush=True)


def dequantize(a: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """int8 -> unit vectors (64, H, W); returns (values, valid mask)."""
    valid = a[0] != -128
    v = a.astype(np.float32) / 127.5
    v = v * np.abs(v)                               # (x/127.5)^2 * sign(x)
    v /= np.maximum(np.linalg.norm(v, axis=0, keepdims=True), 1e-6)
    v[:, ~valid] = 0.0
    return v, valid


def features(wid: str, year: int) -> tuple[np.ndarray, np.ndarray]:
    """(129, H, W) float32 feature stack and its valid mask."""
    e1, v1 = dequantize(np.load(block_path(wid, year)))
    e0, v0 = dequantize(np.load(block_path(wid, year - LAG)))
    cos = (e1 * e0).sum(axis=0)
    f = np.concatenate([e1, e1 - e0, (1.0 - cos)[None]], axis=0)
    return f, v1 & v0


# ---------------------------------------------------------------- labels
def window_transform(w) -> Affine:
    return Affine(RES, 0, w.x0, 0, -RES, w.y0 + BLOCK * RES)


def _burn(geoms, w, all_touched=False, values=None, dtype="uint8") -> np.ndarray:
    geoms = [g for g in geoms if g is not None and not g.is_empty]
    if not geoms:
        return np.zeros((BLOCK, BLOCK), dtype=dtype)
    shapes = zip(geoms, values if values is not None else [1] * len(geoms))
    return rasterize(shapes, out_shape=(BLOCK, BLOCK), transform=window_transform(w), fill=0,
                     all_touched=all_touched, dtype=dtype)


def window_layers(w) -> dict[str, np.ndarray]:
    """Reference rasters for one window, in its UTM grid."""
    pad = 2 * C.BUFFER_M
    bb = tuple(np.add(shapely.bounds(w.geometry), (-pad, -pad, pad, pad)))
    get = lambda name: read_interim(name, bbox=bb).to_crs(w.crs)   # noqa: E731
    pol = get("fed2020_polygons")
    p20 = pol[(pol["Year_added"] == 2020) & pol["Class"].isin(CLEARED_CLASSES)].reset_index(drop=True)
    out = {
        "poly2020": _burn(p20.geometry.values, w),
        "poly2020_id": _burn(p20.geometry.values, w, values=list(range(1, len(p20) + 1)),
                             dtype="int32"),
        "poly_any": _burn(pol.geometry.values, w, all_touched=True),
        "l2": _burn(get("fed2020_buffered").geometry.values, w),
        "l2_15": _burn(get("fed2015_buffered").geometry.values, w),
    }
    nb, cn = get("fires_nbac"), get("fires_cnfdb")
    out["fire_since1981"] = (_burn(nb[nb["YEAR"] >= 1981].geometry.values, w)
                             | _burn(cn[cn["YEAR"] >= 1981].geometry.values, w))
    for y in (TRAIN_YEAR, *APPLY_YEARS):
        out[f"fire_2016_{y}"] = _burn(nb[(nb["YEAR"] >= 2016) & (nb["YEAR"] <= y)].geometry.values, w)
    out["harvest_year"] = harvest_year(w)
    lab = np.full((BLOCK, BLOCK), -1, dtype=np.int8)
    free = (out["l2"] == 0) & (out["poly_any"] == 0)
    lab[free & (out["fire_since1981"] == 0)] = 0
    lab[free & (out[f"fire_2016_{TRAIN_YEAR}"] == 1)] = 2
    lab[ndimage.binary_erosion(out["poly2020"] == 1)] = 1
    out["label"] = lab
    return out


HARVEST = C.RAW / "harvest" / "CA_Forest_Harvest_1985-2022.tif"
HARVEST_URL = "https://opendata.nfis.org/downloads/forest_change/CA_Forest_Harvest_1985-2022.zip"
HARVEST_LAST = 2022


def harvest_year(w) -> np.ndarray:
    """NRCan CA Forest Harvest 1985-2022 (Landsat, 30 m, year of harvest; 0 = none),
    nearest-neighbour onto the window grid. Independent of the federal footprint."""
    from rasterio.enums import Resampling
    from rasterio.vrt import WarpedVRT
    if not HARVEST.exists():
        import zipfile
        z = _download(HARVEST_URL, HARVEST.parent / "CA_Forest_Harvest_1985-2022.zip")
        zipfile.ZipFile(z).extractall(HARVEST.parent)
    with rasterio.open(HARVEST) as src, WarpedVRT(src, crs=w.crs, transform=window_transform(w),
                                                  width=BLOCK, height=BLOCK,
                                                  resampling=Resampling.nearest) as vrt:
        a = vrt.read(1)
    return np.where((a >= 1985) & (a <= HARVEST_LAST), a, 0).astype(np.uint16)


def layers_path(wid: str):
    return DET / "layers" / f"{wid}.npz"


def build_layers() -> None:
    win = load_windows()
    (DET / "layers").mkdir(parents=True, exist_ok=True)
    for w in win.itertuples():
        if layers_path(w.wid).exists():
            continue
        lay = window_layers(w)
        np.savez_compressed(layers_path(w.wid), **lay)
        n = {k: int((lay["label"] == v).sum()) for k, v in (("intact", 0), ("cleared", 1), ("burned", 2))}
        print(f"  layers {w.wid}: {n}", flush=True)


def load_layers(wid: str) -> dict[str, np.ndarray]:
    with np.load(layers_path(wid)) as z:
        return {k: z[k] for k in z.files}


# ---------------------------------------------------------------- samples
def sample_window(w, seed: int) -> pd.DataFrame:
    lay = load_layers(w.wid)
    f, valid = features(w.wid, TRAIN_YEAR)
    rng = np.random.default_rng(seed)
    frames = []
    for lab in (0, 1, 2):
        ii = np.flatnonzero(((lay["label"] == lab) & valid).ravel())
        if len(ii) == 0:
            continue
        ii = rng.choice(ii, min(SAMPLES_PER_CLASS, len(ii)), replace=False)
        x = f.reshape(f.shape[0], -1)[:, ii].T
        df = pd.DataFrame(x, columns=FEATURES["embedding_rf"])
        df["label"], df["pix"] = lab, ii
        df["poly_id"] = lay["poly2020_id"].ravel()[ii] if lab == 1 else -1
        frames.append(df)
    out = pd.concat(frames, ignore_index=True)
    out["wid"], out["CODE"] = w.wid, w.CODE
    return out


def build_samples() -> pd.DataFrame:
    win = load_windows()
    s = pd.concat([sample_window(w, SEED + i) for i, w in enumerate(win.itertuples())],
                  ignore_index=True)
    s.to_parquet(DET / "samples_2020.parquet")
    print(s.groupby(["CODE", "label"]).size().unstack().to_string())
    return s


# ---------------------------------------------------------------- post-processing
def components(mask: np.ndarray) -> tuple[np.ndarray, int]:
    lab, n = ndimage.label(mask, structure=np.ones((3, 3), bool))
    if n == 0:
        return lab, 0
    size = np.bincount(lab.ravel())
    small = size < MIN_PX
    small[0] = True
    lab[small[lab]] = 0
    return lab, int((~small).sum())


EDGE_PX = 2      # 20 m margin around mapped polygons absorbs edge misregistration


def classify_components(det: np.ndarray, lay: dict, year: int, prior_new: np.ndarray | None = None):
    """Split thresholded detections (patches >= 2 ha) into

    * ``known``: pixels on a federal polygon (already mapped);
    * the rest, cut back by a 20 m margin around federal polygons and kept
      where a remaining patch is still >= 2 ha, split into ``burn`` (mostly
      inside a 2016-``year`` fire) and ``new``. Patches already "new" at 2020
      (``prior_new``) are not new again.

    New cutblocks are often cut next to older ones, so a detection that merely
    touches a mapped polygon is not discarded whole (the Earth Engine
    post-processing in ``apply.py`` does discard it: a stricter rule).
    """
    lab, _ = components(det)
    z = np.zeros_like(det, bool)
    if lab.max() == 0:
        return {"known": z, "burn": z.copy(), "new": z.copy()}
    poly = lay["poly_any"] == 1
    known = (lab > 0) & poly
    near = ndimage.binary_dilation(poly, iterations=EDGE_PX) if poly.any() else poly
    rest, _ = components((lab > 0) & ~near)
    if rest.max() == 0:
        return {"known": known, "burn": z.copy(), "new": z.copy()}
    n = rest.max() + 1
    size = np.bincount(rest.ravel(), minlength=n).astype(float)
    fire = np.bincount(rest.ravel(), weights=lay[f"fire_2016_{year}"].ravel().astype(float),
                       minlength=n) / np.maximum(size, 1) > 0.5
    seen = (np.bincount(rest.ravel(), weights=prior_new.ravel().astype(float), minlength=n) > 0
            if prior_new is not None else np.zeros(n, bool))
    burn_c, new_c = fire.copy(), ~fire & ~seen
    burn_c[0] = new_c[0] = False
    return {"known": known, "burn": burn_c[rest], "new": new_c[rest]}


def _pct(mask: np.ndarray, ref: np.ndarray) -> float:
    """Share (%) of ``mask`` pixels inside ``ref``; NaN if ``mask`` is empty."""
    n = int(mask.sum())
    return float(100 * (mask & ref).sum() / n) if n else float("nan")


def buffer(mask: np.ndarray) -> np.ndarray:
    if not mask.any():
        return np.zeros_like(mask, bool)
    return ndimage.distance_transform_edt(~mask) <= BUFFER_PX


# ---------------------------------------------------------------- run
def _sfx(fs: str) -> str:
    """File suffix of a feature set's rasters (the full model keeps the bare name)."""
    return "" if fs == "embedding_rf" else f"_{fs}"


def run(n_splits: int = 5, model: str = "gbt", seed: int = 0) -> dict:
    """Gradient-boosted trees (fast to apply to ~1 million pixels per window)."""
    win = load_windows()
    s = pd.read_parquet(DET / "samples_2020.parquet")
    out_dir = DET / "prob"
    out_dir.mkdir(exist_ok=True)
    groups = s["CODE"].to_numpy()
    k = min(n_splits, len(np.unique(groups)))
    results = {}
    for fs, feats in FEATURES.items():
        X, y = s[feats].to_numpy(np.float32), (s["label"] == 1).to_numpy().astype(int)
        oof = np.zeros(len(s))
        models = {}
        for fold, (tr, te) in enumerate(GroupKFold(n_splits=k).split(X, y, groups)):
            m = make_model(model, seed).fit(X[tr], y[tr])
            oof[te] = m.predict_proba(X[te])[:, 1]
            for code in np.unique(groups[te]):
                models[code] = m
        neg = s["label"] != 1
        t = threshold_at_fpr(oof[neg.to_numpy()], FPR)
        det = oof >= t
        pos = y == 1
        res = {"auc": float(roc_auc_score(y, oof)), "average_precision": float(average_precision_score(y, oof)),
               "threshold_at_1pct_fa": float(t), "recall_at_1pct_fa": float(det[pos].mean()),
               "false_alarm_intact": float(det[(s["label"] == 0).to_numpy()].mean()),
               "false_alarm_burned": float(det[(s["label"] == 2).to_numpy()].mean()),
               "n_samples": int(len(s)), "n_windows": int(s["wid"].nunique()),
               "n_ranges": int(len(np.unique(groups))), "folds": k}
        per_range = {}
        for code, g in s.assign(p=oof).groupby("CODE"):
            yy = (g["label"] == 1).astype(int)
            if yy.nunique() == 2:
                per_range[code] = float(roc_auc_score(yy, g["p"]))
        res["per_range_auc"] = per_range
        # wall-to-wall in held-out windows, at 2020 and the application years
        rows = []
        for w in win.itertuples():
            if w.kind == "burn":
                continue
            lay = load_layers(w.wid)
            row = {"wid": w.wid, "CODE": w.CODE, "kind": w.kind, "n2020": w.n2020}
            prior_new = None
            new_any = np.zeros((BLOCK, BLOCK), bool)
            for yr in (TRAIN_YEAR, *APPLY_YEARS):
                f, valid = features(w.wid, yr)
                fi = [FEATURES["embedding_rf"].index(c) for c in feats]
                p = np.zeros(BLOCK * BLOCK, np.float32)
                flat = f.reshape(f.shape[0], -1)[fi].T
                v = valid.ravel()
                p[v] = models[w.CODE].predict_proba(flat[v])[:, 1]
                p = p.reshape(BLOCK, BLOCK)
                del f, flat
                np.save(out_dir / f"{w.wid}_{yr}{_sfx(fs)}.npy", (p * 255).astype(np.uint8))
                parts = classify_components(p >= t, lay, yr, prior_new)
                ha = lambda m: float(m.sum() * RES * RES / 1e4)     # noqa: E731
                row[f"det_known_ha_{yr}"] = ha(parts["known"])
                row[f"det_burn_ha_{yr}"] = ha(parts["burn"])
                row[f"det_new_ha_{yr}"] = ha(parts["new"])
                hy = lay["harvest_year"]
                if yr == TRAIN_YEAR:
                    prior_new = parts["new"]
                    # are 2020 "unconfirmed" detections real cutblocks the federal map lacks?
                    row["new_2020_in_harvest_2015_2020_pct"] = _pct(parts["new"], (hy >= 2015) & (hy <= 2020))
                    pid = lay["poly2020_id"]
                    hit = np.unique(pid[parts["known"] & (pid > 0)])
                    big = np.bincount(pid.ravel())[1:] * RES * RES >= 2e4   # polygons >= 2 ha
                    ids = np.flatnonzero(big) + 1
                    row["polygons_2020_ge2ha"] = int(len(ids))
                    row["polygons_2020_hit"] = int(np.isin(ids, hit).sum())
                    detb = buffer(parts["known"] | parts["new"])
                    growth = (lay["l2"] == 1) & (lay["l2_15"] == 0)
                    row["official_growth_15_20_pct"] = 100 * growth.mean()
                    row["det_buffered_growth_20_pct"] = 100 * (detb & (lay["l2_15"] == 0)).mean()
                    row["det_buffered_growth_hits_official_pct"] = 100 * (detb & growth).mean()
                    row["new_2020_buffered_outside_l2_pct"] = 100 * (buffer(parts["new"]) & (lay["l2"] == 0)).mean()
                else:
                    new_any |= parts["new"]
                    if yr == APPLY_YEARS[0]:
                        # precision floor: share of new 2020-2023 detections on a mapped
                        # 2020-2022 harvest (2023 harvests are real but not in the layer)
                        row["new_2023_in_harvest_2020_2022_pct"] = _pct(parts["new"], (hy >= 2020) & (hy <= HARVEST_LAST))
            # recall: 2021-2022 harvest patches (>= 2 ha, off federal polygons and fires)
            # hit by a new detection
            hy = lay["harvest_year"]
            truth = (hy >= 2021) & (hy <= HARVEST_LAST) & (lay["poly_any"] == 0) & (lay[f"fire_2016_{APPLY_YEARS[-1]}"] == 0)
            tl, nt = components(truth)
            row["harvest_2021_2022_patches"] = nt
            row["harvest_2021_2022_patches_hit"] = int(len(np.setdiff1d(np.unique(tl[new_any & (tl > 0)]), [0])))
            row["harvest_2021_2022_ha"] = float((tl > 0).sum() * RES * RES / 1e4)
            row["new_20_25_ha"] = float(new_any.sum() * RES * RES / 1e4)
            row["new_20_25_buffered_outside_l2_pct"] = 100 * (buffer(new_any) & (lay["l2"] == 0)).mean()
            np.save(out_dir / f"{w.wid}_new_2020_2025{_sfx(fs)}.npy", new_any)
            rows.append(row)
            print(f"  [{fs}] {w.wid}: {row['polygons_2020_hit']}/{row['polygons_2020_ge2ha']} polygons, "
                  f"new 2020-25 {row['new_20_25_ha']:.0f} ha", flush=True)
        wt = pd.DataFrame(rows)
        wt.to_csv(C.TABLES / f"detector_windows_{fs}.csv", index=False)
        res["polygon_detection_ge2ha"] = float(wt["polygons_2020_hit"].sum() / max(wt["polygons_2020_ge2ha"].sum(), 1))
        for c in ("official_growth_15_20_pct", "det_buffered_growth_20_pct",
                  "det_buffered_growth_hits_official_pct", "new_2020_buffered_outside_l2_pct",
                  "new_20_25_buffered_outside_l2_pct"):
            res[f"mean_{c}"] = float(wt[c].mean())
        res["harvest_2021_2022_patch_recall"] = float(wt["harvest_2021_2022_patches_hit"].sum()
                                                      / max(wt["harvest_2021_2022_patches"].sum(), 1))
        a23 = wt["det_new_ha_2023"]
        res["new_2023_on_harvest_pct_area_weighted"] = float(
            (wt["new_2023_in_harvest_2020_2022_pct"].fillna(0) * a23).sum() / max(a23.sum(), 1e-9))
        a20 = wt[f"det_new_ha_{TRAIN_YEAR}"]
        res["new_2020_on_harvest_pct_area_weighted"] = float(
            (wt["new_2020_in_harvest_2015_2020_pct"].fillna(0) * a20).sum() / max(a20.sum(), 1e-9))
        res["unconfirmed_2020_ha_per_100km2"] = float(wt[f"det_new_ha_{TRAIN_YEAR}"].sum()
                                                      / (len(wt) * BLOCK**2 * RES**2 / 1e8))
        res["new_2020_2025_ha_per_100km2"] = float(wt["new_20_25_ha"].sum()
                                                   / (len(wt) * BLOCK**2 * RES**2 / 1e8))
        results[fs] = res
        print(json.dumps({k2: v2 for k2, v2 in res.items() if k2 != "per_range_auc"}, indent=1))
    (C.TABLES / "detector_eval_windows.json").write_text(json.dumps(results, indent=2))
    rows = [{"features": fs, **{k2: v2 for k2, v2 in r.items() if k2 != "per_range_auc"}}
            for fs, r in results.items()]
    pd.DataFrame(rows).to_csv(C.TABLES / "detector_eval_windows.csv", index=False)
    return results


# ---------------------------------------------------------------- did industry keep its pace?
# best balance on held-out ranges: the full model's recall of independent 2021-2022
# harvests with a fifth of its false "new" clearings at 2020 (cosine change alone has
# fewer false alarms but finds half the federal polygons)
OPERATING = "embedding_change_rf"


def pace(fs: str = OPERATING) -> dict:
    """Polygonal clearing since 2020 (detector) against polygonal clearing
    2015-2020 (federal polygons first mapped in 2020), like for like:

    * clearing area: new 2020-2025 detections minus the detector's 2020
      false-new rate (its noise floor), divided by its 2020 polygon recall;
    * buffered footprint added outside the previous footprint (500 m), with the
      2020 false-new buffer as the noise floor.

    Roads and seismic lines are below 10 m and left out of both sides."""
    ev = json.loads((C.TABLES / "detector_eval_windows.json").read_text())[fs]
    t, recall = ev["threshold_at_1pct_fa"], ev["polygon_detection_ge2ha"]
    rows = []
    for w in load_windows().itertuples():
        if w.kind == "burn":
            continue
        lay = load_layers(w.wid)
        p20 = np.load(DET / "prob" / f"{w.wid}_{TRAIN_YEAR}{_sfx(fs)}.npy") / 255
        noise = classify_components(p20 >= t, lay, TRAIN_YEAR)["new"]
        new = np.load(DET / "prob" / f"{w.wid}_new_2020_2025{_sfx(fs)}.npy")
        off = lay["poly2020"] == 1
        ha = lambda m: float(m.sum() * RES * RES / 1e4)       # noqa: E731
        rows.append({"wid": w.wid, "CODE": w.CODE, "kind": w.kind,
                     "federal_clearing_15_20_ha": ha(off),
                     "detected_new_20_25_ha": ha(new), "noise_2020_ha": ha(noise),
                     "federal_buffered_added_15_20_ha": ha(buffer(off) & (lay["l2_15"] == 0)),
                     "detected_buffered_added_20_25_ha": ha(buffer(new) & (lay["l2"] == 0)),
                     "noise_buffered_2020_ha": ha(buffer(noise) & (lay["l2"] == 0))})
    d = pd.DataFrame(rows)
    d.to_csv(C.TABLES / "detector_pace_windows.csv", index=False)
    tot = d.drop(columns=["wid", "CODE", "kind"]).sum()
    est = max(tot["detected_new_20_25_ha"] - tot["noise_2020_ha"], 0) / recall
    est_b = max(tot["detected_buffered_added_20_25_ha"] - tot["noise_buffered_2020_ha"], 0) / recall
    out = {"feature_set": fs, "windows": int(len(d)), "polygon_recall_2020": recall,
           **{k: float(v) for k, v in tot.items()},
           "estimated_clearing_20_25_ha": est,
           "pace_ratio_clearing": est / tot["federal_clearing_15_20_ha"],
           "estimated_buffered_added_20_25_ha": est_b,
           "pace_ratio_buffered": est_b / tot["federal_buffered_added_15_20_ha"],
           "windows_with_more_after_2020": int(((d["detected_new_20_25_ha"] - d["noise_2020_ha"]) / recall
                                                > d["federal_clearing_15_20_ha"]).sum())}
    # independent check: NRCan harvest map in the same windows (harvest only, to 2022)
    hy = {w.wid: load_layers(w.wid)["harvest_year"] for w in load_windows().itertuples() if w.kind != "burn"}
    per_year = {y: float(sum((h == y).sum() for h in hy.values()) * RES * RES / 1e4) for y in range(2015, HARVEST_LAST + 1)}
    out["harvest_ha_per_year_2015_2022"] = per_year
    out["harvest_pace_ratio_2021_22_vs_2015_20"] = (np.mean([per_year[y] for y in range(2021, HARVEST_LAST + 1)])
                                                    / np.mean([per_year[y] for y in range(2015, 2021)]))
    p20 = {w: load_layers(w)["poly2020"] == 1 for w in hy}
    a = sum(m.sum() for m in p20.values())
    out["federal_2020_polygons_on_pre2015_harvest_share"] = float(
        sum((p20[w] & (hy[w] > 0) & (hy[w] < 2015)).sum() for w in hy) / a)
    (C.TABLES / "detector_pace.json").write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=1))
    return out


def national_harvest_trend(res: float = 120.0) -> pd.DataFrame:
    """Harvest area by year inside every range, from NRCan's national harvest map:
    a selection-free check on the post-2020 pace (the detector windows were drawn
    where 2015-2020 clearing was mapped, so their own trend is biased upward
    for 2015-2020). The map's overviews are nearest-neighbour samples of the 30 m
    pixels, so counts at ``res`` estimate area without bias."""
    from rasterio.features import rasterize as _rz
    from rasterio.windows import from_bounds
    ranges = read_interim("ranges")
    rows = []
    with rasterio.open(HARVEST) as src:
        r_l = ranges.to_crs(src.crs)
        for r in r_l.itertuples():
            win = from_bounds(*r.geometry.bounds, transform=src.transform).round_offsets().round_lengths()
            h = max(1, int(win.height * src.res[1] / res))
            wd = max(1, int(win.width * src.res[0] / res))
            a = src.read(1, window=win, out_shape=(h, wd), boundless=True, fill_value=0)
            tr = src.window_transform(win) * Affine.scale(win.width / wd, win.height / h)
            m = _rz([(r.geometry, 1)], out_shape=(h, wd), transform=tr, fill=0, dtype="uint8").astype(bool)
            px_ha = abs(tr.a * tr.e) / 1e4
            yrs, n = np.unique(a[m & (a >= 1985) & (a <= HARVEST_LAST)], return_counts=True)
            for y, k in zip(yrs, n):
                rows.append({"CODE": r.CODE, "year": int(y), "ha": float(k * px_ha)})
    d = pd.DataFrame(rows)
    d["prov"] = d["CODE"].str.rstrip("0123456789")
    d.to_csv(C.TABLES / "harvest_by_range_year.csv", index=False)
    nat = d.groupby("year")["ha"].sum()
    print(nat.loc[2005:].round(0).to_string())
    return d


# ---------------------------------------------------------------- dNBR baseline (no AI)
NBR_BANDS = ("B8A", "B12")


def nbr_composite(w, year: int) -> np.ndarray:
    """Median summer NBR from Sentinel-2 L2A (Planetary Computer) on the window grid;
    gaps are filled from cloudier scenes over June-September (as in ``hero.py``)."""
    a = _nbr_composite(w, year)
    if np.isnan(a).mean() > 0.05:
        b = _nbr_composite(w, year, max_cloud=60, window=("06-01", "09-30"))
        a = np.where(np.isnan(a), b, a)
    return a


def _nbr_composite(w, year: int, max_cloud: int = 30, window=("07-01", "09-15")) -> np.ndarray:
    import requests
    from rasterio.enums import Resampling
    from rasterio.vrt import WarpedVRT
    from ..hero import SAS, SCL_BAD, search
    tf = Transformer.from_crs(w.crs, "EPSG:4326", always_xy=True)
    x0, y0, size = w.x0, w.y0, BLOCK * RES
    lon, lat = tf.transform([x0, x0 + size, x0, x0 + size], [y0, y0, y0 + size, y0 + size])
    items = search((min(lon), min(lat), max(lon), max(lat)), year, max_cloud=max_cloud, per_tile=4,
                   window=window)
    token = requests.get(SAS, timeout=60).json()["token"]
    stack = []
    for it in items:
        def read(asset, resamp):
            href = it["assets"][asset]["href"] + "?" + token
            with rasterio.open(href) as src, WarpedVRT(src, crs=w.crs, transform=window_transform(w),
                                                       width=BLOCK, height=BLOCK, resampling=resamp,
                                                       nodata=0) as vrt:
                return vrt.read(1)
        base = float(it["properties"].get("s2:processing_baseline", "0") or 0)
        off = 1000.0 if base >= 4.0 else 0.0
        try:
            scl = read("SCL", Resampling.nearest)
            nir, swir = (read(b, Resampling.bilinear).astype(np.float32) for b in NBR_BANDS)
        except rasterio.RasterioIOError as e:  # pragma: no cover - network
            print(f"    skip {it['id']}: {e}")
            continue
        ok = ~np.isin(scl, list(SCL_BAD)) & (scl > 0) & (nir > 0) & (swir > 0)
        nir, swir = nir - off, swir - off
        with np.errstate(all="ignore"):
            nbr = (nir - swir) / (nir + swir)
        nbr[~ok] = np.nan
        stack.append(nbr)
    with np.errstate(all="ignore"):
        return np.nanmedian(np.stack(stack), axis=0) if stack else np.full((BLOCK, BLOCK), np.nan)


def build_dnbr() -> None:
    """dNBR = NBR(2017) - NBR(2020): the same 3-year change as the embedding features."""
    win = load_windows()
    (DET / "dnbr").mkdir(parents=True, exist_ok=True)
    for w in win.itertuples():
        out = DET / "dnbr" / f"{w.wid}.npy"
        if out.exists():
            continue
        d = nbr_composite(w, TRAIN_YEAR - LAG) - nbr_composite(w, TRAIN_YEAR)
        np.save(out, d.astype(np.float32))
        print(f"  dNBR {w.wid}: {np.isnan(d).mean():.1%} missing", flush=True)


def run_dnbr_baseline() -> dict:
    """The classic index as a score, no model: pixel metrics on the same samples
    and wall-to-wall polygon detection at 2020 with the same post-processing."""
    win = load_windows()
    s = pd.read_parquet(DET / "samples_2020.parquet")
    dn = {w.wid: np.load(DET / "dnbr" / f"{w.wid}.npy") for w in win.itertuples()}
    s["dNBR"] = [dn[w].ravel()[p] for w, p in zip(s["wid"], s["pix"])]
    s = s[np.isfinite(s["dNBR"])]
    y = (s["label"] == 1).to_numpy().astype(int)
    score = s["dNBR"].to_numpy()
    t = threshold_at_fpr(score[s["label"].to_numpy() != 1], FPR)
    det = score >= t
    res = {"auc": float(roc_auc_score(y, score)), "average_precision": float(average_precision_score(y, score)),
           "threshold_at_1pct_fa": float(t), "recall_at_1pct_fa": float(det[y == 1].mean()),
           "false_alarm_intact": float(det[s["label"].to_numpy() == 0].mean()),
           "false_alarm_burned": float(det[s["label"].to_numpy() == 2].mean()),
           "n_samples": int(len(s)), "n_windows": int(s["wid"].nunique())}
    hit = total = 0
    for w in win.itertuples():
        if w.kind == "burn":
            continue
        lay = load_layers(w.wid)
        parts = classify_components(np.nan_to_num(dn[w.wid], nan=-9) >= t, lay, TRAIN_YEAR)
        pid = lay["poly2020_id"]
        big = np.bincount(pid.ravel())[1:] * RES * RES >= 2e4
        ids = np.flatnonzero(big) + 1
        hit += int(np.isin(ids, np.unique(pid[parts["known"] & (pid > 0)])).sum())
        total += len(ids)
    res["polygon_detection_ge2ha"] = hit / max(total, 1)
    print(json.dumps(res, indent=1))
    (C.TABLES / "detector_eval_windows_dnbr.json").write_text(json.dumps(res, indent=2))
    return res


# ---------------------------------------------------------------- figure
def figure(wid: str | None = None) -> None:
    """fig8: one held-out window (2020 detections vs the federal map; new
    clearings since 2020 vs the independent harvest map) and the comparison
    of methods."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    from ..figures import FIRE, INDUSTRY, INK, INK2, MUTED, SURFACE, _save
    ev = json.loads((C.TABLES / "detector_eval_windows.json").read_text())
    dn = C.TABLES / "detector_eval_windows_dnbr.json"
    base = json.loads(dn.read_text()) if dn.exists() else None
    fs = OPERATING
    wt = pd.read_csv(C.TABLES / f"detector_windows_{fs}.csv")
    if wid is None:   # the random window with the most independent 2021-2022 harvest
        wid = wt[wt["kind"] == "random"].sort_values("harvest_2021_2022_ha").iloc[-1]["wid"]
    w = load_windows().set_index("wid").loc[wid]
    lay = load_layers(wid)
    p20 = np.load(DET / "prob" / f"{wid}_{TRAIN_YEAR}{_sfx(fs)}.npy") / 255
    new = np.load(DET / "prob" / f"{wid}_new_2020_2025{_sfx(fs)}.npy")
    t = ev[fs]["threshold_at_1pct_fa"]
    hy = lay["harvest_year"]
    fig = plt.figure(figsize=(11, 4.4))
    gs = fig.add_gridspec(1, 3, width_ratios=[1, 1, 0.9], wspace=0.08)
    ax1, ax2, ax3 = (fig.add_subplot(gs[0, i]) for i in range(3))
    ext = (0, BLOCK * RES / 1000, 0, BLOCK * RES / 1000)
    ax1.imshow(p20, cmap="Greys", vmin=0, vmax=1, extent=ext)
    ax1.contour(np.flipud(lay["poly2020"] == 1), levels=[0.5], colors=[INDUSTRY], linewidths=0.6, extent=ext)
    ax1.contour(np.flipud(p20 >= t), levels=[0.5], colors=[FIRE], linewidths=0.6, extent=ext)
    ax1.set_title("2020: detector vs federal map", fontsize=10)
    ax1.legend(handles=[Line2D([], [], color=INDUSTRY, label="federal polygons, first mapped 2020"),
                        Line2D([], [], color=FIRE, label="detector (range held out of training)")],
               loc="upper center", bbox_to_anchor=(0.5, -0.02), fontsize=7, frameon=False)
    bg = np.where(hy > 0, 0.85, 1.0)
    ax2.imshow(bg, cmap="Greys_r", vmin=0, vmax=1, extent=ext)
    ax2.contour(np.flipud((hy >= 2021) & (hy <= HARVEST_LAST)), levels=[0.5], colors=[INDUSTRY],
                linewidths=0.7, extent=ext)
    ax2.imshow(np.ma.masked_where(~new, new), cmap="autumn", alpha=0.8, extent=ext)
    ax2.set_title("New clearings since 2020", fontsize=10)
    ax2.legend(handles=[Line2D([], [], color="#ff4500", lw=4, label="detected new clearing, 2020-2025"),
                        Line2D([], [], color=INDUSTRY, label="NRCan harvest 2021-2022 (independent)"),
                        Line2D([], [], color="#d9d9d9", lw=4, label="any harvest 1985-2022")],
               loc="upper center", bbox_to_anchor=(0.5, -0.02), fontsize=7, frameon=False)
    for a in (ax1, ax2):
        a.set_xticks([]); a.set_yticks([])
        a.text(0.99, 0.01, "10 km", transform=a.transAxes, ha="right", va="bottom", fontsize=7, color=MUTED)
    rows = [("Embeddings, full\n(AI)", ev["embedding_rf"]),
            ("Embedding change\n(AI, used)", ev["embedding_change_rf"]),
            ("Cosine change\nalone", ev["cos_change_only"])]
    if base:
        rows.append(("Burn ratio change\n(dNBR, no AI)", base))
    y = np.arange(len(rows))[::-1]
    ax3.barh(y + 0.18, [r["auc"] for _, r in rows], height=0.34, color=INK2, label="AUC (pixels)")
    ax3.barh(y - 0.18, [r["recall_at_1pct_fa"] for _, r in rows], height=0.34, color=FIRE,
             label="recall at 1% false alarms")
    for yi, (_, r) in zip(y, rows):
        ax3.text(r["auc"] + 0.01, yi + 0.18, f"{r['auc']:.2f}", va="center", fontsize=7.5, color=INK)
        ax3.text(r["recall_at_1pct_fa"] + 0.01, yi - 0.18, f"{r['recall_at_1pct_fa']:.2f}", va="center",
                 fontsize=7.5, color=INK)
    ax3.set_yticks(y, [n for n, _ in rows], fontsize=8)
    ax3.yaxis.tick_right()
    ax3.set_xlim(0, 1.12)
    ax3.set_title("Held-out ranges", fontsize=10)
    ax3.legend(loc="upper center", bbox_to_anchor=(0.5, -0.08), fontsize=7, frameon=False, ncol=2)
    fig.suptitle(f"Detecting new industrial clearings ({w.CODE} window, 10 m)", x=0.01, ha="left",
                 fontsize=12, fontweight="bold", color=INK)
    fig.text(0.01, -0.12, "The AlphaEarth Foundations Satellite Embedding dataset is produced by Google and "
             "Google DeepMind. Harvest: NRCan CA Forest Harvest 1985-2022 (Hermosilla et al. 2016). "
             "Contains modified Copernicus Sentinel data.", fontsize=6.5, color=MUTED)
    fig.patch.set_facecolor(SURFACE)
    _save(fig, "fig8_detector", exts=("png",))   # raster panels: no SVG


def main(argv=None):
    p = argparse.ArgumentParser(prog="caribou.detector.windows", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("steps", nargs="+", choices=["select", "download", "labels", "samples", "run",
                                                 "dnbr", "baseline", "pace", "trend", "figure"])
    p.add_argument("--workers", type=int, default=6)
    a = p.parse_args(argv)
    for step in a.steps:
        t0 = time.time()
        print(f"=== windows {step}")
        if step == "select":
            select_windows()
        elif step == "download":
            download_all(a.workers)
        elif step == "labels":
            build_layers()
        elif step == "samples":
            build_samples()
        elif step == "run":
            run()
        elif step == "dnbr":
            build_dnbr()
        elif step == "baseline":
            run_dnbr_baseline()
        elif step == "pace":
            pace()
        elif step == "trend":
            national_harvest_trend()
        elif step == "figure":
            figure()
        print(f"=== windows {step} done in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
