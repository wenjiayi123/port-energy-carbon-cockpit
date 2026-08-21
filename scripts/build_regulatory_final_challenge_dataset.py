#!/usr/bin/env python3
"""Freeze a second, previously unread 2025 regulatory challenge schedule."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "backend/app/data/datasets/port_la_2025_regulatory_forward_challenge_hourly.csv"
SOURCE_METADATA = SOURCE.with_suffix(".metadata.json")
OUTPUT = ROOT / "backend/app/data/datasets/port_la_2025_regulatory_final_challenge_hourly.csv"
OUTPUT_METADATA = OUTPUT.with_suffix(".metadata.json")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    frame = pd.read_csv(SOURCE)
    source_metadata = json.loads(SOURCE_METADATA.read_text(encoding="utf-8"))
    hour_index = np.arange(len(frame), dtype=int)
    maritime_cycle = (hour_index + 3 * 24) % (23 * 24)
    customs_cycle = (hour_index + 11 * 24) % (17 * 24)
    maritime_active = maritime_cycle < 36
    maritime_release = (maritime_cycle >= 36) & (maritime_cycle < 66)
    customs_active = customs_cycle < 24
    customs_release = (customs_cycle >= 24) & (customs_cycle < 54)
    frame["maritime_inspection_ratio"] = np.where(maritime_active, 0.080, 0.0)
    frame["customs_inspection_ratio"] = np.where(customs_active, 0.100, 0.002)
    frame["maritime_release_ratio"] = np.where(
        maritime_active, 0.010, np.where(maritime_release, 0.14, 0.40)
    )
    frame["customs_release_ratio"] = np.where(
        customs_active, 0.008, np.where(customs_release, 0.13, 0.36)
    )
    active = maritime_active | customs_active
    frame["document_readiness_ratio"] = np.where(active, 0.52, 0.84)
    frame["inspection_resource_available_ratio"] = np.where(active, 0.65, 0.88)
    frame["expected_hold_hours"] = np.where(
        maritime_active & customs_active,
        24.0,
        np.where(maritime_active, 20.0, np.where(customs_active, 16.0, 2.0)),
    )
    frame["source_id"] = (
        frame["source_id"].astype(str).str.replace(
            "+FROZEN-FORWARD-CHALLENGE-V1", "", regex=False
        )
        + "+FROZEN-FINAL-CHALLENGE-V1"
    )
    frame[frame.select_dtypes(include=["number"]).columns] = frame.select_dtypes(
        include=["number"]
    ).round(8)
    frame.to_csv(OUTPUT, index=False)
    metadata = dict(source_metadata)
    metadata.update(
        {
            "id": "port_la_2025_regulatory_final_challenge_hourly",
            "name": "Port of Los Angeles 2025 frozen final regulatory resilience challenge",
            "version": "2025.regulatory-final.1",
            "scope_note": (
                "FROZEN_FINAL_REGULATORY_ENERGY_CHALLENGE_NOT_FIELD_KPI. This second schedule was generated and "
                "hashed before projected-policy fitting and was not used for training or model selection."
            ),
            "intended_use": "One-time final challenge for the selected dominance-projected incremental SAC.",
            "scenario_generation": {
                "generator": "scripts/build_regulatory_final_challenge_dataset.py",
                "generator_sha256": sha256(Path(__file__)),
                "base_forward_dataset_id": source_metadata["id"],
                "base_forward_csv_sha256": sha256(SOURCE),
                "base_forward_metadata_sha256": sha256(SOURCE_METADATA),
                "randomness": "none",
                "frozen_before_projected_policy_training": True,
                "previous_challenge_metrics_used": False,
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
    )
    metadata["split_policy"] = {
        "train": "2025-01-01 through 2025-08-31; not used",
        "validation": "2025-09-01 through 2025-10-31; not used",
        "test": "2025-11-01 through 2025-12-31; evaluated once after 2024 validation selection",
    }
    OUTPUT_METADATA.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "rows": len(frame),
                "csv_sha256": sha256(OUTPUT),
                "metadata_sha256": sha256(OUTPUT_METADATA),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
