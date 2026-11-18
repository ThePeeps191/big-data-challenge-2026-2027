"""A synthetic world, so the whole pipeline can be checked against hand-computed areas.

Range ``TT1``: a 10 km x 10 km square, x in [0, 10] km, y in [0, 10] km.
All features are full-height vertical strips with edges on the 100 m grid,
so pixel-centre rasterization is exact and every share is a strip width / 10.

    strip (km)   what is there
    0 - 1        official human footprint 2015 and 2020 (buffered)
    1 - 2        official human footprint 2020 only (new 2015-2020)
    4 - 5        NBAC fire 2023 (after the baseline)
    5 - 6        CNFDB+NBAC fire 1983, reburned by the 2023 NBAC fire
    6 - 7        CNFDB+NBAC fire 1983 (ages out by 2025)
    7 - 8        CNFDB+NBAC fire 2000
    9 - 10       CNFDB fire 1975 only (outside every window used)

Official totals: 2020 = human2020 + fires 1981-2020 -> strips 0-2, 5-8 (50%)
                 2015 = human2015 + fires 1976-2015 -> strips 0-1, 5-8 (40%)
"""

import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="caribou_test_")
os.environ["CARIBOU_ROOT"] = _tmp  # must happen before caribou.config is imported

import geopandas as gpd  # noqa: E402
import pytest  # noqa: E402
from shapely.geometry import box  # noqa: E402

KM = 1000.0


def strip(x0, x1):
    return box(x0 * KM, 0, x1 * KM, 10 * KM)


@pytest.fixture(scope="session")
def world():
    from caribou import config as C
    from shapely.ops import unary_union

    crs = C.AREA_CRS
    herd = "Test Herd"

    def save(gdf, name):
        gdf.to_file(C.INTERIM / f"{name}.gpkg", driver="GPKG", engine="pyogrio", layer=name)

    save(gpd.GeoDataFrame({"HERD": [herd], "CODE": ["TT1"], "name": [herd], "threshold": [0.65],
                           "area_km2": [100.0]}, geometry=[strip(0, 10)], crs=crs), "ranges")
    h15, h20 = strip(0, 1), unary_union([strip(0, 1), strip(1, 2)])
    tot20 = unary_union([h20, strip(5, 8)])
    tot15 = unary_union([h15, strip(5, 8)])
    for name, geom in (("fed2020_buffered", h20), ("fed2015_buffered", h15),
                       ("fed2020_total", tot20), ("fed2015_total", tot15)):
        g = gpd.GeoDataFrame({"HERD": [herd], "FEATURE": [0]}, geometry=[geom], crs=crs)
        save(g.explode(index_parts=False, ignore_index=True), name)
    save(gpd.GeoDataFrame({"YEAR": [1975, 1983, 2000]},
                          geometry=[strip(9, 10), strip(5, 7), strip(7, 8)], crs=crs), "fires_cnfdb")
    save(gpd.GeoDataFrame({"YEAR": [1983, 2000, 2023]},
                          geometry=[strip(5, 7), strip(7, 8), strip(4, 6)], crs=crs), "fires_nbac")
    return C
