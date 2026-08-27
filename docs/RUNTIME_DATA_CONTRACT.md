# Realtime energy-carbon data contract

## Purpose and fixed boundary

`energy-carbon-runtime.v1` is the stable digital-twin contract used by the bundled simulator and
future site adapters. The application, prediction service, policy layer, approval workflow,
executor interface, receipt, KPI engine and audit view all consume this contract. A port cutover
replaces adapters, mappings and calibration parameters; it does not require a new user workflow or
new business API.

The bundled implementation always reports:

```text
simulation_mode=true
live_data_verified=false
dispatch_allowed=false
production_authority=false
```

## Field schema

Every item in `signals` is a `telemetry-field.v1` object:

| Field | Meaning |
| --- | --- |
| `field_id`, `value`, `unit` | Stable semantic identifier and unit-bearing current value. |
| `event_time`, `ingest_time` | Business/simulation occurrence time and API ingestion time, both timezone-aware UTC. |
| `source_type`, `source_id` | One of 公开观测、公开再分析、官方聚合、历史回放、物理模拟、工程派生、现场实测 and its concrete dataset/device/adapter. |
| `quality_status`, `confidence` | 正常、插值、延迟、漂移、失联、异常 plus a 0–1 confidence. |
| `is_measured`, `is_simulated`, `is_derived` | Exactly one must be true. Historical public measurement is not called live measurement. |
| `site_id`, `asset_id` | Stable site and asset addressing. |
| `schema_version`, `trace_id` | Contract version and end-to-end correlation identifier. |
| `source_record_time`, `assumption_id` | Original public-record time and documented engineering assumption where applicable. |

## Current signal families

| Family | Representative fields | Bundled source |
| --- | --- | --- |
| Public grid and tariff | regional demand, carbon factor, electricity price | EIA-930 observation; EIA monthly price plus disclosed LADWP time-of-use shaping |
| Electrical topology | grid import/frequency, transformer capacity/loading/reserve, site peak | Energy-conservation simulation and declared equipment ratings |
| Renewable energy | PV available power and step energy | Bounded daylight/cloud engineering model (`solar-profile-v1`) |
| BESS | SOC, SOH, power, temperature, efficiency, equivalent cycles, degradation cost | Charge/discharge conservation, efficiency, thermal and throughput-aging models |
| Shore power | opportunity, load and connected-vessel proxy | Official daily vessel anchors plus rated auxiliary demand assumptions |
| Port operations | TEU demand, processed TEU, queue, delay, vessels at berth/anchor | Official aggregate anchors plus deterministic hourly allocation and conservation |
| Equipment | quay/yard crane availability and utilization, AGV fleet and charging | Rated fleet state machine coupled to workload and injected faults |
| Buildings and reefer | HVAC, setpoint, lighting, illuminance, pumps/fans, connected reefers and load | Temperature, occupancy, daylight and cooling engineering equations |
| Market engineering calendar | demand-response active flag, flexible shed, engineering avoided cost | Explicit engineering events; never market settlement or revenue evidence |
| KPI and governance | energy, carbon, cost, service, safety, life cost, quality and provenance ratios | Derived from the same current state and action transition |

## Causality and physical constraints

- Public monthly TEU is not relabelled as hourly measurement. It is a deterministic hourly
  allocation with `is_derived=true` and interpolation quality.
- Official vessel rows remain official aggregates; non-report days remain explicit interpolation.
- Component demand drives transformer load. Increased workload therefore changes crane, yard,
  charging, reefer, base load, processed volume and queue state together.
- BESS power is bounded by rated power, SOC 10–90%, charge/discharge efficiency, thermal derating,
  SOH and available energy. Equivalent cycles and degradation cost accumulate from throughput.
- The safety projector curtails flexible AGV/HVAC demand before transformer capacity can be
  exceeded. Any remaining overload is a critical fail-closed condition.
- Demand-response value is an engineering avoided-cost estimate only. `settlement_evidence=false`.
- The random seed drives bounded disturbances only. A fixed seed and action sequence reproduce
  the same values.

## Quality gate

Prediction, recommendation and execution require all of the following:

1. simulator state is running;
2. no communication-loss condition;
3. energy-balance error is within tolerance;
4. no transformer overload;
5. no critical battery thermal condition;
6. field classifications pass schema validation.

If any condition fails, `decision_allowed=false`, the snapshot becomes `failed_closed`, and the
forecast/decision API returns HTTP 409. Stopping the simulator changes all field quality to `失联`
and confidence to zero.

## Future site adapter mapping

| Adapter to replace | Field prefix | Minimum real-port work |
| --- | --- | --- |
| EMS/grid-meter | `grid.*`, `transformer.*`, `demand_response.*` | Signed meter data, tariffs, transformer topology, time synchronization and calibration. |
| BMS | `battery.*` | Pack/rack topology, SOC/SOH validation, thermal limits, warranty curves and independent protection. |
| PV/renewable meter | `solar.*` | Inverter telemetry, curtailment state and metered generation. |
| BA | `hvac.*`, `lighting.*`, `pumps_fans.*`, `weather.*` | Sensor/actuator point list, engineering units, schedules and safe setpoint ranges. |
| TOS/yard system | `operations.*`, `equipment.*`, `reefer.*`, `charging.*` | Job events, equipment states, reefer/yard/AGV identifiers, queues and service rules. |
| Shore-power PLC/meter | `shore_power.*` | Vessel compatibility, connector state, protection/interlock status and metering. |
| Identity/audit | approval and command principal | SSO, named roles, two-person separation, immutable audit export and retention. |

Site adapters must emit the same `telemetry-field.v1` objects. A field becomes `现场实测` only
after its source, unit, timestamp, signature, calibration and quality gate are verified.

The aggregate runtime fields do not by themselves prove distribution-network safety. Named
single-line topology, switchgear, power-quality, transformer, charging and BMS evidence is
evaluated separately through `port-electrical-network-input.v1`; see
[Electrical network digital twin](ELECTRICAL_NETWORK_DIGITAL_TWIN.md). Its public default remains
blocked at 0/6 evidence domains and 0/14 gates.

## APIs

- `GET /api/runtime/contract`
- `GET /api/runtime/snapshot`
- `GET /api/runtime/history`
- `GET /api/runtime/forecast` and `/api/runtime/forecast/model`
- `GET /api/runtime/scenarios`
- `POST /api/runtime/scenarios/inject`
- `POST /api/runtime/control`
- `POST/GET /api/runtime/decisions`
- `POST /api/runtime/decisions/{id}/approve`
- `POST /api/runtime/decisions/{id}/execute`
- `POST /api/runtime/decisions/{id}/rollback`
- `GET /api/runtime/decisions/{id}/audit`
