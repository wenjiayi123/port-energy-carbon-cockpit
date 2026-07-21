# Dataset contract

## Canonical CSV

| Column | Unit | Meaning |
|---|---|---|
| `period` | ISO month/date | source observation period |
| `split` | `train` or `test` | immutable fitting boundary |
| `loaded_import_teu` | TEU/period | loaded imports |
| `loaded_export_teu` | TEU/period | loaded exports |
| `total_teu` | TEU/period | total container throughput |
| `grid_carbon_kg_per_kwh` | kgCO2e/kWh | location/time-specific grid factor |
| `electricity_price_per_kwh` | CNY/kWh | scenario or metered electricity price |
| `fuel_price_per_liter` | CNY/liter | scenario or purchased fuel price |
| `source_id` | text | provenance key |

Additional columns are allowed and remain available to a future environment
extension. Required numeric columns must be non-negative.

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

The same parameters may be placed once in the adjacent metadata file under
`environment_parameters`. Set `temporal_mode` to `profiled_period` for aggregate
monthly/daily rows, or `sequential_rows` for immutable hourly TOS/EMS snapshots.

Place repository datasets in `backend/app/data/datasets/<id>.csv` and add
`<id>.metadata.json` with source URLs, license/terms, attribution, units,
assumptions, split policy, and scope limits. External absolute CSV paths are also
accepted.

## Default public benchmark

`port_la_2025_monthly.csv` uses official monthly container statistics published
by the Port of Los Angeles. The grid factor is the U.S. EPA eGRID 2023 CAMX total
output rate, converted from 429.983 lb/MWh to 0.19504 kg/kWh. Electricity and fuel
prices are explicitly marked CNY-denominated scenario assumptions; they are not
claimed as Port of Los Angeles published values.

This dataset does not include AIS identities, berth calls, terminal equipment,
weather, yard occupancy, AGV batteries, or renewable-generation telemetry. The
environment's hourly demand profile is deterministic and synthetic, while the
monthly throughput anchor and grid factor are sourced public values.

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
  --environment-config /data/verified_terminal_parameters.json \
  --source-id my_terminal_tos \
  --source-url https://example.invalid/data-catalog \
  --license proprietary-authorized
```

For live integration, build a read-only extractor from TOS/EMS/AIS into this
contract, version snapshots in object storage, and train from immutable snapshots.
With `sequential_rows` plus verified physical columns or metadata, the same
environment, five algorithms, API, and dashboard run without code changes. Do
not train directly from a mutable production table.

NOAA provides downloadable historical vessel traffic/AIS data that can be used
for a future movement-demand adapter: [NOAA AccessAIS](https://coast.noaa.gov/digitalcoast/data/vesseltraffic.html).
