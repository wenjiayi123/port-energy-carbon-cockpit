from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pandas as pd

from app.rl.dataset import (
    DEPLOYMENT_COLUMNS,
    FLEXIBLE_OPERATIONS_COLUMNS,
    OPERATIONAL_COLUMNS,
    REGULATORY_COLUMNS,
)
from app.rl.dataset import PortDataset


PROJECT_ROOT = Path(__file__).resolve().parents[3]


def test_v5_site_export_mapper_preserves_contract_and_evidence(tmp_path: Path) -> None:
    source_dataset = PortDataset.load("port_la_2020_2024_operational_flex_hourly")
    required = sorted(
        OPERATIONAL_COLUMNS
        | DEPLOYMENT_COLUMNS
        | REGULATORY_COLUMNS
        | FLEXIBLE_OPERATIONS_COLUMNS
    )
    base = [
        "period",
        "split",
        "loaded_import_teu",
        "loaded_export_teu",
        "total_teu",
        "grid_carbon_kg_per_kwh",
        "electricity_price_per_kwh",
        "fuel_price_per_liter",
    ]
    rows = pd.concat(
        [source_dataset.frame[source_dataset.frame["split"] == split].head(1) for split in ("train", "validation", "test")],
        ignore_index=True,
    )
    mapping = {name: f"site_{name}" for name in base + required}
    source_path = tmp_path / "site_export.csv"
    rows[base + required].rename(columns={name: mapping[name] for name in mapping}).to_csv(
        source_path,
        index=False,
    )
    mapping_path = tmp_path / "column_map.json"
    mapping_path.write_text(json.dumps(mapping), encoding="utf-8")
    evidence_path = tmp_path / "site_evidence.json"
    evidence_path.write_text(
        json.dumps(
            {
                "independent_measurement_columns": required,
                "source_domains": ["terminal_operating_system"],
                "lineage_fields": ["source_system", "event_time", "unit", "quality"],
                "shadow_days": 0,
            }
        ),
        encoding="utf-8",
    )
    output_path = tmp_path / "mapped_v5.csv"
    command = [
        sys.executable,
        str(PROJECT_ROOT / "scripts/prepare_port_dataset.py"),
        "--input",
        str(source_path),
        "--output",
        str(output_path),
        "--column-map",
        str(mapping_path),
        "--site-training-evidence",
        str(evidence_path),
        "--source-id",
        "site-export-fixture",
        "--source-url",
        "https://example.invalid/site-export-evidence",
        "--license",
        "terminal-controlled-test-fixture",
        "--timezone",
        "Asia/Kuala_Lumpur",
        "--currency",
        "MYR",
        "--environment-id",
        "PortEnergyDispatchEnv-v5",
    ]
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr

    mapped_frame = pd.read_csv(output_path)
    mapped_metadata = json.loads(output_path.with_suffix(".metadata.json").read_text())
    assert mapped_metadata["environment_id"] == "PortEnergyDispatchEnv-v5"
    assert set(required) <= set(mapped_frame.columns)
    assert mapped_metadata["field_mapping"]["agv_mean_soc"] == {
        "source_column": "site_agv_mean_soc",
        "transformation": "identity",
    }
    assert mapped_metadata["site_training_evidence"]["shadow_days"] == 0
    assert mapped_metadata["environment_parameters"] == {}
    assert "terminal_operating_system" in mapped_metadata["site_training_evidence"][
        "source_domains"
    ]


def test_v5_site_export_mapper_rejects_incomplete_observation_contract(
    tmp_path: Path,
) -> None:
    source_dataset = PortDataset.load("port_la_2020_2024_operational_flex_hourly")
    base = [
        "period",
        "split",
        "loaded_import_teu",
        "loaded_export_teu",
        "total_teu",
        "grid_carbon_kg_per_kwh",
        "electricity_price_per_kwh",
        "fuel_price_per_liter",
    ]
    rows = pd.concat(
        [
            source_dataset.frame[source_dataset.frame["split"] == split].head(1)
            for split in ("train", "validation", "test")
        ],
        ignore_index=True,
    )
    source_path = tmp_path / "incomplete_site_export.csv"
    rows[base].to_csv(source_path, index=False)
    output_path = tmp_path / "must_not_be_created.csv"
    command = [
        sys.executable,
        str(PROJECT_ROOT / "scripts/prepare_port_dataset.py"),
        "--input",
        str(source_path),
        "--output",
        str(output_path),
        "--source-id",
        "incomplete-site-export",
        "--source-url",
        "https://example.invalid/incomplete",
        "--license",
        "terminal-controlled-test-fixture",
        "--timezone",
        "Asia/Kuala_Lumpur",
        "--currency",
        "MYR",
        "--environment-id",
        "PortEnergyDispatchEnv-v5",
    ]
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    assert completed.returncode != 0
    assert "source mapping is incomplete" in completed.stderr
    assert not output_path.exists()
