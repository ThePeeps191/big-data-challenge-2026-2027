# Manuscript outline

Working notes for the STEM Fellowship HSBDC 2026-27 manuscript (due **2027-01-10**).
Every number below comes from a file in `outputs/tables/`; the file is named next to it
so the text can be refreshed when the pipeline is re-run. `[cite: n]` points to
[`REFERENCES.md`](REFERENCES.md).

Status markers: **(done)** result exists and is final for the manuscript; **(prelim)** result
depends on the 2026 hotspot-based perimeters (re-run when NBAC 2026 is published, expected
around May 2027); **(todo)** still to do.

## Official requirements (Google Classroom, 2026-27 HSBDC documents, read 2026-11-17)

Sources: *Manuscript Guidelines*, *Manuscript Rubric*, *Word Count FAQ*, *Program
Checkpoints*, *Checkpoint 2* and *LaTeX Overview* PDFs on the Classroom.

**Format**
- **Template:** the official Overleaf template is mandatory
  (https://www.overleaf.com/read/rpqgjmbkphfs; two-column, numbered references). Make a
  copy; change content, not layout.
- **Word limit:** **3,000 words, a hard limit.** Marks are deducted if you go over, and
  the paper becomes ineligible for SFJ. **Counted:** main body, headings, quotations,
  equations (one word each). **Excluded:** abstract, title and author information,
  keywords, acknowledgements, references, **tables and figures including their
  captions**, and in-text citations or figure references. Appendices are not listed, and
  the FAQ says "err on the side of caution", so **count appendix text**. Put detail in
  tables with full captions instead.
- **Title page:** title of 12 words or fewer, in Title Case; authors and affiliations;
  corresponding author's email; word count.
- **Keywords:** 3-5. **Abstract:** 250 words or fewer (hard limit; it is published on its
  own in the SFJ proceedings). No references or figure citations in it; cover aim,
  methods, results, conclusions and implications.

**Sections and content**
- **Introduction:** the research question tied to the theme; the variables; the
  datasets and why they suit the question.
- **Methods:**
  - Paragraph form, no bullets; reproducible; give the reasons for each choice.
  - For data: sources, variables, geographic and temporal coverage, cleaning and
    processing.
  - For ML/AI: why that model, features, training and testing procedure, parameters and
    evaluation metrics.
- **Results:** report all results, including those contrary to the hypothesis, and
  outliers. No interpretation. Give the ML benchmarks.
- **Discussion (double weight in the rubric):** paragraph form. Interpret against the
  objectives; compare with the literature; state limitations and future directions.
- **Conclusion:** one short paragraph. **Acknowledgements** are optional.
  **Appendices** are optional and may hold code, model details and extra tables.
- **References:** Vancouver style, [1].

**Rubric** (0-4 per category; Discussion counts double)
- Categories: Abstract, Introduction, Research Question, Methodology, Data Diversity,
  Figures/Tables, Results, Discussion, Relevance, References (quality), References
  (quantity), Language & Clarity, Formatting, Word Count.
- Full marks on References (quantity) need **at least 20 references**, and on quality,
  peer-reviewed sources "exclusively" (government reports are fine but lower).
- Figures and tables must each be necessary, with no redundancy.

**Deadlines**
- Nov 21, optional: annotated bibliography. At least 10 peer-reviewed sources; Vancouver
  citation, summary, relevance and limitations for each.
- Dec 5, optional: project proposal.
- **Jan 10: manuscript.** **Jan 17: poster and slide.** Feb 5: Canada West conference.

**Prizes**
- Top 2 posters and top 2 3-minute talks: money.
- Top 2 manuscripts: SFJ publication fee waiver (the fee is otherwise $400).

**How to fit 3,000 words**
- Main text carries the argument. Detail goes in **tables** (excluded with their
  captions): the per-range scorecard, detector comparison, 2026 calibration and data
  sources.
- Rough budget:
  - Introduction ~450
  - Methods ~1,000
  - Results ~600
  - Discussion ~800
  - Conclusion ~100
  - Headings ~50

## Title options (12 words or fewer, Title Case)

1. Wildfires Push Boreal Caribou Ranges Below Canada's Habitat Threshold (10 words)
2. Updating Canada's Boreal Caribou Habitat Scorecard After Record Wildfire Years (10 words)
3. Fire, Not Industry: Boreal Caribou Habitat Loss After 2020 (9 words)

## Argument in five sentences

1. Canada's recovery strategy requires each of 51 boreal caribou ranges to stay at least 65%
   undisturbed (40% for SK1), but the official disturbance map stops in 2020.
2. We rebuilt the federal map from its open parts, exactly (reproduction section), and
   extended it through the 2021-2025 fires and, preliminarily, 2026.
3. The number of ranges that clearly meet their threshold (whole uncertainty band above
   the line) fell from 21 (2020) to 14 (2025) and 13-14 (2026, preliminary; Nipigon's
   band edge is 64.96%). Five ranges that
   met the line in 2020 are now clearly below it (NWT, Kississing, Manitoba North,
   Atikaki-Berens, Brightsand) and three straddle it (SK1, Wapisu, Nipigon). All the
   crossings are fire-driven.
4. Fire-driven ranges recover on their own as burns age out of the 40-year window; industry-
   driven ranges never do without restoration. This triage tells managers which herds need
   time, which need restoration and which need protection now.
5. An AI detector built on open satellite embeddings finds 30 of 39 independently mapped
   2021-2022 harvest patches that no federal map records yet. It beats a classic burn
   index, which cannot separate clearings from fires or see well sites and regrowing cuts.
   Industry kept roughly its 2015-2020 pace while fire burned about 40 times more area,
   so the post-2020 collapse is a fire story.

## Sections

### Abstract (≤ 250 words, hard limit; published on its own in the SFJ proceedings)

Problem, gap, method in one sentence each; three headline numbers (ranges meeting 2020 /
2025 / 2026; area burned; crossings); the triage; detector accuracy; one sentence on use.

### 1. Introduction

- Boreal caribou: threatened under SARA; decline linked to habitat disturbance
  (disturbance-recruitment model) [cite: 1, 5].
- The 65% rule: 60% probability of a self-sustaining population; definition of disturbance
  (500 m buffer, 40-year fires); SK1 40% exception [cite: 1, 2].
- The federal map: 2010, 2015, 2020 editions; the 2020 edition published in 2024; 21 of 51
  ranges meet [cite: 3, 4].
- Record fires: 2023 largest, 2025 second-largest, 2026 [cite: 11, 12].
- Gap: regional tallies exist (ABMI for Alberta 2023; Wildlife Science Centre CHIP for AB and BC,
  fire to 2024, not comparable to 65%); no national update with the federal method.
- Research questions (the five in IDEA.md), stated as aims.

### 2. Data (Table 1)

| Dataset | Provider, version | Resolution / type | Years | Role | Licence |
| --- | --- | --- | --- | --- | --- |
| Anthropogenic disturbance footprint, 2015 and 2020 editions; 51 ranges | ECCC (2024 release) | Vector (Landsat-interpreted) | 2015, 2020 | Baseline, labels | OGL-Canada |
| Canadian National Fire Database (CNFDB) | NRCan-CFS, 2025-06-30 | Vector (agency perimeters) | 1972-2024 | Fires in the federal baseline; fire-source check | OGL-Canada |
| National Burned Area Composite (NBAC) | NRCan-CFS, v20260513 | Vector | 1972-2025 | Fires 2021-2025; annual burn record | OGL-Canada |
| Fire M3 Fire Perimeter Estimate | NRCan CWFIS | Vector (hotspot-based) | 2021-2026 | Preliminary 2026; calibration | OGL-Canada |
| Federal progress report, Figure 2 data | ECCC 2024 | Table | 2020 | Validation | OGL-Canada |
| Satellite Embedding V1 (AlphaEarth Foundations) | Google / Google DeepMind (Source Cooperative copy) | 10 m, 64 bands, annual | 2017-2025 | Detector features | CC-BY 4.0 |
| CA Forest Harvest | NRCan-CFS (Hermosilla et al. 2016) | 30 m raster (year) | 1985-2022 | Independent detector check | OGL-Canada |
| Sentinel-2 L2A | ESA Copernicus, via Microsoft Planetary Computer | 10-20 m | 2017-2026 | dNBR baseline; hero image | Copernicus licence |

### 3. Methods

3.1 **Rebuilding the federal footprint.** Pixel-class tables on a 100 m equal-area grid;
buffered human footprint + CNFDB 1981-2020 reproduces layer 3. Same for 2015. (Fig. S1 /
Table S1.)

3.2 **Update rules and uncertainty band.** Headline rule `official_adj`; four alternatives
(rebuild CNFDB / NBAC, no age-out, CNFDB 2021-2024 fire source) and a 250 m grid. Status =
meets / below only if the whole band is on one side. Human-only rule as sensitivity.

3.3 **Preliminary 2026.** Hotspot-based perimeter estimate, calibrated against NBAC
2021-2025 inside the ranges, by province (`prelim2026_calibration*.csv`,
`prelim2026_factors.csv`).

3.4 **Fire vs industry since 2020.** New fire ground vs projected industry (2015-2020 pace).

3.5 **Recovery clock.** Year each range is back above its threshold with no new disturbance;
ceiling set by the human footprint; restoration need.

3.6 **2030 outlook.** Monte Carlo (20,000 runs): bootstrap of each range's own annual burn
share, industry at its 2015-2020 rate ×0.5-1.5, 40-year age-out; restarted from 2026.

3.7 **Detector for new clearings (AI).** Satellite Embedding V1 (64-D, 10 m) + 3-year change;
gradient-boosted trees; labels from federal polygons first mapped in 2020, NBAC burns and
intact forest; held-out ranges; seeded random windows; dNBR baseline (no AI).

### 4. Results

4.1 **Reproduction (done)** (`scorecard.csv`, `summary.json`):
- Our rebuild of the 2020 footprint from its parts (buffered human footprint + CNFDB
  1981-2020) agrees with the official layer on 99.84-100% of pixels per range (median
  difference 0.0001 points). The 2015 edition rebuilds to a 0.28-point median.
- All 51 per-range shares are within the report's whole-% rounding (max 0.50 points).
- The count is 21 of 51, the same as published. Brightsand is 64.8% in the layers but
  published as exactly 65%.
- A fresh download on 2026-11-17 reproduces the committed 2025 values exactly.

4.2 **2025 scorecard (done)** (Fig. 1, Fig. 2, `final_table.csv`):
- 202,150 km² of range (8.3%) burned in 2021-2025; 120,273 km² of it was not already
  disturbed. 45,473 km² came back as the 1981-85 fires aged out.
- 14 ranges meet their threshold with the whole band; 16 if the band only has to reach it.
- Clear crossings: Kississing 67→50%, Atikaki-Berens 68→51%, Manitoba North 66→55%, NWT
  70→64%, Brightsand 65→62% (borderline in 2020).
- 20 ranges had more than 10% of their area burn, and 8 lost more than 10 points.
- Fire-source check: CNFDB perimeters map 4-11% more burned area than NBAC in 2021-2024
  (up to 35% in Saskatchewan). The NBAC headline is therefore conservative, and no status
  changes.

4.3 **2026, preliminary (prelim)** (Fig. 7, `prelim2026*.csv`):
- The hotspot estimate overstates burned area; NBAC confirms 0.74-0.86 of it in each year
  2021-2025.
- Brightsand 62→54% (16.7% of the range burned, the Wabakimi fire); NWT 64→62%.
- Nipigon becomes uncertain (65.5%, band 65.0-67.2).
- 13 ranges clearly meet their threshold (14 if Nipigon's 64.96% band edge is read as
  65%).
4.4 Fire vs industry; the human-only rule (done): Fig. 4.
4.5 **Recovery clock and triage (done/prelim)** (Fig. 3, `final_table.csv`):
- 19 ranges need restoration: 57,412 km² of buffered footprint (largest: Chinchaga 14,156;
  East Side Athabasca 5,914; West Side Athabasca 5,858).
- 16 ranges need time: NWT back above the line by 2033, Brightsand by 2066, Kississing by
  2065.
- 6 are at risk and 10 are secure.

4.6 **2030 outlook (prelim)** (Fig. 5):
- Restarted from 2026: SK1, Wapisu and Nipigon are below in 94-100% of simulated 2030s.
  This is pessimistic: it uses the face-value 2026 burn plus industry catch-up at the full
  2015-2020 pace. Fig. 5 shows the 2025-state outlook; quote the 2026 restart from
  `final_table.csv`.
- From 2025: Pagwachuan 19%, North Interlake 12%, Quebec 8%.
- Human-only rule: 32 ranges would meet in 2020 and 2025.
4.7 **Detector (done)** (`detector_eval_windows.csv/json`, `detector_eval_windows_dnbr.json`,
`detector_pace.json`, Fig. 8):
- Design: 22 random industrial windows plus 7 burn windows, 232,100 labelled pixels from
  19 ranges, 5-fold cross-validation with whole ranges held out.
- Embedding-change model: AUC 0.90; 76% of federal 2020 polygons of at least 2 ha
  found; 19 ha of false "new" clearing per 100 km²; 77% of independent 2021-2022 NRCan
  harvest patches found.
- Full embedding model: AUC 0.94 and 88% of polygons, but 105 ha per 100 km² of false
  "new" clearing.
- dNBR over the same 3 years: AUC 0.52; it confuses clearings with burns.
- On NRCan 2018-2020 harvests vs intact: embedding change AUC 0.99 vs dNBR 0.94. dNBR
  fails on the rest of what the federal map adds (a third of 2020 polygons are not
  harvests).
- On the Quebec pilot blocks: pixel AUC 0.97-0.99 vs dNBR 0.56 on the same pixels (the
  IDEA pilot's single 6-year Landsat feature: 0.86).
- Independent harvest patches 2021-2022 found: 30 of 39 (small sample: give the count).
- Fire vs industry, selection-free (`harvest_by_range_year.csv`):
  - Inside the ranges, harvest cleared about 1,110 km²/yr in 2015-2020 and 990 km² in 2021
    (2022 is the map's last year and incomplete).
  - Fire burned 40,430 km²/yr in 2021-2025, of which 24,060 km²/yr was new ground.
  - The split (industry at the full 2015-2020 pace, buffered) gives fire 85% of the loss.
- Do not quote the windows' pace ratio (0.36): the windows were drawn where 2015-2020
  clearing was mapped, so it is biased low by design. Say so in Methods as a lesson.
- Say so in Methods: the change-only model was added after seeing the first two; all
  three are reported.

### 5. Discussion

- **Should fire count?**
  - Under the human-only rule, 32 ranges meet their threshold in 2020. The reported
    2021-2025 crossings come from fire alone, because the scorecard adds no post-2020
    industry. Industry since 2020 was about 1,000 km²/yr of harvest against about
    40,000 km²/yr burned.
  - Johnson et al. (2020) found fire's effect on recruitment three to four times smaller
    than human disturbance's [cite: 5]. Caribou avoid burns, but adult survival is not
    lower [cite: 6, 7, 8, 9].
  - So the crossings show where the legal threshold is breached, not necessarily where
    herds are failing. That is why the triage separates "needs time" from "needs
    restoration".
- **Fire source matters.**
  - NBAC maps less burned area than the CNFDB perimeters the federal map used [cite: 12].
  - We measured the gap for 2021-2024, kept NBAC for the headline, and showed that no
    status changes with CNFDB. Any future federal update should state which source it uses.
- **What the update cannot see.**
  - Post-2020 linear features (roads, seismic lines; below 10 m pixels).
  - Post-2020 industry outside the sampled windows (projected at the 2015-2020 pace, so
    2025 undisturbed values are an upper bound).
  - Burn severity and unburned islands inside perimeters (the federal rule ignores them too).
- **The 2026 numbers are preliminary.**
  - Hotspot perimeters are "very rough estimates" [cite: 13]. We calibrated them against
    NBAC, and their year-to-year ratio was stable (0.74-0.86).
  - Re-run when NBAC 2026 is released (about May 2027).
- **Forecast limits.** Years are independent (no drought persistence), fire lands at random
  relative to old burns (which understates new loss), and there is no climate trend. The
  2011-2025 record serves as a "recent climate" sensitivity.
- **Policy.**
  - (1) A national update every year instead of every five; the pipeline makes this
    nearly free.
  - (2) Triage: restore footprint where only restoration helps (19 ranges); protect from
    new disturbance where time heals (16); add fire-management priority where a range is
    at the line (6).
  - (3) An AI clearing detector on open embeddings can fill the 5-year gap for industry.

### 6. Conclusion

### Data and code availability

Repository, notebook, licences.

## Figures

| # | File | Message |
| --- | --- | --- |
| 1 | `fig1_slope_2020_2025` | 21 → 14-16 ranges; who fell |
| 2 | `fig7_status_2020_2026` | 2020 → 2025 → 2026 for the ranges that crossed |
| 3 | `fig6_status_map` | Where |
| 3b | `fig9_range_ON4` | One range up close: Brightsand and the 2026 Wabakimi fire |
| 4 | `fig3_recovery_clock_2026` | Time vs restoration (restarted from 2026; the original `fig3_recovery_clock` is the 2025 state) |
| 5 | `fig5_forecast_2030` | Who is next (2025 state; the 2026 restart for SK1, Wapisu and Nipigon is in `final_table.csv`) |
| 6 | `fig8_detector` | The AI finds clearings the map does not have |
| S | `fig2_scorecard_bands`, `fig4_fire_vs_industry`, `fig0_hero_MB12` | Supporting |
