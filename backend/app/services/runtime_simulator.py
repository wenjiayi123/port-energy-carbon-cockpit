from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import random
import threading
import time
from typing import Any
import uuid

from app.rl.dataset import DEFAULT_DATASET_ID, PortDataset
from app.schemas.runtime import RuntimeSnapshot, TelemetryField


RUNTIME_DATASET_ID = "port_la_2020_2024_vessel_activity_hourly"
RUNTIME_SITE_ID = "USLAX-PUBLIC-SIM"
SIMULATED_MINUTES_PER_STEP = 15
DEFAULT_TICK_SECONDS = 5.0


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_z(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def clamp(value: float, minimum: float, maximum: float) -> float:
    return min(maximum, max(minimum, float(value)))


class RealtimePortSimulator:
    """Deterministic, public-data-calibrated energy and operations simulator.

    The source row supplies public workload, grid, tariff, carbon, and vessel
    anchors. Equipment, building, storage, and execution values are generated
    by documented physical equations, bounded state machines, and a seeded
    disturbance process. No field is represented as live port telemetry.
    """

    def __init__(
        self,
        *,
        dataset_id: str = RUNTIME_DATASET_ID,
        seed: int = 20260814,
        tick_seconds: float = DEFAULT_TICK_SECONDS,
        auto_advance: bool = True,
        site_id: str = RUNTIME_SITE_ID,
    ) -> None:
        self.dataset = PortDataset.load(dataset_id or DEFAULT_DATASET_ID)
        self.frame = self.dataset.split("test").reset_index(drop=True)
        self.seed = int(seed)
        self.tick_seconds = max(0.25, float(tick_seconds))
        self.auto_advance = bool(auto_advance)
        self.site_id = site_id
        self._random = random.Random(self.seed)
        self._lock = threading.RLock()
        self._running = True
        self._step = 0
        self._row_index = 0
        self._virtual_start = utc_now().replace(second=0, microsecond=0)
        self._last_monotonic = time.monotonic()
        self._battery_soc = 0.52
        self._battery_soh = 0.986
        self._battery_temperature_c = 28.0
        self._battery_equivalent_cycles = 418.0
        self._queue_teu = 110.0
        self._peak_kw = 0.0
        self._cumulative = {
            "energy_kwh": 0.0,
            "carbon_kg": 0.0,
            "cost_cny": 0.0,
            "processed_teu": 0.0,
            "battery_throughput_kwh": 0.0,
            "equipment_life_cost_cny": 0.0,
        }
        self._scenario = {"id": "normal", "until_step": 0, "injected_at_step": 0}
        self._pending_action: dict[str, float] | None = None
        self._last_snapshot: dict[str, Any] | None = None
        self._history: deque[dict[str, Any]] = deque(maxlen=192)
        self._mutation_idempotency: dict[str, dict[str, Any]] = {}
        self._advance_one()

    @property
    def running(self) -> bool:
        return self._running

    def contract(self) -> dict[str, Any]:
        sample = self.snapshot()
        return {
            "schema_version": sample["schema_version"],
            "telemetry_field_schema_version": "telemetry-field.v1",
            "site_id": self.site_id,
            "data_mode": "public_data_calibrated_realtime_simulation",
            "field_count": len(sample["signals"]),
            "required_field_attributes": list(
                TelemetryField.model_fields
            ),
            "source_adapter_mapping": {
                "public_replay_adapter": [
                    "EIA-930",
                    "Port of Los Angeles vessel activity",
                    "Port of Los Angeles monthly TEU",
                    "EIA tariff anchors",
                ],
                "replace_at_site": {
                    "energy_management_system": [
                        "grid.*",
                        "solar.*",
                        "demand_response.*",
                    ],
                    "battery_management_system": ["battery.*"],
                    "building_automation": ["hvac.*", "lighting.*", "pumps.*"],
                    "terminal_operating_system": [
                        "operations.*",
                        "reefer.*",
                        "equipment.*",
                    ],
                    "meter_and_plc_gateway": [
                        "shore_power.*",
                        "transformer.*",
                        "charging.*",
                    ],
                },
            },
            "assumptions": {
                "equipment-physics-v1": "Declared capacities, efficiencies, and conservation equations.",
                "solar-profile-v1": "Bounded daylight profile with deterministic cloud modulation; engineering simulation.",
                "building-load-v1": "Temperature, occupancy, and daylight response; engineering simulation.",
                "battery-aging-v1": "Equivalent-throughput aging with thermal derating; engineering simulation.",
                "market-event-calendar-v1": "Demand-response events are injected engineering scenarios, not settlement records.",
            },
            "production_controls": {
                "simulation_mode": True,
                "live_data_verified": False,
                "dispatch_allowed": False,
                "production_authority": False,
            },
        }

    def start(self) -> dict[str, Any]:
        with self._lock:
            self._running = True
            self._last_monotonic = time.monotonic()
            self._advance_one()
            return self.snapshot(advance=False)

    def stop(self) -> dict[str, Any]:
        with self._lock:
            self._running = False
            return self._render_stopped_snapshot()

    def reset(self) -> dict[str, Any]:
        with self._lock:
            self._random = random.Random(self.seed)
            self._running = True
            self._step = 0
            self._row_index = 0
            self._virtual_start = utc_now().replace(second=0, microsecond=0)
            self._last_monotonic = time.monotonic()
            self._battery_soc = 0.52
            self._battery_soh = 0.986
            self._battery_temperature_c = 28.0
            self._battery_equivalent_cycles = 418.0
            self._queue_teu = 110.0
            self._peak_kw = 0.0
            for key in self._cumulative:
                self._cumulative[key] = 0.0
            self._scenario = {"id": "normal", "until_step": 0, "injected_at_step": 0}
            self._pending_action = None
            self._history.clear()
            self._advance_one()
            return self.snapshot(advance=False)

    def inject_scenario(
        self,
        scenario_id: str,
        duration_steps: int,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            if idempotency_key and idempotency_key in self._mutation_idempotency:
                return json.loads(json.dumps(self._mutation_idempotency[idempotency_key]))
            self._scenario = {
                "id": scenario_id,
                "until_step": self._step + max(1, int(duration_steps)),
                "injected_at_step": self._step,
            }
            self._advance_one()
            result = self.snapshot(advance=False)
            if idempotency_key:
                self._remember_mutation(idempotency_key, result)
            return result

    def control(
        self,
        action: str,
        idempotency_key: str,
        steps: int = 1,
    ) -> dict[str, Any]:
        with self._lock:
            prior = self._mutation_idempotency.get(idempotency_key)
            if prior is not None:
                return {**json.loads(json.dumps(prior)), "idempotent_replay": True}
            if action == "start":
                result = self.start()
            elif action == "stop":
                result = self.stop()
            elif action == "reset":
                result = self.reset()
            elif action == "advance":
                result = self.advance(steps)
            else:
                raise ValueError("unknown_runtime_control_action")
            self._remember_mutation(idempotency_key, result)
            return {**result, "idempotent_replay": False}

    def _remember_mutation(self, idempotency_key: str, result: dict[str, Any]) -> None:
        self._mutation_idempotency[idempotency_key] = json.loads(json.dumps(result))
        if len(self._mutation_idempotency) > 500:
            oldest = next(iter(self._mutation_idempotency))
            self._mutation_idempotency.pop(oldest, None)

    def advance(self, steps: int = 1) -> dict[str, Any]:
        with self._lock:
            if not self._running:
                return self._render_stopped_snapshot()
            for _ in range(max(1, min(1_000, int(steps)))):
                self._advance_one()
            self._last_monotonic = time.monotonic()
            return self.snapshot(advance=False)

    def snapshot(self, *, advance: bool = True) -> dict[str, Any]:
        with self._lock:
            if not self._running:
                return self._render_stopped_snapshot()
            if advance and self.auto_advance:
                elapsed = max(0.0, time.monotonic() - self._last_monotonic)
                due = min(24, int(elapsed // self.tick_seconds))
                for _ in range(due):
                    self._advance_one()
                if due:
                    self._last_monotonic += due * self.tick_seconds
            if self._last_snapshot is None:
                self._advance_one()
            return json.loads(json.dumps(self._last_snapshot))

    def history(self, limit: int = 48) -> dict[str, Any]:
        with self._lock:
            self.snapshot()
            items = list(self._history)[-max(1, min(192, int(limit))) :]
            return {
                "schema_version": "runtime-history.v1",
                "site_id": self.site_id,
                "count": len(items),
                "items": json.loads(json.dumps(items)),
            }

    def apply_action(self, action: dict[str, float]) -> dict[str, Any]:
        with self._lock:
            before = self.snapshot()
            if not before["decision_allowed"]:
                raise RuntimeError("runtime_quality_gate_failed")
            self._pending_action = {key: float(value) for key, value in action.items()}
            self._advance_one()
            after = self.snapshot(advance=False)
            return {"before": before, "after": after}

    def _active_scenario_id(self) -> str:
        if self._scenario["id"] != "normal" and self._step >= self._scenario["until_step"]:
            self._scenario = {"id": "normal", "until_step": 0, "injected_at_step": 0}
        return str(self._scenario["id"])

    def _advance_one(self) -> None:
        scenario = self._active_scenario_id()
        row = self.frame.iloc[self._row_index % len(self.frame)]
        virtual_time = self._virtual_start + timedelta(
            minutes=self._step * SIMULATED_MINUTES_PER_STEP
        )
        source_record_time = str(row.get("timestamp_utc") or row.get("period"))
        tick_hours = SIMULATED_MINUTES_PER_STEP / 60.0
        hour = virtual_time.hour + virtual_time.minute / 60.0
        daylight = max(0.0, math.sin(math.pi * (hour - 6.0) / 12.0))
        weekly = 0.93 if virtual_time.weekday() >= 5 else 1.0
        public_workload_teu_h = max(0.0, float(row["total_teu"]))
        workload_factor = clamp(public_workload_teu_h / 1_650.0, 0.25, 1.25)
        vessels_at_berth = max(0.0, float(row.get("vessels_at_berth", 0.0)))
        vessels_at_anchor = max(0.0, float(row.get("vessels_at_anchor", 0.0)))

        # Seeded disturbances stay bounded and are correlated with business state.
        disturbance = self._random.gauss(0.0, 1.0)
        ambient_temperature_c = clamp(
            21.0 + 7.0 * daylight + 2.0 * math.sin(2 * math.pi * self._step / 96.0)
            + 0.45 * disturbance,
            12.0,
            42.0,
        )
        if scenario == "extreme_heat":
            ambient_temperature_c = min(48.0, ambient_temperature_c + 12.0)
        wind_speed_m_s = clamp(
            4.8 + 2.1 * math.sin(self._step / 13.0) + 0.35 * disturbance,
            0.2,
            16.0,
        )
        relative_humidity_pct = clamp(
            72.0 - max(0.0, ambient_temperature_c - 24.0) * 1.15
            + 4.0 * math.cos(self._step / 17.0),
            34.0,
            96.0,
        )
        cloud_factor = clamp(0.78 + 0.12 * math.sin(self._step / 11.0) - 0.03 * disturbance, 0.35, 1.0)
        solar_available_kw = 3_800.0 * daylight * cloud_factor

        crane_availability = 0.96
        yard_availability = 0.94
        if scenario == "equipment_fault":
            crane_availability = 0.62
            yard_availability = 0.78
        crane_utilization = clamp((0.54 + 0.34 * workload_factor) * weekly, 0.35, crane_availability)
        yard_utilization = clamp((0.50 + 0.38 * workload_factor) * weekly, 0.35, yard_availability)
        active_cranes = max(1, round(14 * crane_utilization))
        active_yard_cranes = max(1, round(32 * yard_utilization))
        crane_load_kw = 2_900.0 * crane_utilization
        yard_load_kw = 1_250.0 * yard_utilization
        agv_charging_limit_kw = float(
            (self._pending_action or {}).get("agv_charging_limit_kw", 1_800.0)
        )
        agv_charging_kw = min(
            clamp(520.0 + 520.0 * (1.1 - workload_factor) + 90.0 * disturbance, 220.0, 1_650.0),
            clamp(agv_charging_limit_kw, 200.0, 1_800.0),
        )
        active_agvs = max(0, round(58 * yard_utilization))

        shore_opportunity_kw = min(6_800.0, vessels_at_berth * 650.0)
        shore_limit_kw = float((self._pending_action or {}).get("shore_power_limit_kw", 6_800.0))
        shore_ratio = clamp(0.58 + 0.18 * daylight + 0.08 * workload_factor, 0.35, 0.92)
        shore_power_kw = min(shore_opportunity_kw * shore_ratio, clamp(shore_limit_kw, 0.0, 6_800.0))

        hvac_setpoint_c = clamp(
            float((self._pending_action or {}).get("hvac_setpoint_c", 24.0)), 22.0, 27.0
        )
        hvac_load_kw = clamp(
            480.0 + max(0.0, ambient_temperature_c - hvac_setpoint_c) * 92.0,
            350.0,
            2_100.0,
        )
        lighting_load_kw = 230.0 + (1.0 - daylight) * 520.0
        illuminance_lux = 340.0 + daylight * 410.0
        reefer_count = max(120, round(360 + public_workload_teu_h * 0.22))
        reefer_load_kw = reefer_count * (2.35 + max(0.0, ambient_temperature_c - 25.0) * 0.035)
        pump_fan_load_kw = 240.0 + hvac_load_kw * 0.18
        base_load_kw = 2_200.0 + public_workload_teu_h * 0.62
        gross_load_kw = (
            base_load_kw
            + crane_load_kw
            + yard_load_kw
            + agv_charging_kw
            + shore_power_kw
            + hvac_load_kw
            + lighting_load_kw
            + reefer_load_kw
            + pump_fan_load_kw
        )

        grid_capacity_kw = 17_000.0
        if scenario == "transformer_derating":
            grid_capacity_kw *= 0.78
        if scenario == "demand_response_event":
            grid_capacity_kw = min(grid_capacity_kw, 14_500.0)
        electricity_price = float(row["electricity_price_per_kwh"])
        battery_command_kw = float((self._pending_action or {}).get("battery_power_kw", 0.0))
        if not self._pending_action:
            if electricity_price >= 1.55 or gross_load_kw >= grid_capacity_kw * 0.86:
                battery_command_kw = 2_400.0
            elif solar_available_kw >= 2_300.0 and electricity_price <= 1.45:
                battery_command_kw = -1_800.0
        if self._battery_temperature_c >= 46.0 or scenario == "battery_overtemperature":
            battery_command_kw = clamp(battery_command_kw, -900.0, 900.0)
        battery_capacity_kwh = 18_000.0
        battery_power_limit_kw = 5_000.0 * clamp(self._battery_soh, 0.80, 1.0)
        charge_efficiency = 0.95
        discharge_efficiency = 0.95
        max_discharge_kw = (
            max(0.0, self._battery_soc - 0.10)
            * battery_capacity_kwh
            * discharge_efficiency
            / tick_hours
        )
        max_charge_kw = (
            max(0.0, 0.90 - self._battery_soc)
            * battery_capacity_kwh
            / charge_efficiency
            / tick_hours
        )
        projected_battery_kw = clamp(
            battery_command_kw,
            -min(battery_power_limit_kw, max_charge_kw),
            min(battery_power_limit_kw, max_discharge_kw),
        )

        net_before_flex_kw = gross_load_kw - solar_available_kw - projected_battery_kw
        flex_required_kw = max(0.0, net_before_flex_kw - grid_capacity_kw * 0.98)
        shed_agv_kw = min(agv_charging_kw - 200.0, flex_required_kw)
        agv_charging_kw -= max(0.0, shed_agv_kw)
        remaining_flex_kw = max(0.0, flex_required_kw - max(0.0, shed_agv_kw))
        shed_hvac_kw = min(max(0.0, hvac_load_kw - 350.0), remaining_flex_kw)
        hvac_load_kw -= shed_hvac_kw
        flex_load_shed_kw = max(0.0, shed_agv_kw) + shed_hvac_kw
        gross_load_kw -= flex_load_shed_kw
        grid_import_kw = max(0.0, gross_load_kw - solar_available_kw - projected_battery_kw)
        transformer_overload_kw = max(0.0, grid_import_kw - grid_capacity_kw)

        if projected_battery_kw >= 0:
            battery_discharge_kwh = projected_battery_kw * tick_hours
            battery_charge_kwh = 0.0
            self._battery_soc -= battery_discharge_kwh / (
                discharge_efficiency * battery_capacity_kwh
            )
        else:
            battery_charge_kwh = -projected_battery_kw * tick_hours
            battery_discharge_kwh = 0.0
            self._battery_soc += (
                battery_charge_kwh * charge_efficiency / battery_capacity_kwh
            )
        self._battery_soc = clamp(self._battery_soc, 0.10, 0.90)
        battery_throughput_kwh = battery_charge_kwh + battery_discharge_kwh
        cycle_increment = battery_throughput_kwh / (2.0 * battery_capacity_kwh)
        self._battery_equivalent_cycles += cycle_increment
        self._battery_soh = max(0.80, self._battery_soh - cycle_increment * 0.00012)
        target_battery_temperature = (
            ambient_temperature_c
            + abs(projected_battery_kw) / max(1.0, battery_power_limit_kw) * 8.5
        )
        if scenario == "battery_overtemperature":
            target_battery_temperature = max(target_battery_temperature, 53.0)
        self._battery_temperature_c = clamp(
            self._battery_temperature_c * 0.72 + target_battery_temperature * 0.28,
            12.0,
            60.0,
        )

        demand_teu = public_workload_teu_h * tick_hours + self._queue_teu
        capacity_teu = min(
            1_850.0 * crane_utilization,
            2_050.0 * yard_utilization,
        ) * tick_hours
        processed_teu = min(demand_teu, capacity_teu)
        self._queue_teu = max(0.0, demand_teu - processed_teu)
        delay_minutes = self._queue_teu / max(1.0, capacity_teu) * SIMULATED_MINUTES_PER_STEP
        service_fulfilment_pct = processed_teu / max(1.0, demand_teu) * 100.0

        grid_energy_kwh = grid_import_kw * tick_hours
        solar_energy_kwh = min(gross_load_kw, solar_available_kw) * tick_hours
        grid_carbon_kg_per_kwh = float(row["grid_carbon_kg_per_kwh"])
        grid_carbon_kg = grid_energy_kwh * grid_carbon_kg_per_kwh
        auxiliary_energy_kwh = max(0.0, shore_opportunity_kw - shore_power_kw) * tick_hours
        auxiliary_fuel_liters = auxiliary_energy_kwh / 3.8
        fuel_carbon_kg = auxiliary_fuel_liters * 2.68
        carbon_kg = grid_carbon_kg + fuel_carbon_kg
        battery_life_cost_cny = battery_throughput_kwh * 0.18
        cost_cny = (
            grid_energy_kwh * electricity_price
            + auxiliary_fuel_liters * float(row["fuel_price_per_liter"])
            + delay_minutes * 18.0
            + battery_life_cost_cny
        )
        self._peak_kw = max(self._peak_kw, grid_import_kw)
        self._cumulative["energy_kwh"] += grid_energy_kwh + solar_energy_kwh + auxiliary_energy_kwh
        self._cumulative["carbon_kg"] += carbon_kg
        self._cumulative["cost_cny"] += cost_cny
        self._cumulative["processed_teu"] += processed_teu
        self._cumulative["battery_throughput_kwh"] += battery_throughput_kwh
        self._cumulative["equipment_life_cost_cny"] += battery_life_cost_cny

        ingest_time = utc_now()
        trace_id = f"runtime-{self.seed}-{self._step:010d}"
        record_quality = (
            "正常" if str(row.get("eia930_quality_code", "reported")) == "reported" else "插值"
        )
        activity_observed = bool(int(float(row.get("port_activity_observed", 0))))
        signal_context = {
            "event_time": iso_z(virtual_time),
            "ingest_time": iso_z(ingest_time),
            "source_record_time": source_record_time,
            "trace_id": trace_id,
        }
        signals: dict[str, TelemetryField] = {}

        def add(
            field_id: str,
            value: float | int | str | bool | None,
            unit: str,
            asset_id: str,
            *,
            source_type: str,
            source_id: str,
            quality_status: str = "正常",
            confidence: float = 0.9,
            classification: str = "simulated",
            assumption_id: str | None = None,
        ) -> None:
            if scenario == "communications_loss":
                quality_status = "失联"
                confidence = 0.0
            if scenario == "sensor_drift" and field_id in {
                "grid.import_power_kw",
                "transformer.loading_pct",
                "battery.soc_pct",
            }:
                quality_status = "漂移"
                confidence = min(confidence, 0.55)
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    value = float(value) * 1.07
            signals[field_id] = TelemetryField(
                field_id=field_id,
                value=round(float(value), 6)
                if isinstance(value, (int, float)) and not isinstance(value, bool)
                else value,
                unit=unit,
                source_type=source_type,  # type: ignore[arg-type]
                source_id=source_id,
                quality_status=quality_status,  # type: ignore[arg-type]
                confidence=confidence,
                is_measured=classification == "measured",
                is_simulated=classification == "simulated",
                is_derived=classification == "derived",
                site_id=self.site_id,
                asset_id=asset_id,
                assumption_id=assumption_id,
                **signal_context,
            )

        public_source_id = str(row.get("source_id") or self.dataset.dataset_id)[:256]
        add(
            "grid.regional_demand_mw",
            float(row.get("eia930_demand_mw", 0.0)),
            "MW",
            "LADWP-BA",
            source_type="公开观测",
            source_id="EIA-930:LADWP",
            quality_status=record_quality,
            confidence=0.98 if record_quality == "正常" else 0.82,
            classification="measured" if record_quality == "正常" else "derived",
        )
        add(
            "grid.carbon_factor_kg_per_kwh",
            grid_carbon_kg_per_kwh,
            "kgCO2e/kWh",
            "LADWP-BA",
            source_type="公开观测",
            source_id="EIA-930:consumed-carbon",
            quality_status=record_quality,
            confidence=0.96 if record_quality == "正常" else 0.80,
            classification="measured" if record_quality == "正常" else "derived",
        )
        add(
            "grid.electricity_price_cny_per_kwh",
            electricity_price,
            "CNY/kWh",
            "TARIFF-PROXY",
            source_type="工程派生",
            source_id="EIA-monthly+LADWP-TOU",
            confidence=0.78,
            classification="derived",
            assumption_id="tariff-shaping-v1",
        )
        add("grid.import_power_kw", grid_import_kw, "kW", "MAIN-METER", source_type="物理模拟", source_id="runtime-energy-balance", confidence=0.93, assumption_id="equipment-physics-v1")
        add("grid.frequency_hz", clamp(60.0 - transformer_overload_kw / 20_000.0 + disturbance * 0.006, 59.85, 60.15), "Hz", "MAIN-METER", source_type="物理模拟", source_id="grid-frequency-model-v1", confidence=0.82, assumption_id="grid-frequency-model-v1")
        add("transformer.capacity_kw", grid_capacity_kw, "kW", "TX-01", source_type="物理模拟", source_id="asset-parameter:TX-01", confidence=0.95, assumption_id="equipment-physics-v1")
        add("transformer.loading_pct", grid_import_kw / max(1.0, grid_capacity_kw) * 100.0, "%", "TX-01", source_type="工程派生", source_id="runtime-energy-balance", confidence=0.95, classification="derived", assumption_id="equipment-physics-v1")
        add("transformer.reserve_margin_kw", max(0.0, grid_capacity_kw - grid_import_kw), "kW", "TX-01", source_type="工程派生", source_id="runtime-energy-balance", confidence=0.95, classification="derived", assumption_id="equipment-physics-v1")
        add("grid.demand_peak_kw", self._peak_kw, "kW", "MAIN-METER", source_type="工程派生", source_id="runtime-kpi-engine-v1", confidence=0.90, classification="derived")
        add("solar.available_power_kw", solar_available_kw, "kW", "PV-01", source_type="物理模拟", source_id="solar-profile-v1", confidence=0.72, assumption_id="solar-profile-v1")
        add("solar.energy_kwh", solar_energy_kwh, "kWh/step", "PV-01", source_type="工程派生", source_id="runtime-energy-balance", confidence=0.78, classification="derived", assumption_id="solar-profile-v1")
        add("battery.soc_pct", self._battery_soc * 100.0, "%", "BESS-01", source_type="物理模拟", source_id="battery-state-model-v1", confidence=0.96, assumption_id="battery-aging-v1")
        add("battery.soh_pct", self._battery_soh * 100.0, "%", "BESS-01", source_type="物理模拟", source_id="battery-aging-v1", confidence=0.82, assumption_id="battery-aging-v1")
        add("battery.power_kw", projected_battery_kw, "kW", "BESS-01", source_type="物理模拟", source_id="battery-state-model-v1", confidence=0.96, assumption_id="battery-aging-v1")
        add("battery.temperature_c", self._battery_temperature_c, "degC", "BESS-01", source_type="物理模拟", source_id="battery-thermal-model-v1", quality_status="异常" if self._battery_temperature_c >= 50 else "正常", confidence=0.86, assumption_id="battery-aging-v1")
        add("battery.equivalent_cycles", self._battery_equivalent_cycles, "cycles", "BESS-01", source_type="工程派生", source_id="battery-aging-v1", confidence=0.82, classification="derived", assumption_id="battery-aging-v1")
        add("battery.round_trip_efficiency_pct", 90.25, "%", "BESS-01", source_type="物理模拟", source_id="asset-parameter:BESS-01", confidence=0.90, assumption_id="equipment-physics-v1")
        add("battery.degradation_cost_cny", battery_life_cost_cny, "CNY/step", "BESS-01", source_type="工程派生", source_id="battery-aging-v1", confidence=0.66, classification="derived", assumption_id="battery-aging-v1")
        add("shore_power.load_kw", shore_power_kw, "kW", "SHORE-GRID", source_type="物理模拟", source_id="shore-power-state-model-v1", confidence=0.88, assumption_id="equipment-physics-v1")
        add("shore_power.opportunity_kw", shore_opportunity_kw, "kW", "SHORE-GRID", source_type="工程派生", source_id="shore-power-state-model-v1", confidence=0.76, classification="derived", assumption_id="equipment-physics-v1")
        add("shore_power.connected_vessels", round(shore_power_kw / 650.0), "vessels", "SHORE-GRID", source_type="工程派生", source_id="shore-power-state-model-v1", confidence=0.76, classification="derived", assumption_id="equipment-physics-v1")
        add("operations.throughput_demand_teu_h", public_workload_teu_h, "TEU/h", "TERMINAL", source_type="工程派生", source_id=public_source_id, quality_status="插值", confidence=0.70, classification="derived", assumption_id="monthly-teu-hourly-allocation-v1")
        activity_quality = "正常" if activity_observed else "插值"
        add("operations.vessels_at_berth", vessels_at_berth, "vessels", "PORT", source_type="官方聚合" if activity_observed else "工程派生", source_id="POLA-Wharfinger", quality_status=activity_quality, confidence=0.96 if activity_observed else 0.68, classification="measured" if activity_observed else "derived")
        add("operations.vessels_at_anchor", vessels_at_anchor, "vessels", "PORT", source_type="官方聚合" if activity_observed else "工程派生", source_id="POLA-Wharfinger", quality_status=activity_quality, confidence=0.96 if activity_observed else 0.68, classification="measured" if activity_observed else "derived")
        add("operations.processed_teu", processed_teu, "TEU/step", "TERMINAL", source_type="物理模拟", source_id="operations-conservation-v1", confidence=0.86, assumption_id="equipment-physics-v1")
        add("operations.queue_teu", self._queue_teu, "TEU", "TERMINAL", source_type="物理模拟", source_id="operations-conservation-v1", confidence=0.82, assumption_id="equipment-physics-v1")
        add("operations.delay_minutes", delay_minutes, "min", "TERMINAL", source_type="工程派生", source_id="operations-conservation-v1", confidence=0.80, classification="derived", assumption_id="equipment-physics-v1")
        add("equipment.quay_crane_utilization_pct", crane_utilization * 100.0, "%", "QC-FLEET", source_type="物理模拟", source_id="equipment-state-machine-v1", confidence=0.80, assumption_id="equipment-physics-v1")
        add("equipment.active_quay_cranes", active_cranes, "count", "QC-FLEET", source_type="物理模拟", source_id="equipment-state-machine-v1", confidence=0.80, assumption_id="equipment-physics-v1")
        add("equipment.active_yard_cranes", active_yard_cranes, "count", "YC-FLEET", source_type="物理模拟", source_id="equipment-state-machine-v1", confidence=0.78, assumption_id="equipment-physics-v1")
        add("equipment.active_agvs", active_agvs, "count", "AGV-FLEET", source_type="物理模拟", source_id="equipment-state-machine-v1", confidence=0.76, assumption_id="equipment-physics-v1")
        add("charging.agv_load_kw", agv_charging_kw, "kW", "AGV-CHARGERS", source_type="物理模拟", source_id="charging-queue-model-v1", confidence=0.80, assumption_id="equipment-physics-v1")
        add("reefer.connected_count", reefer_count, "count", "REEFER-YARD", source_type="物理模拟", source_id="reefer-load-model-v1", confidence=0.70, assumption_id="building-load-v1")
        add("reefer.load_kw", reefer_load_kw, "kW", "REEFER-YARD", source_type="物理模拟", source_id="reefer-load-model-v1", confidence=0.74, assumption_id="building-load-v1")
        add("hvac.load_kw", hvac_load_kw, "kW", "HVAC-01", source_type="物理模拟", source_id="building-load-v1", confidence=0.78, assumption_id="building-load-v1")
        add("hvac.setpoint_c", hvac_setpoint_c, "degC", "HVAC-01", source_type="物理模拟", source_id="building-load-v1", confidence=0.90, assumption_id="building-load-v1")
        add("weather.ambient_temperature_c", ambient_temperature_c, "degC", "WEATHER-SIM", source_type="物理模拟", source_id="weather-engineering-profile-v1", confidence=0.62, assumption_id="building-load-v1")
        add("weather.wind_speed_m_s", wind_speed_m_s, "m/s", "WEATHER-SIM", source_type="物理模拟", source_id="weather-engineering-profile-v1", confidence=0.58, assumption_id="building-load-v1")
        add("weather.relative_humidity_pct", relative_humidity_pct, "%", "WEATHER-SIM", source_type="物理模拟", source_id="weather-engineering-profile-v1", confidence=0.58, assumption_id="building-load-v1")
        add("lighting.load_kw", lighting_load_kw, "kW", "LIGHTING-01", source_type="物理模拟", source_id="building-load-v1", confidence=0.76, assumption_id="building-load-v1")
        add("lighting.illuminance_lux", illuminance_lux, "lux", "LIGHTING-01", source_type="物理模拟", source_id="building-load-v1", confidence=0.68, assumption_id="building-load-v1")
        add("pumps_fans.load_kw", pump_fan_load_kw, "kW", "AUX-BUILDING", source_type="物理模拟", source_id="building-load-v1", confidence=0.72, assumption_id="building-load-v1")
        add("demand_response.active", scenario == "demand_response_event", "boolean", "DR-CALENDAR", source_type="物理模拟", source_id="market-event-calendar-v1", confidence=1.0, assumption_id="market-event-calendar-v1")
        add("demand_response.flex_load_shed_kw", flex_load_shed_kw, "kW", "FLEX-LOADS", source_type="工程派生", source_id="runtime-safety-projector-v1", confidence=0.96, classification="derived", assumption_id="equipment-physics-v1")
        add("demand_response.engineering_avoided_cost_cny", flex_load_shed_kw * tick_hours * electricity_price, "CNY/step", "DR-CALENDAR", source_type="工程派生", source_id="market-event-calendar-v1", confidence=0.55, classification="derived", assumption_id="market-event-calendar-v1")
        add("demand_response.settlement_verified", False, "boolean", "DR-CALENDAR", source_type="工程派生", source_id="market-event-calendar-v1", confidence=1.0, classification="derived", assumption_id="market-event-calendar-v1")
        add("kpi.step_energy_kwh", grid_energy_kwh + solar_energy_kwh + auxiliary_energy_kwh, "kWh/step", "SITE", source_type="工程派生", source_id="runtime-kpi-engine-v1", confidence=0.90, classification="derived")
        add("kpi.step_carbon_kg", carbon_kg, "kgCO2e/step", "SITE", source_type="工程派生", source_id="runtime-kpi-engine-v1", confidence=0.86, classification="derived")
        add("kpi.step_cost_cny", cost_cny, "CNY/step", "SITE", source_type="工程派生", source_id="runtime-kpi-engine-v1", confidence=0.78, classification="derived")
        add("kpi.service_fulfilment_pct", service_fulfilment_pct, "%", "SITE", source_type="工程派生", source_id="runtime-kpi-engine-v1", confidence=0.82, classification="derived")
        add("kpi.equipment_life_cost_cny", battery_life_cost_cny, "CNY/step", "SITE", source_type="工程派生", source_id="battery-aging-v1", confidence=0.66, classification="derived", assumption_id="battery-aging-v1")

        component_power_kw = (
            base_load_kw
            + crane_load_kw
            + yard_load_kw
            + agv_charging_kw
            + shore_power_kw
            + hvac_load_kw
            + lighting_load_kw
            + reefer_load_kw
            + pump_fan_load_kw
        )
        balance_error_kw = abs(
            grid_import_kw
            + solar_available_kw
            + projected_battery_kw
            - component_power_kw
        )
        source_counts: dict[str, int] = {}
        measured = simulated = derived = 0
        quality_counts: dict[str, int] = {}
        for signal in signals.values():
            source_counts[signal.source_type] = source_counts.get(signal.source_type, 0) + 1
            quality_counts[signal.quality_status] = quality_counts.get(signal.quality_status, 0) + 1
            measured += int(signal.is_measured)
            simulated += int(signal.is_simulated)
            derived += int(signal.is_derived)
        critical_reasons: list[str] = []
        if scenario == "communications_loss":
            critical_reasons.append("communications_loss")
        if transformer_overload_kw > 1e-6:
            critical_reasons.append("transformer_capacity_exceeded")
        if self._battery_temperature_c >= 50.0:
            critical_reasons.append("battery_temperature_high")
        if balance_error_kw > 1e-5:
            critical_reasons.append("energy_balance_mismatch")
        decision_allowed = not critical_reasons and self._running
        snapshot_body = {
            "schema_version": "energy-carbon-runtime.v1",
            "snapshot_id": str(uuid.uuid5(uuid.NAMESPACE_URL, trace_id)),
            "trace_id": trace_id,
            "site_id": self.site_id,
            "simulation_mode": True,
            "simulator_state": "running" if decision_allowed else "failed_closed",
            "data_mode": "public_data_calibrated_realtime_simulation",
            "live_data_verified": False,
            "dispatch_allowed": False,
            "production_authority": False,
            "virtual_event_time": iso_z(virtual_time),
            "generated_at": iso_z(ingest_time),
            "dataset": {
                "dataset_id": self.dataset.dataset_id,
                "dataset_sha256": self.dataset.package_sha256,
                "split": "test",
                "source_record_time": source_record_time,
                "source_record_id": public_source_id,
                "evidence_label": "PUBLIC_DATA_CALIBRATED_SIMULATION_NOT_FIELD_TELEMETRY",
            },
            "seed": self.seed,
            "step": self._step,
            "active_scenario": {
                "scenario_id": scenario,
                "remaining_steps": max(0, int(self._scenario["until_step"]) - self._step),
                "settlement_evidence": False,
            },
            "signals": {name: signal.model_dump(mode="json") for name, signal in signals.items()},
            "topology": {
                "nodes": [
                    "GRID",
                    "TX-01",
                    "PV-01",
                    "BESS-01",
                    "SHORE-GRID",
                    "AGV-CHARGERS",
                    "REEFER-YARD",
                    "HVAC-01",
                    "LIGHTING-01",
                ],
                "energy_balance": "grid + solar + battery_discharge = component_loads + battery_charge",
            },
            "quality": {
                "status": "pass" if decision_allowed else "fail_closed",
                "critical_reasons": critical_reasons,
                "energy_balance_error_kw": round(balance_error_kw, 9),
                "source_type_counts": source_counts,
                "quality_status_counts": quality_counts,
                "classification_counts": {
                    "measured": measured,
                    "simulated": simulated,
                    "derived": derived,
                },
                "classification_pct": {
                    "measured": round(measured / max(1, len(signals)) * 100.0, 2),
                    "simulated": round(simulated / max(1, len(signals)) * 100.0, 2),
                    "derived": round(derived / max(1, len(signals)) * 100.0, 2),
                },
                "freshness_seconds": 0.0,
            },
            "kpis": {
                "current": {
                    "energy_kwh": round(grid_energy_kwh + solar_energy_kwh + auxiliary_energy_kwh, 3),
                    "carbon_kg": round(carbon_kg, 3),
                    "cost_cny": round(cost_cny, 3),
                    "grid_peak_kw": round(self._peak_kw, 3),
                    "service_fulfilment_pct": round(service_fulfilment_pct, 3),
                    "safety_violations": len(critical_reasons),
                    "equipment_life_cost_cny": round(battery_life_cost_cny, 4),
                },
                "cumulative": {key: round(value, 6) for key, value in self._cumulative.items()},
            },
            "decision_allowed": decision_allowed,
        }
        snapshot_body["snapshot_sha256"] = canonical_sha256(snapshot_body)
        validated = RuntimeSnapshot.model_validate(snapshot_body).model_dump(mode="json")
        self._last_snapshot = validated
        self._history.append(
            {
                "step": self._step,
                "virtual_event_time": snapshot_body["virtual_event_time"],
                "snapshot_sha256": snapshot_body["snapshot_sha256"],
                "scenario_id": scenario,
                "decision_allowed": decision_allowed,
                "grid_import_kw": round(grid_import_kw, 3),
                "solar_power_kw": round(solar_available_kw, 3),
                "battery_power_kw": round(projected_battery_kw, 3),
                "battery_soc_pct": round(self._battery_soc * 100.0, 3),
                "carbon_kg": round(carbon_kg, 3),
                "cost_cny": round(cost_cny, 3),
                "service_fulfilment_pct": round(service_fulfilment_pct, 3),
            }
        )
        self._pending_action = None
        self._step += 1
        if self._step % 4 == 0:
            self._row_index = (self._row_index + 1) % len(self.frame)

    def _render_stopped_snapshot(self) -> dict[str, Any]:
        if self._last_snapshot is None:
            self._advance_one()
        stopped = json.loads(json.dumps(self._last_snapshot))
        now = iso_z(utc_now())
        stopped["generated_at"] = now
        stopped["simulator_state"] = "stopped"
        stopped["decision_allowed"] = False
        stopped["quality"]["status"] = "fail_closed"
        reasons = list(stopped["quality"].get("critical_reasons") or [])
        if "simulator_stopped" not in reasons:
            reasons.append("simulator_stopped")
        stopped["quality"]["critical_reasons"] = reasons
        for signal in stopped["signals"].values():
            signal["quality_status"] = "失联"
            signal["confidence"] = 0.0
            signal["ingest_time"] = now
        stopped_without_hash = {key: value for key, value in stopped.items() if key != "snapshot_sha256"}
        stopped["snapshot_sha256"] = canonical_sha256(stopped_without_hash)
        return RuntimeSnapshot.model_validate(stopped).model_dump(mode="json")


runtime_simulator = RealtimePortSimulator()
