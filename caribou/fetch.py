"""Download the open datasets the project uses.

* Federal 2020 disturbance footprint (ArcGIS MapServer, layers 0-4).
  The service caps queries at 2,000 records, so features are fetched by
  OBJECTID in chunks. Geometry is requested in the native EPSG:3978 at full
  resolution (no ``maxAllowableOffset``), rounded to 0.1 m.
* National Burned Area Composite (NBAC) yearly perimeters, 1972 onward.
* Canadian National Fire Database (CNFDB) polygons: the fire source the
  federal footprint merged for 1981-2020.

All downloads are idempotent: files already on disk are skipped.
"""

from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

from . import config as C

USER_AGENT = "caribou-scorecard/0.1 (STEM Fellowship Big Data Challenge research)"
SESSION = requests.Session()
SESSION.headers["User-Agent"] = USER_AGENT


def _get(url: str, *, params=None, data=None, timeout=300, retries=5, stream=False):
    """GET/POST with exponential backoff."""
    for attempt in range(retries):
        try:
            if data is not None:
                r = SESSION.post(url, data=data, timeout=timeout, stream=stream)
            else:
                r = SESSION.get(url, params=params, timeout=timeout, stream=stream)
            r.raise_for_status()
            return r
        except (requests.RequestException,) as exc:  # pragma: no cover - network
            if attempt == retries - 1:
                raise
            wait = 2 ** attempt * 3
            print(f"  retry {attempt + 1}/{retries} after {exc!r}; sleeping {wait}s")
            time.sleep(wait)


# ---------------------------------------------------------------- federal service
def layer_ids(layer: int, service: str = C.FED_SERVICE) -> list[int]:
    r = _get(f"{service}/{layer}/query",
             params={"where": "1=1", "returnIdsOnly": "true", "f": "json"})
    return sorted(r.json()["objectIds"])


def fed_dir(name: str, edition: int = 2020) -> Path:
    return C.RAW / ("fed" if edition == 2020 else f"fed{edition}") / name


def _query_geojson(layer: int, ids: list[int], timeout: int = 600,
                   service: str = C.FED_SERVICE) -> dict:
    payload = {
        "objectIds": ",".join(map(str, ids)),
        "outFields": "*",
        "returnGeometry": "true",
        "outSR": "3978",
        "geometryPrecision": "1",
        "f": "geojson",
    }
    r = _get(f"{service}/{layer}/query", data=payload, timeout=timeout)
    gj = r.json()
    if "error" in gj:
        raise RuntimeError(f"layer {layer}: {gj['error']}")
    return gj


def fetch_layer(name: str, chunk: int | None = None, workers: int = 4,
                edition: int = 2020) -> Path:
    """Download one federal layer to ``data/raw/fed[2015]/<name>/part_*.geojson``.

    Large per-herd layers (buffered, total) are fetched one feature per
    request; line and polygon layers in chunks of 1,000.
    """
    layer = C.FED_LAYERS[name]
    service = C.FED_SERVICES[edition]
    out = fed_dir(name, edition)
    out.mkdir(parents=True, exist_ok=True)
    if (out / "_COMPLETE").exists():
        print(f"[fed{edition}:{name}] already complete")
        return out
    if chunk is None:
        chunk = 1 if name in ("buffered", "total") else (25 if name == "ranges" else 1000)
    ids = layer_ids(layer, service)
    parts = [ids[i:i + chunk] for i in range(0, len(ids), chunk)]
    todo = [(k, p) for k, p in enumerate(parts) if not (out / f"part_{k:05d}.geojson").exists()]
    print(f"[fed{edition}:{name}] layer {layer}: {len(ids)} features, {len(parts)} parts, {len(todo)} to fetch")

    def job(k, p):
        gj = _query_geojson(layer, p, service=service)
        n = len(gj.get("features", []))
        if n != len(p):
            raise RuntimeError(f"layer {layer} part {k}: asked {len(p)} got {n}")
        tmp = out / f"part_{k:05d}.geojson.tmp"
        tmp.write_text(json.dumps(gj))
        tmp.replace(out / f"part_{k:05d}.geojson")
        return k

    with ThreadPoolExecutor(max_workers=1 if chunk == 1 else workers) as ex:
        futs = [ex.submit(job, k, p) for k, p in todo]
        for i, f in enumerate(as_completed(futs), 1):
            f.result()
            if i % 25 == 0 or i == len(futs):
                print(f"  [fed:{name}] {i}/{len(futs)}")
    (out / "_COMPLETE").write_text(str(len(ids)))
    return out


# ---------------------------------------------------------------- fire data
def _download(url: str, dest: Path) -> Path:
    if dest.exists():
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with _get(url, stream=True, timeout=600) as r:
        with open(tmp, "wb") as fh:
            for block in r.iter_content(1 << 20):
                fh.write(block)
    tmp.replace(dest)
    return dest


def nbac_listing() -> dict[int, str]:
    """Map year -> latest yearly NBAC zip filename on the CWFIS datamart."""
    html = _get(C.NBAC_INDEX, timeout=60).text
    found: dict[int, str] = {}
    for fname in set(re.findall(r'href="(NBAC_(\d{4})_(\d{8})\.zip)"', html)):
        name, year, stamp = fname[0], int(fname[1]), fname[2]
        if year not in found or stamp > found[year][1]:
            found[year] = (name, stamp)
    return {y: v[0] for y, v in sorted(found.items())}


def fetch_nbac(first_year: int = C.NBAC_FIRST_YEAR, last_year: int = C.UPDATE_YEAR,
               workers: int = 3) -> list[Path]:
    listing = nbac_listing()
    years = [y for y in listing if first_year <= y <= last_year]
    missing = sorted(set(range(first_year, last_year + 1)) - set(years))
    if missing:
        print(f"[nbac] WARNING: no yearly zip for {missing}")
    dest = C.RAW / "nbac"
    print(f"[nbac] {len(years)} yearly files ({years[0]}-{years[-1]})")
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_download, C.NBAC_INDEX + listing[y], dest / listing[y]): y for y in years}
        for f in as_completed(futs):
            f.result()
    (dest / "_VERSION").write_text("\n".join(listing[y] for y in years))
    return [dest / listing[y] for y in years]


def fetch_cnfdb() -> Path:
    print("[cnfdb] NFDB_poly.zip (~750 MB)")
    return _download(C.CNFDB_URL, C.RAW / "cnfdb" / "NFDB_poly.zip")


def fetch_all() -> None:
    for name in ("ranges", "buffered", "total", "polygons", "lines"):
        fetch_layer(name)
    for name in ("buffered", "total"):
        fetch_layer(name, edition=2015)
    fetch_nbac()
    fetch_cnfdb()


if __name__ == "__main__":  # pragma: no cover
    fetch_all()
