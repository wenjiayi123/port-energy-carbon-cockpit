#!/usr/bin/env python3
"""Build the Port of Los Angeles vessel-activity enhanced hourly dataset."""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import io
import json
from pathlib import Path
import ssl
from typing import Any
from urllib.request import Request, urlopen

import pandas as pd
import pdfplumber


ROOT = Path(__file__).resolve().parents[1]
DATASET_DIR = ROOT / "backend" / "app" / "data" / "datasets"
SOURCE_DIR = ROOT / "backend" / "app" / "data" / "source_snapshots"
BASE_DATASET = DATASET_DIR / "port_la_2020_2025_hourly.csv"
BASE_METADATA = BASE_DATASET.with_suffix(".metadata.json")
DEFAULT_OUTPUT = DATASET_DIR / "port_la_2020_2024_vessel_activity_hourly.csv"
DEFAULT_SOURCE_OUTPUT = SOURCE_DIR / "port_la_vessel_activity_2020_2024.csv"
DEFAULT_CACHE_DIR = ROOT / "tmp" / "pdfs" / "port_la_vessel_activity"

VESSEL_ACTIVITY_URLS = {
    2020: (
        "https://kentico.portoflosangeles.org/getmedia/"
        "0d0d0edf-642c-4c36-a19e-17a3ab9f7fbc/"
        "Port-of-Los-Angeles-Container-Vessel-Activity-Summary-2020"
    ),
    2021: (
        "https://kentico.portoflosangeles.org/getmedia/"
        "ac55745f-1d72-4b4f-b1c3-8984a3bbee48/"
        "Port-of-Los-Angeles-Container-Vessel-Activity-Summary-2021"
    ),
    2022: (
        "https://kentico.portoflosangeles.org/getmedia/"
        "cc5f5153-37b6-4563-bfa3-2b8b55997758/"
        "Port-of-Los-Angeles-Container-Vessel-Activity-Summary-2022"
    ),
    2023: (
        "https://kentico.portoflosangeles.org/getmedia/"
        "f936a4b4-7e56-46ad-9c04-b47623eff754/"
        "Port-of-Los-Angeles-Container-Vessel-Activity-Summary-2023"
    ),
    2024: (
        "https://kentico.portoflosangeles.org/getmedia/"
        "d4f44790-0ed5-49c8-abfb-5c70386d7135/"
        "Port-of-Los-Angeles-Container-Vessel-Activity-Summary-2024"
    ),
}

ACTIVITY_COLUMNS = (
    "vessels_at_anchor",
    "vessels_at_berth",
    "vessels_departed",
    "average_days_at_berth",
    "average_days_in_port",
)
KNOWN_SOURCE_CORRECTIONS = {
    (2020, "6/17/20202"): (
        "6/17/2020",
        "PDF year typo; the row is ordered between 6/16/2020 and 6/18/2020.",
    ),
    (2022, "12/12/2012"): (
        "12/12/2022",
        "PDF year typo; the row is ordered between 12/9/2022 and 12/13/2022.",
    ),
    (2022, "6.8.33"): (
        "6.833",
        "Malformed decimal in the 9/6/2022 average-days-at-berth cell.",
    ),
    (2023, "710/2023"): (
        "7/10/2023",
        "PDF date separator omission; the row is ordered after 7/7/2023.",
    ),
}


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def fetch_pdf(url: str, cache_path: Path, refresh: bool) -> bytes:
    if cache_path.exists() and not refresh:
        payload = cache_path.read_bytes()
    else:
        request = Request(
            url,
            headers={
                "User-Agent": (
                    "CarbonOps reproducible public-dataset builder/4.0 "
                    "(source attribution in generated metadata)"
                )
            },
        )
        context = ssl.create_default_context()
        with urlopen(request, timeout=90, context=context) as response:
            payload = response.read()
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_bytes(payload)
    if not payload.startswith(b"%PDF"):
        raise RuntimeError(f"Official source did not return a PDF: {url}")
    return payload


def parse_pdf(year: int, payload: bytes) -> tuple[pd.DataFrame, list[dict[str, str]]]:
    records: list[dict[str, Any]] = []
    corrections: list[dict[str, str]] = []
    with pdfplumber.open(io.BytesIO(payload)) as document:
        for page in document.pages:
            for line in (page.extract_text() or "").splitlines():
                tokens = line.split()
                if not tokens or "/" not in tokens[0] or not tokens[0][0].isdigit():
                    continue
                if len(tokens) != 6:
                    raise ValueError(
                        f"Unexpected {year} vessel-activity row layout: {line}"
                    )
                corrected: list[str] = []
                for token in tokens:
                    replacement = KNOWN_SOURCE_CORRECTIONS.get((year, token))
                    if replacement is None:
                        corrected.append(token)
                        continue
                    replacement_value, reason = replacement
                    corrected.append(replacement_value)
                    corrections.append(
                        {
                            "year": str(year),
                            "source_value": token,
                            "corrected_value": replacement_value,
                            "reason": reason,
                        }
                    )
                try:
                    activity_date = datetime.strptime(corrected[0], "%m/%d/%Y").date()
                    numeric = [float(value) for value in corrected[1:]]
                except ValueError as error:
                    raise ValueError(
                        f"Invalid {year} vessel-activity row: {line}"
                    ) from error
                if activity_date.year != year:
                    raise ValueError(
                        f"Unexpected year in {year} activity table: {activity_date}"
                    )
                records.append(
                    {
                        "activity_date": activity_date.isoformat(),
                        **dict(zip(ACTIVITY_COLUMNS, numeric, strict=True)),
                    }
                )
    frame = pd.DataFrame(records).drop_duplicates("activity_date", keep="last")
    if len(frame) < 200:
        raise ValueError(
            f"Expected at least 200 official activity rows for {year}, found {len(frame)}"
        )
    return frame.sort_values("activity_date").reset_index(drop=True), corrections


def build_daily_source(
    cache_dir: Path, refresh: bool
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    frames: list[pd.DataFrame] = []
    evidence: list[dict[str, Any]] = []
    for year, url in VESSEL_ACTIVITY_URLS.items():
        payload = fetch_pdf(
            url, cache_dir / f"port_la_vessel_activity_{year}.pdf", refresh
        )
        frame, corrections = parse_pdf(year, payload)
        frames.append(frame)
        evidence.append(
            {
                "year": year,
                "url": url,
                "pdf_sha256": sha256_bytes(payload),
                "pdf_bytes": len(payload),
                "derived_daily_rows": len(frame),
                "first_date": str(frame["activity_date"].min()),
                "last_date": str(frame["activity_date"].max()),
                "declared_source_corrections": corrections,
            }
        )
        print(
            f"Port of Los Angeles vessel activity {year}: {len(frame)} rows", flush=True
        )
    return pd.concat(frames, ignore_index=True), evidence


def split_for_year(year: int) -> str:
    if year <= 2022:
        return "train"
    return "validation" if year == 2023 else "test"


def build_enhanced_hourly(hourly: pd.DataFrame, daily: pd.DataFrame) -> pd.DataFrame:
    selected = hourly[
        (hourly["timestamp_utc"] >= "2020-01-01T00:00:00Z")
        & (hourly["timestamp_utc"] <= "2024-12-31T23:00:00Z")
    ].copy()
    selected["timestamp"] = pd.to_datetime(selected["timestamp_utc"], utc=True)
    selected["activity_date"] = (
        selected["timestamp"].dt.tz_convert("America/Los_Angeles").dt.date.astype(str)
    )

    observed = daily.copy()
    observed["activity_date"] = pd.to_datetime(observed["activity_date"])
    calendar = pd.DataFrame(
        {
            "activity_date": pd.date_range(
                "2019-12-31",
                "2024-12-31",
                freq="D",
            )
        }
    )
    calendar = calendar.merge(
        observed, on="activity_date", how="left", validate="one_to_one"
    )
    calendar["port_activity_observed"] = (
        calendar["vessels_at_berth"].notna().astype(int)
    )
    calendar["port_activity_quality_code"] = calendar["port_activity_observed"].map(
        {1: "reported_by_port", 0: "calendar_interpolation"}
    )
    for column in ACTIVITY_COLUMNS:
        calendar[column] = calendar[column].interpolate(
            method="linear", limit_direction="both"
        )
    calendar["activity_date"] = calendar["activity_date"].dt.date.astype(str)

    result = selected.merge(
        calendar, on="activity_date", how="inner", validate="many_to_one"
    )
    if len(result) != len(selected):
        raise RuntimeError(
            f"Hourly join lost rows: selected={len(selected)}, joined={len(result)}"
        )
    years = result["timestamp"].dt.year
    result["split"] = years.map(split_for_year)
    result["source_id"] = (
        result["source_id"].astype(str)
        + "+POLA-VESSEL-ACTIVITY:"
        + result["activity_date"]
    )
    result = result.drop(columns=["timestamp"])
    columns = [
        "timestamp_utc",
        "period",
        "split",
        "loaded_import_teu",
        "loaded_export_teu",
        "total_teu",
        "grid_carbon_kg_per_kwh",
        "electricity_price_per_kwh",
        "fuel_price_per_liter",
        "vessels_at_anchor",
        "vessels_at_berth",
        "vessels_departed",
        "average_days_at_berth",
        "average_days_in_port",
        "port_activity_observed",
        "port_activity_quality_code",
        "activity_date",
        *[
            column
            for column in selected.columns
            if column
            not in {
                "timestamp_utc",
                "period",
                "split",
                "loaded_import_teu",
                "loaded_export_teu",
                "total_teu",
                "grid_carbon_kg_per_kwh",
                "electricity_price_per_kwh",
                "fuel_price_per_liter",
                "timestamp",
                "activity_date",
                "source_id",
            }
        ],
        "source_id",
    ]
    return result[columns].sort_values("timestamp_utc").reset_index(drop=True)


def write_package(
    frame: pd.DataFrame,
    daily: pd.DataFrame,
    evidence: list[dict[str, Any]],
    output: Path,
    source_output: Path,
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    source_output.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(output, index=False, float_format="%.8f")
    daily.to_csv(source_output, index=False, float_format="%.5f")

    base_metadata = json.loads(BASE_METADATA.read_text(encoding="utf-8"))
    reported_days = int(
        frame[["activity_date", "port_activity_observed"]]
        .drop_duplicates()["port_activity_observed"]
        .sum()
    )
    total_days = int(frame["activity_date"].nunique())
    csv_sha256 = sha256_bytes(output.read_bytes())
    source_csv_sha256 = sha256_bytes(source_output.read_bytes())
    metadata = {
        "id": output.stem,
        "name": (
            "Port of Los Angeles 2020-2024 vessel-activity enhanced hourly "
            "energy-carbon dispatch benchmark"
        ),
        "version": "2020-2024.1",
        "license": base_metadata["license"],
        "source_urls": [
            *base_metadata["source_urls"],
            *VESSEL_ACTIVITY_URLS.values(),
        ],
        "attribution": (
            "Port of Los Angeles Wharfinger Division vessel-activity summaries; "
            "Port of Los Angeles container statistics; U.S. EIA; U.S. EPA."
        ),
        "scope_note": (
            "Offline public-data benchmark. Vessel counts and dwell are official "
            "daily port statistics; non-reporting calendar days are explicitly "
            "interpolated. Hourly TEU remains a disclosed allocation, and energy "
            "values are regional/model inputs rather than terminal telemetry."
        ),
        "temporal_mode": "sequential_rows",
        "time_column": "timestamp_utc",
        "environment_id": "PortEnergyDispatchEnv-v2",
        "evaluation_episode_limit": 48,
        "evaluation_sampling": (
            "48 deterministic, uniformly spaced 24-hour episodes spanning each "
            "validation/test year; start indices are persisted in report evidence"
        ),
        "port_profile": {
            "port_id": "USLAX",
            "port_name": "Port of Los Angeles",
            "timezone": "America/Los_Angeles",
            "currency": "CNY scenario converted from public USD anchors",
            "deployment_mode": "offline_public_benchmark",
        },
        "operational_feature_contract": {
            "required_columns": [
                *ACTIVITY_COLUMNS,
                "port_activity_observed",
            ],
            "actual_source_resolution": "daily business-day reports",
            "hourly_fill_method": "linear calendar-day interpolation",
        },
        "units": {
            **base_metadata["units"],
            "vessels_at_anchor": "vessels/day snapshot",
            "vessels_at_berth": "vessels/day snapshot",
            "vessels_departed": "vessels/day",
            "average_days_at_berth": "days",
            "average_days_in_port": "days",
            "port_activity_observed": "0/1",
        },
        "assumptions": [
            *base_metadata["assumptions"],
            (
                "Official daily vessel-activity rows are repeated across their "
                "calendar day; non-reporting days use explicit linear interpolation."
            ),
            (
                "Aggregate shore-power opportunity is capped by the declared "
                "terminal capacity and modeled as vessels-at-berth multiplied by "
                "the declared mean auxiliary demand per vessel."
            ),
        ],
        "intended_use": (
            "Leakage-safe comparison of PPO, SAC, TD3, DQN and constrained MPC "
            "with actual daily port workload signals plus public hourly grid data."
        ),
        "environment_parameters": {
            **base_metadata["environment_parameters"],
            "vessel_auxiliary_demand_kw": 650.0,
            "shore_power_available_ratio": 1.0,
        },
        "split_policy": {
            "train": "2020-01-01 through 2022-12-31",
            "validation": "2023-01-01 through 2023-12-31",
            "test": "2024-01-01 through 2024-12-31",
        },
        "public_source_evidence": {
            "base_dataset_package_sha256": sha256_bytes(
                BASE_DATASET.read_bytes() + b"\0" + BASE_METADATA.read_bytes()
            ),
            "vessel_activity_pdf_count": len(evidence),
            "vessel_activity_daily_rows": len(daily),
            "vessel_activity_reported_calendar_days": reported_days,
            "vessel_activity_total_calendar_days": total_days,
            "vessel_activity_reported_day_coverage": round(
                reported_days / max(1, total_days), 6
            ),
            "vessel_activity_source_csv": str(source_output.relative_to(ROOT)),
            "vessel_activity_source_csv_sha256": source_csv_sha256,
            "pdf_sources": evidence,
        },
        "quality": {
            "rows": len(frame),
            "start": str(frame["timestamp_utc"].min()),
            "end": str(frame["timestamp_utc"].max()),
            "missing_cells": int(frame.isna().sum().sum()),
            "duplicate_timestamps": int(frame["timestamp_utc"].duplicated().sum()),
            "csv_sha256": csv_sha256,
        },
    }
    metadata_path = output.with_suffix(".metadata.json")
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "dataset": str(output),
                "metadata": str(metadata_path),
                "source_snapshot": str(source_output),
                "rows": len(frame),
                "official_daily_rows": len(daily),
                "csv_sha256": csv_sha256,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--source-output", type=Path, default=DEFAULT_SOURCE_OUTPUT)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    daily, evidence = build_daily_source(args.cache_dir, args.refresh)
    hourly = pd.read_csv(BASE_DATASET)
    enhanced = build_enhanced_hourly(hourly, daily)
    write_package(enhanced, daily, evidence, args.output, args.source_output)


if __name__ == "__main__":
    main()
