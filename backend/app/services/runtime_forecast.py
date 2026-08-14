from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import json
import math
import threading
from typing import Any

import numpy as np

from app.rl.dataset import PortDataset
from app.services.runtime_simulator import RUNTIME_DATASET_ID, iso_z, utc_now


FORECAST_HORIZONS = (1, 3, 6)
TARGET_NAMES = (
    "terminal_load_kw",
    "regional_grid_demand_mw",
    "grid_carbon_kg_per_kwh",
    "electricity_price_cny_per_kwh",
    "throughput_demand_teu_h",
)
TARGET_SCALES = np.array([17_000.0, 5_000.0, 0.8, 3.5, 1_800.0], dtype=np.float64)


def _canonical_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


class RuntimeForecastModel:
    """Leakage-safe multi-output ridge forecast over public and engineered targets."""

    def __init__(self, dataset_id: str = RUNTIME_DATASET_ID) -> None:
        self.dataset = PortDataset.load(dataset_id)
        self._lock = threading.RLock()
        self._models: dict[int, dict[str, Any]] = {}
        self._artifact: dict[str, Any] | None = None

    def _row_features(self, frame) -> np.ndarray:
        timestamps = [
            datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            for value in frame["timestamp_utc"].tolist()
        ]
        hours = np.array([item.hour + item.minute / 60.0 for item in timestamps])
        day_of_year = np.array([item.timetuple().tm_yday for item in timestamps])
        daylight = np.maximum(0.0, np.sin(np.pi * (hours - 6.0) / 12.0))
        seasonal_temp = 21.0 + 7.0 * daylight + 4.0 * np.sin(
            2.0 * np.pi * (day_of_year - 90.0) / 365.25
        )
        solar = 3_800.0 * daylight * 0.78
        workload = frame["total_teu"].to_numpy(dtype=np.float64)
        vessels = frame["vessels_at_berth"].to_numpy(dtype=np.float64)
        regional = frame["eia930_demand_mw"].to_numpy(dtype=np.float64)
        carbon = frame["grid_carbon_kg_per_kwh"].to_numpy(dtype=np.float64)
        price = frame["electricity_price_per_kwh"].to_numpy(dtype=np.float64)
        return np.column_stack(
            (
                np.ones(len(frame)),
                np.sin(2.0 * np.pi * hours / 24.0),
                np.cos(2.0 * np.pi * hours / 24.0),
                np.sin(2.0 * np.pi * day_of_year / 365.25),
                np.cos(2.0 * np.pi * day_of_year / 365.25),
                workload / 1_800.0,
                vessels / 20.0,
                regional / 5_000.0,
                carbon / 0.8,
                price / 3.5,
                seasonal_temp / 45.0,
                solar / 3_800.0,
            )
        )

    @staticmethod
    def _row_targets(frame) -> np.ndarray:
        timestamps = [
            datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            for value in frame["timestamp_utc"].tolist()
        ]
        hours = np.array([item.hour + item.minute / 60.0 for item in timestamps])
        daylight = np.maximum(0.0, np.sin(np.pi * (hours - 6.0) / 12.0))
        workload = frame["total_teu"].to_numpy(dtype=np.float64)
        vessels = frame["vessels_at_berth"].to_numpy(dtype=np.float64)
        utilization = np.clip(0.54 + 0.34 * workload / 1_650.0, 0.35, 0.96)
        shore = np.minimum(6_800.0, vessels * 650.0) * np.clip(
            0.58 + 0.18 * daylight + 0.08 * workload / 1_650.0,
            0.35,
            0.92,
        )
        ambient = 21.0 + 7.0 * daylight
        hvac = np.clip(480.0 + np.maximum(0.0, ambient - 24.0) * 92.0, 350.0, 2_100.0)
        lighting = 230.0 + (1.0 - daylight) * 520.0
        reefer = np.maximum(120.0, np.round(360.0 + workload * 0.22)) * (
            2.35 + np.maximum(0.0, ambient - 25.0) * 0.035
        )
        solar = 3_800.0 * daylight * 0.78
        terminal_load = (
            2_200.0
            + workload * 0.62
            + 2_900.0 * utilization
            + 1_250.0 * utilization
            + 650.0
            + shore
            + hvac
            + lighting
            + reefer
            + (240.0 + hvac * 0.18)
            - solar
        )
        return np.column_stack(
            (
                terminal_load,
                frame["eia930_demand_mw"].to_numpy(dtype=np.float64),
                frame["grid_carbon_kg_per_kwh"].to_numpy(dtype=np.float64),
                frame["electricity_price_per_kwh"].to_numpy(dtype=np.float64),
                workload,
            )
        )

    @staticmethod
    def _fit(x: np.ndarray, y: np.ndarray, alpha: float) -> np.ndarray:
        # Solve ridge regression as an augmented least-squares problem instead
        # of forming X.T @ X.  The feature matrix contains strongly correlated
        # engineering signals, so the normal equations amplify host BLAS
        # differences and previously produced different evidence hashes on
        # macOS and Linux.  The augmented system has a much lower effective
        # condition number; explicit coefficient quantization then makes the
        # published artifact reproducible without changing business-scale
        # predictions.
        regularizer = np.eye(x.shape[1], dtype=np.float64) * math.sqrt(alpha)
        regularizer[0, 0] = 0.0
        augmented_x = np.vstack((x, regularizer))
        augmented_y = np.vstack((y, np.zeros((x.shape[1], y.shape[1]))))
        beta, *_ = np.linalg.lstsq(augmented_x, augmented_y, rcond=None)
        return np.round(beta, 8)

    def _ensure_fitted(self) -> None:
        with self._lock:
            if self._artifact is not None:
                return
            train = self.dataset.split("train").reset_index(drop=True)
            validation = self.dataset.split("validation").reset_index(drop=True)
            test = self.dataset.split("test").reset_index(drop=True)
            alpha_candidates = (0.001, 0.01, 0.1, 1.0, 10.0)
            model_evidence: dict[str, Any] = {}
            for horizon in FORECAST_HORIZONS:
                train_x_all = self._row_features(train)
                train_y_all = self._row_targets(train) / TARGET_SCALES
                validation_x_all = self._row_features(validation)
                validation_y_all = self._row_targets(validation) / TARGET_SCALES
                test_x_all = self._row_features(test)
                test_y_all = self._row_targets(test) / TARGET_SCALES
                train_x, train_y = train_x_all[:-horizon], train_y_all[horizon:]
                validation_x, validation_y = (
                    validation_x_all[:-horizon],
                    validation_y_all[horizon:],
                )
                test_x, test_y = test_x_all[:-horizon], test_y_all[horizon:]
                candidates: list[dict[str, float]] = []
                selected_alpha = alpha_candidates[0]
                selected_score = math.inf
                selected_beta: np.ndarray | None = None
                for alpha in alpha_candidates:
                    beta = self._fit(train_x, train_y, alpha)
                    prediction = validation_x @ beta
                    score = float(np.mean(np.abs(prediction - validation_y)))
                    candidates.append(
                        {"alpha": alpha, "validation_scaled_mae": round(score, 12)}
                    )
                    if score < selected_score:
                        selected_alpha = alpha
                        selected_score = score
                        selected_beta = beta
                assert selected_beta is not None
                validation_prediction = validation_x @ selected_beta
                test_prediction = test_x @ selected_beta
                validation_mae = np.mean(
                    np.abs(validation_prediction - validation_y) * TARGET_SCALES,
                    axis=0,
                )
                test_mae = np.mean(
                    np.abs(test_prediction - test_y) * TARGET_SCALES,
                    axis=0,
                )
                residual_std = np.std(
                    (validation_prediction - validation_y) * TARGET_SCALES,
                    axis=0,
                )
                self._models[horizon] = {
                    "beta": selected_beta,
                    "residual_std": residual_std,
                    "alpha": selected_alpha,
                }
                model_evidence[str(horizon)] = {
                    "alpha_selection_split": "validation",
                    "selected_alpha": selected_alpha,
                    "alpha_candidates": candidates,
                    "validation_rows": len(validation_x),
                    "test_rows": len(test_x),
                    "validation_mae": {
                        name: round(float(value), 6)
                        for name, value in zip(TARGET_NAMES, validation_mae, strict=True)
                    },
                    "held_out_test_mae": {
                        name: round(float(value), 6)
                        for name, value in zip(TARGET_NAMES, test_mae, strict=True)
                    },
                    "coefficient_sha256": hashlib.sha256(
                        np.round(selected_beta, 10).astype("<f8").tobytes()
                    ).hexdigest(),
                }
            artifact_without_hash = {
                "schema_version": "runtime-forecast-model.v1",
                "model_type": "multi_output_ridge_regression",
                "model_id": "public-calibrated-causal-ridge-v1",
                "fit_solver": "augmented_least_squares",
                "coefficient_quantization_decimals": 8,
                "dataset_id": self.dataset.dataset_id,
                "dataset_sha256": self.dataset.package_sha256,
                "train_split": "train",
                "selection_split": "validation",
                "test_split": "test",
                "future_test_rows_accessed_during_inference": False,
                "target_boundary": (
                    "regional targets are public observations; terminal_load_kw is an "
                    "engineering-derived target, not a terminal meter label"
                ),
                "features": [
                    "intercept",
                    "hour_sin",
                    "hour_cos",
                    "day_sin",
                    "day_cos",
                    "workload",
                    "vessels_at_berth",
                    "regional_demand",
                    "carbon_factor",
                    "electricity_price",
                    "engineering_temperature",
                    "engineering_solar",
                ],
                "horizons_hours": list(FORECAST_HORIZONS),
                "evidence": model_evidence,
            }
            artifact_without_hash["model_sha256"] = _canonical_hash(artifact_without_hash)
            self._artifact = artifact_without_hash

    def metadata(self) -> dict[str, Any]:
        self._ensure_fitted()
        assert self._artifact is not None
        return json.loads(json.dumps(self._artifact))

    def predict(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        self._ensure_fitted()
        if not snapshot.get("decision_allowed"):
            raise RuntimeError("runtime_quality_gate_failed")
        signals = snapshot["signals"]
        event_time = datetime.fromisoformat(
            str(snapshot["virtual_event_time"]).replace("Z", "+00:00")
        )
        hour = event_time.hour + event_time.minute / 60.0
        day = event_time.timetuple().tm_yday

        def signal(name: str) -> float:
            return float(signals[name]["value"])

        current_features = np.array(
            [
                1.0,
                math.sin(2.0 * math.pi * hour / 24.0),
                math.cos(2.0 * math.pi * hour / 24.0),
                math.sin(2.0 * math.pi * day / 365.25),
                math.cos(2.0 * math.pi * day / 365.25),
                signal("operations.throughput_demand_teu_h") / 1_800.0,
                signal("operations.vessels_at_berth") / 20.0,
                signal("grid.regional_demand_mw") / 5_000.0,
                signal("grid.carbon_factor_kg_per_kwh") / 0.8,
                signal("grid.electricity_price_cny_per_kwh") / 3.5,
                signal("weather.ambient_temperature_c") / 45.0,
                signal("solar.available_power_kw") / 3_800.0,
            ],
            dtype=np.float64,
        )
        points: list[dict[str, Any]] = []
        for horizon in FORECAST_HORIZONS:
            model = self._models[horizon]
            prediction = (current_features @ model["beta"]) * TARGET_SCALES
            residual_std = np.asarray(model["residual_std"])
            prediction = np.maximum(prediction, 0.0)
            output = {
                name: round(float(value), 6)
                for name, value in zip(TARGET_NAMES, prediction, strict=True)
            }
            interval = {
                name: {
                    "lower": round(max(0.0, float(value - 1.96 * std)), 6),
                    "upper": round(float(value + 1.96 * std), 6),
                }
                for name, value, std in zip(
                    TARGET_NAMES,
                    prediction,
                    residual_std,
                    strict=True,
                )
            }
            points.append(
                {
                    "horizon_hours": horizon,
                    "event_time": iso_z(
                        event_time.replace(minute=0, second=0, microsecond=0)
                        + timedelta(hours=horizon)
                    ),
                    "predictions": output,
                    "prediction_interval_approx_95pct": interval,
                }
            )
        assert self._artifact is not None
        return {
            "schema_version": "runtime-forecast.v1",
            "generated_at": iso_z(utc_now()),
            "input_snapshot_id": snapshot["snapshot_id"],
            "input_snapshot_sha256": snapshot["snapshot_sha256"],
            "input_trace_id": snapshot["trace_id"],
            "data_mode": "model_inference_from_current_simulated_state",
            "true_model_inference": True,
            "model": {
                "model_id": self._artifact["model_id"],
                "model_type": self._artifact["model_type"],
                "model_sha256": self._artifact["model_sha256"],
                "dataset_id": self._artifact["dataset_id"],
                "dataset_sha256": self._artifact["dataset_sha256"],
                "train_split": "train",
                "selection_split": "validation",
                "test_split": "test",
                "target_boundary": self._artifact["target_boundary"],
                "held_out_test_mae_by_horizon": {
                    horizon: evidence["held_out_test_mae"]
                    for horizon, evidence in self._artifact["evidence"].items()
                },
                "future_test_rows_accessed_during_inference": self._artifact[
                    "future_test_rows_accessed_during_inference"
                ],
            },
            "points": points,
        }


runtime_forecast_model = RuntimeForecastModel()
