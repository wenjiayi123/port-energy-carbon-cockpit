from __future__ import annotations

from typing import Any

from app.rl.dataset import DEPLOYMENT_COLUMNS, PortDataset


LIVE_LINEAGE_FIELDS = {
    "source_event_id",
    "observed_at_utc",
    "ingested_at_utc",
    "quality_flags",
}


def assess_dataset_landing_readiness(dataset: PortDataset) -> dict[str, Any]:
    """Separate offline row volume from real-port information density."""

    evidence = dataset.metadata.get("public_source_evidence") or {}
    daily_anchors = int(evidence.get("vessel_activity_daily_rows") or 0)
    reported_day_coverage = float(evidence.get("vessel_activity_reported_day_coverage") or 0.0)
    if daily_anchors:
        anchor_type = "official_daily_vessel_activity_records"
        independent_operational_anchors = daily_anchors
    else:
        monthly_values = (
            int(dataset.frame["period"].nunique())
            if "period" in dataset.frame.columns
            else 0
        )
        anchor_type = "official_monthly_throughput_periods"
        independent_operational_anchors = monthly_values

    missing_deployment = sorted(DEPLOYMENT_COLUMNS - set(dataset.frame.columns))
    missing_lineage = sorted(LIVE_LINEAGE_FIELDS - set(dataset.frame.columns))
    parameter_evidence = dataset.metadata.get("environment_parameter_evidence") or {}
    environment_parameters = dataset.metadata.get("environment_parameters") or {}
    uncalibrated_parameters = sorted(
        name for name in environment_parameters if name not in parameter_evidence
    )
    expansion_ratio = round(
        len(dataset.frame) / max(1, independent_operational_anchors),
        3,
    )
    blockers: list[str] = []
    if dataset.environment_id != "PortEnergyDispatchEnv-v3":
        blockers.append("production_environment_contract_not_v3")
    if missing_deployment:
        blockers.append("missing_live_deployment_observations")
    if missing_lineage:
        blockers.append("missing_event_level_lineage_and_ingestion_timestamps")
    if uncalibrated_parameters:
        blockers.append("terminal_parameters_lack_owner_calibration_evidence")
    if dataset.temporal_mode != "sequential_rows":
        blockers.append("dataset_is_not_event_sequential")

    information_density = (
        "modeled_hourly_rows_with_daily_official_anchors"
        if daily_anchors
        else "modeled_hourly_rows_with_monthly_official_anchors"
    )
    landing_score = 100
    landing_score -= 20 if dataset.environment_id != "PortEnergyDispatchEnv-v3" else 0
    landing_score -= min(25, len(missing_deployment) * 3)
    landing_score -= min(20, len(missing_lineage) * 5)
    landing_score -= 20 if uncalibrated_parameters else 0
    landing_score -= 10 if reported_day_coverage and reported_day_coverage < 0.9 else 0
    landing_score = max(0, landing_score)
    return {
        "dataset_id": dataset.dataset_id,
        "environment_id": dataset.environment_id,
        "offline_quality": dataset.quality_report(),
        "evidence_tier": "offline_public_replay",
        "offline_research_ready": dataset.quality_report()["status"] == "pass",
        "production_training_ready": not blockers,
        "production_shadow_ready": False,
        "landing_score": landing_score,
        "landing_grade": (
            "A" if landing_score >= 90 else "B" if landing_score >= 75 else "C" if landing_score >= 60 else "D"
        ),
        "row_volume": int(len(dataset.frame)),
        "information_density": information_density,
        "independent_operational_anchor_type": anchor_type,
        "independent_operational_anchors": independent_operational_anchors,
        "modeled_rows_per_operational_anchor": expansion_ratio,
        "reported_day_coverage": round(reported_day_coverage, 6) if daily_anchors else None,
        "missing_v3_observation_fields": missing_deployment,
        "missing_live_lineage_fields": missing_lineage,
        "uncalibrated_environment_parameters": uncalibrated_parameters,
        "blockers": blockers,
        "required_next_evidence": [
            "Native TOS work orders, vessel calls, berth events and equipment states at source resolution",
            "EMS/SCADA meter intervals with correction lineage and meter-quality flags",
            "Weather/navigation and shore-power compatibility observations with source timestamps",
            "Terminal-owner calibration records for capacities, loads, tariffs, delay costs and safety limits",
            "Chronological shadow observations retained separately from the frozen public benchmark",
        ],
        "note": (
            "A high row count can come from deterministic expansion. Production readiness is based on "
            "independent source observations, lineage, calibration and live freshness, not CSV size alone."
        ),
    }
