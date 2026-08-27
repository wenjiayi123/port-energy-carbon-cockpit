from __future__ import annotations

import hashlib
import json
from typing import Any

from app.schemas.dashboard import PortEmissionsInventory


INVENTORY_SCHEMA_VERSION = "port-emissions-inventory.v1"
CRITERIA_POLLUTANTS = (
    "co2",
    "ch4",
    "n2o",
    "nox",
    "sox",
    "pm10",
    "pm2_5",
    "black_carbon",
)


def _canonical_sha256(value: dict[str, Any]) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class PortEmissionsInventoryService:
    """Build an honest port-related emissions inventory from available evidence.

    The public benchmark can calculate two aggregate CO2e sources. It cannot
    establish source ownership, disaggregate every port source, or derive
    criteria-air-pollutant emissions. Missing evidence remains unavailable.
    """

    def build(
        self,
        *,
        grid_carbon_kg: float,
        auxiliary_fuel_carbon_kg: float,
        dataset_id: str,
        dataset_sha256: str,
        dataset_metadata: dict[str, Any] | None,
        trajectory_steps: int,
    ) -> PortEmissionsInventory:
        metadata = dict(dataset_metadata or {})
        dataset_version = str(metadata.get("version") or "unversioned")
        source_urls = [str(value) for value in metadata.get("source_urls") or []]
        eia_url = next(
            (value for value in source_urls if "eia.gov" in value),
            "https://www.eia.gov/electricity/gridmonitor/about/",
        )

        unavailable_pollutants = {name: None for name in CRITERIA_POLLUTANTS}
        source_categories: list[dict[str, Any]] = [
            {
                "source_id": "ocean_going_vessels_at_berth",
                "label_zh": "远洋船舶靠泊辅机",
                "label_en": "Ocean-going vessels at berth",
                "actor": "third_party_or_operator_controlled_vessel_requires_site_evidence",
                "availability": "calculated_scenario",
                "activity_data_status": "engineering_derived_auxiliary_fuel_from_shore_power_gap",
                "inventory_boundary": "port_related_activity",
                "ghg_scope": "unassigned_requires_ownership_and_control_evidence",
                "legacy_scope": "scope_1_auxiliary_fuel",
                "co2e_kg": round(max(0.0, auxiliary_fuel_carbon_kg), 3),
                "pollutants_kg": dict(unavailable_pollutants),
                "factor_ids": ["benchmark_auxiliary_fuel_co2e_v1"],
                "evidence_class": "simulated_derived",
                "assurance_status": "unassured_scenario",
                "missing_evidence": [
                    "vessel_imo_number_and_owner",
                    "engine_and_fuel_specification",
                    "measured_fuel_or_engine_load",
                    "organizational_control_determination",
                    "pollutant_specific_emission_factors",
                ],
            },
            {
                "source_id": "harbor_craft",
                "label_zh": "港作船与拖轮",
                "label_en": "Harbor craft and tugboats",
                "actor": "port_and_third_party_harbor_craft",
                "availability": "unavailable",
                "activity_data_status": "not_connected",
                "inventory_boundary": "port_related_activity",
                "ghg_scope": "unassigned_requires_ownership_and_control_evidence",
                "legacy_scope": None,
                "co2e_kg": None,
                "pollutants_kg": dict(unavailable_pollutants),
                "factor_ids": [],
                "evidence_class": "missing",
                "assurance_status": "blocked_missing_activity_data",
                "missing_evidence": [
                    "craft_registry",
                    "engine_and_fuel_specification",
                    "operating_hours_and_load",
                ],
            },
            {
                "source_id": "cargo_handling_equipment",
                "label_zh": "港口装卸设备",
                "label_en": "Cargo-handling equipment",
                "actor": "terminal_equipment",
                "availability": "unavailable_source_disaggregation",
                "activity_data_status": "aggregate_load_only",
                "inventory_boundary": "port_related_activity",
                "ghg_scope": "unassigned_requires_asset_ownership_and_energy_submetering",
                "legacy_scope": None,
                "co2e_kg": None,
                "pollutants_kg": dict(unavailable_pollutants),
                "factor_ids": [],
                "evidence_class": "missing_disaggregation",
                "assurance_status": "blocked_missing_submetering",
                "missing_evidence": [
                    "asset_registry",
                    "equipment_fuel_and_electricity_submeters",
                    "engine_tier_and_aftertreatment",
                    "operating_mode_and_load",
                ],
            },
            {
                "source_id": "heavy_duty_vehicles",
                "label_zh": "外集卡与重型车辆",
                "label_en": "Heavy-duty vehicles",
                "actor": "third_party_and_terminal_road_fleet",
                "availability": "unavailable",
                "activity_data_status": "not_connected",
                "inventory_boundary": "port_related_activity",
                "ghg_scope": "unassigned_requires_fleet_ownership_and_trip_boundary",
                "legacy_scope": None,
                "co2e_kg": None,
                "pollutants_kg": dict(unavailable_pollutants),
                "factor_ids": [],
                "evidence_class": "missing",
                "assurance_status": "blocked_missing_activity_data",
                "missing_evidence": [
                    "gate_transactions",
                    "vehicle_class_and_fuel",
                    "distance_idle_time_and_load",
                ],
            },
            {
                "source_id": "rail_locomotives",
                "label_zh": "港区铁路机车",
                "label_en": "Rail locomotives",
                "actor": "rail_operator",
                "availability": "unavailable",
                "activity_data_status": "not_connected",
                "inventory_boundary": "port_related_activity",
                "ghg_scope": "unassigned_requires_operator_and_boundary_evidence",
                "legacy_scope": None,
                "co2e_kg": None,
                "pollutants_kg": dict(unavailable_pollutants),
                "factor_ids": [],
                "evidence_class": "missing",
                "assurance_status": "blocked_missing_activity_data",
                "missing_evidence": [
                    "locomotive_registry",
                    "fuel_and_engine_tier",
                    "moves_hours_and_load",
                ],
            },
            {
                "source_id": "purchased_electricity",
                "label_zh": "外购电力",
                "label_en": "Purchased electricity",
                "actor": "terminal_electric_load",
                "availability": "calculated_scenario",
                "activity_data_status": "public_grid_proxy_and_simulated_terminal_load",
                "inventory_boundary": "terminal_energy_scenario",
                "ghg_scope": "scope_2_location_based",
                "legacy_scope": "scope_2_location_based_electricity",
                "co2e_kg": round(max(0.0, grid_carbon_kg), 3),
                "pollutants_kg": dict(unavailable_pollutants),
                "factor_ids": ["eia930_ldwp_consumed_intensity_dynamic"],
                "evidence_class": "public_observation_plus_simulated_load",
                "assurance_status": "unassured_public_proxy",
                "missing_evidence": [
                    "terminal_revenue_meter_intervals",
                    "utility_invoice_reconciliation",
                    "supplier_specific_market_based_instruments",
                    "pollutant_specific_grid_factors",
                ],
            },
            {
                "source_id": "stationary_combustion",
                "label_zh": "固定燃烧源与备用发电",
                "label_en": "Stationary combustion and backup generation",
                "actor": "terminal_stationary_assets",
                "availability": "unavailable",
                "activity_data_status": "not_connected",
                "inventory_boundary": "port_related_activity",
                "ghg_scope": "scope_1_if_owned_or_operationally_controlled",
                "legacy_scope": None,
                "co2e_kg": None,
                "pollutants_kg": dict(unavailable_pollutants),
                "factor_ids": [],
                "evidence_class": "missing",
                "assurance_status": "blocked_missing_activity_data",
                "missing_evidence": [
                    "generator_and_boiler_registry",
                    "fuel_receipts_and_runtime",
                    "engine_and_control_technology",
                ],
            },
        ]

        factor_register = [
            {
                "factor_id": "eia930_ldwp_consumed_intensity_dynamic",
                "substance": "co2e",
                "value": None,
                "unit": "kgCO2e/kWh",
                "value_mode": "hourly_dataset_column",
                "source_name": "U.S. EIA Hourly Electric Grid Monitor",
                "source_url": eia_url,
                "dataset_version": dataset_version,
                "quality": "public_hourly_consumed_intensity_with_declared_imputation",
                "status": "active_public_proxy",
            },
            {
                "factor_id": "benchmark_auxiliary_fuel_co2e_v1",
                "substance": "co2e",
                "value": float(
                    (metadata.get("environment_parameters") or {}).get(
                        "fuel_carbon_kg_per_liter",
                        2.68,
                    )
                ),
                "unit": "kgCO2e/liter",
                "value_mode": "declared_scenario_parameter",
                "source_name": "versioned dataset environment parameter",
                "source_url": None,
                "dataset_version": dataset_version,
                "quality": "scenario_assumption_not_site_factor",
                "status": "active_scenario_only",
            },
        ]

        calculated = [item for item in source_categories if item["co2e_kg"] is not None]
        live_measured = [item for item in source_categories if item["evidence_class"] == "live_measured"]
        criteria_ready = [
            item
            for item in source_categories
            if any(value is not None for value in item["pollutants_kg"].values())
        ]
        port_related_total = round(sum(float(item["co2e_kg"]) for item in calculated), 3)
        coverage_pct = round(len(calculated) / len(source_categories) * 100.0, 1)
        payload: dict[str, Any] = {
            "schema_version": INVENTORY_SCHEMA_VERSION,
            "inventory_kind": "port_related_activity_inventory",
            "reporting_boundary": {
                "geographic_boundary": "public_benchmark_terminal_scenario",
                "organizational_boundary": "unestablished_requires_named_entity_and_control_approach",
                "operational_boundary": "held_out_trajectory_only",
                "reporting_period": f"{trajectory_steps}-step held-out trajectory",
                "boundary_status": "blocked_for_corporate_inventory",
            },
            "methodology": {
                "port_source_framework": "IMO_port_emissions_source_categories",
                "ghg_reporting_alignment": "ISO_14064_1_contract_mapping_not_certification",
                "energy_management_alignment": "ISO_50001_evidence_inputs_not_certification",
                "scope_classification_rule": "ownership_and_operational_control_evidence_required",
                "missing_values_policy": "unavailable_not_zero",
            },
            "dataset_id": dataset_id,
            "dataset_sha256": dataset_sha256,
            "source_categories": source_categories,
            "factor_register": factor_register,
            "totals": {
                "port_related_activity_co2e_kg": port_related_total,
                "scope_1_kg": None,
                "scope_2_location_based_kg": round(max(0.0, grid_carbon_kg), 3),
                "scope_2_market_based_kg": None,
                "scope_3_kg": None,
                "assured_total_co2e_kg": None,
                "note": "Only modeled port-related activity total is available; corporate scope totals require ownership and control evidence.",
            },
            "coverage": {
                "source_category_count": len(source_categories),
                "co2e_calculated_count": len(calculated),
                "live_measured_count": len(live_measured),
                "criteria_pollutant_ready_count": len(criteria_ready),
                "criteria_pollutant_count": len(CRITERIA_POLLUTANTS),
                "modeled_source_coverage_pct": coverage_pct,
                "inventory_complete": len(calculated) == len(source_categories),
                "live_inventory_ready": len(live_measured) == len(source_categories),
            },
            "assurance": {
                "status": "blocked",
                "third_party_verified": False,
                "regulatory_submission_allowed": False,
                "uncertainty_quantified": False,
                "base_year_recalculation_policy": "not_established",
                "correction_and_reconciliation_policy": "not_established",
                "blockers": [
                    "named_reporting_entity_and_control_approach_missing",
                    "five_port_source_categories_lack_activity_data",
                    "live_meter_and_fuel_reconciliation_missing",
                    "market_based_scope_2_instruments_missing",
                    "criteria_pollutant_factors_and_activity_data_missing",
                    "uncertainty_and_independent_verification_missing",
                ],
            },
            "production_boundary": {
                "simulation_mode": True,
                "live_data_verified": False,
                "inventory_assured": False,
                "regulatory_submission_allowed": False,
            },
        }
        payload["evidence_sha256"] = _canonical_sha256(payload)
        return PortEmissionsInventory(**payload)


port_emissions_inventory_service = PortEmissionsInventoryService()
