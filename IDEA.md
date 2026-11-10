# Fire vs Caribou: updating Canada's boreal caribou habitat scorecard

Draft, 2026-11-09. Everything under "First-look results" is a quick test, not a finished result.

## One-line pitch

Canada's law says a boreal caribou herd needs 65% of its range undisturbed. The official map stops in 2020. We update it through the record fire years and show which herds have fallen through the line.

## Competition context

- **Event:** STEM Fellowship National High School Big Data & AI Challenge 2026-27, Canada West Conference.
- **Theme:** "Preserving Biodiversity and Advancing Land's Environmental Resilience Using Open Data, Satellite Intelligence and AI". The theme page names wildfires and invasive species outbreaks and asks teams to identify patterns, predict risks and propose data-driven solutions.
- **Constraints:** open data only; laptops, Google Colab, Google Earth Engine.
- **Deliverables:** manuscript (Jan 10, 2027), poster and 3-minute one-slide talk (Jan 17, 2027), conference (Feb 5, 2027).
- **Judging:** no rubric is published. Awards are for the poster, the talk and the manuscript. Judges are generalists.

## The problem

- Under the federal recovery strategy for boreal woodland caribou (Species at Risk Act), each of the 51 ranges needs **at least 65% undisturbed habitat**. The strategy ties 65% to roughly a 60% chance that a local population is self-sustaining (confirm against the strategy text before quoting).
- **Official definition of disturbed:** human footprint visible on Landsat (roads, seismic lines, cutblocks, well sites, mines, etc.) buffered by 500 m, plus areas burned in the last 40 years.
- The federal footprint has been updated every five years: 2010, 2015, 2020. A May 2024 federal progress report said 21 of 51 ranges met the threshold, using pre-2023 data (figure taken from our earlier shortlist; not re-checked).
- 2023 and 2025 were Canada's largest and second-largest fire seasons on record.
- **Who needs the answer:** Environment and Climate Change Canada, provinces and territories writing range plans, Indigenous governments, NGOs.
- **Gap:** four separate searches found no national update after the 2023 fires, only figures for single ranges (e.g. ENGO letters on Alberta ranges).

## Research questions

1. How many of the 51 ranges are at or above 65% undisturbed after the 2021-2025 fires, and which crossed the line?
2. How much new human disturbance (cutblocks, pads) has appeared since 2020 that the official map does not have?
3. For each range, how much of the habitat lost since 2020 is from fire and how much from industry?
4. Which ranges are most likely to cross the line by 2030?

## Deliverables

1. **Scorecard:** percent undisturbed for all 51 ranges, 2020 vs 2025, at full resolution with an uncertainty band. Headline only crossings that fall outside the band.
2. **Classifier:** a model that maps new polygonal human disturbance since 2020, tested on held-out ranges against the federal 2020 layer.
3. **Fire vs industry split** for every range, in an open notebook that can be re-run each year.
4. **Forecast (small):** probability that each range is below 65% by 2030.

Stretch only: a burn-severity adjustment (unburned patches inside fire perimeters), and a U-Net comparison for the classifier.

## Data (all open)

| Dataset | Use | Where |
| --- | --- | --- |
| Federal 2020 disturbance footprint and range boundaries | Baseline scorecard, training labels | ArcGIS map service: `https://maps-cartes.ec.gc.ca/arcgis/rest/services/STB_DGST/DisturbanceFootprintUpdatedFor2020/MapServer` (Open Government record: "2020 - Anthropogenic disturbance footprint within boreal caribou ranges across Canada") |
| National Burned Area Composite (NBAC) | Fire perimeters by year | `https://cwfis.cfs.nrcan.gc.ca/downloads/nbac/` (yearly zips, 1972-2025 as of Nov 2026) |
| Landsat Collection 2 Level-2 | 30 m time series, 1984 onward | Earth Engine, or Microsoft Planetary Computer `landsat-c2-l2` |
| Sentinel-2 L2A | 10 m imagery, 2017 onward | Earth Engine, or Planetary Computer `sentinel-2-l2a` |
| Federal forest-harvest layer (CA Forest Harvest 1985-2022) | Cross-check detected clearings | Suggested by a reviewer; not yet opened by us |

Map service layers:

| Layer | Content | Key fields |
| --- | --- | --- |
| 0 | Linear anthropogenic disturbances 2020 | `Class`, `Year_added`, `HERD` |
| 1 | Polygonal anthropogenic disturbances 2020 | `Class`, `Year_added`, `HERD` |
| 2 | Anthropogenic disturbances buffered by 500 m | `HERD` |
| 3 | Buffered anthropogenic disturbances merged with 40-year fire data (the official total) | `HERD` |
| 4 | Boreal caribou ranges (federal recovery strategy 2012), 51 polygons | `HERD`, `CODE` |

Notes on access: the service returns at most 2,000 records per query, so page by `OBJECTID` or query per herd. `maxAllowableOffset` simplifies geometry; leave it out for final numbers.

`Year_added` counts (these are the training labels):

| Year added | Polygons (layer 1) | Lines (layer 0) |
| --- | --- | --- |
| 2010 | 66,392 | 250,417 |
| 2015 | 19,756 | 64,420 |
| 2020 | 28,055 | 19,424 |

Polygon classes, all years: Cutblock 50,212; Well site 40,314; Harvest 12,636; Mine 4,540; Settlement 3,330; Oil/Gas 1,610; Unknown 1,086; Agriculture 475.

## First-look results (2026-11-09)

Method used: federal layers 3 and 4 plus NBAC perimeters, rasterized on 1 km and 500 m grids in NBAC's Lambert projection. 2025 undisturbed = 1 minus the share covered by (2020 total disturbance, with 1981-1985 fires aged out unless under buffered human footprint) plus fires of 2021-2025. Range and footprint outlines were simplified to about 300 m.

| Measure | Result |
| --- | --- |
| Ranges at or above 65% in 2020 (our reproduction) | 20 of 51 (official figure: 21) |
| Ranges at or above 65% after 2021-2025 fires | 14 to 15 |
| Range area burned 2021-2025 | about 193,000 km2, 8.3% of all range area (2023 alone: 3.4%) |
| Of that, ground not already counted as disturbed | about 116,000 km2 |
| Ranges with more than 10% of area burned in five years | 21 |
| Ranges that lost more than 10 points | 9 |
| Ranges that recovered above 65% as old fires aged out | 0 |
| Largest difference between 1 km and 500 m grids | 0.9 points (2020), 1.3 points (2025) |

Ranges that crossed below 65%:

| Range | 2020 | 2025 | Read as |
| --- | --- | --- | --- |
| Atikaki-Berens | 69% | 52% | Clear crossing |
| Kississing | 68% | 54% | Clear crossing |
| Manitoba North | 67% | 56% | Clear crossing |
| Brightsand | 65% | 63% | Inside the uncertainty; do not headline |
| Northwest Territories (largest range) | 70% | 63-64% | Inside the uncertainty; do not headline |
| Wapisu | above 65% | 65.7% | Crosses only if old fires are not aged out |

Largest falls among ranges already below the line: Calendar 40% to 13% (67% of the range burned in 2021-2025), Owl-Flintstone 57% to 33% (48% burned), Snake-Sahtahneh 21% to 11% (51% burned), Maxhamish 32% to 20% (33% burned), Naosap 39% to 25% (29% burned).

Ranges within 3 points of the line in 2025 (most sensitive to method choices): Manouane, William Lake, Wapisu, Quebec, Churchill, Brightsand, Nipigon, Manitoba East, Northwest Territories.

Range names above are as spelled in the federal layer, with obvious typos corrected (the layer has "Atikaki-Bernes" and "Owl-Flinstone").

## Method

### 1. Scorecard

1. Download layers 2, 3 and 4 at full resolution, per herd.
2. Reproduce the official 2020 percent undisturbed for every range. Reconcile range by range with the official table and find which range explains 20 vs 21.
3. Build the 2025 fire layer: NBAC fires from the current 40-year window. Confirm with the federal department which fire dataset and window it uses.
4. Recompute. Report each range with a band from: grid or vector method, with and without ageing out old fires, and preliminary vs final 2025 perimeters.
5. Headline only crossings whose whole band is below 65%.

### 2. Classifier for new human disturbance

- **Task:** label each pixel as intact forest, burned, or newly cleared by people.
- **Labels:** federal features with `Year_added = 2020` (positives), NBAC perimeters (burned), untouched forest away from any footprint (negatives).
- **Features per pixel:** yearly summer Landsat/Sentinel-2 indices (NBR, NDVI, NDMI): value before and after, size of the largest drop, year of the largest drop, recovery slope. Optionally Google's AlphaEarth annual embeddings in Earth Engine (availability not yet checked).
- **Model:** random forest or gradient-boosted trees (Earth Engine `smileRandomForest` / `smileGradientTreeBoost`, or scikit-learn / XGBoost in Colab).
- **Validation:** train on some ranges, test on ranges never seen; report precision, recall and polygon-level detection against the federal 2020 layer.
- **Apply:** run on 2020-2025, remove anything inside fire perimeters, buffer new clearings by 500 m, add to the scorecard.
- **Out of scope:** narrow seismic lines and roads (thinner than a pixel). State this up front.

Pilot (one 824 km2 window in the Quebec range, about 49.62-49.88 N, 76.2-75.8 W, Landsat 30 m):

- Labels: 148 cutblock polygons added in 2020, 2,020 ha.
- One feature (drop in NBR from 2014-15 to 2020-21): AUC 0.86. At a 1% false-alarm rate it caught 24% of cutblock pixels and 11% of polygons.
- Why it is weak: "added in 2020" covers anything cut between 2015 and 2020, and older cuts have already regrown. Hence the multi-year features above.
- Applied to 2020-21 to 2025-26: 153 new clearings of 2 ha or more (2,261 ha) that are in neither the federal map nor any fire perimeter. Unvalidated.
- Ranges with the most cutblocks added in 2020: Quebec 4,702; Pagwachuan 1,131; Saskatchewan Boreal Plain 924; Nipigon 867.

### 3. Fire vs industry split

For each range: new disturbed area since 2020 from fire (NBAC) and from the classifier's clearings (buffered 500 m), with overlap assigned to whichever came first.

### 4. Forecast

A simulation, not a trained model. For each range, resample its annual burned fraction from the NBAC record, add the recent rate of new human disturbance, age out old fires, and report the share of runs below 65% in 2030.

## Poster and talk

- **Hook:** "Canada's law says a caribou herd needs 65% of its range undisturbed. The official map stops in 2020. We updated it: three herds have fallen through the line since, and nobody had counted."
- **Hero image:** one range (Calendar or Atikaki-Berens) before and after its fires in satellite false colour. Beside it, a slope chart of all 51 ranges from 2020 to 2025 with the 65% line across it and the falling herds in red.
- **Supporting figures:** fire vs industry bars per range; classifier accuracy on held-out ranges; map of new clearings.

## Schedule

| Date | Milestone |
| --- | --- |
| Nov 20 | Scorecard reproduced at full resolution; 20-vs-21 explained; federal department emailed |
| Nov 30 | 2025 scorecard with uncertainty bands; hero image chosen |
| Dec 14 | Classifier trained and tested on held-out ranges; fire vs industry split |
| Dec 21 | Forecast done; manuscript draft; search again for a federal update |
| Jan 10 | Manuscript due |
| Jan 17 | Poster and one-slide talk due |
| Feb 5 | Canada West Conference |

## Week-one checklist

- [ ] Reconcile the 2020 reproduction with the official table, range by range.
- [ ] Check whether NBAC 2025 perimeters are final or preliminary.
- [ ] Email the federal department: which fire dataset and which 40-year window?
- [ ] Compare the 153 pilot clearings with the federal forest-harvest layer.
- [ ] Re-run the scorecard with unsimplified geometry.
- [ ] Ask the organizers how AI is weighted in judging.

## Questions a judge will ask

| Question | Answer |
| --- | --- |
| Fire is natural. Why count it? | The federal definition counts fires of the last 40 years. We use the official method and also report fire and industry separately. |
| Isn't this just an overlay? | The scorecard is. The classifier for post-2020 industry and the fire vs industry split are new, and nobody has mapped them nationally. |
| How sure are you about a range at 64%? | We give a band per range and headline only crossings outside it. |
| Did you match the official numbers? | 20 of 51 against the official 21 so far; the reconciliation is a week-one task. |
| What if the government publishes first? | Then ours is an independent check, and the industry map and the split are still ours. |

## Risks

- The federal department publishes its own update before February.
- The classifier underperforms. Fallback: report the fire-only scorecard as a lower bound on disturbance, and present the classifier as work in progress with honest accuracy.
- Method details differ from the official one (fire dataset, window, buffering), shifting ranges near the line.
- The AI component reads as secondary to judges. Mitigation: the classifier and forecast are in the main deliverables.

## Not yet verified

- The 21-of-51 official figure and the per-range official table.
- Whether NBAC 2025 is final.
- The exact official fire dataset and 40-year window.
- The 153 pilot clearings (no comparison with a harvest map yet).
- AlphaEarth embedding availability in Earth Engine.
- The 60% self-sustaining probability attached to the 65% threshold.

## How this idea was chosen

Eight ideas were tested with first looks in real data and scored by an independent AI reviewer over three rounds on impact, wow, novelty, evidence, rigor and theme fit. This idea scored highest: impact 9, wow 8, novelty 7, evidence 8, rigor 7, theme 9. Its weakest points are novelty (the headline is the official method re-run with new data) and rigor (the items in the week-one checklist).

Backup: snow geese and the Hudson Bay coast (has goose-damaged marsh recovered since the geese left?). A matched-control Landsat test at five sites found damage at four, with recovery varying by site, but the confounders (flooding, erosion, tides, uplift) are unresolved.

Dropped: reclaimed well sites (no difference from same-age clearings), overwintering-fire watch-list (36 cases in 12 years), Kakhovka reservoir forest (already published by several teams), beavers in the Arctic (look-alike thaw lakes), beaver ponds as fire refuges (no beaver signal at three sites), emperor penguins (off-theme).
