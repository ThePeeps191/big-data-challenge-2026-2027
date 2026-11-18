"""Hero image: one range before and after its fires, Sentinel-2 false colour.

Bands SWIR2 / NIR / red (B12, B8A, B04): healthy forest is green, fresh burns
are red-brown, water is black. Summer (Jul 1 - Sep 15) median of the
least-cloudy scenes per MGRS tile, clouds and shadows masked with the scene
classification layer, read at reduced resolution through COG overviews.

Imagery: Copernicus Sentinel-2 L2A via Microsoft Planetary Computer
(anonymous STAC search + SAS-signed URLs; no account needed).
"""

from __future__ import annotations

import math

import matplotlib

matplotlib.use("Agg")
import geopandas as gpd  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import shapely  # noqa: E402
import numpy as np  # noqa: E402
import rasterio  # noqa: E402
import requests  # noqa: E402
from rasterio.enums import Resampling  # noqa: E402
from rasterio.transform import from_origin  # noqa: E402
from rasterio.vrt import WarpedVRT  # noqa: E402

from . import config as C  # noqa: E402
from .figures import INK, MUTED, SURFACE, _save  # noqa: E402
from .pixels import sql_quote  # noqa: E402
from .prepare import read_interim  # noqa: E402

STAC = "https://planetarycomputer.microsoft.com/api/stac/v1/search"
SAS = "https://planetarycomputer.microsoft.com/api/sas/v1/token/sentinel-2-l2a"
BANDS = ["B12", "B8A", "B04"]
SCL_BAD = {0, 1, 3, 8, 9, 10, 11}  # nodata, saturated, shadow, cloud med/high, cirrus, snow


def search(bbox_wgs84, year, max_cloud=20, per_tile=3, window=("07-01", "09-15")):
    body = {"collections": ["sentinel-2-l2a"], "bbox": list(bbox_wgs84),
            "datetime": f"{year}-{window[0]}T00:00:00Z/{year}-{window[1]}T23:59:59Z",
            "query": {"eo:cloud_cover": {"lt": max_cloud}}, "limit": 250}
    items = []
    url, payload = STAC, body
    while url:
        r = requests.post(url, json=payload, timeout=120)
        r.raise_for_status()
        js = r.json()
        items += js["features"]
        nxt = [l for l in js.get("links", []) if l.get("rel") == "next"]
        url, payload = (nxt[0]["href"], nxt[0].get("body")) if nxt else (None, None)
    by_tile = {}
    # rank by cloud cover *plus* missing data: otherwise swath-edge slivers (cloud-free
    # because they barely cover the tile) win and leave holes
    def badness(i):
        p = i["properties"]
        return p["eo:cloud_cover"] + p.get("s2:nodata_pixel_percentage", 0)

    for it in sorted(items, key=badness):
        t = it["properties"].get("s2:mgrs_tile")
        by_tile.setdefault(t, [])
        if len(by_tile[t]) < per_tile:
            by_tile[t].append(it)
    return [i for v in by_tile.values() for i in v]


def composite(items, x0, y1, W, H, res):
    token = requests.get(SAS, timeout=60).json()["token"]
    stack = np.full((len(items), 3, H, W), np.nan, dtype=np.float16)  # halves memory
    for k, it in enumerate(items):
        def read(asset, resamp):
            href = it["assets"][asset]["href"] + "?" + token
            with rasterio.open(href) as src, WarpedVRT(
                    src, crs=C.AREA_CRS, transform=from_origin(x0, y1, res, res), width=W,
                    height=H, resampling=resamp, nodata=0) as vrt:
                return vrt.read(1)
        # Processing baseline 04.00+ (Jan 2022 on) adds +1000 to L2A digital numbers
        baseline = float(it["properties"].get("s2:processing_baseline", "0") or 0)
        offset = 1000.0 if baseline >= 4.0 else 0.0
        try:
            scl = read("SCL", Resampling.nearest)
            ok = ~np.isin(scl, list(SCL_BAD)) & (scl > 0)
            for b, band in enumerate(BANDS):
                v = read(band, Resampling.average).astype(np.float32)
                bad = ~ok | (v == 0)
                v = v - offset
                v[bad] = np.nan
                stack[k, b] = v
        except rasterio.RasterioIOError as e:  # pragma: no cover - network
            print(f"    skip {it['id']}: {e}")
    with np.errstate(all="ignore"):
        return np.nanmedian(stack.astype(np.float32), axis=0)


def to_rgb(img, lo=None, hi=None):
    rgb = np.moveaxis(img, 0, -1)
    lo = np.nanpercentile(rgb, 2, axis=(0, 1)) if lo is None else lo
    hi = np.nanpercentile(rgb, 98, axis=(0, 1)) if hi is None else hi
    out = np.clip((rgb - lo) / (hi - lo), 0, 1)
    out = out ** 0.8
    out[np.isnan(out)] = 1.0
    return out, lo, hi


# "After" defaults to the first summer *after* the last fire season: during the
# 2025 season itself, smoke over active fires is masked as cloud and leaves holes.
AFTER_YEAR = C.UPDATE_YEAR + 1


def hero(code: str, years=(C.BASELINE_YEAR, AFTER_YEAR), res: float = 100.0, pad_km: float = 5):
    from pyproj import Transformer
    rr = read_interim("ranges", where=f"CODE = {sql_quote(code)}")
    geom = rr.geometry.iat[0]
    name = rr["name"].iat[0]
    minx, miny, maxx, maxy = geom.buffer(pad_km * 1000).bounds
    x0, y1 = math.floor(minx / res) * res, math.ceil(maxy / res) * res
    W, H = math.ceil((maxx - x0) / res), math.ceil((y1 - miny) / res)
    tf = Transformer.from_crs(C.AREA_CRS, "EPSG:4326", always_xy=True)
    xs, ys = tf.transform([minx, maxx, minx, maxx], [miny, miny, maxy, maxy])
    bbox = (min(xs), min(ys), max(xs), max(ys))
    imgs = {}
    cache = C.INTERIM / "hero"
    cache.mkdir(exist_ok=True)
    for y in years:
        cfile = cache / f"{code}_{y}_{int(res)}m.npy"
        if cfile.exists():
            imgs[y] = np.load(cfile)
            continue
        items = search(bbox, y)
        print(f"  {name} {y}: {len(items)} scenes")
        img = composite(items, x0, y1, W, H, res)
        gap = np.isnan(img).any(axis=0)
        if gap.mean() > 0.002:  # cloud-masked swaths: fill from a wider, cloudier window
            items2 = [i for i in search(bbox, y, max_cloud=60, per_tile=4, window=("06-01", "09-30"))
                      if i["id"] not in {j["id"] for j in items}]
            print(f"  {name} {y}: filling {gap.mean():.1%} gaps from {len(items2)} more scenes")
            fill = composite(items2, x0, y1, W, H, res)
            img = np.where(np.isnan(img), fill, img)
        np.save(cfile, img)
        imgs[y] = img
    ext = (x0, x0 + W * res, y1 - H * res, y1)
    fires = read_interim("fires_nbac", bbox=(ext[0], ext[2], ext[1], ext[3]))
    fires = fires[fires["YEAR"] > C.BASELINE_YEAR].clip((ext[0], ext[2], ext[1], ext[3]))
    fig, axes = plt.subplots(1, 2, figsize=(11, 5.4 * H / W + 0.9))
    fig.subplots_adjust(left=0.01, right=0.99, top=0.9, bottom=0.05, wspace=0.03)
    _, lo, hi = to_rgb(imgs[years[0]])
    for ax, y in zip(axes, years):
        rgb, _, _ = to_rgb(imgs[y], lo, hi)
        ax.imshow(rgb, extent=ext, interpolation="bilinear")
        rr.boundary.plot(ax=ax, color="white", linewidth=1.4)
        rr.boundary.plot(ax=ax, color=INK, linewidth=0.6)
        if y > C.BASELINE_YEAR and len(fires):
            outer = gpd.GeoSeries(shapely.get_exterior_ring(shapely.get_parts(
                shapely.union_all(fires.geometry.values))), crs=C.AREA_CRS)
            outer.plot(ax=ax, color="#fab219", linewidth=0.6)
        ax.set_xlim(ext[0], ext[1])
        ax.set_ylim(ext[2], ext[3])
        ax.set_axis_off()
        ax.set_title(f"Summer {y}", color=INK, loc="left")
    fig.suptitle(f"{name}: before and after the {C.BASELINE_YEAR + 1}-{C.UPDATE_YEAR} fires",
                 x=0.01, ha="left", fontsize=13, fontweight="bold", color=INK)
    fig.text(0.01, 0.005, "Sentinel-2 L2A false colour (SWIR2/NIR/red): forest green, recent burns magenta. "
             "White/black line: federal range boundary; amber: outer edge of NBAC fire perimeters "
             f"{C.BASELINE_YEAR + 1}-{C.UPDATE_YEAR}. Contains modified Copernicus Sentinel data.",
             fontsize=7.5, color=MUTED)
    fig.patch.set_facecolor(SURFACE)
    _save(fig, f"fig0_hero_{code}", exts=("png",))  # raster: no SVG
