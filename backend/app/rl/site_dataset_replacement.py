from __future__ import annotations

from typing import Any

from app.rl.dataset import (
    DEPLOYMENT_COLUMNS,
    FLEXIBLE_OPERATIONS_COLUMNS,
    HYBRID_OPERATIONS_COLUMNS,
    OPERATIONAL_COLUMNS,
    REGULATORY_COLUMNS,
    PortDataset,
)
from app.rl.environment import DEFAULT_ENVIRONMENT_PARAMETERS


REQUIRED_SOURCE_DOMAINS = {
    "terminal_operating_system",
    "ais_vts_and_port_call",
    "ems_scada_and_revenue_metering",
    "equipment_plc_and_bms",
    "reefer_monitoring",
    "building_automation",
    "regulatory_authorities",
    "weather_and_navigation",
}
REQUIRED_SCENARIOS = {
    "peak_season",
    "off_peak_season",
    "extreme_weather",
    "equipment_fault",
    "grid_derating",
    "planned_maintenance",
    "demand_response",
}
REQUIRED_LINEAGE_FIELDS = {
    "source_system",
    "source_record_id",
    "event_time",
    "ingest_time",
    "unit",
    "quality",
    "revision",
    "asset_id",
    "site_id",
}
REQUIRED_SITE_MEASUREMENT_COLUMNS = {
    "loaded_import_teu",
    "loaded_export_teu",
    "total_teu",
    "grid_carbon_kg_per_kwh",
    "electricity_price_per_kwh",
    "fuel_price_per_liter",
}
HYBRID_ENVIRONMENT_PARAMETERS = {
    "hybrid_residual_trust_ratio",
    "jit_deviation_cost_cny_per_hour",
    "berth_conflict_cost_cny_per_hour",
    "crane_task_lateness_cny_per_teu",
    "yard_rehandle_cost_cny_per_teu",
    "truck_queue_cost_cny_per_teu_hour",
    "maintenance_overdue_cost_cny_per_hour",
}


def assess_site_replacement_readiness(dataset: PortDataset) -> dict[str, Any]:
    metadata = dataset.metadata
    evidence = metadata.get("site_training_evidence") or {}
    required_columns = (
        REQUIRED_SITE_MEASUREMENT_COLUMNS
        | OPERATIONAL_COLUMNS
        | DEPLOYMENT_COLUMNS
        | REGULATORY_COLUMNS
        | FLEXIBLE_OPERATIONS_COLUMNS
    )
    if dataset.environment_id == "PortEnergyHybridResidualEnv-v6":
        required_columns |= HYBRID_OPERATIONS_COLUMNS
    present_columns = set(dataset.frame.columns)
    independent_columns = set(evidence.get("independent_measurement_columns") or [])
    source_domains = set(evidence.get("source_domains") or [])
    lineage_fields = set(evidence.get("lineage_fields") or [])
    scenarios = set(evidence.get("covered_scenarios") or [])
    calibrated_parameters = set(evidence.get("calibrated_environment_parameters") or [])
    configured_parameters = set((metadata.get("environment_parameters") or {}).keys())
    required_parameters = set(DEFAULT_ENVIRONMENT_PARAMETERS)
    if dataset.environment_id == "PortEnergyHybridResidualEnv-v6":
        required_parameters |= HYBRID_ENVIRONMENT_PARAMETERS
    source_receipts = evidence.get("source_receipts") or []
    signed_live_domains = {
        str(item.get("domain"))
        for item in source_receipts
        if item.get("live_data_verified") is True
        and item.get("signature_verified") is True
        and item.get("record_count", 0) > 0
    }

    checks = {
        "supported_environment": dataset.environment_id
        in {"PortEnergyDispatchEnv-v5", "PortEnergyHybridResidualEnv-v6"},
        "all_required_columns_present": required_columns <= present_columns,
        "all_required_columns_independently_measured": required_columns <= independent_columns,
        "all_source_domains_received": REQUIRED_SOURCE_DOMAINS <= source_domains,
        "all_source_domains_signed_live": REQUIRED_SOURCE_DOMAINS <= signed_live_domains,
        "complete_event_lineage": REQUIRED_LINEAGE_FIELDS <= lineage_fields,
        "all_environment_parameters_declared": required_parameters <= configured_parameters,
        "environment_parameters_calibrated": required_parameters <= calibrated_parameters,
        "minimum_shadow_days": int(evidence.get("shadow_days") or 0) >= 180,
        "four_seasons_covered": len(set(evidence.get("covered_seasons") or [])) >= 4,
        "required_scenarios_covered": REQUIRED_SCENARIOS <= scenarios,
        "meter_coverage_complete": float(evidence.get("meter_coverage_pct") or 0) == 100.0,
        "energy_balance_reconciled": float(evidence.get("energy_balance_error_pct") or 100) <= 2.0,
        "bill_reconciled": float(evidence.get("bill_reconciliation_error_pct") or 100) <= 1.0,
        "operator_acceptance_signed": bool(evidence.get("operator_acceptance_signed")),
        "independent_review_signed": bool(evidence.get("independent_review_signed")),
    }
    blockers = [name for name, passed in checks.items() if not passed]
    return {
        "schema_version": "site-dataset-replacement-readiness.v2",
        "dataset_id": dataset.dataset_id,
        "dataset_package_sha256": dataset.package_sha256,
        "environment_id": dataset.environment_id,
        "offline_schema_compatible": checks["supported_environment"]
        and checks["all_required_columns_present"],
        "site_training_ready": not blockers,
        "required_source_domains": sorted(REQUIRED_SOURCE_DOMAINS),
        "received_source_domains": sorted(source_domains),
        "signed_live_source_domains": sorted(signed_live_domains),
        "required_measurement_columns": sorted(required_columns),
        "missing_measurement_columns": sorted(required_columns - present_columns),
        "modeled_or_unverified_columns": sorted(required_columns - independent_columns),
        "required_environment_parameters": sorted(required_parameters),
        "missing_environment_parameters": sorted(required_parameters - configured_parameters),
        "uncalibrated_environment_parameters": sorted(required_parameters - calibrated_parameters),
        "checks": checks,
        "blockers": blockers,
        "production_boundary": {
            "training_admission_only": True,
            "dispatch_allowed": False,
            "production_authority": False,
        },
        "note": (
            "A passing replacement package may be used for site retraining and shadow evaluation. "
            "It does not authorize physical dispatch or bypass site-cutover acceptance."
        ),
    }
