#!/usr/bin/env python3
"""Build the frozen PortEnergyDispatchEnv-v4 regulatory stress package.

The public energy and vessel-activity columns are copied from the registered
Port of Los Angeles package. Regulatory events and v3 deployment inputs are
deterministic scenario variables, never represented as measured port records.
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
OUTPUT = ROOT / "backend/app/data/datasets/port_la_2024_regulatory_resilience_hourly.csv"
OUTPUT_METADATA = OUTPUT.with_suffix(".metadata.json")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    source = pd.read_csv(SOURCE)
    source_metadata = json.loads(SOURCE_METADATA.read_text(encoding="utf-8"))
    frame = source[source["timestamp_utc"].astype(str).str.startswith("2024-")].copy()
    timestamps = pd.to_datetime(frame["timestamp_utc"], utc=True)
    hour_index = np.arange(len(frame), dtype=int)
    hour = timestamps.dt.hour.to_numpy()
    day_of_year = timestamps.dt.dayofyear.to_numpy()

    frame["split"] = np.where(
        timestamps < pd.Timestamp("2024-09-01", tz="UTC"),
        "train",
        np.where(
            timestamps < pd.Timestamp("2024-11-01", tz="UTC"),
            "validation",
            "test",
        ),
    )

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
    stress_active = maritime_active | customs_active
    frame["document_readiness_ratio"] = np.where(stress_active, 0.58, 0.88)
    frame["inspection_resource_available_ratio"] = np.where(stress_active, 0.70, 0.92)
    # Zero deliberately records that no row is an observed authority event.
    frame["regulatory_scenario_observed"] = 0.0
    frame["expected_hold_hours"] = np.where(
        maritime_active & customs_active,
        20.0,
        np.where(maritime_active, 16.0, np.where(customs_active, 12.0, 2.0)),
    )

    storm = (day_of_year % 23 == 0) | (day_of_year % 37 == 0)
    frame["wind_speed_m_s"] = 4.5 + 1.8 * np.sin(2 * np.pi * hour / 24)
    frame["wave_height_m"] = np.where(storm, 1.8, 0.55)
    frame["visibility_km"] = np.where(storm, 7.0, 18.0)
    frame["precipitation_mm"] = np.where(storm, 3.0, 0.0)
    frame["berth_available_ratio"] = np.where(storm, 0.82, 0.96)
    frame["crane_available_ratio"] = np.where(storm, 0.80, 0.94)
    frame["yard_available_ratio"] = np.where(storm, 0.84, 0.93)
    frame["grid_available_ratio"] = 0.98
    frame["shore_power_compatible_ratio"] = 0.90
    solar_shape = np.maximum(0.0, np.sin(np.pi * (hour - 6) / 12))
    frame["renewable_power_available_kw"] = 1_200.0 * solar_shape
    frame["source_id"] = frame["source_id"].astype(str) + "+FROZEN-REGULATORY-STRESS-V1"

    numeric_columns = frame.select_dtypes(include=["number"]).columns
    frame[numeric_columns] = frame[numeric_columns].round(8)
    frame.to_csv(OUTPUT, index=False)

    units = dict(source_metadata["units"])
    units.update(
        {
            "maritime_inspection_ratio": "0-1 frozen scenario share of hourly TEU",
            "customs_inspection_ratio": "0-1 frozen scenario share of hourly TEU",
            "maritime_release_ratio": "0-1 exogenous scenario release share per hour",
            "customs_release_ratio": "0-1 exogenous scenario release share per hour",
            "document_readiness_ratio": "0-1 scenario readiness signal",
            "inspection_resource_available_ratio": "0-1 scenario terminal resource signal",
            "regulatory_scenario_observed": "0/1; fixed at 0 because events are synthetic",
            "expected_hold_hours": "hours scenario expectation",
            "wind_speed_m_s": "m/s deterministic deployment scenario",
            "wave_height_m": "m deterministic deployment scenario",
            "visibility_km": "km deterministic deployment scenario",
            "precipitation_mm": "mm/hour deterministic deployment scenario",
            "berth_available_ratio": "0-1 deterministic deployment scenario",
            "crane_available_ratio": "0-1 deterministic deployment scenario",
            "yard_available_ratio": "0-1 deterministic deployment scenario",
            "grid_available_ratio": "0-1 deterministic deployment scenario",
            "shore_power_compatible_ratio": "0-1 deterministic deployment scenario",
            "renewable_power_available_kw": "kW deterministic deployment scenario",
        }
    )
    environment_parameters = dict(source_metadata["environment_parameters"])
    environment_parameters.update(
        {
            "inspection_readiness_load_kw": 240.0,
            "regulatory_recovery_load_kw": 520.0,
            "inspection_auxiliary_kwh_per_teu_hour": 0.08,
            "released_staging_capacity_teu_per_hour": 900.0,
            "recovery_capacity_ratio": 0.35,
        }
    )
    metadata = {
        "id": "port_la_2024_regulatory_resilience_hourly",
        "name": "Port of Los Angeles 2024 frozen maritime/customs inspection energy-carbon resilience scenario",
        "version": "2024.regulatory-resilience.1",
        "license": source_metadata["license"],
        "source_urls": [
            *source_metadata["source_urls"],
            "https://www.imo.org/en/ourwork/iiis/pages/port%20state%20control.aspx",
            "https://www.help.cbp.gov/s/article/Article-1268?language=en_US",
            "https://www.help.cbp.gov/s/article/Article-1267",
        ],
        "attribution": (
            source_metadata["attribution"]
            + " Regulatory process boundaries referenced to IMO Port State Control and U.S. CBP hold/release guidance."
        ),
        "scope_note": (
            "PREDECLARED_REGULATORY_ENERGY_STRESS_SCENARIO_NOT_FIELD_KPI. Public energy, TEU and vessel-activity "
            "signals are retained from the source package; every maritime/customs inspection, release, weather, "
            "availability and renewable input added here is a deterministic stress variable, not terminal or authority telemetry."
        ),
        "temporal_mode": "sequential_rows",
        "time_column": "timestamp_utc",
        "environment_id": "PortEnergyDispatchEnv-v4",
        "evaluation_episode_limit": 48,
        "evaluation_sampling": "48 deterministic uniformly spaced 24-hour windows; validation selects, test reports once",
        "port_profile": {
            "port_id": "USLAX-SCENARIO",
            "port_name": "Port of Los Angeles public-data regulatory resilience stress scenario",
            "timezone": "America/Los_Angeles",
            "currency": "CNY scenario converted from public USD anchors",
            "deployment_mode": "offline_public_stress_benchmark",
        },
        "operational_feature_contract": {
            "required_columns": [
                "vessels_at_anchor",
                "vessels_at_berth",
                "vessels_departed",
                "average_days_at_berth",
                "average_days_in_port",
                "port_activity_observed",
                "wind_speed_m_s",
                "wave_height_m",
                "visibility_km",
                "precipitation_mm",
                "berth_available_ratio",
                "crane_available_ratio",
                "yard_available_ratio",
                "grid_available_ratio",
                "shore_power_compatible_ratio",
                "renewable_power_available_kw",
                "maritime_inspection_ratio",
                "customs_inspection_ratio",
                "maritime_release_ratio",
                "customs_release_ratio",
                "document_readiness_ratio",
                "inspection_resource_available_ratio",
                "regulatory_scenario_observed",
                "expected_hold_hours",
            ],
            "regulatory_authority_boundary": (
                "Inspection selection, detention and release are exogenous. The policy may only allocate terminal readiness and post-release recovery."
            ),
        },
        "units": units,
        "assumptions": [
            *source_metadata["assumptions"],
            "Maritime/customs arrival and release profiles are frozen deterministic stress schedules, not historical authority records.",
            "No action can change an authority hold or release ratio; actions only affect terminal readiness and post-release recovery.",
            "Held cargo contributes a declared auxiliary-energy proxy and delay cost so regulatory disruption propagates into energy, carbon and cost.",
            "Deployment observations are neutral deterministic scenario values and do not upgrade the package to production readiness.",
        ],
        "intended_use": (
            "Leakage-safe training and held-out comparison of inspection-aware terminal energy-carbon recovery strategies."
        ),
        "environment_parameters": environment_parameters,
        "split_policy": {
            "train": "2024-01-01 through 2024-08-31",
            "validation": "2024-09-01 through 2024-10-31",
            "test": "2024-11-01 through 2024-12-31",
        },
        "scenario_generation": {
            "generator": "scripts/build_regulatory_resilience_dataset.py",
            "generator_sha256": sha256(Path(__file__)),
            "base_dataset_id": source_metadata["id"],
            "base_dataset_csv_sha256": sha256(SOURCE),
            "base_dataset_metadata_sha256": sha256(SOURCE_METADATA),
            "randomness": "none",
            "authority_inputs": "exogenous",
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
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "dataset": str(OUTPUT.relative_to(ROOT)),
                "rows": len(frame),
                "csv_sha256": sha256(OUTPUT),
                "metadata_sha256": sha256(OUTPUT_METADATA),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
