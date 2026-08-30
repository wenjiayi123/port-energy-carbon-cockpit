#!/usr/bin/env python3
"""Build the versioned PortEnergyDispatchEnv-v5 public/reality hybrid package.

Official Port of Los Angeles vessel/activity and throughput anchors plus U.S.
EIA/EPA electricity inputs are preserved byte-for-byte from the registered
base rows. Deployment, regulatory and flexible-load columns are deterministic
engineering scenarios with field-level provenance; none are labelled as port
telemetry. A future port replaces those columns through the documented v5
substitution contract without changing the environment interface.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "backend/app/data/datasets/port_la_2020_2024_vessel_activity_hourly.csv"
SOURCE_METADATA = SOURCE.with_suffix(".metadata.json")
OUTPUT = ROOT / "backend/app/data/datasets/port_la_2020_2024_operational_flex_hourly.csv"
OUTPUT_METADATA = OUTPUT.with_suffix(".metadata.json")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    frame = pd.read_csv(SOURCE)
    public_columns = list(frame.columns)
    source_metadata = json.loads(SOURCE_METADATA.read_text(encoding="utf-8"))
    timestamps = pd.to_datetime(frame["timestamp_utc"], utc=True)
    hour_index = np.arange(len(frame), dtype=int)
    hour = timestamps.dt.hour.to_numpy()
    day_of_year = timestamps.dt.dayofyear.to_numpy()
    day_index = (timestamps.dt.floor("D") - timestamps.iloc[0].floor("D")).dt.days.to_numpy()

    # Frozen exogenous regulatory process scenario. Authority selection and
    # release remain observations; no policy action can alter them.
    maritime_cycle = hour_index % (17 * 24)
    customs_cycle = (hour_index + 5 * 24) % (11 * 24)
    maritime_active = maritime_cycle < 24
    maritime_release = (maritime_cycle >= 24) & (maritime_cycle < 42)
    customs_active = customs_cycle < 18
    customs_release = (customs_cycle >= 18) & (customs_cycle < 36)
    frame["maritime_inspection_ratio"] = np.where(maritime_active, 0.060, 0.0)
    frame["customs_inspection_ratio"] = np.where(customs_active, 0.080, 0.002)
    frame["maritime_release_ratio"] = np.where(
        maritime_active, 0.015, np.where(maritime_release, 0.18, 0.45)
    )
    frame["customs_release_ratio"] = np.where(
        customs_active, 0.012, np.where(customs_release, 0.16, 0.40)
    )
    regulatory_stress = maritime_active | customs_active
    frame["document_readiness_ratio"] = np.where(regulatory_stress, 0.58, 0.88)
    frame["inspection_resource_available_ratio"] = np.where(
        regulatory_stress, 0.70, 0.92
    )
    frame["regulatory_scenario_observed"] = 0.0
    frame["expected_hold_hours"] = np.where(
        maritime_active & customs_active,
        20.0,
        np.where(maritime_active, 16.0, np.where(customs_active, 12.0, 2.0)),
    )

    # Reproducible deployment stresses. They are deliberately not described as
    # NOAA observations or equipment telemetry.
    storm = (day_of_year % 23 == 0) | (day_of_year % 37 == 0)
    maintenance = ((day_index % 31) == 0) & np.isin(hour, [1, 2, 3, 4])
    equipment_fault = ((day_index % 47) == 0) & np.isin(hour, [8, 9, 10, 11])
    grid_derating = ((day_index % 61) == 0) & np.isin(hour, [16, 17, 18, 19])
    frame["wind_speed_m_s"] = 4.5 + 1.8 * np.sin(2 * np.pi * hour / 24)
    frame["wave_height_m"] = np.where(storm, 1.8, 0.55)
    frame["visibility_km"] = np.where(storm, 7.0, 18.0)
    frame["precipitation_mm"] = np.where(storm, 3.0, 0.0)
    frame["berth_available_ratio"] = np.where(storm, 0.82, 0.96)
    frame["crane_available_ratio"] = np.where(
        equipment_fault, 0.68, np.where(storm, 0.80, 0.94)
    )
    frame["yard_available_ratio"] = np.where(
        equipment_fault, 0.72, np.where(storm, 0.84, 0.93)
    )
    frame["grid_available_ratio"] = np.where(grid_derating, 0.78, 0.98)
    frame["shore_power_compatible_ratio"] = 0.90
    solar_shape = np.maximum(0.0, np.sin(np.pi * (hour - 6) / 12))
    solar_forecast = np.maximum(0.0, np.sin(np.pi * ((hour + 3) % 24 - 6) / 12))
    frame["renewable_power_available_kw"] = 1_200.0 * solar_shape
    frame["renewable_power_forecast_kw"] = 1_200.0 * solar_forecast

    # Flexible-load engineering scenario. Values are deterministic functions of
    # the real public workload and declared parameters, not independent samples.
    activity = np.clip(frame["total_teu"].to_numpy(dtype=float) / 1_800.0, 0.0, 1.4)
    frame["agv_fleet_available_ratio"] = np.where(equipment_fault, 0.72, 0.94)
    frame["agv_mean_soc"] = np.clip(
        0.48 + 0.16 * np.sin(2 * np.pi * (hour - 4) / 24) - 0.05 * activity,
        0.18,
        0.82,
    )
    frame["agv_charge_demand_kwh"] = np.clip(650.0 + 1.25 * frame["total_teu"], 650, 3_800)
    departure_pressure = np.where(
        np.isin(hour, [5, 6, 7, 8, 16, 17, 18, 19]), 0.78, 0.28
    )
    frame["agv_departure_requirement_kwh"] = (
        frame["agv_charge_demand_kwh"] * departure_pressure
    )
    frame["charger_available_ratio"] = np.where(maintenance, 0.62, 0.95)
    frame["reefer_connected_count"] = np.maximum(
        40.0, 90.0 + 0.18 * frame["loaded_import_teu"]
    )
    frame["reefer_baseline_load_kw"] = frame["reefer_connected_count"] * 3.5
    frame["reefer_thermal_margin_c"] = np.clip(
        1.55 + 0.65 * np.cos(2 * np.pi * (hour - 3) / 24) - np.where(storm, 0.35, 0),
        0.45,
        2.4,
    )
    frame["building_critical_load_kw"] = 620.0
    frame["building_flexible_load_kw"] = (
        520.0 + 620.0 * np.maximum(0.0, np.sin(np.pi * (hour - 6) / 14))
    )
    frame["shore_power_reserved_kw"] = np.minimum(
        6_800.0,
        frame["vessels_at_berth"].to_numpy(dtype=float) * 650.0 * 0.90,
    )
    frame["shore_power_window_remaining_hours"] = np.maximum(1.0, 8.0 - (hour % 8))
    frame["equipment_health_ratio"] = np.where(
        equipment_fault, 0.72, np.where(maintenance, 0.84, 0.96)
    )
    frame["crane_fault_risk"] = np.where(equipment_fault, 0.42, 0.04)
    frame["yard_fault_risk"] = np.where(equipment_fault, 0.36, 0.035)
    high_price = frame["electricity_price_per_kwh"] >= float(
        frame["electricity_price_per_kwh"].quantile(0.85)
    )
    response_active = high_price & np.isin(hour, [16, 17, 18, 19, 20])
    frame["demand_response_active"] = response_active.astype(float)
    frame["demand_response_target_kw"] = np.where(response_active, 1_100.0, 0.0)
    frame["demand_response_remaining_hours"] = np.where(
        response_active, np.maximum(1.0, 21.0 - hour), 0.0
    )
    frame["maintenance_window_active"] = maintenance.astype(float)
    frame["source_id"] = frame["source_id"].astype(str) + "+FLEX-V5-SCENARIO-V1"

    numeric_columns = frame.select_dtypes(include=["number"]).columns
    frame[numeric_columns] = frame[numeric_columns].round(8)
    frame.to_csv(OUTPUT, index=False)

    units = dict(source_metadata["units"])
    unit_updates = {
        "maritime_inspection_ratio": "0-1 deterministic scenario share",
        "customs_inspection_ratio": "0-1 deterministic scenario share",
        "maritime_release_ratio": "0-1 exogenous scenario release share/hour",
        "customs_release_ratio": "0-1 exogenous scenario release share/hour",
        "document_readiness_ratio": "0-1 deterministic scenario",
        "inspection_resource_available_ratio": "0-1 deterministic scenario",
        "regulatory_scenario_observed": "0/1; fixed 0 because not telemetry",
        "expected_hold_hours": "hours deterministic scenario",
        "wind_speed_m_s": "m/s deterministic scenario",
        "wave_height_m": "m deterministic scenario",
        "visibility_km": "km deterministic scenario",
        "precipitation_mm": "mm/hour deterministic scenario",
        "berth_available_ratio": "0-1 deterministic scenario",
        "crane_available_ratio": "0-1 deterministic scenario",
        "yard_available_ratio": "0-1 deterministic scenario",
        "grid_available_ratio": "0-1 deterministic scenario",
        "shore_power_compatible_ratio": "0-1 deterministic scenario",
        "renewable_power_available_kw": "kW deterministic scenario",
        "renewable_power_forecast_kw": "kW causal deterministic forecast",
        "agv_fleet_available_ratio": "0-1 deterministic engineering scenario",
        "agv_mean_soc": "0-1 deterministic engineering scenario",
        "agv_charge_demand_kwh": "kWh/hour workload-derived engineering scenario",
        "agv_departure_requirement_kwh": "kWh hard departure obligation scenario",
        "charger_available_ratio": "0-1 deterministic engineering scenario",
        "reefer_connected_count": "count workload-derived engineering scenario",
        "reefer_baseline_load_kw": "kW workload-derived engineering scenario",
        "reefer_thermal_margin_c": "degC deterministic thermal-margin scenario",
        "building_critical_load_kw": "kW declared engineering scenario",
        "building_flexible_load_kw": "kW declared engineering scenario",
        "shore_power_reserved_kw": "kW vessel-activity-derived reservation scenario",
        "shore_power_window_remaining_hours": "hours deterministic reservation window",
        "equipment_health_ratio": "0-1 deterministic health scenario",
        "crane_fault_risk": "0-1 deterministic risk scenario",
        "yard_fault_risk": "0-1 deterministic risk scenario",
        "demand_response_active": "0/1 price-triggered deterministic scenario",
        "demand_response_target_kw": "kW deterministic contractual scenario",
        "demand_response_remaining_hours": "hours deterministic event window",
        "maintenance_window_active": "0/1 deterministic scenario",
    }
    units.update(unit_updates)
    parameters = dict(source_metadata["environment_parameters"])
    parameters.update(
        {
            "inspection_readiness_load_kw": 240.0,
            "regulatory_recovery_load_kw": 520.0,
            "inspection_auxiliary_kwh_per_teu_hour": 0.08,
            "released_staging_capacity_teu_per_hour": 900.0,
            "recovery_capacity_ratio": 0.35,
            "demand_charge_cny_per_kw": 0.12,
            "agv_charger_capacity_kw": 4_000.0,
            "agv_charge_efficiency": 0.94,
            "reefer_minimum_service_ratio": 0.75,
            "reefer_thermal_debt_limit": 1.0,
            "reefer_thermal_recovery_rate": 0.45,
            "building_minimum_flexible_load_ratio": 0.35,
            "demand_response_non_delivery_cny_per_kwh": 5.0,
            "agv_missed_energy_cny_per_kwh": 3.0,
            "reefer_safety_cny_per_degree_hour": 1_200.0,
        }
    )
    scenario_columns = [name for name in frame.columns if name not in public_columns]
    required_columns = [
        "vessels_at_anchor",
        "vessels_at_berth",
        "vessels_departed",
        "average_days_at_berth",
        "average_days_in_port",
        "port_activity_observed",
        *[name for name in scenario_columns if name != "source_id"],
    ]
    metadata = {
        "id": "port_la_2020_2024_operational_flex_hourly",
        "name": "Port of Los Angeles public-anchor operational-flex v5 benchmark",
        "version": "2020-2024.flex-v5.1",
        "license": source_metadata["license"],
        "source_urls": source_metadata["source_urls"],
        "attribution": source_metadata["attribution"],
        "scope_note": (
            "PUBLIC_ANCHOR_PLUS_DECLARED_ENGINEERING_SCENARIO_NOT_FIELD_KPI. "
            "Official daily vessel activity, monthly throughput and public hourly grid inputs are retained. "
            "Every v3/v4/v5 deployment, regulatory, AGV, reefer, building, reservation, health, maintenance "
            "and demand-response field is deterministic supplementation and is not port telemetry."
        ),
        "temporal_mode": "sequential_rows",
        "time_column": "timestamp_utc",
        "environment_id": "PortEnergyDispatchEnv-v5",
        "evaluation_episode_limit": 48,
        "evaluation_sampling": "48 deterministic uniformly spaced 24-hour windows per validation/test year",
        "port_profile": {
            "port_id": "USLAX-PUBLIC-FLEX-SCENARIO",
            "port_name": "Port of Los Angeles public-anchor operational-flex scenario",
            "timezone": "America/Los_Angeles",
            "deployment_mode": "offline_public_anchor_engineering_scenario",
        },
        "operational_feature_contract": {
            "required_columns": required_columns,
            "regulatory_authority_boundary": (
                "Inspection, detention and release are exogenous. The policy controls only terminal readiness and recovery."
            ),
            "rl_authority_boundary": (
                "RL may propose bounded shore-power use, equipment activation, storage, readiness/recovery, AGV charging, "
                "reefer service, building-flex use and demand-response commitment. Hard obligations are projected."
            ),
        },
        "field_provenance": {
            "public_anchor_columns": public_columns,
            "modeled_supplement_columns": scenario_columns,
            "independent_field_measurement_columns": [],
            "public_anchor_note": source_metadata["scope_note"],
            "modeled_supplement_note": (
                "Deterministic, reproducible reality-based variables. Row count does not increase independent measurement density."
            ),
        },
        "real_world_substitution_contract": {
            "schema_version": "port-energy-flex-observation.v5",
            "replace_columns_in_place": scenario_columns,
            "required_lineage_fields": [
                "source_system",
                "source_record_id",
                "event_time",
                "ingest_time",
                "unit",
                "quality",
                "revision",
                "asset_id",
                "site_id",
            ],
            "calibration_required": True,
            "shadow_retraining_required": True,
            "production_authority_after_replacement": False,
        },
        "units": units,
        "assumptions": [
            *source_metadata["assumptions"],
            "All new v5 fields are deterministic engineering scenarios and remain source-classified as modeled_supplement.",
            "AGV departure energy, refrigerated-container thermal safety, grid capacity and storage bounds are hard constraints, not reward-only preferences.",
            "Berth assignment, named crane/yard/truck scheduling, power flow, emissions ledger, settlement, authority release and physical interlocks are outside RL authority.",
        ],
        "intended_use": (
            "Leakage-safe real learner fitting on public workload/grid anchors plus reproducible flexible-load stress scenarios; "
            "future port adapters replace scenario columns under the same contract."
        ),
        "environment_parameters": parameters,
        "split_policy": source_metadata["split_policy"],
        "scenario_generation": {
            "generator": "scripts/build_operational_flex_dataset.py",
            "generator_sha256": sha256(Path(__file__)),
            "base_dataset_id": source_metadata["id"],
            "base_dataset_csv_sha256": sha256(SOURCE),
            "base_dataset_metadata_sha256": sha256(SOURCE_METADATA),
            "randomness": "none",
        },
        "safety_boundary": {
            "simulation_mode": True,
            "live_data_verified": False,
            "dispatch_allowed": False,
            "production_authority": False,
        },
        "quality": {
            "rows": int(len(frame)),
            "start": str(frame.iloc[0]["timestamp_utc"]),
            "end": str(frame.iloc[-1]["timestamp_utc"]),
            "missing_cells": int(frame.isna().sum().sum()),
            "duplicate_timestamps": int(frame["timestamp_utc"].duplicated().sum()),
            "csv_sha256": sha256(OUTPUT),
        },
    }
    OUTPUT_METADATA.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "dataset": str(OUTPUT.relative_to(ROOT)),
                "rows": len(frame),
                "columns": len(frame.columns),
                "csv_sha256": sha256(OUTPUT),
                "metadata_sha256": sha256(OUTPUT_METADATA),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
