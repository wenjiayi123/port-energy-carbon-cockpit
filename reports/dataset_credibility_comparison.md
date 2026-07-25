# Public dataset credibility comparison

Evidence label: `PUBLIC_DATASET_COMPARISON_NOT_FIELD_TELEMETRY`

| Dimension | 2020–2025 energy-carbon benchmark | 2020–2024 vessel-activity enhanced benchmark |
| --- | ---: | ---: |
| Canonical hourly rows | 52,608 | 43,848 |
| Train / validation / test | 35,064 / 8,784 / 8,760 | 26,304 / 8,760 / 8,784 |
| Official port workload observations | 72 monthly TEU anchors | 60 monthly TEU anchors + 1,238 daily vessel-activity rows |
| Official hourly grid-carbon rows | 51,726 | 43,848-row subset of the same versioned EIA package |
| Port operations fields | monthly throughput only | anchor, berth, departed, berth dwell, total port dwell |
| Environment | v1, 19 observations | v2, 25 observations |
| Source corrections | none declared | four deterministic PDF corrections, all recorded in metadata |
| Missing/duplicate cells | 0 / 0 | 0 / 0 |

## Decision

Use the vessel-activity enhanced package for new RL training because it has
substantially higher port-operation information content and preserves daily
source provenance. Keep the 52,608-hour package and its existing benchmark
report unchanged as the longer energy-carbon evidence baseline.

The enhanced held-out MPC report covers the same 48 × 24-hour evaluation
budget. Against the same full-shore-power fixed-resource comparator it reports
8.904% carbon reduction, 8.215% scenario-cost reduction, 100.000% throughput
retention and 100% constraint satisfaction. Against the harder
validation-selected 80%/80% static comparator it reports 2.765% carbon
reduction and 2.108% cost reduction, with a 3.609% higher peak. These remain
offline scenario metrics, not field KPIs or evidence of RL superiority.

The enhanced package does not become terminal telemetry: non-reporting days are
explicit linear interpolations, hourly TEU remains a deterministic allocation,
and terminal meters, TOS events, equipment telemetry and field outcomes are not
present.

The NOAA AccessAIS national archive is a useful optional scale-up source for
vessel movement. NOAA's
[annual point-data summary](https://coast.noaa.gov/data/marinecadastre/ais/point-data-summary.pdf)
lists 3.1 billion records and 116.7 GB compressed for 2024, but AIS does not
contain terminal energy, crane, yard, tariff or verified TEU labels. Bulk AIS
size alone therefore does not make the dispatch objective more credible. Use a
spatially clipped, versioned AIS snapshot only when terminal geofences and
matching operational labels are available.

## Reproduction

```bash
make data-enhanced
PYTHONPATH=backend backend/.venv/bin/python -m app.rl.cli \
  validate-data port_la_2020_2024_vessel_activity_hourly
```

The adjacent dataset metadata records all source URLs, PDF SHA-256 values,
derived daily row counts, disclosed corrections, split rules and package hash.
