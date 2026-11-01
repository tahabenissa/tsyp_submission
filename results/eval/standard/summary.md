# Standard scenario results (file mode, development sites)

Sites: azmet, fawn, kansas. Episodes per detector: 756. Fit on the train years, scored on the validation year. Run time 12.5 min.

## False alarms on the clean validation year

| detector      |   false_alarms_per_station_year |   worst_site |   day_share |
|:--------------|--------------------------------:|-------------:|------------:|
| M             |                            1.66 |         2.99 |        0.01 |
| S             |                            4.66 |         5.99 |        0.01 |
| S or M        |                            6.32 |         6.99 |        0.02 |
| S:cusum       |                            2.66 |         3.99 |        0.01 |
| S:mahalanobis |                            2.00 |         2.99 |        0.01 |
| S:replay      |                            0.00 |         0.00 |        0.00 |
| S:trend       |                            3.66 |         6.99 |        0.08 |

Per site:

| detector      |   azmet |   fawn |   kansas |
|:--------------|--------:|-------:|---------:|
| M             |    2.99 |   2.00 |     0.00 |
| S             |    2.99 |   4.99 |     5.99 |
| S or M        |    5.99 |   6.99 |     5.99 |
| S:cusum       |    1.00 |   3.99 |     2.99 |
| S:mahalanobis |    2.00 |   1.00 |     2.99 |
| S:replay      |    0.00 |   0.00 |     0.00 |
| S:trend       |    0.00 |   6.99 |     3.99 |

## Detection per attack (S = detector S combined flag, M = detector M)

| detector   | attack   | relative_to   | rate (95% CI)           |   median_latency_days |   median_abs_onset_error_days |
|:-----------|:---------|:--------------|:------------------------|----------------------:|------------------------------:|
| M          | drift    | range         | 84/144 = 58% (50%-66%)  |                 54.00 |                        nan    |
| M          | drift    | std           | 5/144 = 3% (1%-8%)      |                102.00 |                        nan    |
| M          | drift    | value         | 48/144 = 33% (26%-41%)  |                 54.50 |                        nan    |
| M          | replay   |               | 33/36 = 92% (78%-97%)   |                  0.00 |                        nan    |
| M          | step     | range         | 48/96 = 50% (40%-60%)   |                 16.50 |                        nan    |
| M          | step     | std           | 9/96 = 9% (5%-17%)      |                  5.00 |                        nan    |
| M          | step     | value         | 31/96 = 32% (24%-42%)   |                 19.00 |                        nan    |
| S          | drift    | range         | 136/144 = 94% (89%-97%) |                 30.00 |                         24.00 |
| S          | drift    | std           | 71/144 = 49% (41%-57%)  |                 48.00 |                         36.00 |
| S          | drift    | value         | 117/144 = 81% (74%-87%) |                 40.00 |                         27.00 |
| S          | replay   |               | 36/36 = 100% (90%-100%) |                  0.00 |                          1.00 |
| S          | step     | range         | 86/96 = 90% (82%-94%)   |                  6.50 |                          2.00 |
| S          | step     | std           | 34/96 = 35% (27%-45%)   |                 27.50 |                          6.50 |
| S          | step     | value         | 67/96 = 70% (60%-78%)   |                 12.00 |                          3.00 |
| S or M     | drift    | range         | 137/144 = 95% (90%-98%) |                 31.00 |                        nan    |
| S or M     | drift    | std           | 73/144 = 51% (43%-59%)  |                 52.00 |                        nan    |
| S or M     | drift    | value         | 120/144 = 83% (76%-89%) |                 40.50 |                        nan    |
| S or M     | replay   |               | 36/36 = 100% (90%-100%) |                  0.00 |                        nan    |
| S or M     | step     | range         | 87/96 = 91% (83%-95%)   |                  6.00 |                        nan    |
| S or M     | step     | std           | 37/96 = 39% (29%-49%)   |                 23.00 |                        nan    |
| S or M     | step     | value         | 72/96 = 75% (65%-83%)   |                 12.00 |                        nan    |

## Detector S detection rate per variable

| variable    |   ('drift', 'range') |   ('drift', 'std') |   ('drift', 'value') |   ('step', 'range') |   ('step', 'std') |   ('step', 'value') |
|:------------|---------------------:|-------------------:|---------------------:|--------------------:|------------------:|--------------------:|
| rh_pct      |                 0.81 |               0.25 |                 0.78 |                0.75 |              0.21 |                0.71 |
| solar_mj_m2 |                 1.00 |               0.69 |                 0.97 |                0.96 |              0.54 |                0.88 |
| temp_c      |                 1.00 |               0.67 |                 0.97 |                1.00 |              0.46 |                0.83 |
| wind_ms     |                 0.97 |               0.36 |                 0.53 |                0.88 |              0.21 |                0.38 |

## Detector S parts

| detector      | attack   | relative_to   |   detected |   episodes |   detection_rate |   median_latency_days |
|:--------------|:---------|:--------------|-----------:|-----------:|-----------------:|----------------------:|
| S:cusum       | drift    | range         |     129.00 |     144.00 |             0.90 |                 34.00 |
| S:cusum       | drift    | std           |      61.00 |     144.00 |             0.42 |                 52.00 |
| S:cusum       | drift    | value         |     106.00 |     144.00 |             0.74 |                 41.50 |
| S:cusum       | replay   |               |      29.00 |      36.00 |             0.81 |                  1.00 |
| S:cusum       | step     | range         |      79.00 |      96.00 |             0.82 |                  8.00 |
| S:cusum       | step     | std           |      28.00 |      96.00 |             0.29 |                 25.50 |
| S:cusum       | step     | value         |      61.00 |      96.00 |             0.64 |                 12.00 |
| S:mahalanobis | drift    | range         |     112.00 |     144.00 |             0.78 |                 40.00 |
| S:mahalanobis | drift    | std           |      30.00 |     144.00 |             0.21 |                 59.50 |
| S:mahalanobis | drift    | value         |      74.00 |     144.00 |             0.51 |                 48.00 |
| S:mahalanobis | replay   |               |      35.00 |      36.00 |             0.97 |                  0.00 |
| S:mahalanobis | step     | range         |      73.00 |      96.00 |             0.76 |                 10.00 |
| S:mahalanobis | step     | std           |      18.00 |      96.00 |             0.19 |                 29.50 |
| S:mahalanobis | step     | value         |      49.00 |      96.00 |             0.51 |                 14.00 |
| S:replay      | drift    | range         |       0.00 |     144.00 |             0.00 |                nan    |
| S:replay      | drift    | std           |       0.00 |     144.00 |             0.00 |                nan    |
| S:replay      | drift    | value         |       0.00 |     144.00 |             0.00 |                nan    |
| S:replay      | replay   |               |      36.00 |      36.00 |             1.00 |                  0.00 |
| S:replay      | step     | range         |       0.00 |      96.00 |             0.00 |                nan    |
| S:replay      | step     | std           |       0.00 |      96.00 |             0.00 |                nan    |
| S:replay      | step     | value         |       0.00 |      96.00 |             0.00 |                nan    |
| S:trend       | drift    | range         |      99.00 |     144.00 |             0.69 |                 45.00 |
| S:trend       | drift    | std           |      32.00 |     144.00 |             0.22 |                 60.50 |
| S:trend       | drift    | value         |      79.00 |     144.00 |             0.55 |                 51.00 |
| S:trend       | replay   |               |       3.00 |      36.00 |             0.08 |                  5.00 |
| S:trend       | step     | range         |      64.00 |      96.00 |             0.67 |                 32.50 |
| S:trend       | step     | std           |      19.00 |      96.00 |             0.20 |                 39.00 |
| S:trend       | step     | value         |      50.00 |      96.00 |             0.52 |                 37.50 |
