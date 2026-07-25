# Dataset contract

## Canonical CSV

| Column | Unit | Meaning |
|---|---|---|
| `period` | ISO month/date | source observation period |
| `split` | `train`, `validation`, or `test` | immutable fit/selection/final boundary |
| `loaded_import_teu` | TEU/period | loaded imports |
| `loaded_export_teu` | TEU/period | loaded exports |
| `total_teu` | TEU/period | total container throughput |
| `grid_carbon_kg_per_kwh` | kgCO2e/kWh | location/time-specific grid factor |
| `electricity_price_per_kwh` | CNY/kWh | scenario or metered electricity price |
| `fuel_price_per_liter` | CNY/liter | scenario or purchased fuel price |
| `source_id` | text | provenance key |

Additional columns are allowed. Required numeric columns must be non-negative;
availability and compatibility ratios must be within `[0, 1]`.

The bundled hourly public dataset also preserves EIA demand/carbon fields,
their quality code, the monthly EIA price anchor, official monthly total TEU,
and the source observation key.

For a terminal-calibrated environment, add these optional numeric columns to
the CSV. A value in the current row takes priority over metadata and code
defaults:

| Column | Unit | Meaning |
|---|---|---|
| `observation_hours` | hours | time covered by `total_teu` |
| `crane_capacity_teu_per_hour` | TEU/h | nominal quay-crane system capacity |
| `yard_capacity_teu_per_hour` | TEU/h | nominal yard system capacity |
| `shore_demand_kw` | kW | vessel auxiliary-load opportunity |
| `base_load_kw` | kW | fixed terminal electrical load |
| `load_kw_per_teu` | kW/TEU | variable handling load |
| `crane_load_kw`, `yard_load_kw` | kW | full-ratio equipment load |
| `grid_capacity_kw` | kW | terminal import limit |
| `fuel_kwh_per_liter` | kWh/liter | auxiliary-fuel energy conversion |
| `fuel_carbon_kg_per_liter` | kgCO2e/liter | verified fuel factor |
| `delay_cost_cny_per_minute` | CNY/min | declared operating-cost coefficient |
| `delay_limit_minutes` | minutes | safety/service constraint |
| `battery_capacity_kwh` | kWh | usable storage nameplate assumption |
| `battery_power_kw` | kW | charge/discharge rating |
| `battery_initial_soc`, `battery_min_soc`, `battery_max_soc` | ratio | storage SOC bounds |
| `battery_charge_efficiency`, `battery_discharge_efficiency` | ratio | one-way efficiency |
| `battery_degradation_cny_per_kwh` | CNY/kWh | scenario cycling-cost coefficient |
| `terminal_soc_tolerance` | ratio | end-of-episode SOC tolerance |
| `vessels_at_anchor`, `vessels_at_berth`, `vessels_departed` | vessels | aggregate port activity |
| `average_days_at_berth`, `average_days_in_port` | days | aggregate dwell observations |
| `port_activity_observed` | 0/1 | reported-source versus filled-row indicator |
| `wind_speed_m_s`, `wave_height_m`, `visibility_km`, `precipitation_mm` | source units | weather/navigation inputs |
| `berth_available_ratio`, `crane_available_ratio`, `yard_available_ratio` | ratio | terminal-approved availability |
| `grid_available_ratio` | ratio | available fraction of declared grid capacity |
| `shore_power_available_ratio`, `shore_power_compatible_ratio` | ratio | infrastructure and vessel compatibility |
| `renewable_power_available_kw` | kW | onsite zero-direct-emission supply available to the load |

The same parameters may be placed once in the adjacent metadata file under
`environment_parameters`. Set `temporal_mode` to `profiled_period` for aggregate
monthly/daily rows, or `sequential_rows` for immutable hourly TOS/EMS snapshots.

Place repository datasets in `backend/app/data/datasets/<id>.csv` and add
`<id>.metadata.json` with source URLs, license/terms, attribution, units,
assumptions, split policy, and scope limits. External absolute CSV paths are also
accepted.

All three temporal splits are required. Hyperparameters and checkpoints may be
selected using `validation`; the held-out `test` rows are reserved for the final
report and must never be passed to `model.learn`.

## Default public benchmark

`port_la_2020_2025_hourly.csv` contains 52,608 contiguous hours. It combines
72 official monthly Port of Los Angeles TEU anchors, U.S. EIA California
commercial monthly price anchors, and EIA Hourly Electric Grid Monitor LADWP
demand/consumed-carbon signals. Of 52,608 hours, 51,726 carbon values are
reported and 882 are explicitly quality-coded month-hour median imputations.

The chronological split is 2020–2023 train (35,064 rows), 2024 validation
(8,784), and 2025 held-out test (8,760). Monthly TEU is allocated through a
disclosed deterministic profile. LADWP commercial time-of-use periods provide
the intraday price shape, normalized back to each EIA monthly mean. EPA eGRID
CAMX is retained as an annual cross-check. The resulting hourly series is a
dispatch benchmark, not terminal telemetry or a port invoice.

Fuel price and terminal/storage physical parameters are declared scenario
assumptions. This dataset does not include AIS identities, berth calls, actual
equipment availability, yard occupancy, maintenance or renewable-procurement
telemetry.

## Vessel-activity enhanced benchmark

`port_la_2020_2024_vessel_activity_hourly.csv` contains 43,848 contiguous
hours and adds 1,238 official Port of Los Angeles business-day vessel-activity
rows. v2 uses six additional observations for anchor, berth, departure and
dwell state. Non-reporting days are explicitly interpolated and quality coded.
Use this package for new RL training; retain the 52,608-hour v1 package for the
longer energy-carbon benchmark and existing metric evidence.

## Replace with a port dataset

If the source already follows the canonical schema:

```bash
cd backend
.venv/bin/python -m app.rl.cli validate-data /data/my_port.csv
.venv/bin/python -m app.rl.cli train --algorithm sac --dataset /data/my_port.csv --total-steps 120000
```

If column names differ:

```bash
backend/.venv/bin/python scripts/prepare_port_dataset.py \
  --input /data/tos_export.csv \
  --output /data/my_port.csv \
  --period-col month \
  --split-col dataset_split \
  --import-col import_teu \
  --export-col export_teu \
  --total-col throughput_teu \
  --grid-carbon-col grid_kg_per_kwh \
  --electricity-price-col power_cny_per_kwh \
  --fuel-price-col fuel_cny_per_liter \
  --observation-hours-col interval_hours \
  --temporal-mode sequential_rows \
  --time-col observed_at_utc \
  --environment-id PortEnergyDispatchEnv-v3 \
  --environment-config /data/verified_terminal_parameters.json \
  --port-id my_port \
  --timezone Asia/Kuala_Lumpur \
  --currency MYR \
  --source-id my_terminal_tos \
  --source-url https://example.invalid/data-catalog \
  --license proprietary-authorized
```

Map every v3 weather, activity, availability, compatibility and renewable
column with the corresponding `--*-col` option. v3 rejects incomplete datasets.

For live integration, build a read-only extractor from TOS/EMS/AIS into this
contract, version snapshots in object storage, and train from immutable snapshots.
With `sequential_rows` plus verified physical columns or metadata, the same
environment, five algorithms, API, and dashboard run without code changes. Do
not train directly from a mutable production table.

NOAA provides downloadable historical vessel traffic/AIS data that can be used
for a future movement-demand adapter: [NOAA AccessAIS](https://coast.noaa.gov/digitalcoast/data/vesseltraffic.html).
