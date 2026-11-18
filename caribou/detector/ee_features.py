"""Earth Engine feature stacks for the detector.

Requires an authenticated Earth Engine account:

    earthengine authenticate          # once, opens a browser
    set EE_PROJECT=<your-cloud-project>   (or pass project= to init)

Two feature sets, both defined for an *assessment year* ``Y`` so the same
model trained at Y = 2020 (federal labels) is applied at Y = 2025:

* ``emb``  Google Satellite Embedding V1 (annual, 64 bands at 10 m):
           the embedding in Y, and its change over three years (Y - (Y-3)).
           Embeddings start in 2017, so a symmetric 3-year lag is the
           longest that exists for Y = 2020.
* ``ls``   Landsat Collection 2 Level-2 summer (Jun 15 - Sep 15) medians of
           NBR, NDVI, NDMI: value in Y-1..Y ("post"), in Y-6..Y-5 ("pre"),
           post - pre, the largest single-year NBR drop over Y-5..Y and
           the year of that drop (relative to Y).
"""

from __future__ import annotations

import os

import numpy as np
import pandas as pd

try:
    import ee
except ImportError:  # pragma: no cover
    ee = None

EMBEDDING = "GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL"
EMB_BANDS = [f"A{i:02d}" for i in range(64)]
LANDSAT = {
    "LT05": ("LANDSAT/LT05/C02/T1_L2", ["SR_B1", "SR_B2", "SR_B3", "SR_B4", "SR_B5", "SR_B7"]),
    "LE07": ("LANDSAT/LE07/C02/T1_L2", ["SR_B1", "SR_B2", "SR_B3", "SR_B4", "SR_B5", "SR_B7"]),
    "LC08": ("LANDSAT/LC08/C02/T1_L2", ["SR_B2", "SR_B3", "SR_B4", "SR_B5", "SR_B6", "SR_B7"]),
    "LC09": ("LANDSAT/LC09/C02/T1_L2", ["SR_B2", "SR_B3", "SR_B4", "SR_B5", "SR_B6", "SR_B7"]),
}
COMMON = ["blue", "green", "red", "nir", "swir1", "swir2"]


def init(project: str | None = None) -> None:
    project = project or os.environ.get("EE_PROJECT")
    ee.Initialize(project=project) if project else ee.Initialize()


# ---------------------------------------------------------------- embeddings
def embedding(year: int) -> "ee.Image":
    col = ee.ImageCollection(EMBEDDING).filter(ee.Filter.calendarRange(year, year, "year"))
    return col.mosaic().select(EMB_BANDS)


def emb_stack(year: int, lag: int = 3) -> "ee.Image":
    now = embedding(year)
    then = embedding(year - lag)
    diff = now.subtract(then).rename([f"d{b}" for b in EMB_BANDS])
    return now.addBands(diff)


def emb_feature_names() -> list[str]:
    return EMB_BANDS + [f"d{b}" for b in EMB_BANDS]


# ---------------------------------------------------------------- landsat
def _prep_landsat(img):
    qa = img.select("QA_PIXEL")
    bad = (1 << 1) | (1 << 3) | (1 << 4) | (1 << 5)   # dilated cloud, cloud, shadow, snow
    mask = qa.bitwiseAnd(bad).eq(0)
    sr = img.select(ee.List(img.get("bands_in"))).multiply(0.0000275).add(-0.2)
    sr = sr.rename(COMMON)
    nbr = sr.normalizedDifference(["nir", "swir2"]).rename("NBR")
    ndvi = sr.normalizedDifference(["nir", "red"]).rename("NDVI")
    ndmi = sr.normalizedDifference(["nir", "swir1"]).rename("NDMI")
    return nbr.addBands([ndvi, ndmi]).updateMask(mask)


def summer_indices(y0: int, y1: int) -> "ee.Image":
    """Median summer NBR/NDVI/NDMI over years y0..y1 from every Landsat sensor."""
    cols = []
    for _key, (cid, bands) in LANDSAT.items():
        c = (ee.ImageCollection(cid)
             .filter(ee.Filter.calendarRange(y0, y1, "year"))
             .filter(ee.Filter.dayOfYear(166, 258))           # ~Jun 15 - Sep 15
             .map(lambda im, b=bands: im.set("bands_in", b)))
        cols.append(c)
    merged = cols[0]
    for c in cols[1:]:
        merged = merged.merge(c)
    return merged.map(_prep_landsat).median()


def ls_stack(year: int) -> "ee.Image":
    post = summer_indices(year - 1, year).rename(["NBR_post", "NDVI_post", "NDMI_post"])
    pre = summer_indices(year - 6, year - 5).rename(["NBR_pre", "NDVI_pre", "NDMI_pre"])
    delta = post.subtract(pre).rename(["dNBR", "dNDVI", "dNDMI"])
    annual = [summer_indices(y, y).select("NBR") for y in range(year - 6, year + 1)]
    drops = [annual[i].subtract(annual[i + 1]).rename("drop") for i in range(len(annual) - 1)]
    drop_ic = ee.ImageCollection([d.addBands(ee.Image.constant(i - (len(drops) - 1))
                                             .toFloat().rename("when")) for i, d in enumerate(drops)])
    best = drop_ic.qualityMosaic("drop").rename(["NBR_maxdrop", "NBR_maxdrop_when"])
    return post.addBands([pre, delta, best])


def ls_feature_names() -> list[str]:
    return ["NBR_post", "NDVI_post", "NDMI_post", "NBR_pre", "NDVI_pre", "NDMI_pre",
            "dNBR", "dNDVI", "dNDMI", "NBR_maxdrop", "NBR_maxdrop_when"]


def stack(kind: str, year: int) -> "ee.Image":
    if kind == "emb":
        return emb_stack(year)
    if kind == "ls":
        return ls_stack(year)
    if kind == "both":
        return emb_stack(year).addBands(ls_stack(year))
    raise ValueError(kind)


def feature_names(kind: str) -> list[str]:
    return {"emb": emb_feature_names(), "ls": ls_feature_names(),
            "both": emb_feature_names() + ls_feature_names()}[kind]


def water_mask() -> "ee.Image":
    """1 where open water is seen more than half the time (JRC GSW)."""
    return ee.Image("JRC/GSW1_4/GlobalSurfaceWater").select("occurrence").gt(50).unmask(0)


# ---------------------------------------------------------------- sampling
def sample_points(points_wgs84: pd.DataFrame, kind: str, year: int, scale: float = 30,
                  batch: int = 2000) -> pd.DataFrame:
    """Sample a feature stack at label points (``pid``, lon, lat columns).

    Points are sent in batches; results come back as a DataFrame via
    ``ee.data.computeFeatures``.
    """
    img = stack(kind, year).addBands(water_mask().rename("water"))
    out = []
    for i in range(0, len(points_wgs84), batch):
        chunk = points_wgs84.iloc[i:i + batch]
        fc = ee.FeatureCollection([
            ee.Feature(ee.Geometry.Point([float(x), float(y)]), {"pid": int(p)})
            for p, x, y in zip(chunk["pid"], chunk["lon"], chunk["lat"])])
        samp = img.sampleRegions(collection=fc, properties=["pid"], scale=scale,
                                 tileScale=4, geometries=False)
        df = ee.data.computeFeatures({"expression": samp, "fileFormat": "PANDAS_DATAFRAME"})
        out.append(pd.DataFrame(df).drop(columns=["geo"], errors="ignore"))
        print(f"    sampled {min(i + batch, len(points_wgs84))}/{len(points_wgs84)} ({kind} {year})")
    return pd.concat(out, ignore_index=True)


# ---------------------------------------------------------------- pixels
def compute_tile(img: "ee.Image", x0: float, y1: float, width: int, height: int,
                 res: float, crs_wkt: str) -> np.ndarray:
    """Fetch one tile of a single-band image as a numpy array (computePixels)."""
    req = {
        "expression": img,
        "fileFormat": "NUMPY_NDARRAY",
        "grid": {
            "dimensions": {"width": int(width), "height": int(height)},
            "affineTransform": {"scaleX": res, "shearX": 0, "translateX": x0,
                                "shearY": 0, "scaleY": -res, "translateY": y1},
            "crsWkt": crs_wkt,
        },
    }
    arr = ee.data.computePixels(req)
    return np.asarray(arr[arr.dtype.names[0]] if arr.dtype.names else arr)
