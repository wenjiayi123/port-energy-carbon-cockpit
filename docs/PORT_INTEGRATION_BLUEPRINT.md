# Real-port integration blueprint

This repository is ready for a terminal-approved data connection, not for
unreviewed production dispatch. The production contract is
`PortEnergyDispatchEnv-v3`; it fails closed until every required feed and
operator gate is present.

## What stays unchanged

All ports use the same five executable methods:

| Method | Family | Action contract |
| --- | --- | --- |
| PPO | reinforcement learning | 4 continuous controls |
| SAC | reinforcement learning | 4 continuous controls |
| TD3 | reinforcement learning | 4 continuous controls |
| DQN | reinforcement learning | 81 explicit `3×3×3×3` combinations |
| MPC | control theory | constrained four-step beam search |

The controls are shore-power ratio `[0, 1]`, active crane ratio `[0.6, 1]`,
active yard-resource ratio `[0.6, 1]`, and battery power ratio `[-1, 1]`.
Positive battery power discharges to the port load.

The step reward is implemented in `backend/app/rl/environment.py`:

```text
0.65 × processed_teu / demand_teu
+ w_carbon × (-carbon_kg / 6000)
+ w_shore × shore_power_ratio
+ w_cost × (-cost / 12000)
+ w_delay × (-delay_minutes / 90)
+ w_safety × (-4 × safety_violation)
+ w_peak × (-(load_kw / grid_capacity_kw)²)
+ w_storage × terminal_soc_restoration_term
```

The weights are normalized at runtime. Hard grid, equipment-availability,
battery SOC, terminal SOC, berth, shore-compatibility and delay constraints
remain separate from the soft objective.

## Production observation contract

The v3 environment contains 35 normalized observations:

- 19 energy-dispatch observations: demand and three-hour forecasts, backlog,
  grid carbon, price, fuel price, grid headroom, storage state and previous
  action, time encodings, cargo mix, cumulative carbon and delay.
- 6 port-activity observations: vessels at anchor, at berth and departed,
  average days at berth and in port, plus source-observation quality.
- 10 deployment observations: wind, wave, visibility, precipitation, berth,
  crane, yard and grid availability, shore-power compatibility, and onsite
  renewable power.

Weather values are observations. Terminal-approved safety logic must convert
local operating limits into availability ratios; the project does not invent
universal wind, wave or visibility shutdown thresholds.

## Integration sequence

1. Copy one live template in `configs/ports.yaml` and set the port ID,
   timezone, currency and local regulatory profile.
2. Export immutable hourly snapshots from the TOS, EMS, berth/vessel,
   equipment, weather/navigation and shore-power registries.
3. Map the snapshot with `scripts/prepare_port_dataset.py`. Sequential data
   must include a real timestamp column and source URLs.
4. Keep chronological `train`, `validation` and `test` partitions. Fit
   normalizers and policies on `train`; select hyperparameters on
   `validation`; access `test` only for the final report and replay.
5. Replace scenario parameters with terminal-approved rated capacity,
   equipment loads, storage limits, tariffs, carbon factors and delay costs.
6. Validate the package through `/api/rl/datasets/validate` and confirm the
   CSV, metadata and package SHA-256 values.
7. Train PPO, SAC, TD3 and DQN with `render_mode=None`; run the constrained MPC
   comparator under the same data and objective profiles.
8. Run held-out evaluation, drift checks, artifact hashing and dry-run
   verification. Visual replay is generated only after training.
9. Connect identity, audit and human authorization. Keep
   `production_dispatch_authorized: false` until the terminal owner accepts
   the field test.
10. Enable production dispatch only through a separately reviewed connector;
    changing a scenario file alone never authorizes a physical command.

Example mapper:

```bash
python scripts/prepare_port_dataset.py \
  --input exports/terminal_hourly.csv \
  --output backend/app/data/datasets/my_port_v1.csv \
  --temporal-mode sequential_rows \
  --time-col observed_at_utc \
  --environment-id PortEnergyDispatchEnv-v3 \
  --port-id MYPORT \
  --timezone Asia/Kuala_Lumpur \
  --currency MYR \
  --source-id terminal-approved-snapshot-2026q2 \
  --source-url https://data-owner.example/evidence/2026q2 \
  --license "Terminal-approved internal use" \
  --wind-speed-col wind_m_s \
  --wave-height-col wave_m \
  --visibility-col visibility_km \
  --precipitation-col precipitation_mm \
  --berth-available-ratio-col berth_available_ratio \
  --crane-available-ratio-col crane_available_ratio \
  --yard-available-ratio-col yard_available_ratio \
  --grid-available-ratio-col grid_available_ratio \
  --shore-power-compatible-ratio-col shore_compatible_ratio \
  --renewable-power-available-col onsite_renewable_kw
```

Map the remaining canonical cargo, energy and vessel fields using the matching
CLI options shown by `python scripts/prepare_port_dataset.py --help`.

## International deployment factors

The registry includes Los Angeles, Rotterdam and Singapore templates. It
records IMO decarbonization context and local regulatory work as requirements,
not automated legal conclusions. A new port must supply local tariffs, grid
rules, equipment ratings, shore-power standards, weather operating limits,
labor and maintenance constraints, carbon-accounting method and audit
retention before field acceptance.

The common decarbonization context follows the
[2023 IMO GHG Strategy](https://www.imo.org/en/mediacentre/hottopics/pages/cutting-ghg-emissions.aspx).
The Rotterdam template also flags
[EU Alternative Fuels Infrastructure Regulation](https://eur-lex.europa.eu/eli/reg/2023/1804/2026-01-08/eng)
shore-side electricity requirements. These links define review inputs; they do
not make the software a compliance determination engine.
