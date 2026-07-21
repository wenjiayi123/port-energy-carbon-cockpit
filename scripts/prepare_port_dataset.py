#!/usr/bin/env python3
"""Map a port export into the canonical training CSV and validate it."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.rl.dataset import PortDataset  # noqa: E402


CANONICAL_COLUMNS = {
    "period": "period_col",
    "split": "split_col",
    "loaded_import_teu": "import_col",
    "loaded_export_teu": "export_col",
    "total_teu": "total_col",
    "grid_carbon_kg_per_kwh": "grid_carbon_col",
    "electricity_price_per_kwh": "electricity_price_col",
    "fuel_price_per_liter": "fuel_price_col",
}

OPTIONAL_COLUMNS = {
    "observation_hours": "observation_hours_col",
    "crane_capacity_teu_per_hour": "crane_capacity_col",
    "yard_capacity_teu_per_hour": "yard_capacity_col",
    "shore_demand_kw": "shore_demand_col",
    "base_load_kw": "base_load_col",
    "load_kw_per_teu": "load_per_teu_col",
    "crane_load_kw": "crane_load_col",
    "yard_load_kw": "yard_load_col",
    "grid_capacity_kw": "grid_capacity_col",
    "fuel_kwh_per_liter": "fuel_efficiency_col",
    "fuel_carbon_kg_per_liter": "fuel_carbon_col",
    "delay_cost_cny_per_minute": "delay_cost_col",
    "delay_limit_minutes": "delay_limit_col",
}
OPTIONAL_UNITS = {
    "observation_hours": "hours",
    "crane_capacity_teu_per_hour": "TEU/hour",
    "yard_capacity_teu_per_hour": "TEU/hour",
    "shore_demand_kw": "kW",
    "base_load_kw": "kW",
    "load_kw_per_teu": "kW/TEU",
    "crane_load_kw": "kW",
    "yard_load_kw": "kW",
    "grid_capacity_kw": "kW",
    "fuel_kwh_per_liter": "kWh/liter",
    "fuel_carbon_kg_per_liter": "kgCO2e/liter",
    "delay_cost_cny_per_minute": "CNY/minute",
    "delay_limit_minutes": "minutes",
}


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--input", required=True, type=Path)
    result.add_argument("--output", required=True, type=Path)
    result.add_argument("--period-col", default="period")
    result.add_argument("--split-col", default="split")
    result.add_argument("--import-col", default="loaded_import_teu")
    result.add_argument("--export-col", default="loaded_export_teu")
    result.add_argument("--total-col", default="total_teu")
    result.add_argument("--grid-carbon-col", default="grid_carbon_kg_per_kwh")
    result.add_argument("--electricity-price-col", default="electricity_price_per_kwh")
    result.add_argument("--fuel-price-col", default="fuel_price_per_liter")
    result.add_argument("--observation-hours-col")
    result.add_argument("--crane-capacity-col")
    result.add_argument("--yard-capacity-col")
    result.add_argument("--shore-demand-col")
    result.add_argument("--base-load-col")
    result.add_argument("--load-per-teu-col")
    result.add_argument("--crane-load-col")
    result.add_argument("--yard-load-col")
    result.add_argument("--grid-capacity-col")
    result.add_argument("--fuel-efficiency-col")
    result.add_argument("--fuel-carbon-col")
    result.add_argument("--delay-cost-col")
    result.add_argument("--delay-limit-col")
    result.add_argument("--temporal-mode", choices=["profiled_period", "sequential_rows"], default="profiled_period")
    result.add_argument("--environment-config", type=Path, help="JSON object with terminal environment parameters")
    result.add_argument("--source-id", required=True)
    result.add_argument("--source-url", action="append", default=[])
    result.add_argument("--license", dest="license_name", required=True)
    result.add_argument("--name", default="Canonical port training dataset")
    return result


def main() -> None:
    args = parser().parse_args()
    source = args.input.expanduser().resolve()
    output = args.output.expanduser().resolve()
    if source == output:
        raise SystemExit("--output must differ from --input")
    frame = pd.read_csv(source)
    mapping = {
        str(getattr(args, argument_name)): canonical
        for canonical, argument_name in CANONICAL_COLUMNS.items()
    }
    missing = sorted(column for column in mapping if column not in frame.columns)
    if missing:
        raise SystemExit(f"source columns not found: {', '.join(missing)}")
    renamed = frame.rename(columns=mapping)
    canonical = renamed[list(CANONICAL_COLUMNS)].copy()
    for canonical_name, argument_name in OPTIONAL_COLUMNS.items():
        source_column = getattr(args, argument_name)
        if source_column:
            if source_column not in frame.columns:
                raise SystemExit(f"source column not found: {source_column}")
            canonical[canonical_name] = frame[source_column]
    canonical["source_id"] = args.source_id
    output.parent.mkdir(parents=True, exist_ok=True)
    canonical.to_csv(output, index=False)
    environment_parameters = {}
    if args.environment_config:
        environment_parameters = json.loads(args.environment_config.expanduser().read_text(encoding="utf-8"))
        if not isinstance(environment_parameters, dict):
            raise SystemExit("--environment-config must contain one JSON object")
    units = {
        "loaded_import_teu": "TEU/period",
        "loaded_export_teu": "TEU/period",
        "total_teu": "TEU/period",
        "grid_carbon_kg_per_kwh": "kgCO2e/kWh",
        "electricity_price_per_kwh": "CNY/kWh",
        "fuel_price_per_liter": "CNY/liter",
    }
    units.update({column: unit for column, unit in OPTIONAL_UNITS.items() if column in canonical.columns})
    metadata = {
        "id": output.stem,
        "name": args.name,
        "license": args.license_name,
        "source_urls": args.source_url,
        "attribution": f"Prepared from {source.name}; source_id={args.source_id}",
        "scope_note": "Canonical snapshot prepared for offline training and held-out evaluation.",
        "temporal_mode": args.temporal_mode,
        "environment_parameters": environment_parameters,
        "units": units,
    }
    output.with_suffix(".metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(PortDataset.load(output).describe(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
