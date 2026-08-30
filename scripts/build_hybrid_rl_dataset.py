#!/usr/bin/env python3
"""Build the deterministic v6 hybrid-RL dataset package.

The v5 public-anchor package is preserved. New vessel-collaboration,
operations-solver and predictive-maintenance signals are deterministic
engineering scenarios with field-level provenance. They are deliberately not
labelled as independent port telemetry and are replaceable in place at a site.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (
    ROOT
    / "backend/app/data/datasets/port_la_2020_2024_operational_flex_hourly.csv"
)
SOURCE_METADATA = SOURCE.with_suffix(".metadata.json")
OUTPUT = ROOT / "backend/app/data/datasets/port_la_2020_2024_hybrid_rl_hourly.csv"
OUTPUT_METADATA = OUTPUT.with_suffix(".metadata.json")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    frame = pd.read_csv(SOURCE)
    source_metadata = json.loads(SOURCE_METADATA.read_text(encoding="utf-8"))
    timestamps = pd.to_datetime(frame["timestamp_utc"], utc=True)
    hour = timestamps.dt.hour.to_numpy()
    day_index = (
        timestamps.dt.floor("D") - timestamps.iloc[0].floor("D")
    ).dt.days.to_numpy()

    total_teu = frame["total_teu"].to_numpy(dtype=float)
    anchor = frame["vessels_at_anchor"].to_numpy(dtype=float)
    berth = frame["vessels_at_berth"].to_numpy(dtype=float)
    weather_factor = np.clip(
        1.0
        - 0.12 * frame["wave_height_m"].to_numpy(dtype=float)
        - 0.01 * frame["precipitation_mm"].to_numpy(dtype=float),
        0.45,
        1.0,
    )
    berth_availability = frame["berth_available_ratio"].to_numpy(dtype=float)
    crane_availability = frame["crane_available_ratio"].to_numpy(dtype=float)
    yard_availability = frame["yard_available_ratio"].to_numpy(dtype=float)
    equipment_health = frame["equipment_health_ratio"].to_numpy(dtype=float)
    crane_risk = frame["crane_fault_risk"].to_numpy(dtype=float)
    yard_risk = frame["yard_fault_risk"].to_numpy(dtype=float)

    peak_arrival = np.where(np.isin(hour, [5, 6, 7, 8, 16, 17, 18, 19]), 1.0, 0.0)
    night_resource = np.where(np.isin(hour, [0, 1, 2, 3, 4]), 0.78, 0.94)
    call_pressure = np.clip(anchor / np.maximum(1.0, anchor + berth), 0.0, 1.0)

    # Ship-port coordination inputs. These are aggregate decision-instance
    # proxies; named vessel calls and certified milestone data replace them at
    # a real port.
    frame["jit_window_feasible_ratio"] = np.clip(
        weather_factor * berth_availability * (1.0 - 0.30 * call_pressure), 0.0, 1.0
    )
    frame["pilot_tug_readiness_ratio"] = np.clip(
        night_resource * weather_factor * (1.0 - 0.08 * peak_arrival), 0.0, 1.0
    )
    frame["arrival_uncertainty_hours"] = np.clip(
        0.75 + 2.4 * call_pressure + 1.8 * (1.0 - weather_factor), 0.25, 6.0
    )
    frame["anchorage_auxiliary_fuel_l_per_hour"] = np.maximum(0.0, anchor * 115.0)
    frame["green_berth_candidate_ratio"] = np.clip(
        frame["shore_power_compatible_ratio"].to_numpy(dtype=float)
        * berth_availability,
        0.0,
        1.0,
    )
    frame["berth_conflict_ratio"] = np.clip(
        0.55 * call_pressure + 0.45 * (1.0 - berth_availability), 0.0, 1.0
    )

    # Aggregate solver-instance signals. RL selects objective weights and
    # search priorities; a deterministic optimizer remains responsible for
    # named assignments, precedence, capacity and mutual exclusion.
    frame["crane_task_backlog_teu"] = np.maximum(
        0.0, total_teu * (1.10 - crane_availability)
    )
    import_share = frame["loaded_import_teu"].to_numpy(dtype=float) / np.maximum(
        1.0, total_teu
    )
    frame["crane_precedence_pressure_ratio"] = np.clip(
        0.35 + 0.35 * import_share + 0.30 * call_pressure, 0.0, 1.0
    )
    frame["yard_rehandle_ratio"] = np.clip(
        0.06 + 0.20 * import_share + 0.28 * (1.0 - yard_availability), 0.0, 0.65
    )
    frame["yard_slot_capacity_ratio"] = np.clip(
        yard_availability * (0.96 - 0.12 * peak_arrival), 0.45, 1.0
    )
    frame["truck_gate_queue_teu"] = np.maximum(
        0.0, total_teu * (0.10 + 0.22 * peak_arrival + 0.12 * call_pressure)
    )
    frame["truck_appointment_pressure_ratio"] = np.clip(
        0.24 + 0.48 * peak_arrival + 0.20 * call_pressure, 0.0, 1.0
    )
    frame["truck_gate_capacity_teu_per_hour"] = np.clip(
        1_050.0 * (1.0 - 0.18 * peak_arrival) * weather_factor, 520.0, 1_050.0
    )

    # Predictive-maintenance signals are causal deterministic forecasts from
    # declared failure cycles and current health, not telemetry-derived labels.
    maintenance_cycle = (day_index % 31) / 30.0
    frame["maintenance_due_ratio"] = np.clip(
        0.55 * maintenance_cycle + 0.45 * (1.0 - equipment_health), 0.0, 1.0
    )
    frame["maintenance_resource_available_ratio"] = np.clip(
        np.where(np.isin(hour, [1, 2, 3, 4, 13, 14]), 0.92, 0.58)
        * weather_factor,
        0.0,
        1.0,
    )
    frame["failure_risk_forecast"] = np.clip(
        0.45 * np.maximum(crane_risk, yard_risk)
        + 0.35 * (1.0 - equipment_health)
        + 0.20 * maintenance_cycle,
        0.0,
        1.0,
    )
    frame["source_id"] = frame["source_id"].astype(str) + "+HYBRID-RL-V6-SCENARIO-V1"

    numeric_columns = frame.select_dtypes(include=["number"]).columns
    frame[numeric_columns] = frame[numeric_columns].round(8)
    frame.to_csv(OUTPUT, index=False)

    new_columns = [name for name in frame.columns if name not in pd.read_csv(SOURCE, nrows=0).columns]
    units = dict(source_metadata["units"])
    units.update(
        {
            "jit_window_feasible_ratio": "0-1 deterministic coordination scenario",
            "pilot_tug_readiness_ratio": "0-1 deterministic coordination scenario",
            "arrival_uncertainty_hours": "hours deterministic scenario",
            "anchorage_auxiliary_fuel_l_per_hour": "litres/hour workload-derived scenario",
            "green_berth_candidate_ratio": "0-1 deterministic compatibility scenario",
            "berth_conflict_ratio": "0-1 deterministic congestion scenario",
            "crane_task_backlog_teu": "TEU workload-derived solver-instance scenario",
            "crane_precedence_pressure_ratio": "0-1 deterministic precedence scenario",
            "yard_rehandle_ratio": "0-1 deterministic rehandle scenario",
            "yard_slot_capacity_ratio": "0-1 deterministic capacity scenario",
            "truck_gate_queue_teu": "TEU workload-derived queue scenario",
            "truck_appointment_pressure_ratio": "0-1 deterministic appointment scenario",
            "truck_gate_capacity_teu_per_hour": "TEU/hour declared engineering scenario",
            "maintenance_due_ratio": "0-1 deterministic due-state scenario",
            "maintenance_resource_available_ratio": "0-1 deterministic resource scenario",
            "failure_risk_forecast": "0-1 causal deterministic risk forecast",
        }
    )
    parameters = dict(source_metadata["environment_parameters"])
    parameters.update(
        {
            "hybrid_residual_trust_ratio": 0.20,
            "jit_deviation_cost_cny_per_hour": 2_400.0,
            "berth_conflict_cost_cny_per_hour": 4_000.0,
            "crane_task_lateness_cny_per_teu": 9.0,
            "yard_rehandle_cost_cny_per_teu": 7.0,
            "truck_queue_cost_cny_per_teu_hour": 11.0,
            "maintenance_overdue_cost_cny_per_hour": 8_000.0,
        }
    )
    inherited_public = list(source_metadata["field_provenance"]["public_anchor_columns"])
    inherited_modeled = list(source_metadata["field_provenance"]["modeled_supplement_columns"])
    required_columns = list(
        source_metadata["operational_feature_contract"]["required_columns"]
    ) + new_columns
    metadata = {
        **{
            key: value
            for key, value in source_metadata.items()
            if key
            not in {
                "id",
                "name",
                "version",
                "scope_note",
                "environment_id",
                "operational_feature_contract",
                "field_provenance",
                "real_world_substitution_contract",
                "units",
                "assumptions",
                "intended_use",
                "environment_parameters",
                "scenario_generation",
                "quality",
            }
        },
        "id": "port_la_2020_2024_hybrid_rl_hourly",
        "name": "Port of Los Angeles public-anchor hybrid residual-RL v6 benchmark",
        "version": "2020-2024.hybrid-v6.1",
        "scope_note": (
            "PUBLIC_ANCHOR_PLUS_DECLARED_ENGINEERING_SCENARIO_NOT_FIELD_KPI. "
            "Vessel-collaboration, solver-instance and predictive-maintenance fields "
            "are deterministic supplements and are not independent port telemetry."
        ),
        "environment_id": "PortEnergyHybridResidualEnv-v6",
        "operational_feature_contract": {
            "required_columns": required_columns,
            "rl_authority_boundary": (
                "RL emits bounded residual controls and six strategic priorities. "
                "Control, constraint programming and hard projections emit feasible commands."
            ),
            "named_schedule_boundary": (
                "Named vessel, berth, crane, yard-slot and truck-gate assignments remain solver outputs."
            ),
        },
        "field_provenance": {
            "public_anchor_columns": inherited_public,
            "modeled_supplement_columns": inherited_modeled + new_columns,
            "independent_field_measurement_columns": [],
            "public_anchor_note": source_metadata["field_provenance"]["public_anchor_note"],
            "modeled_supplement_note": (
                "Deterministic reality-based variables; row count does not increase independent measurement density."
            ),
        },
        "real_world_substitution_contract": {
            "schema_version": "port-energy-hybrid-observation.v6",
            "replace_columns_in_place": inherited_modeled + new_columns,
            "required_lineage_fields": source_metadata["real_world_substitution_contract"][
                "required_lineage_fields"
            ],
            "calibration_required": True,
            "shadow_retraining_required": True,
            "production_authority_after_replacement": False,
        },
        "units": units,
        "assumptions": [
            *source_metadata["assumptions"],
            "All v6 additions are deterministic engineering scenarios and remain modeled_supplement.",
            "Residual RL cannot bypass control, solver, safety, authority or physical-dispatch boundaries.",
            "RL priorities are not named operational orders; a constraint solver must produce the executable plan.",
        ],
        "intended_use": (
            "Leakage-safe residual-RL and RL-guided solver research using public workload/grid anchors; "
            "site adapters replace scenario columns without changing the v6 interface."
        ),
        "environment_parameters": parameters,
        "scenario_generation": {
            "generator": "scripts/build_hybrid_rl_dataset.py",
            "generator_sha256": sha256(Path(__file__)),
            "base_dataset_id": source_metadata["id"],
            "base_dataset_csv_sha256": sha256(SOURCE),
            "base_dataset_metadata_sha256": sha256(SOURCE_METADATA),
            "randomness": "none",
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
                "new_modeled_columns": len(new_columns),
                "csv_sha256": sha256(OUTPUT),
                "metadata_sha256": sha256(OUTPUT_METADATA),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
