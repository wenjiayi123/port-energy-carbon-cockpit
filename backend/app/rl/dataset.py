from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import logging
import math
from pathlib import Path
from threading import RLock
from typing import Any

import pandas as pd


DATASET_DIR = Path(__file__).resolve().parents[1] / "data" / "datasets"
PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATASET_ID = "port_la_2020_2025_hourly"
REQUIRED_COLUMNS = {
    "period",
    "split",
    "loaded_import_teu",
    "loaded_export_teu",
    "total_teu",
    "grid_carbon_kg_per_kwh",
    "electricity_price_per_kwh",
    "fuel_price_per_liter",
    "source_id",
}
TEXT_COLUMNS = {"period", "split", "source_id"}
OPTIONAL_NUMERIC_COLUMNS = {
    "eia_commercial_price_usd_per_kwh",
    "eia930_demand_mw",
    "eia930_consumed_electricity_mwh",
    "eia930_consumed_carbon_lb_per_kwh",
    "monthly_eia_price_cny_per_kwh",
    "monthly_total_teu",
    "observation_hours",
    "crane_capacity_teu_per_hour",
    "yard_capacity_teu_per_hour",
    "shore_demand_kw",
    "base_load_kw",
    "load_kw_per_teu",
    "crane_load_kw",
    "yard_load_kw",
    "grid_capacity_kw",
    "fuel_kwh_per_liter",
    "fuel_carbon_kg_per_liter",
    "delay_cost_cny_per_minute",
    "delay_limit_minutes",
    "battery_capacity_kwh",
    "battery_power_kw",
    "battery_initial_soc",
    "battery_min_soc",
    "battery_max_soc",
    "battery_charge_efficiency",
    "battery_discharge_efficiency",
    "battery_degradation_cny_per_kwh",
    "terminal_soc_tolerance",
    "demand_charge_cny_per_kw",
    "vessel_auxiliary_demand_kw",
    "shore_power_available_ratio",
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
}
OPERATIONAL_COLUMNS = {
    "vessels_at_anchor",
    "vessels_at_berth",
    "vessels_departed",
    "average_days_at_berth",
    "average_days_in_port",
    "port_activity_observed",
}
DEPLOYMENT_COLUMNS = {
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
}
RATIO_COLUMNS = {
    "shore_power_available_ratio",
    "berth_available_ratio",
    "crane_available_ratio",
    "yard_available_ratio",
    "grid_available_ratio",
    "shore_power_compatible_ratio",
}
DRIFT_COLUMNS = {
    "loaded_import_teu",
    "loaded_export_teu",
    "total_teu",
    "grid_carbon_kg_per_kwh",
    "electricity_price_per_kwh",
    "fuel_price_per_liter",
    "eia930_demand_mw",
    "eia930_consumed_carbon_lb_per_kwh",
}
REQUIRED_METADATA_FIELDS = {
    "id",
    "version",
    "license",
    "source_urls",
    "attribution",
    "scope_note",
    "units",
    "assumptions",
    "intended_use",
}
_DATASET_CACHE: dict[tuple[Any, ...], Any] = {}
_DATASET_CACHE_LOCK = RLock()
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PortDataset:
    dataset_id: str
    csv_path: Path
    frame: pd.DataFrame
    metadata: dict[str, Any]
    sha256: str
    metadata_sha256: str
    package_sha256: str

    @classmethod
    def load(cls, dataset: str | Path = DEFAULT_DATASET_ID) -> "PortDataset":
        csv_path = resolve_dataset_path(dataset)
        if not csv_path.exists():
            raise FileNotFoundError(f"Training dataset does not exist: {csv_path}")
        metadata_path = csv_path.with_suffix(".metadata.json")
        csv_stat = csv_path.stat()
        metadata_stat = metadata_path.stat() if metadata_path.exists() else None
        cache_key = (
            str(csv_path.resolve()),
            csv_stat.st_size,
            csv_stat.st_mtime_ns,
            metadata_stat.st_size if metadata_stat else 0,
            metadata_stat.st_mtime_ns if metadata_stat else 0,
        )
        with _DATASET_CACHE_LOCK:
            cached = _DATASET_CACHE.get(cache_key)
        if cached is not None:
            return cached
        frame = pd.read_csv(csv_path)
        missing = REQUIRED_COLUMNS - set(frame.columns)
        if missing:
            raise ValueError(f"Dataset is missing required columns: {', '.join(sorted(missing))}")
        if frame.empty:
            raise ValueError("Training dataset contains no rows")
        required_splits = {"train", "validation", "test"}
        observed_splits = set(frame["split"].astype(str))
        if not required_splits.issubset(observed_splits):
            missing_splits = ", ".join(sorted(required_splits - observed_splits))
            raise ValueError(f"Dataset is missing required temporal splits: {missing_splits}")
        period_split_counts = frame.groupby("period")["split"].nunique()
        if bool((period_split_counts > 1).any()):
            raise ValueError("A period cannot appear in more than one temporal split")
        if (
            frame[list(TEXT_COLUMNS)]
            .fillna("")
            .astype(str)
            .apply(lambda column: column.str.strip().eq(""))
            .any()
            .any()
        ):
            raise ValueError("Dataset period, split, and source_id values must be non-empty")
        numeric = REQUIRED_COLUMNS - TEXT_COLUMNS
        for column in numeric:
            frame[column] = pd.to_numeric(frame[column], errors="raise")
        present_optional = OPTIONAL_NUMERIC_COLUMNS & set(frame.columns)
        for column in present_optional:
            frame[column] = pd.to_numeric(frame[column], errors="raise")
        all_numeric = numeric | present_optional
        if not frame[list(all_numeric)].map(math.isfinite).all().all():
            raise ValueError("Dataset numeric values must be finite")
        if (frame[list(all_numeric)] < 0).any().any():
            raise ValueError("Dataset numeric values must be non-negative")
        present_ratios = RATIO_COLUMNS & set(frame.columns)
        if present_ratios and (frame[list(present_ratios)] > 1).any().any():
            raise ValueError("Dataset availability and compatibility ratios must not exceed 1")
        metadata_bytes = metadata_path.read_bytes() if metadata_path.exists() else b""
        metadata = json.loads(metadata_bytes.decode("utf-8")) if metadata_bytes else {}
        temporal_mode = str(metadata.get("temporal_mode") or "profiled_period")
        if temporal_mode not in {"profiled_period", "sequential_rows"}:
            raise ValueError("metadata temporal_mode must be profiled_period or sequential_rows")
        if temporal_mode == "sequential_rows":
            time_column = str(metadata.get("time_column") or "")
            if not time_column or time_column not in frame.columns:
                raise ValueError("sequential_rows datasets require metadata.time_column in the CSV")
            timestamps = pd.to_datetime(frame[time_column], utc=True, errors="raise")
            if bool(timestamps.duplicated().any()):
                raise ValueError("Sequential dataset timestamps must be unique")
            if not bool(timestamps.is_monotonic_increasing):
                raise ValueError("Sequential dataset timestamps must be chronological")
            deltas = timestamps.diff().dropna().dt.total_seconds()
            if bool((deltas != 3600.0).any()):
                raise ValueError("Sequential hourly dataset must contain contiguous one-hour rows")
        environment_parameters = metadata.get("environment_parameters") or {}
        if not isinstance(environment_parameters, dict):
            raise ValueError("metadata environment_parameters must be an object")
        allowed_parameters = OPTIONAL_NUMERIC_COLUMNS - {"observation_hours"}
        unknown_parameters = set(environment_parameters) - allowed_parameters
        if unknown_parameters:
            raise ValueError(
                f"Unknown environment parameters: {', '.join(sorted(unknown_parameters))}"
            )
        for name, value in environment_parameters.items():
            numeric_value = float(value)
            if numeric_value < 0 or (
                name
                in {
                    "fuel_kwh_per_liter",
                    "battery_capacity_kwh",
                    "battery_power_kw",
                    "battery_charge_efficiency",
                    "battery_discharge_efficiency",
                }
                and numeric_value == 0
            ):
                raise ValueError(f"Invalid environment parameter {name}: {value}")
        min_soc = float(environment_parameters.get("battery_min_soc", 0.0))
        initial_soc = float(environment_parameters.get("battery_initial_soc", 0.5))
        max_soc = float(environment_parameters.get("battery_max_soc", 1.0))
        if not 0.0 <= min_soc < initial_soc < max_soc <= 1.0:
            raise ValueError("Battery SOC parameters must satisfy 0 <= min < initial < max <= 1")
        csv_bytes = csv_path.read_bytes()
        digest = hashlib.sha256(csv_bytes).hexdigest()
        metadata_digest = hashlib.sha256(metadata_bytes).hexdigest()
        package_digest = hashlib.sha256(csv_bytes + b"\0" + metadata_bytes).hexdigest()
        result = cls(
            str(metadata.get("id") or csv_path.stem),
            csv_path,
            frame,
            metadata,
            digest,
            metadata_digest,
            package_digest,
        )
        with _DATASET_CACHE_LOCK:
            if len(_DATASET_CACHE) >= 16:
                _DATASET_CACHE.clear()
            _DATASET_CACHE[cache_key] = result
        return result

    def split(self, name: str) -> pd.DataFrame:
        selected = self.frame[self.frame["split"].astype(str) == name].reset_index(drop=True)
        if selected.empty:
            raise ValueError(f"Dataset split is empty: {name}")
        return selected

    @property
    def temporal_mode(self) -> str:
        mode = str(self.metadata.get("temporal_mode") or "profiled_period")
        if mode not in {"profiled_period", "sequential_rows"}:
            raise ValueError("metadata temporal_mode must be profiled_period or sequential_rows")
        return mode

    @property
    def environment_id(self) -> str:
        environment_id = str(self.metadata.get("environment_id") or "PortEnergyDispatchEnv-v1")
        if environment_id not in {
            "PortEnergyDispatchEnv-v1",
            "PortEnergyDispatchEnv-v2",
            "PortEnergyDispatchEnv-v3",
        }:
            raise ValueError(f"Unsupported environment_id: {environment_id}")
        return environment_id

    def evaluation_start_indices(self, split: str, episode_hours: int) -> list[int]:
        frame = self.split(split)
        if self.temporal_mode == "sequential_rows":
            stride = max(1, int(episode_hours))
            starts = list(range(0, max(1, len(frame) - stride + 1), stride))
            requested_limit = int(self.metadata.get("evaluation_episode_limit") or len(starts))
            limit = max(1, min(requested_limit, len(starts)))
            if limit == len(starts):
                return starts
            if limit == 1:
                return [starts[0]]
            # Deterministically span the full split instead of cherry-picking
            # adjacent low-load days. The selected start indices are persisted
            # in the benchmark report for exact replay.
            positions = {round(index * (len(starts) - 1) / (limit - 1)) for index in range(limit)}
            return [starts[position] for position in sorted(positions)]
        return list(range(len(frame)))

    def describe(self) -> dict[str, Any]:
        from app.rl.landing_readiness import assess_dataset_landing_readiness

        return {
            "id": self.dataset_id,
            "path": portable_dataset_reference(self.csv_path),
            "rows": int(len(self.frame)),
            "train_rows": int((self.frame["split"] == "train").sum()),
            "validation_rows": int((self.frame["split"] == "validation").sum()),
            "test_rows": int((self.frame["split"] == "test").sum()),
            "columns": list(self.frame.columns),
            "sha256": self.sha256,
            "metadata_sha256": self.metadata_sha256,
            "package_sha256": self.package_sha256,
            "metadata": self.metadata,
            "environment_id": self.environment_id,
            "operational_feature_coverage": self.operational_feature_coverage(),
            "quality": self.quality_report(),
            "drift": self.drift_report(),
            "landing_readiness": assess_dataset_landing_readiness(self),
            "valid": True,
        }

    def operational_feature_coverage(self) -> dict[str, Any]:
        fields = sorted(
            OPERATIONAL_COLUMNS
            | (DEPLOYMENT_COLUMNS if self.environment_id == "PortEnergyDispatchEnv-v3" else set())
        )
        available = [name for name in fields if name in self.frame.columns]
        required = list(
            self.metadata.get("operational_feature_contract", {}).get("required_columns", [])
        )
        missing_required = sorted(name for name in required if name not in available)
        return {
            "available_columns": available,
            "missing_columns": sorted(set(fields) - set(available)),
            "required_columns": required,
            "missing_required_columns": missing_required,
            "status": "pass" if not missing_required else "blocked",
            "note": (
                "Column presence is not source verification; provenance and "
                "measurement quality remain governed by dataset metadata."
            ),
        }

    def quality_report(self) -> dict[str, Any]:
        """Return evidence-oriented quality checks without inventing source coverage."""
        identity_period = (
            str(self.metadata.get("time_column"))
            if self.temporal_mode == "sequential_rows"
            else "period"
        )
        duplicate_mask = self.frame.duplicated(
            subset=[identity_period, "split", "source_id"],
            keep=False,
        )
        missing_cells = int(self.frame.isna().sum().sum())
        missing_metadata = sorted(
            name for name in REQUIRED_METADATA_FIELDS if not self.metadata.get(name)
        )
        source_urls = self.metadata.get("source_urls")
        source_urls_valid = (
            isinstance(source_urls, list)
            and bool(source_urls)
            and all(
                isinstance(value, str) and value.startswith(("https://", "http://"))
                for value in source_urls
            )
        )
        unit_coverage = sorted(
            column
            for column in REQUIRED_COLUMNS - TEXT_COLUMNS
            if column not in (self.metadata.get("units") or {})
        )
        warnings: list[str] = []
        score = 100
        if missing_cells:
            score -= min(35, missing_cells * 5)
            warnings.append(f"missing_cells:{missing_cells}")
        duplicate_rows = int(duplicate_mask.sum())
        if duplicate_rows:
            score -= min(25, duplicate_rows * 5)
            warnings.append(f"duplicate_identity_rows:{duplicate_rows}")
        if missing_metadata:
            score -= min(30, len(missing_metadata) * 5)
            warnings.append(f"missing_metadata:{','.join(missing_metadata)}")
        if not source_urls_valid:
            score -= 10
            warnings.append("source_urls_missing_or_invalid")
        if unit_coverage:
            score -= min(15, len(unit_coverage) * 3)
            warnings.append(f"missing_units:{','.join(unit_coverage)}")
        train_rows = int((self.frame["split"].astype(str) == "train").sum())
        validation_rows = int((self.frame["split"].astype(str) == "validation").sum())
        test_rows = int((self.frame["split"].astype(str) == "test").sum())
        if min(train_rows, validation_rows, test_rows) < 2:
            score -= 15
            warnings.append("insufficient_split_rows")
        score = max(0, score)
        grade = "A" if score >= 90 else "B" if score >= 75 else "C" if score >= 60 else "D"
        return {
            "status": "pass"
            if score >= 75 and not duplicate_rows and not missing_cells
            else "review",
            "score": score,
            "grade": grade,
            "rows": int(len(self.frame)),
            "split_rows": {
                "train": train_rows,
                "validation": validation_rows,
                "test": test_rows,
            },
            "missing_cells": missing_cells,
            "duplicate_identity_rows": duplicate_rows,
            "source_count": int(self.frame["source_id"].nunique()),
            "metadata_completeness": round(
                (len(REQUIRED_METADATA_FIELDS) - len(missing_metadata))
                / len(REQUIRED_METADATA_FIELDS),
                4,
            ),
            "missing_metadata_fields": missing_metadata,
            "missing_unit_fields": unit_coverage,
            "warnings": warnings,
            "evidence_hash": self.package_sha256,
        }

    def drift_report(self) -> dict[str, Any]:
        """Compare train/test distributions using standardized mean differences."""
        train = self.split("train")
        test = self.split("test")
        shifts: dict[str, float] = {}
        for column in sorted(DRIFT_COLUMNS & set(self.frame.columns)):
            train_values = train[column].astype(float)
            test_values = test[column].astype(float)
            difference = abs(float(train_values.mean()) - float(test_values.mean()))
            magnitude = max(abs(float(train_values.mean())), abs(float(test_values.mean())), 1.0)
            tolerance = max(1e-12, magnitude * 1e-9)
            pooled_std = math.sqrt(
                max(0.0, (float(train_values.var(ddof=0)) + float(test_values.var(ddof=0))) / 2)
            )
            if difference <= tolerance:
                standardized_difference = 0.0
            elif pooled_std <= tolerance:
                standardized_difference = 99.0
            else:
                standardized_difference = min(99.0, difference / pooled_std)
            shifts[column] = round(standardized_difference, 4)
        max_shift = max(shifts.values(), default=0.0)
        status = "stable" if max_shift <= 0.5 else "review" if max_shift <= 1.0 else "high_shift"
        return {
            "status": status,
            "method": "absolute_standardized_mean_difference",
            "warning_threshold": 0.5,
            "high_shift_threshold": 1.0,
            "max_shift": round(max_shift, 4),
            "feature_shifts": shifts,
            "note": "Offline split comparison only; production drift requires timestamped live observations.",
        }


def resolve_dataset_path(dataset: str | Path) -> Path:
    value = Path(dataset)
    if value.suffix.lower() == ".csv":
        if value.is_absolute():
            return value
        project_root = Path(__file__).resolve().parents[3]
        project_relative = project_root / value
        return project_relative if project_relative.exists() else DATASET_DIR / value.name
    return DATASET_DIR / f"{value.name}.csv"


def registered_dataset_path(dataset: str) -> Path:
    """Select a bundled dataset from trusted directory entries.

    HTTP values are used only as lookup keys.  The returned path always comes
    from the server-owned registry, so a caller cannot smuggle a filesystem
    path into pandas or the metadata reader.
    """
    raw = str(dataset).strip()
    if not raw or raw != Path(raw).name or "\\" in raw or Path(raw).suffix:
        raise ValueError("HTTP dataset references must use a registered dataset ID")
    registered = {
        candidate.stem: candidate.resolve()
        for candidate in DATASET_DIR.glob("*.csv")
        if candidate.is_file()
    }
    candidate = registered.get(raw)
    if candidate is None:
        raise ValueError(f"Unknown registered dataset: {raw}")
    return candidate


def load_registered_dataset(dataset: str) -> PortDataset:
    """Load an HTTP-safe dataset selected from the bundled registry."""
    return PortDataset.load(registered_dataset_path(dataset))


def registered_dataset_id(dataset: str | Path) -> str:
    """Resolve a bundled dataset ID without accepting filesystem paths.

    The CLI intentionally supports absolute files for operator-controlled data
    preparation. HTTP callers are restricted to datasets already registered in
    ``app/data/datasets`` so an API request cannot probe arbitrary server files.
    """
    return registered_dataset_path(str(dataset)).stem


def portable_dataset_reference(path: str | Path) -> str:
    """Prefer a repository-relative reference over a host-specific absolute path."""
    resolved = Path(path).resolve()
    try:
        return resolved.relative_to(PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        return str(resolved)


def list_datasets() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for csv_path in sorted(DATASET_DIR.glob("*.csv")):
        try:
            items.append(PortDataset.load(csv_path).describe())
        except Exception:
            logger.exception("Bundled dataset validation failed: %s", csv_path.name)
            items.append(
                {
                    "id": csv_path.stem,
                    "path": str(csv_path),
                    "valid": False,
                    "error": "dataset_validation_failed",
                }
            )
    return items
