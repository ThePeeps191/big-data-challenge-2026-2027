"""Turn raw downloads into analysis-ready GeoPackages.

Every output is in the equal-area CRS (``config.AREA_CRS``), has valid
polygonal geometry, and is exploded to single parts so a spatial index can
pick out only the pieces that touch a tile. Nothing is simplified.

Outputs (``data/interim``):

* ``ranges.gpkg``                 51 ranges: HERD, CODE, name, threshold, area_km2
* ``fed{2020,2015}_buffered.gpkg`` official buffered human footprint, by HERD
* ``fed{2020,2015}_total.gpkg``   official total footprint (human + 40-yr fire)
* ``fed2020_polygons.gpkg``       polygonal features (Class, Year_added, HERD)
* ``fed2020_lines.gpkg``          linear features
* ``fires_nbac.gpkg``             NBAC perimeters touching a range (YEAR, ...)
* ``fires_cnfdb.gpkg``            CNFDB polygons touching a range (YEAR, ...)
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pyogrio
import shapely

from . import config as C
from .fetch import fed_dir

pyogrio.set_gdal_config_options({"OGR_GEOJSON_MAX_OBJ_SIZE": "0"})  # huge features


# ---------------------------------------------------------------- geometry helpers
def polygonal(geoms: np.ndarray) -> np.ndarray:
    """make_valid, then keep only the polygonal part of each geometry."""
    geoms = shapely.make_valid(np.asarray(geoms, dtype=object))
    out = np.empty(len(geoms), dtype=object)
    for i, g in enumerate(geoms):
        if g is None or g.is_empty:
            out[i] = None
        elif g.geom_type in ("Polygon", "MultiPolygon"):
            out[i] = g
        else:  # GeometryCollection from make_valid: drop slivers of lines/points
            parts = [p for p in shapely.get_parts(g) if p.geom_type in ("Polygon", "MultiPolygon")]
            out[i] = shapely.union_all(parts) if parts else None
    return out


def explode_polygons(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty]
    gdf = gdf.explode(index_parts=False, ignore_index=True)
    return gdf[gdf.geom_type == "Polygon"].reset_index(drop=True)


def write(gdf: gpd.GeoDataFrame, name: str) -> Path:
    path = C.INTERIM / f"{name}.gpkg"
    tmp = path.with_suffix(".tmp.gpkg")
    if tmp.exists():
        tmp.unlink()
    gdf.to_file(tmp, driver="GPKG", engine="pyogrio", layer=name)
    tmp.replace(path)
    print(f"  wrote {path.name}: {len(gdf):,} features")
    return path


def read_interim(name: str, **kw) -> gpd.GeoDataFrame:
    return gpd.read_file(C.INTERIM / f"{name}.gpkg", engine="pyogrio", **kw)


# ---------------------------------------------------------------- federal layers
PROVINCE_ORDER = ["NT", "BC", "AB", "SK", "MB", "ON", "QC", "NL"]  # west to east


def code_sort_key(code: str) -> tuple[int, int]:
    """'AB10' -> (2, 10): provinces west to east, then range number."""
    prov = code.rstrip("0123456789")
    return (PROVINCE_ORDER.index(prov) if prov in PROVINCE_ORDER else 99,
            int(code[len(prov):] or 0))


def read_fed(name: str, edition: int = 2020) -> gpd.GeoDataFrame:
    folder = fed_dir(name, edition)
    if not (folder / "_COMPLETE").exists():
        raise FileNotFoundError(f"{folder} incomplete: run `python -m caribou fetch`")
    parts = sorted(folder.glob("part_*.geojson"))
    frames = [pyogrio.read_dataframe(p) for p in parts]
    gdf = pd.concat(frames, ignore_index=True)
    gdf = gpd.GeoDataFrame(gdf, geometry="geometry", crs=C.SOURCE_CRS)
    expected = int((folder / "_COMPLETE").read_text())
    assert len(gdf) == expected, f"{name}: {len(gdf)} != {expected}"
    return gdf.to_crs(C.AREA_CRS)


def prepare_ranges() -> gpd.GeoDataFrame:
    print("[prepare] ranges")
    g = read_fed("ranges")
    g = g[["HERD", "CODE", "geometry"]].copy()
    g["CODE_LAYER"] = g["CODE"]
    g["CODE"] = [C.CODE_BY_HERD.get(h, c) for h, c in zip(g["HERD"], g["CODE"])]
    g["geometry"] = polygonal(g.geometry.values)
    g["name"] = g["HERD"].map(C.display_name)
    g["threshold"] = g["CODE"].map(C.threshold_for)
    g["area_km2"] = g.area / 1e6
    g = g.sort_values("CODE", key=lambda s: s.map(code_sort_key)).reset_index(drop=True)
    assert len(g) == 51 and g["CODE"].is_unique
    write(g, "ranges")
    return g


def herd_key(name: str) -> str:
    """'Atikaki_Bernes', 'AtikakiBernes', 'Atikaki-Bernes' -> 'atikakibernes'."""
    return re.sub(r"[^a-z]", "", name.lower())


def harmonize_herds(herds: pd.Series) -> pd.Series:
    """Map herd names of another edition (2015 drops spaces and punctuation)
    onto the 2020 range names."""
    ref = read_interim("ranges", read_geometry=False)["HERD"]
    lookup = {herd_key(h): h for h in ref}
    out = herds.map(lambda h: lookup.get(herd_key(h)))
    missing = sorted(set(herds[out.isna()]))
    if missing:
        raise ValueError(f"unmatched herd names: {missing}")
    return out


def prepare_footprint(name: str, edition: int) -> None:
    print(f"[prepare] fed{edition} {name}")
    g = read_fed(name, edition)[["HERD", "geometry"]]
    g["HERD"] = harmonize_herds(g["HERD"])
    g["FEATURE"] = np.arange(len(g))  # source feature, kept through the explode
    # Explode first and repair only the invalid parts: repairing a whole
    # dissolved multipolygon (millions of vertices) is very slow and buys
    # nothing, since rasterizing and area sums work part by part.
    g = g.explode(index_parts=False, ignore_index=True)
    bad = ~shapely.is_valid(g.geometry.values)
    print(f"  {len(g):,} parts, {bad.sum():,} invalid -> make_valid")
    if bad.any():
        g.loc[bad, "geometry"] = polygonal(g.geometry.values[bad])
    write(explode_polygons(g), f"fed{edition}_{name}")


def prepare_features() -> None:
    print("[prepare] fed2020 polygons")
    g = read_fed("polygons")[["Class", "Year_added", "HERD", "geometry"]]
    g["geometry"] = polygonal(g.geometry.values)
    write(g[g.geometry.notna() & ~g.geometry.is_empty].reset_index(drop=True), "fed2020_polygons")
    print("[prepare] fed2020 lines")
    g = read_fed("lines")[["Class", "Year_added", "HERD", "geometry"]]
    write(g[g.geometry.notna() & ~g.geometry.is_empty].reset_index(drop=True), "fed2020_lines")


# ---------------------------------------------------------------- fires
def _touching_ranges(fires: gpd.GeoDataFrame, ranges: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    tree = shapely.STRtree(fires.geometry.values)
    _, idx = tree.query(ranges.geometry.values, predicate="intersects")
    return fires.iloc[np.unique(idx)].reset_index(drop=True)


def _shp_in_zip(zpath: Path, contains: str = "") -> str:
    names = [n for n in zipfile.ZipFile(zpath).namelist()
             if n.lower().endswith(".shp") and contains in n]
    if len(names) != 1:
        raise ValueError(f"{zpath}: expected one .shp matching {contains!r}, found {names}")
    return f"zip://{zpath.as_posix()}!{names[0]}"


def prepare_nbac(ranges: gpd.GeoDataFrame | None = None) -> None:
    print("[prepare] NBAC")
    ranges = read_interim("ranges") if ranges is None else ranges
    frames = []
    for z in sorted((C.RAW / "nbac").glob("NBAC_*.zip")):
        src = _shp_in_zip(z)
        cols = [c for c in ("YEAR", "NFIREID", "ADJ_HA", "POLY_HA", "PRESCRIBED", "VERSION")
                if c in pyogrio.read_info(src)["fields"]]
        g = pyogrio.read_dataframe(src, columns=cols)
        g = g.to_crs(C.AREA_CRS)
        g["geometry"] = polygonal(g.geometry.values)
        g = g[g.geometry.notna()]
        g = _touching_ranges(g, ranges)
        frames.append(g)
        print(f"  {z.name}: {len(g):,} perimeters touch a range")
    out = gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), crs=C.AREA_CRS)
    out["YEAR"] = out["YEAR"].astype(int)
    write(out, "fires_nbac")


def prepare_cnfdb(ranges: gpd.GeoDataFrame | None = None, first_year: int = 1950) -> None:
    print("[prepare] CNFDB")
    ranges = read_interim("ranges") if ranges is None else ranges
    # The zip holds 1972-2020 and 2021-2024 shapefiles. The federal footprint
    # merged CNFDB 1981-2020, so the baseline reconstruction uses the first;
    # post-2020 fires come from NBAC.
    src = _shp_in_zip(C.RAW / "cnfdb" / "NFDB_poly.zip", contains="to2020")
    fields = pyogrio.read_info(src)["fields"]
    cols = [c for c in ("YEAR", "SRC_AGENCY", "FIRE_ID", "SIZE_HA", "CAUSE", "SRC_AGY2")
            if c in fields]
    g = pyogrio.read_dataframe(src, columns=cols, where=f"YEAR >= {first_year}")
    print(f"  read {len(g):,} polygons since {first_year}")
    g = g.to_crs(C.AREA_CRS)
    g["geometry"] = polygonal(g.geometry.values)
    g = g[g.geometry.notna()]
    g = _touching_ranges(g, ranges)
    g["YEAR"] = g["YEAR"].astype(int)
    write(g, "fires_cnfdb")


def prepare_all() -> None:
    ranges = prepare_ranges()
    for edition in (2020, 2015):
        for name in ("buffered", "total"):
            prepare_footprint(name, edition)
    prepare_features()
    prepare_nbac(ranges)
    prepare_cnfdb(ranges)


if __name__ == "__main__":  # pragma: no cover
    prepare_all()
