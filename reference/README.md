# Reference data

`official_2020_disturbance.csv` - per-range disturbance in 2020 as published by the
federal government (data behind Figure 2, "Disturbance in boreal caribou ranges as of
2020", in *Report on the Progress of Recovery Strategy Implementation for the Woodland
Caribou, Boreal population, in Canada for the Period 2017-2022*, ECCC, May 2024).
Whole percentages of range area: fire only, fire and human overlapping, human only
(buffered 500 m), total, and the maximum disturbance allowed (35%; 60% for SK1).

Source: https://www.canada.ca/en/environment-climate-change/services/species-risk-public-registry/report-progress-recovery-document/caribou-rangifer-tarandus-boreal-report-progress-recovery-strategy-2017-2022-action-plan-2018-2023.html

Range codes follow the report (SK1 = Saskatchewan Boreal Shield, SK2 = Boreal Plain).
The federal range layer's CODE field swaps the two; see `caribou/config.py`.

The report states that 21 of 51 ranges meet their threshold on 2020 data; counting
ranges with `total_pct <= max_disturbance_pct` in this table gives the same 21
(Brightsand, ON4, is exactly at 35%).
