"""Project-wide constants: paths, projections, thresholds, data URLs.

Everything that encodes a method choice lives here so that the methods
section of the manuscript can point at one file.
"""

from __future__ import annotations

import os
from pathlib import Path

# ---------------------------------------------------------------- paths
ROOT = Path(os.environ.get("CARIBOU_ROOT", Path(__file__).resolve().parents[1]))
DATA = ROOT / "data"
RAW = DATA / "raw"            # untouched downloads
INTERIM = DATA / "interim"    # cleaned vectors, per-range pixel tables
OUTPUTS = ROOT / "outputs"    # tables and figures that go in the paper
REFERENCE = Path(__file__).resolve().parents[1] / "reference"  # published figures (in the repo)
TABLES = OUTPUTS / "tables"
FIGURES = OUTPUTS / "figures"

for _p in (RAW, INTERIM, TABLES, FIGURES):
    _p.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------- projections
# The federal service serves EPSG:3978 (NAD83 / Canada Atlas Lambert), which is
# conformal, not equal-area. All area work is done in Canada Albers Equal Area.
SOURCE_CRS = "EPSG:3978"
AREA_CRS = "ESRI:102001"

# ---------------------------------------------------------------- method constants
BUFFER_M = 500                 # federal buffer on anthropogenic features
FIRE_WINDOW_YEARS = 40         # a fire counts as disturbance for 40 years
BASELINE_YEAR = 2020           # data year of the latest federal footprint
UPDATE_YEAR = 2025             # latest complete fire season in NBAC
DEFAULT_THRESHOLD = 0.65
THRESHOLDS = {"SK1": 0.40}     # Saskatchewan Boreal Shield exception

# The federal range layer (layer 4, CODE field) swaps the two Saskatchewan
# codes relative to the recovery strategy and the federal 2020 mapping summary
# (SK1 = Boreal Shield, SK2 = Boreal Plain). Codes are reassigned by HERD name
# so that the 40% exception lands on the Boreal Shield range.
CODE_BY_HERD = {
    "Saskatchewan Boreal Shield": "SK1",
    "Saskatchewan Boreal Plain": "SK2",
}

# Federal baseline merged CNFDB fires 1981-2020 (service description).
# A fire of year Y counts in data year D when D - WINDOW + 1 <= Y <= D.
def window_start(data_year: int, window: int = FIRE_WINDOW_YEARS) -> int:
    return data_year - window + 1


def threshold_for(code: str) -> float:
    return THRESHOLDS.get(code, DEFAULT_THRESHOLD)


# ---------------------------------------------------------------- data sources
FED_SERVICE = (
    "https://maps-cartes.ec.gc.ca/arcgis/rest/services/STB_DGST/"
    "DisturbanceFootprintUpdatedFor2020/MapServer"
)
# The 2015 edition: its buffered layer (official 2015 human footprint) gives the
# 2015->2020 industrial growth rate, and its total layer (fires 1976-2015) is a
# second, independent test of our fire reconstruction.
FED_SERVICE_2015 = FED_SERVICE.replace("UpdatedFor2020", "UpdatedFor2015")
FED_SERVICES = {2020: FED_SERVICE, 2015: FED_SERVICE_2015}
FED_LAYERS = {
    "lines": 0,          # linear anthropogenic disturbances (Class, Year_added, HERD)
    "polygons": 1,       # polygonal anthropogenic disturbances
    "buffered": 2,       # anthropogenic disturbance buffered 500 m (one feature per herd)
    "total": 3,          # buffered + 40-year CNFDB fire (official total)
    "ranges": 4,         # 51 ranges (HERD, CODE)
}

NBAC_INDEX = "https://cwfis.cfs.nrcan.gc.ca/downloads/nbac/"
NBAC_FIRST_YEAR = 1972
CNFDB_URL = (
    "https://cwfis.cfs.nrcan.gc.ca/downloads/nfdb/fire_poly/current_version/"
    "NFDB_poly.zip"
)

# Typos in the federal layer, corrected for display only (joins use raw names).
NAME_FIXES = {
    "Atikaki-Bernes": "Atikaki-Berens",
    "Owl-Flinstone": "Owl-Flintstone",
}


def display_name(herd: str) -> str:
    return NAME_FIXES.get(herd, herd)


# ---------------------------------------------------------------- raster engine
DEFAULT_RES = 100.0     # metres; 30 m reproduces Landsat-scale mapping
TILE_PX = 4096          # tile edge in pixels

# Pixel-table year encoding: year - YEAR0 stored in a uint8; 0 means "never".
YEAR0 = 1900
