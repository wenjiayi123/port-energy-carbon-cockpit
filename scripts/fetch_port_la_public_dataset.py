#!/usr/bin/env python3
"""Build the canonical 2020-2025 benchmark from official public sources.

The script intentionally uses only the Python standard library. Each Port page
and the EIA API response are hashed next to the derived CSV so later source
changes are detectable.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen


YEARS = tuple(range(2020, 2026))
MONTHS = {
    name: index
    for index, name in enumerate(
        (
            "January",
            "February",
            "March",
            "April",
            "May",
            "June",
            "July",
            "August",
            "September",
            "October",
            "November",
            "December",
        ),
        start=1,
    )
}
PORT_URL = (
    "https://www.portoflosangeles.org/Business/statistics/"
    "Container-Statistics/Historical-TEU-Statistics-{year}"
)
EPA_URL = "https://www.epa.gov/egrid/summary-data"
EIA_DOC_URL = "https://www.eia.gov/opendata/documentation.php"
EIA_API_BASE = "https://api.eia.gov/v2/electricity/retail-sales/data/"
CAMX_CO2E_LB_PER_MWH = Decimal("429.983")
KG_PER_LB = Decimal("0.45359237")
CAMX_KG_PER_KWH = (CAMX_CO2E_LB_PER_MWH * KG_PER_LB / Decimal("1000")).quantize(
    Decimal("0.00001")
)
# The EIA series is reported in USD cents/kWh. The environment uses a declared
# CNY benchmark currency, so this explicit fixed conversion preserves monthly
# price variation without implying a terminal-specific settled tariff.
FX_CNY_PER_USD = Decimal("7.20")
DEFAULT_OUTPUT = (
    Path(__file__).resolve().parents[1]
    / "backend"
    / "app"
    / "data"
    / "datasets"
    / "port_la_2020_2025_monthly.csv"
)


class StatisticsTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_table = False
        self.in_row = False
        self.in_cell = False
        self.rows: list[list[str]] = []
        self.current_row: list[str] = []
        self.current_cell: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "table" and "Container Statistics" in (attributes.get("summary") or ""):
            self.in_table = True
        elif self.in_table and tag == "tr":
            self.in_row = True
            self.current_row = []
        elif self.in_table and self.in_row and tag in {"td", "th"}:
            self.in_cell = True
            self.current_cell = []

    def handle_data(self, data: str) -> None:
        if self.in_cell:
            self.current_cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self.in_table and self.in_row and self.in_cell and tag in {"td", "th"}:
            self.current_row.append(" ".join("".join(self.current_cell).split()))
            self.in_cell = False
        elif self.in_table and self.in_row and tag == "tr":
            if self.current_row:
                self.rows.append(self.current_row)
            self.in_row = False
        elif self.in_table and tag == "table":
            self.in_table = False


def fetch(url: str) -> bytes:
    request = Request(
        url,
        headers={
            "User-Agent": (
                "CarbonOps reproducible public-dataset builder/1.0 "
                "(source attribution in generated metadata)"
            )
        },
    )
    with urlopen(request, timeout=45) as response:
        return response.read()


def parse_number(value: str) -> Decimal:
    cleaned = value.replace(",", "").replace("\xa0", "").strip()
    if cleaned.startswith("(") and cleaned.endswith(")"):
        cleaned = f"-{cleaned[1:-1]}"
    return Decimal(cleaned)


def split_for_year(year: int) -> str:
    if year <= 2023:
        return "train"
    return "validation" if year == 2024 else "test"


def eia_query_url() -> str:
    parameters = [
        ("api_key", "DEMO_KEY"),
        ("frequency", "monthly"),
        ("data[0]", "price"),
        ("facets[stateid][]", "CA"),
        ("facets[sectorid][]", "COM"),
        ("start", "2020-01"),
        ("end", "2025-12"),
        ("sort[0][column]", "period"),
        ("sort[0][direction]", "asc"),
        ("length", "100"),
    ]
    return f"{EIA_API_BASE}?{urlencode(parameters)}"


def parse_eia_prices(payload: bytes) -> dict[str, Decimal]:
    document = json.loads(payload.decode("utf-8"))
    rows = document.get("response", {}).get("data", [])
    prices: dict[str, Decimal] = {}
    for row in rows:
        period = str(row.get("period", ""))
        if not ("2020-01" <= period <= "2025-12"):
            continue
        if row.get("stateid") != "CA" or row.get("sectorid") != "COM":
            continue
        prices[period] = Decimal(str(row["price"])) / Decimal("100")
    if len(prices) != 72:
        raise ValueError(f"Expected 72 EIA monthly price rows, found {len(prices)}")
    return prices


def parse_year(
    year: int,
    payload: bytes,
    electricity_prices_usd: dict[str, Decimal],
) -> list[dict[str, str]]:
    parser = StatisticsTableParser()
    parser.feed(payload.decode("utf-8", errors="replace"))
    records: list[dict[str, str]] = []
    for cells in parser.rows:
        if len(cells) < 8 or cells[0] not in MONTHS:
            continue
        month = MONTHS[cells[0]]
        period = f"{year}-{month:02d}"
        total_imports = parse_number(cells[3])
        total_exports = parse_number(cells[6])
        electricity_usd_per_kwh = electricity_prices_usd[period]
        electricity_cny_per_kwh = (
            electricity_usd_per_kwh * FX_CNY_PER_USD
        ).quantize(Decimal("0.0001"))
        records.append(
            {
                "period": period,
                "split": split_for_year(year),
                "loaded_import_teu": f"{parse_number(cells[1]):.2f}",
                "loaded_export_teu": f"{parse_number(cells[4]):.2f}",
                # Some historical pages contain presentation punctuation in the
                # displayed total. The identity Total Imports + Total Exports is
                # used consistently and remains fully sourced from the same row.
                "total_teu": f"{total_imports + total_exports:.2f}",
                "grid_carbon_kg_per_kwh": f"{CAMX_KG_PER_KWH:.5f}",
                "electricity_price_per_kwh": f"{electricity_cny_per_kwh:.4f}",
                "fuel_price_per_liter": "7.85",
                "eia_commercial_price_usd_per_kwh": (
                    f"{electricity_usd_per_kwh:.4f}"
                ),
                "source_id": (
                    f"port_la_official_{year}_eia_ca_commercial_"
                    "epa_egrid2023_camx"
                ),
            }
        )
    if len(records) != 12:
        raise ValueError(f"Expected 12 official monthly rows for {year}, found {len(records)}")
    return records


def build_dataset(output: Path) -> tuple[Path, Path]:
    rows: list[dict[str, str]] = []
    snapshots: list[dict[str, str | int]] = []
    source_urls: list[str] = []
    eia_url = eia_query_url()
    eia_payload = fetch(eia_url)
    electricity_prices_usd = parse_eia_prices(eia_payload)
    for year in YEARS:
        url = PORT_URL.format(year=year)
        payload = fetch(url)
        year_rows = parse_year(year, payload, electricity_prices_usd)
        rows.extend(year_rows)
        source_urls.append(url)
        snapshots.append(
            {
                "year": year,
                "url": url,
                "sha256": hashlib.sha256(payload).hexdigest(),
                "derived_rows": len(year_rows),
            }
        )
    source_urls.extend((EIA_DOC_URL, EPA_URL))
    snapshots.append(
        {
            "publisher": "U.S. EIA",
            "series": "California commercial monthly average retail electricity price",
            "url": eia_url,
            "sha256": hashlib.sha256(eia_payload).hexdigest(),
            "derived_rows": len(electricity_prices_usd),
        }
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0])
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    metadata = {
        "id": output.stem,
        "name": (
            "Port of Los Angeles 2020-2025 official monthly container throughput "
            "+ EIA California commercial electricity price + EPA eGRID 2023 CAMX"
        ),
        "version": "2020-2025.1",
        "license": (
            "Port of Los Angeles statistics are provided free of charge with source "
            "credit requested. U.S. EIA and EPA data are U.S. federal public data. "
            "Repository MIT terms do not replace publisher attribution and "
            "disclaimers."
        ),
        "source_urls": source_urls,
        "source_snapshots": snapshots,
        "fetched_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "attribution": (
            "Monthly container counts: Port of Los Angeles official 2020-2025 pages. "
            "Monthly electricity-price proxy: U.S. EIA California commercial-sector "
            "average retail price. "
            "Grid CO2e factor: U.S. EPA eGRID 2023 CAMX total output rate, converted "
            f"from {CAMX_CO2E_LB_PER_MWH} lb/MWh to {CAMX_KG_PER_KWH} kg/kWh."
        ),
        "scope_note": (
            "72 first-party Port throughput observations joined by month to 72 U.S. "
            "EIA California commercial-price observations. The EIA series is a public "
            "state/sector proxy, not the terminal tariff. Hourly episodes are "
            "deterministic model expansions, not terminal meter telemetry."
        ),
        "intended_use": (
            "Offline algorithm benchmarking, temporal validation, and held-out "
            "evaluation. Not approved for autonomous production dispatch."
        ),
        "temporal_mode": "profiled_period",
        "carbon_factor_quality": {
            "method": "location_based",
            "scope": "scope_2_purchased_electricity",
            "geography": "eGRID CAMX subregion",
            "factor_vintage": "2023",
            "publisher": "U.S. EPA eGRID",
            "factor_type": "total output emission rate",
            "market_based_factor": None,
            "uncertainty": (
                "One regional annual factor is applied across 2020-2025 and does not "
                "represent terminal-specific or hourly marginal emissions."
            ),
        },
        "environment_parameters": {
            "crane_capacity_teu_per_hour": 1520.0,
            "yard_capacity_teu_per_hour": 1650.0,
            "shore_demand_kw": 6800.0,
            "base_load_kw": 2200.0,
            "load_kw_per_teu": 0.62,
            "crane_load_kw": 2900.0,
            "yard_load_kw": 1250.0,
            "grid_capacity_kw": 17000.0,
            "fuel_kwh_per_liter": 3.8,
            "fuel_carbon_kg_per_liter": 2.68,
            "delay_cost_cny_per_minute": 18.0,
            "delay_limit_minutes": 120.0,
        },
        "units": {
            "loaded_import_teu": "TEU/month",
            "loaded_export_teu": "TEU/month",
            "total_teu": "TEU/month",
            "grid_carbon_kg_per_kwh": "kgCO2e/kWh",
            "electricity_price_per_kwh": "CNY/kWh",
            "fuel_price_per_liter": "CNY/liter",
            "eia_commercial_price_usd_per_kwh": "USD/kWh",
        },
        "assumptions": {
            "total_teu_transformation": (
                "Derived as official Total Imports + official Total Exports for every "
                "month. This avoids a documented punctuation anomaly in the displayed "
                "November 2020 total while preserving first-party row values."
            ),
            "electricity_price_per_kwh": (
                "U.S. EIA California commercial monthly average retail price, "
                f"converted from USD to CNY at a fixed {FX_CNY_PER_USD} CNY/USD "
                "benchmark rate. It is a public regional proxy, not a Port of Los "
                "Angeles tariff or invoice."
            ),
            "fuel_price_per_liter": (
                "Fixed 7.85 CNY/liter scenario assumption; not published by the port."
            ),
            "hourly_profile": (
                "Each official monthly TEU observation is expanded by the disclosed "
                "normalized profile in environment.py."
            ),
            "environment_parameters": (
                "Capacity, load, fuel conversion, delay cost, and safety limits are "
                "benchmark assumptions requiring terminal calibration."
            ),
        },
        "split_policy": "chronological_by_calendar_year",
        "train_split": "2020-01 through 2023-12 (48 official monthly rows)",
        "validation_split": "2024-01 through 2024-12 (12 official monthly rows)",
        "test_split": "2025-01 through 2025-12 (12 official monthly rows)",
    }
    metadata_path = output.with_suffix(".metadata.json")
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return output, metadata_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch official 2020-2025 Port of Los Angeles throughput and EIA prices"
        )
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    paths = build_dataset(args.output)
    print(json.dumps({"status": "written", "paths": [str(path) for path in paths]}))


if __name__ == "__main__":
    main()
