# Fire vs Caribou: updating Canada's boreal caribou habitat scorecard

Draft, 2026-11-09. Everything under "First-look results" is a quick test, not a finished result.

## One-line pitch

Canada's law says each boreal caribou herd needs 65% of its range undisturbed. The national map stops in 2020. We update it through the record fire years with the method Canada uses, and show which herds have fallen through the line.

## Competition context

- **Event:** STEM Fellowship National High School Big Data & AI Challenge 2026-27, Canada West Conference.
- **Theme:** "Preserving Biodiversity and Advancing Land's Environmental Resilience Using Open Data, Satellite Intelligence and AI". The theme page names wildfires and invasive species outbreaks and asks teams to identify patterns, predict risks and propose data-driven solutions.
- **Constraints:** open data only; laptops, Google Colab, Google Earth Engine.
- **Deliverables:** manuscript (Jan 10, 2027), poster and 3-minute one-slide talk (Jan 17, 2027), conference (Feb 5, 2027).
- **Judging:** no rubric is published. Awards are for the poster, the talk and the manuscript. Judges are generalists.

## The problem

- Under the federal recovery strategy for boreal woodland caribou (Species at Risk Act), each of the 51 ranges needs **at least 65% undisturbed habitat**. One exception: Saskatchewan's Boreal Shield range (SK1) has a **40%** threshold. The strategy ties 65% to roughly a 60% chance that a local population is self-sustaining (confirm against the strategy text before quoting).
- **Official definition of disturbed:** human footprint visible on Landsat (roads, seismic lines, cutblocks, well sites, mines, etc.) buffered by 500 m, plus areas burned in the last 40 years.
- The federal footprint has been updated every five years: 2010, 2015, 2020. The 2020 layer was published in July 2024. The federal government says 21 of 51 ranges meet their threshold on 2020 data.
- 2023 and 2025 were Canada's largest and second-largest fire seasons on record.
- **Who needs the answer:** Environment and Climate Change Canada, provinces and territories writing range plans, Indigenous governments, NGOs.
- **Gap:** regional counts exist (the Alberta Biodiversity Monitoring Institute measured the 2023 burn in Alberta, a joint conservation-group letter reported it by range, and a Wildlife Science Centre tracker covers BC and Alberta ranges with fire to 2024). What is missing is a **national update using the federal method**. Four separate searches found none.

## Research questions

1. How many of the 51 ranges meet their threshold after the 2021-2025 fires, and which crossed the line?
2. How much new human disturbance (cutblocks, pads) has appeared since 2020 that the official map does not have?
3. For each range, how much of the habitat lost since 2020 is from fire and how much from industry?
4. When would each range cross back above its threshold if nothing else burned and nothing else was built?
5. Which ranges are most likely to cross the line by 2030?

## Deliverables

1. **Scorecard:** percent undisturbed for all 51 ranges, 2020 vs 2025, at full resolution with an uncertainty band, under the official rule and under a human-only rule. Headline only crossings that fall outside the band.
2. **Detector:** a model that maps new polygonal human disturbance since 2020, tested on held-out ranges against the federal 2020 layer.
3. **Fire vs industry split and recovery year** for every range, in an open notebook that can be re-run each year.
4. **Forecast (small):** probability that each range is below its threshold by 2030.

Stretch only: a burn-severity adjustment (unburned patches inside fire perimeters), and a U-Net comparison for the detector.

## Data (all open)

| Dataset | Use | Where |
| --- | --- | --- |
| Federal 2020 disturbance footprint and range boundaries | Baseline scorecard, training labels | ArcGIS map service: `https://maps-cartes.ec.gc.ca/arcgis/rest/services/STB_DGST/DisturbanceFootprintUpdatedFor2020/MapServer` (Open Government record: "2020 - Anthropogenic disturbance footprint within boreal caribou ranges across Canada") |
| Canadian National Fire Database (CNFDB) fire polygons | Fires 1981-2020, the dataset the federal layer merged in; use it to age out old fires | Canadian Wildland Fire Information System datamart (not yet opened by us) |
| National Burned Area Composite (NBAC) | Fire perimeters 2021-2025 | `https://cwfis.cfs.nrcan.gc.ca/downloads/nbac/` (yearly zips, 1972-2025 as of Nov 2026) |
| Landsat Collection 2 Level-2 | 30 m time series, 1984 onward | Earth Engine, or Microsoft Planetary Computer `landsat-c2-l2` |
| Sentinel-2 L2A | 10 m imagery, 2017 onward | Earth Engine, or Planetary Computer `sentinel-2-l2a` |
| Google Satellite Embedding V1 | Learned 64-value summary of each 10 m pixel per year, for the detector | Earth Engine; annual layers from 2017, with a cloud copy reported to reach 2025 (not yet checked by us) |
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

Method used: federal layers 3 and 4 plus NBAC perimeters, rasterized on 1 km and 500 m grids in NBAC's Lambert projection. 2025 undisturbed = 1 minus the share covered by (2020 total disturbance, with 1981-1985 fires aged out unless under buffered human footprint) plus fires of 2021-2025. Range and footprint outlines were simplified to about 300 m. The first look aged out old fires using NBAC, not the CNFDB polygons that are in the federal baseline. SK1 is scored against 40%, all other ranges against 65%.

| Measure | Result |
| --- | --- |
| Ranges meeting their threshold in 2020 (our reproduction) | 21 of 51, matching the official figure (20 at 65%, plus SK1 at 40%) |
| Ranges meeting their threshold after 2021-2025 fires | 14 to 16 |
| Range area burned 2021-2025 | about 193,000 km2, 8.3% of all range area (2023 alone: 3.4%) |
| Of that, ground not already counted as disturbed | about 116,000 km2 |
| Ranges with more than 10% of area burned in five years | 21 |
| Ranges that lost more than 10 points | 9 |
| Ranges that recovered above 65% as old fires aged out | 0 |
| Largest difference between 1 km and 500 m grids | 0.9 points (2020), 1.3 points (2025) |

Ranges that crossed below their threshold:

| Range | 2020 | 2025 | Read as |
| --- | --- | --- | --- |
| Atikaki-Berens | 69% | 52% | Clear crossing |
| Kississing | 68% | 54% | Clear crossing |
| Manitoba North | 67% | 56% | Clear crossing |
| Brightsand | 65% | 63% | Inside the uncertainty; do not headline |
| Northwest Territories (largest range) | 70% | 63-64% | Inside the uncertainty; do not headline |
| Wapisu | above 65% | 65.7% | Crosses only if old fires are not aged out |
| Saskatchewan Boreal Shield (SK1, threshold 40%) | 43% | 35-42% | Crosses only if old fires are not aged out |

Largest falls among ranges already below the line: Calendar 40% to 13% (67% of the range burned in 2021-2025), Owl-Flintstone 57% to 33% (about 47% burned), Snake-Sahtahneh 21% to 11% (51% burned), Maxhamish 32% to 20% (33% burned), Naosap 39% to 25% (29% burned).

Ranges within 3 points of the 65% line in 2025 (most sensitive to method choices): Manouane, William Lake, Wapisu, Quebec, Churchill, Brightsand, Nipigon, Manitoba East, Northwest Territories.

Range names above are as spelled in the federal layer, with obvious typos corrected (the layer has "Atikaki-Bernes" and "Owl-Flinstone").

## Method

### 1. Scorecard

1. Download layers 2, 3 and 4 at full resolution, per herd.
2. Reproduce the official 2020 percent undisturbed for every range and reconcile range by range with the official table. The count already matches (21 of 51).
3. Build the 2025 fire layer: CNFDB polygons for the part of the 40-year window up to 2020 (so the fires aged out are the ones actually in the baseline), NBAC for 2021-2025. Say so in the methods. Confirm the window with the federal department.
4. Recompute. Report each range with a band from: grid or vector method, with and without ageing out old fires, and preliminary vs final 2025 perimeters.
5. Repeat under a **human-only rule** (no fire). A Journal of Wildlife Management study from Alberta's Richardson range (Konkolics and colleagues) reportedly found caribou avoid burns but that using burned areas did not lower adult female survival, so a judge may ask whether fire should count at all. The gap between the two rules shows how much the answer depends on that assumption.
6. Headline only crossings whose whole band is below the threshold.

### 2. Detector for new human disturbance

- **Task:** label each pixel as intact forest, burned, or newly cleared by people.
- **Labels:** federal features with `Year_added = 2020` (positives), fire perimeters (burned), untouched forest away from any footprint (negatives).
- **Features, option A (test first):** Google Satellite Embedding V1, one 64-value vector per 10 m pixel per year. Use the embedding for 2020, for 2025, and their difference.
- **Features, option B (baseline to beat):** yearly summer Landsat/Sentinel-2 indices (NBR, NDVI, NDMI): value before and after, size of the largest drop, year of the largest drop, recovery slope.
- **Model:** random forest or gradient-boosted trees (Earth Engine `smileRandomForest` / `smileGradientTreeBoost`, or scikit-learn / XGBoost in Colab).
- **Validation:** train on some ranges, test on ranges never seen; report precision, recall and polygon-level detection against the federal 2020 layer.
- **Apply:** run on 2020-2025, remove anything inside fire perimeters, buffer new clearings by 500 m, add to the scorecard.
- **Out of scope:** narrow seismic lines and roads (thinner than a pixel). State this up front.

Pilot (one 824 km2 window in the Quebec range, about 49.62-49.88 N, 76.2-75.8 W, Landsat 30 m):

- Labels: 148 cutblock polygons added in 2020, 2,020 ha.
- One feature (drop in NBR from 2014-15 to 2020-21): AUC 0.86. At a 1% false-alarm rate it caught 24% of cutblock pixels and 11% of polygons.
- Why it is weak: "added in 2020" covers anything cut between 2015 and 2020, and older cuts have already regrown.
- Applied to 2020-21 to 2025-26: 153 new clearings of 2 ha or more (2,261 ha) that are in neither the federal map nor any fire perimeter. Unvalidated.
- Ranges with the most cutblocks added in 2020: Quebec 4,702; Pagwachuan 1,131; Saskatchewan Boreal Plain 924; Nipigon 867.

### 3. Fire vs industry split and the recovery clock

- **Split:** for each range, new disturbed area since 2020 from fire and from the detector's clearings (buffered 500 m), with overlap assigned to whichever came first.
- **Recovery clock:** under the federal rule a fire counts for 40 years and then ages out; industrial footprint counts until someone restores it. For each range, compute the year it would cross back above its threshold with no new fire and no new industry. Fire-driven ranges recover on their own (the 2021-2025 burns age out between 2061 and 2065). Industry-driven ranges never do without restoration. This turns the split into a policy result: which herds need time and which need restoration.

### 4. Forecast

A simulation, not a trained model. For each range, resample its annual burned fraction from the fire record, add the recent rate of new human disturbance, age out old fires, and report the share of runs below the threshold in 2030.

## Poster and talk

- **Hook:** "Canada's law says each caribou herd needs 65% of its range undisturbed. The national map stops in 2020. We updated it with the method Canada uses, and found which herds have fallen through the line since."
- **Hero image:** one range before and after its fires in satellite false colour. Beside it, a slope chart of all 51 ranges from 2020 to 2025 with the threshold line across it and the falling herds in red.
- **Hero range options:** Atikaki-Berens is the cleanest crossing. Calendar is the most dramatic burn but was already far below the line. Owl-Flintstone (57% to 33%, already below the line) was hit by the 2025 Nopiming fire, which reportedly drew national news coverage about the herd.
- **Supporting figures:** recovery year per range; fire vs industry bars; detector accuracy on held-out ranges; map of new clearings.

## Schedule

| Date | Milestone |
| --- | --- |
| Nov 13 | Decide between this idea and the budworm backup (see "Backups") |
| Nov 20 | Scorecard reproduced at full resolution with CNFDB; federal department emailed |
| Nov 30 | 2025 scorecard with uncertainty bands under both rules; hero image chosen |
| Dec 14 | Detector trained and tested on held-out ranges; split and recovery years |
| Dec 21 | Forecast done; manuscript draft; search again for a federal update |
| Jan 10 | Manuscript due |
| Jan 17 | Poster and one-slide talk due |
| Feb 5 | Canada West Conference |

## Week-one checklist

- [ ] Confirm SK1's 40% threshold and the 21-of-51 figure in the federal sources.
- [ ] Swap the aged-out 1981-1985 fires to the CNFDB polygons used in the federal layer.
- [ ] Reconcile per-range 2020 values with the official table.
- [ ] Check whether NBAC 2025 perimeters are final or preliminary.
- [ ] Email the federal department: which 40-year window, and is a 2025 update planned?
- [ ] Pilot the embedding detector on the same 824 km2 Quebec window and compare with AUC 0.86.
- [ ] Compute the recovery year for the three clearly crossing ranges.
- [ ] Compare the 153 pilot clearings with the federal forest-harvest layer.
- [ ] Re-run the scorecard with unsimplified geometry.
- [ ] Ask the organizers how AI is weighted in judging.

## Questions a judge will ask

| Question | Answer |
| --- | --- |
| Fire is natural. Should it count at all? | The federal definition counts fires of the last 40 years. We report results under the official rule and under a human-only rule, and show the gap. |
| Isn't this just an overlay? | The scorecard is. The detector for post-2020 industry, the fire vs industry split and the recovery clock are new. |
| How sure are you about a range at 64%? | We give a band per range and headline only crossings outside it. |
| Did you match the official numbers? | Yes at the count level: 21 of 51 in 2020. Per-range reconciliation is a week-one task. |
| Hasn't someone already counted the burned habitat? | Regionally, yes, in Alberta and BC. Nobody has published a national update with the federal method. |
| What if the government publishes first? | The 2020 layer came out four years after its data year, so a 2025 layer before February is unlikely. If it does, ours is an independent check, and the detector, the split and the recovery clock are still ours. |

## Risks

- Method details differ from the official one (fire dataset, window, buffering), shifting ranges near the line.
- The detector underperforms. Fallback: report the fire-only scorecard as a lower bound on disturbance, and present the detector as work in progress with honest accuracy.
- The AI component reads as secondary to judges. Mitigation: the detector and forecast are in the main deliverables.
- The federal department publishes its own update before February (low, given its past pace).

## Not yet verified

These come from our earlier shortlist or from a second review that read most sources through search excerpts. Open each source before quoting it.

- SK1's 40% threshold, and the 21-of-51 official figure.
- That the federal layer used CNFDB polygons for 1981-2020, and its July 2024 publication date.
- Whether NBAC 2025 is final.
- The regional counts (ABMI, joint letter, Wildlife Science Centre tracker).
- The Konkolics caribou-and-burns study.
- Satellite Embedding V1 coverage (annual from 2017; 2025 in the cloud copy).
- The Nopiming fire and Owl-Flintstone news coverage.
- The 153 pilot clearings (no comparison with a harvest map yet).
- The 60% self-sustaining probability attached to the 65% threshold.

## How this idea was chosen

Eight ideas were tested with first looks in real data and scored by an independent AI reviewer over three rounds on impact, wow, novelty, evidence, rigor and theme fit. This idea scored highest: impact 9, wow 8, novelty 7, evidence 8, rigor 7, theme 9. A second review kept it first and added the recovery clock to address novelty, its weakest point.

## Backups

- **Budworm meets the 2023 fire year (untested).** Inside Quebec's 2023 burn, did forest defoliated by spruce budworm burn more than matched forest that was not? Data: Quebec's yearly defoliation polygons, 2023 fire perimeters, ecoforest maps, fire-weather grids. First check: what share of the 2023 burn inside the intensive protection zone had three or more years of defoliation. Under 10%, drop it. **Decision rule for Nov 13:** pick budworm only if the overlap passes and a crude matched comparison shows a gap; otherwise build caribou.
- **Snow geese and the Hudson Bay coast.** Has goose-damaged marsh recovered as goose numbers decline, and where? A matched-control Landsat test at five sites found damage at four, with recovery varying by site. Open gaps: flooding, erosion, tides and uplift are not separated from grazing. Next step: ask the Arctic Goose Joint Venture whether a coast-wide recovery map would change any decision.
- **Other untested candidates from the second review:** emerald ash borer (use Winnipeg's losses to build an early warning for Calgary), and an invasive leafy spurge finder with satellite embeddings.

Dropped: reclaimed well sites (no difference from same-age clearings), overwintering-fire watch-list (36 cases in 12 years), Kakhovka reservoir forest (already published by several teams), beavers in the Arctic (look-alike thaw lakes), beaver ponds as fire refuges (no beaver signal at three sites), emperor penguins (off-theme).
