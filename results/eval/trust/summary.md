# Trust score, responses and decisions (leave one site out)

Runs: 756 attacked + 3 clean site-years. Run time 15.7 min.

## Compromise probability on the held-out site

| site   |   brier |   brier_no_skill |   roc_auc |
|:-------|--------:|-----------------:|----------:|
| azmet  |   0.122 |            0.162 |     0.756 |
| fawn   |   0.132 |            0.162 |     0.725 |
| kansas |   0.139 |            0.162 |     0.719 |
| all    |   0.131 |            0.162 |     0.728 |

Reliability (all held-out days):

|         |       days |   mean_probability |   attacked_share |
|:--------|-----------:|-------------------:|-----------------:|
| 0.0-0.1 |  73968.000 |              0.070 |            0.104 |
| 0.1-0.2 | 119643.000 |              0.139 |            0.130 |
| 0.2-0.3 |  38657.000 |              0.247 |            0.235 |
| 0.3-0.4 |  17940.000 |              0.343 |            0.302 |
| 0.4-0.5 |   7189.000 |              0.445 |            0.461 |
| 0.5-0.6 |   4280.000 |              0.547 |            0.594 |
| 0.6-0.7 |   3016.000 |              0.641 |            0.696 |
| 0.7-0.8 |   3280.000 |              0.751 |            0.586 |
| 0.8-0.9 |   2952.000 |              0.851 |            0.763 |
| 0.9-1.0 |   6869.000 |              0.972 |            0.950 |

## Cost on honest stations (clean 2024)

| site   |   deweight_below |   quarantine_below |   deweighted_day_share |   quarantined_days_per_year |   quarantines_per_year |   verification_requests_per_year |   decision_days_changed_by_defence |
|:-------|-----------------:|-------------------:|-----------------------:|----------------------------:|-----------------------:|---------------------------------:|-----------------------------------:|
| azmet  |            0.584 |              0.313 |                  0.033 |                       0.000 |                  0.000 |                            0.998 |                              0.000 |
| fawn   |            0.557 |              0.402 |                  0.000 |                       0.000 |                  0.000 |                            0.000 |                              0.000 |
| kansas |            0.568 |              0.337 |                  0.090 |                      28.941 |                  0.998 |                            1.996 |                              0.011 |

## Responses during the attack

| attack   | relative_to   |   episodes | de-weighted             |   median days to de-weight | quarantined             |   median days to quarantine |   mean weight during attack |
|:---------|:--------------|-----------:|:------------------------|---------------------------:|:------------------------|----------------------------:|----------------------------:|
| drift    | range         |        144 | 126/144 = 88% (81%-92%) |                      34.00 | 108/144 = 75% (67%-81%) |                       40.50 |                        0.56 |
| drift    | std           |        144 | 57/144 = 40% (32%-48%)  |                      50.00 | 21/144 = 15% (10%-21%)  |                       47.00 |                        0.91 |
| drift    | value         |        144 | 106/144 = 74% (66%-80%) |                      37.50 | 82/144 = 57% (49%-65%)  |                       40.50 |                        0.68 |
| replay   |               |         36 | 29/36 = 81% (65%-90%)   |                       0.00 | 30/36 = 83% (68%-92%)   |                        1.00 |                        0.32 |
| step     | range         |         96 | 78/96 = 81% (72%-88%)   |                       8.50 | 65/96 = 68% (58%-76%)   |                       13.00 |                        0.46 |
| step     | std           |         96 | 22/96 = 23% (16%-32%)   |                      31.00 | 12/96 = 12% (7%-21%)    |                       31.00 |                        0.90 |
| step     | value         |         96 | 63/96 = 66% (56%-74%)   |                      14.00 | 49/96 = 51% (41%-61%)   |                       19.00 |                        0.61 |

## Decisions: without (C0) and with (C4) the defence

| attack   | relative_to   |   episodes | C0 wrong decision (no defence)   | C4 wrong decision (full system)   | C4 wrong AND issued as TRUSTED   |   C0 wrong days |   C4 wrong days |   C4 wrong TRUSTED days |
|:---------|:--------------|-----------:|:---------------------------------|:----------------------------------|:---------------------------------|----------------:|----------------:|------------------------:|
| drift    | range         |        144 | 129/144 = 90% (84%-94%)          | 116/144 = 81% (73%-86%)           | 55/144 = 38% (31%-46%)           |            0.11 |            0.06 |                    0.02 |
| drift    | std           |        144 | 99/144 = 69% (61%-76%)           | 100/144 = 69% (61%-76%)           | 72/144 = 50% (42%-58%)           |            0.02 |            0.03 |                    0.02 |
| drift    | value         |        144 | 127/144 = 88% (82%-92%)          | 115/144 = 80% (73%-86%)           | 61/144 = 42% (35%-51%)           |            0.07 |            0.05 |                    0.02 |
| replay   |               |         36 | 21/36 = 58% (42%-73%)            | 19/36 = 53% (37%-68%)             | 1/36 = 3% (0%-14%)               |            0.16 |            0.14 |                    0.01 |
| step     | range         |         96 | 82/96 = 85% (77%-91%)            | 71/96 = 74% (64%-82%)             | 23/96 = 24% (17%-33%)            |            0.10 |            0.05 |                    0.02 |
| step     | std           |         96 | 65/96 = 68% (58%-76%)            | 67/96 = 70% (60%-78%)             | 51/96 = 53% (43%-63%)            |            0.02 |            0.03 |                    0.02 |
| step     | value         |         96 | 76/96 = 79% (70%-86%)            | 68/96 = 71% (61%-79%)             | 29/96 = 30% (22%-40%)            |            0.06 |            0.04 |                    0.01 |

Of the attacks that changed the decision without defence:

| attack   | relative_to   |   attacks that changed the decision without defence | still wrong with the full system   | wrong AND issued as TRUSTED   |
|:---------|:--------------|----------------------------------------------------:|:-----------------------------------|:------------------------------|
| drift    | range         |                                                 129 | 116/129 = 90% (84%-94%)            | 55/129 = 43% (34%-51%)        |
| drift    | std           |                                                  99 | 96/99 = 97% (91%-99%)              | 72/99 = 73% (63%-81%)         |
| drift    | value         |                                                 127 | 113/127 = 89% (82%-93%)            | 61/127 = 48% (40%-57%)        |
| replay   |               |                                                  21 | 18/21 = 86% (65%-95%)              | 1/21 = 5% (1%-23%)            |
| step     | range         |                                                  82 | 70/82 = 85% (76%-91%)              | 23/82 = 28% (19%-39%)         |
| step     | std           |                                                  65 | 64/65 = 98% (92%-100%)             | 51/65 = 78% (67%-87%)         |
| step     | value         |                                                  76 | 66/76 = 87% (77%-93%)              | 29/76 = 38% (28%-49%)         |

## Per variable

| variable    | attack   |   episodes |   deweighted |   quarantined |   wrong_c0 |   wrong_c4 |   wrong_trusted_c4 |
|:------------|:---------|-----------:|-------------:|--------------:|-----------:|-----------:|-------------------:|
| rh_pct      | drift    |        108 |         0.60 |          0.40 |       0.83 |       0.77 |               0.50 |
| rh_pct      | step     |         72 |         0.51 |          0.35 |       0.78 |       0.78 |               0.42 |
| solar_mj_m2 | drift    |        108 |         0.75 |          0.63 |       0.89 |       0.79 |               0.39 |
| solar_mj_m2 | step     |         72 |         0.68 |          0.56 |       0.79 |       0.60 |               0.25 |
| temp_c      | drift    |        108 |         0.88 |          0.72 |       0.88 |       0.81 |               0.33 |
| temp_c      | step     |         72 |         0.74 |          0.65 |       0.83 |       0.76 |               0.31 |
| wind_ms     | drift    |        108 |         0.44 |          0.20 |       0.69 |       0.69 |               0.52 |
| wind_ms     | step     |         72 |         0.33 |          0.19 |       0.69 |       0.72 |               0.46 |

## Fusion coefficients (one model per held-out site)

| site   |   intercept |   cusum_ratio |   cusum_recent |   maha_log |   replay_log |   trend_ratio |   gap7 |   gap30 |   m_flag |   m_recent |
|:-------|------------:|--------------:|---------------:|-----------:|-------------:|--------------:|-------:|--------:|---------:|-----------:|
| azmet  |       -2.87 |         -0.05 |           0.17 |       0.90 |         0.23 |         -0.57 |   1.34 |    1.51 |     0.73 |      -0.14 |
| fawn   |       -3.64 |          0.28 |          -0.03 |       0.55 |         0.01 |         -0.40 |   1.05 |    2.07 |     0.29 |      -0.20 |
| kansas |       -2.68 |          0.69 |           0.45 |       0.73 |         0.35 |         -1.40 |   1.67 |    1.54 |     0.20 |      -0.15 |

## Example actions: azmet step_temp_c_up_value_2024-04-15

| date                | action               |   trust | reason                                                                    |
|:--------------------|:---------------------|--------:|:--------------------------------------------------------------------------|
| 2024-03-23 00:00:00 | verification request |    0.58 | week-long gap against NASA POWER                                          |
| 2024-05-08 00:00:00 | verification request |    0.54 | month-long gap against NASA POWER; temp_c up, step since about 2024-04-12 |
| 2024-05-25 00:00:00 | verification request |    0.48 | month-long gap against NASA POWER                                         |
| 2024-06-08 00:00:00 | verification request |    0.36 | month-long gap against NASA POWER; temp_c up, step since about 2024-05-08 |
| 2024-06-13 00:00:00 | quarantine           |    0.31 | month-long gap against NASA POWER; temp_c up, step since about 2024-05-08 |
| 2024-06-13 00:00:00 | alert                |    0.31 | month-long gap against NASA POWER; temp_c up, step since about 2024-05-08 |
| 2024-07-05 00:00:00 | release              |    0.59 | agrees with its context again                                             |
