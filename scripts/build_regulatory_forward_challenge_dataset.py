#!/usr/bin/env python3
"""Build the untouched 2025 forward challenge for the v4 incremental policy."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "backend/app/data/datasets/port_la_2020_2025_hourly.csv"
SOURCE_METADATA = SOURCE.with_suffix(".metadata.json")
OUTPUT = ROOT / "backend/app/data/datasets/port_la_2025_regulatory_forward_challenge_hourly.csv"
OUTPUT_METADATA = OUTPUT.with_suffix(".metadata.json")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    source = pd.read_csv(SOURCE)
    source_metadata = json.loads(SOURCE_METADATA.read_text(encoding="utf-8"))
    frame = source[source["timestamp_utc"].astype(str).str.startswith("2025-")].copy()
    timestamps = pd.to_datetime(frame["timestamp_utc"], utc=True)
    hour_index = np.arange(len(frame), dtype=int)
    hour = timestamps.dt.hour.to_numpy()
    day_of_year = timestamps.dt.dayofyear.to_numpy()
    frame["split"] = np.where(
        timestamps < pd.Timestamp("2025-09-01", tz="UTC"),
        "train",
        np.where(timestamps < pd.Timestamp("2025-11-01", tz="UTC"), "validation", "test"),
    )

    # The forward schedule changes phase and cycle lengths from the 2024
    # development package. It is frozen before any forward evaluation.
    maritime_cycle = (hour_index + 13 * 24) % (19 * 24)
    customs_cycle = (hour_index + 7 * 24) % (13 * 24)
    maritime_active = maritime_cycle < 30
    maritime_release = (maritime_cycle >= 30) & (maritime_cycle < 54)
    customs_active = customs_cycle < 20
    customs_release = (customs_cycle >= 20) & (customs_cycle < 44)
    frame["maritime_inspection_ratio"] = np.where(maritime_active, 0.070, 0.0)
    frame["customs_inspection_ratio"] = np.where(customs_active, 0.090, 0.002)
    frame["maritime_release_ratio"] = np.where(
        maritime_active, 0.012, np.where(maritime_release, 0.16, 0.42)
    )
    frame["customs_release_ratio"] = np.where(
        customs_active, 0.010, np.where(customs_release, 0.15, 0.38)
    )
    active = maritime_active | customs_active
    frame["document_readiness_ratio"] = np.where(active, 0.55, 0.86)
    frame["inspection_resource_available_ratio"] = np.where(active, 0.68, 0.90)
    frame["regulatory_scenario_observed"] = 0.0
    frame["expected_hold_hours"] = np.where(
        maritime_active & customs_active,
        22.0,
        np.where(maritime_active, 18.0, np.where(customs_active, 14.0, 2.0)),
    )

    # The source has no daily vessel activity. These are declared scenario
    # covariates, not fabricated official records.
    frame["vessels_at_berth"] = np.clip(frame["total_teu"].to_numpy() / 150.0, 4.0, 14.0)
    frame["vessels_at_anchor"] = 3.0 + 2.0 * (1.0 + np.sin(2 * np.pi * day_of_year / 31.0))
    frame["vessels_departed"] = np.clip(frame["vessels_at_berth"] / 3.0, 1.0, 5.0)
    frame["average_days_at_berth"] = 1.6
    frame["average_days_in_port"] = 3.2
    frame["port_activity_observed"] = 0.0

    storm = (day_of_year % 29 == 0) | (day_of_year % 41 == 0)
    frame["wind_speed_m_s"] = 4.8 + 2.0 * np.sin(2 * np.pi * hour / 24)
    frame["wave_height_m"] = np.where(storm, 2.0, 0.60)
    frame["visibility_km"] = np.where(storm, 6.0, 17.0)
    frame["precipitation_mm"] = np.where(storm, 3.5, 0.0)
    frame["berth_available_ratio"] = np.where(storm, 0.80, 0.95)
    frame["crane_available_ratio"] = np.where(storm, 0.78, 0.93)
    frame["yard_available_ratio"] = np.where(storm, 0.82, 0.92)
    frame["grid_available_ratio"] = 0.98
    frame["shore_power_compatible_ratio"] = 0.88
    frame["renewable_power_available_kw"] = 1_100.0 * np.maximum(
        0.0, np.sin(np.pi * (hour - 6) / 12)
    )
    frame["source_id"] = frame["source_id"].astype(str) + "+FROZEN-FORWARD-CHALLENGE-V1"
    frame[frame.select_dtypes(include=["number"]).columns] = frame.select_dtypes(
        include=["number"]
    ).round(8)
    frame.to_csv(OUTPUT, index=False)

    units = dict(source_metadata["units"])
    units.update(
        {
            "vessels_at_anchor": "vessels deterministic forward scenario",
            "vessels_at_berth": "vessels deterministic forward scenario",
            "vessels_departed": "vessels deterministic forward scenario",
            "average_days_at_berth": "days deterministic forward scenario",
            "average_days_in_port": "days deterministic forward scenario",
            "port_activity_observed": "0/1 fixed at 0; no official daily feed",
            "wind_speed_m_s": "m/s deterministic forward scenario",
            "wave_height_m": "m deterministic forward scenario",
            "visibility_km": "km deterministic forward scenario",
            "precipitation_mm": "mm/hour deterministic forward scenario",
            "berth_available_ratio": "0-1 deterministic forward scenario",
            "crane_available_ratio": "0-1 deterministic forward scenario",
            "yard_available_ratio": "0-1 deterministic forward scenario",
            "grid_available_ratio": "0-1 deterministic forward scenario",
            "shore_power_compatible_ratio": "0-1 deterministic forward scenario",
            "renewable_power_available_kw": "kW deterministic forward scenario",
            "maritime_inspection_ratio": "0-1 frozen forward scenario share",
            "customs_inspection_ratio": "0-1 frozen forward scenario share",
            "maritime_release_ratio": "0-1 exogenous forward scenario release share",
            "customs_release_ratio": "0-1 exogenous forward scenario release share",
            "document_readiness_ratio": "0-1 deterministic forward scenario",
            "inspection_resource_available_ratio": "0-1 deterministic forward scenario",
            "regulatory_scenario_observed": "0/1 fixed at 0; not authority telemetry",
            "expected_hold_hours": "hours deterministic forward scenario",
        }
    )
    parameters = dict(source_metadata["environment_parameters"])
    parameters.update(
        {
            "inspection_readiness_load_kw": 240.0,
            "regulatory_recovery_load_kw": 520.0,
            "inspection_auxiliary_kwh_per_teu_hour": 0.08,
            "released_staging_capacity_teu_per_hour": 900.0,
            "recovery_capacity_ratio": 0.35,
        }
    )
    required = [
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
    ]
    metadata = {
        "id": "port_la_2025_regulatory_forward_challenge_hourly",
        "name": "Port of Los Angeles 2025 frozen regulatory energy-carbon forward challenge",
        "version": "2025.regulatory-forward.1",
        "license": source_metadata["license"],
        "source_urls": [
            *source_metadata["source_urls"],
            "https://www.imo.org/en/ourwork/iiis/pages/port%20state%20control.aspx",
            "https://www.help.cbp.gov/s/article/Article-1268?language=en_US",
            "https://www.help.cbp.gov/s/article/Article-1267",
        ],
        "attribution": source_metadata["attribution"] + "; IMO and U.S. CBP process-boundary references.",
        "scope_note": (
            "FROZEN_FORWARD_REGULATORY_ENERGY_CHALLENGE_NOT_FIELD_KPI. Public 2025 TEU and energy inputs "
            "come from the base package; vessel, deployment and regulatory inputs are deterministic stress variables."
        ),
        "temporal_mode": "sequential_rows",
        "time_column": "timestamp_utc",
        "environment_id": "PortEnergyDispatchEnv-v4",
        "evaluation_episode_limit": 48,
        "evaluation_sampling": "48 frozen uniformly spaced 24-hour windows",
        "operational_feature_contract": {
            "required_columns": required,
            "regulatory_authority_boundary": "Authority inspection and release are exogenous; the policy has no release authority.",
        },
        "units": units,
        "assumptions": [
            *source_metadata["assumptions"],
            "All v2/v3/v4 fields added by this generator are deterministic forward-stress variables, not measured records.",
            "The generator and hashes freeze the forward challenge before evaluation.",
            "The policy can allocate terminal readiness and recovery only; it cannot alter authority holds or release.",
        ],
        "intended_use": "One-time forward challenge for the selected incremental regulatory policy.",
        "environment_parameters": parameters,
        "split_policy": {
            "train": "2025-01-01 through 2025-08-31; not used to refit the selected 2024 policy",
            "validation": "2025-09-01 through 2025-10-31; not used for policy selection",
            "test": "2025-11-01 through 2025-12-31; one-time forward challenge",
        },
        "scenario_generation": {
            "generator": "scripts/build_regulatory_forward_challenge_dataset.py",
            "generator_sha256": sha256(Path(__file__)),
            "base_dataset_id": source_metadata["id"],
            "base_dataset_csv_sha256": sha256(SOURCE),
            "base_dataset_metadata_sha256": sha256(SOURCE_METADATA),
            "randomness": "none",
            "frozen_before_evaluation": True,
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
    print(json.dumps({"rows": len(frame), "csv_sha256": sha256(OUTPUT)}, indent=2))


if __name__ == "__main__":
    main()
