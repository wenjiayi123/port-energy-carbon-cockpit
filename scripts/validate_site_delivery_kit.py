#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.schemas.site_cutover import (  # noqa: E402
    APPROVAL_ROLES,
    MODULE_DOMAINS,
    REQUIRED_SHADOW_SCENARIOS,
    SiteCutoverRequest,
)
from app.services.site_cutover import SiteCutoverService  # noqa: E402


SCHEMA_VERSION = "site-delivery-kit-validation.v1"
ZERO64 = "0" * 64
ZERO_SIGNATURE = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=="
ZERO_PUBLIC_KEY = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
REQUIRED_FILES = {
    "site_profile.template.yaml",
    "system_mapping.template.csv",
    "meter_device_points.template.csv",
    "network_zones.template.csv",
    "raci.template.csv",
    "shadow_acceptance_plan.template.csv",
    "domain_acceptance_register.template.csv",
    "cutover_gates.template.csv",
    "approval_register.template.csv",
    "site_cutover_package.template.json",
    "trusted_signers.template.json",
}
CSV_REQUIRED_COLUMNS = {
    "system_mapping.template.csv": {
        "mapping_id",
        "adapter_class",
        "domain",
        "source_system",
        "target_adapter",
        "write_allowed",
        "source_record_key",
        "event_id_field",
        "observed_at_field",
        "received_at_field",
        "quality_field",
        "revision_field",
        "receipt_field",
        "max_age_seconds",
        "status",
        "evidence_sha256",
    },
    "meter_device_points.template.csv": {
        "point_id",
        "asset_id",
        "asset_type",
        "feeder_id",
        "meter_id",
        "external_tag",
        "measurement_kind",
        "unit",
        "sample_seconds",
        "source_record_key",
        "calibration_certificate_id",
        "quality_code_field",
        "timestamp_field",
        "timezone",
        "reconciliation_group",
        "status",
        "evidence_sha256",
    },
    "network_zones.template.csv": {
        "record_id",
        "record_type",
        "zone_name",
        "source_zone",
        "destination_zone",
        "read_only",
        "default_deny",
        "mutual_tls",
        "firewall_rule_id",
        "status",
        "evidence_sha256",
    },
    "raci.template.csv": {
        "activity_id",
        "activity",
        "port_owner",
        "operations_owner",
        "energy_carbon_owner",
        "ot_safety_owner",
        "chief_information_security_officer",
        "independent_verifier",
        "data_owner",
        "finance_owner",
        "it_platform_owner",
        "status",
    },
    "shadow_acceptance_plan.template.csv": {
        "work_package_id",
        "start_day",
        "end_day",
        "scenario",
        "operating_season",
        "acceptance_gate",
        "evidence_owner",
        "approval_role",
        "status",
        "evidence_sha256",
    },
    "domain_acceptance_register.template.csv": {
        "domain_id",
        "domain",
        "site_id",
        "tenant_id",
        "assessment_window_id",
        "independently_verified",
        "acceptance_conclusion",
        "exception_ids",
        "signed_payload_sha256",
        "signature",
        "status",
    },
    "cutover_gates.template.csv": {
        "gate_id",
        "required_condition",
        "evidence_reference",
        "owner_role",
        "status",
        "verified_at",
        "verifier_id",
    },
    "approval_register.template.csv": {
        "approval_id",
        "role",
        "approver_id",
        "decision",
        "acceptance_package_sha256",
        "approval_record_sha256",
        "key_id",
        "signature",
        "status",
    },
}
REQUIRED_LIVE_ADAPTERS = {
    "terminal_operations_system",
    "energy_management_system",
    "vessel_traffic_and_berth",
    "equipment_scada",
    "weather_navigation",
    "shore_power_compatibility",
}
REQUIRED_METER_ASSET_TYPES = {
    "quay_crane",
    "yard_crane",
    "yard_vehicle",
    "yard_vehicle_charger",
    "reefer_bank",
    "shore_power",
    "battery_storage",
    "building",
    "grid_import",
    "transformer",
    "distribution_feeder",
}
REQUIRED_NETWORK_ZONES = {
    "IT_ZONE",
    "IT_DMZ",
    "OT_DMZ",
    "OT_CONTROL",
    "SAFETY_INTERLOCK",
}
RACI_ROLES = [
    "port_owner",
    "operations_owner",
    "energy_carbon_owner",
    "ot_safety_owner",
    "chief_information_security_officer",
    "independent_verifier",
    "data_owner",
    "finance_owner",
    "it_platform_owner",
]
PLACEHOLDER_PATTERN = re.compile(
    r"REPLACE_WITH_[A-Z0-9_]+|REPLACE_KEY_[A-Za-z0-9_]+|TEMPLATE_INCOMPLETE"
)


def _read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        return list(reader.fieldnames or []), list(reader)


def _bool(value: str) -> bool:
    return value.strip().lower() == "true"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _has_real_sha256(value: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-f]{64}", value)) and value != ZERO64


def _check(
    checks: list[dict[str, str]],
    name: str,
    passed: bool,
    detail: str,
    errors: list[str],
) -> None:
    checks.append(
        {"name": name, "status": "pass" if passed else "fail", "detail": detail}
    )
    if not passed:
        errors.append(f"{name}: {detail}")


def _strict_check(
    checks: list[dict[str, str]],
    name: str,
    passed: bool,
    detail: str,
    blockers: list[str],
) -> None:
    checks.append(
        {
            "name": name,
            "status": "pass" if passed else "blocked",
            "detail": detail,
        }
    )
    if not passed:
        blockers.append(f"{name}: {detail}")


def validate_kit(kit_dir: Path, *, strict: bool = False) -> dict[str, Any]:
    kit_dir = kit_dir.resolve()
    checks: list[dict[str, str]] = []
    errors: list[str] = []
    blockers: list[str] = []
    warnings: list[str] = []
    csv_data: dict[str, list[dict[str, str]]] = {}
    manifest: dict[str, str] = {}

    missing = sorted(name for name in REQUIRED_FILES if not (kit_dir / name).is_file())
    _check(
        checks,
        "required_files",
        not missing,
        "all 11 controlled templates present" if not missing else f"missing {missing}",
        errors,
    )
    if missing:
        return _result(
            kit_dir,
            strict,
            checks,
            errors,
            blockers,
            warnings,
            manifest,
            0,
            {},
        )

    for name in sorted(REQUIRED_FILES):
        manifest[name] = _sha256(kit_dir / name)

    for name, required_columns in CSV_REQUIRED_COLUMNS.items():
        headers, rows = _read_csv(kit_dir / name)
        csv_data[name] = rows
        missing_columns = sorted(required_columns - set(headers))
        duplicate_headers = sorted({item for item in headers if headers.count(item) > 1})
        ids = [next(iter(row.values()), "") for row in rows]
        _check(
            checks,
            f"csv_contract:{name}",
            bool(rows) and not missing_columns and not duplicate_headers and len(ids) == len(set(ids)),
            (
                f"{len(rows)} rows, required columns and unique first-column IDs present"
                if rows and not missing_columns and not duplicate_headers and len(ids) == len(set(ids))
                else f"rows={len(rows)} missing_columns={missing_columns} duplicate_headers={duplicate_headers}"
            ),
            errors,
        )

    profile = yaml.safe_load((kit_dir / "site_profile.template.yaml").read_text(encoding="utf-8"))
    boundary = profile.get("application_control_boundary", {}) if isinstance(profile, dict) else {}
    safe_boundary = (
        boundary.get("production_authority") is False
        and boundary.get("production_dispatch_allowed") is False
        and boundary.get("interlock_bypass_allowed") is False
        and boundary.get("external_instruction_gateway_required") is True
    )
    _check(
        checks,
        "application_control_boundary",
        safe_boundary,
        "application remains advisory-only and external gateway/interlocks retain control",
        errors,
    )

    systems = csv_data["system_mapping.template.csv"]
    adapters = {row["adapter_class"] for row in systems}
    all_read_only = all(not _bool(row["write_allowed"]) for row in systems)
    _check(
        checks,
        "live_adapter_coverage",
        REQUIRED_LIVE_ADAPTERS <= adapters and all_read_only,
        f"required adapters={len(REQUIRED_LIVE_ADAPTERS & adapters)}/6; application write paths={sum(_bool(row['write_allowed']) for row in systems)}",
        errors,
    )

    points = csv_data["meter_device_points.template.csv"]
    asset_types = {row["asset_type"] for row in points}
    reconciliation_groups = {row["reconciliation_group"] for row in points}
    _check(
        checks,
        "meter_point_coverage",
        REQUIRED_METER_ASSET_TYPES <= asset_types and len(reconciliation_groups) >= 8,
        f"required asset classes={len(REQUIRED_METER_ASSET_TYPES & asset_types)}/{len(REQUIRED_METER_ASSET_TYPES)}; reconciliation groups={len(reconciliation_groups)}",
        errors,
    )

    network = csv_data["network_zones.template.csv"]
    zones = {row["zone_name"] for row in network if row["record_type"] == "zone"}
    conduits = [row for row in network if row["record_type"] == "conduit"]
    conduit_controls = all(
        _bool(row["read_only"])
        and _bool(row["default_deny"])
        and _bool(row["mutual_tls"])
        for row in conduits
    )
    forbidden_direct = any(
        row["source_zone"] == "IT_ZONE"
        and row["destination_zone"] in {"OT_CONTROL", "SAFETY_INTERLOCK"}
        for row in conduits
    )
    _check(
        checks,
        "network_zone_and_conduit_controls",
        REQUIRED_NETWORK_ZONES <= zones and bool(conduits) and conduit_controls and not forbidden_direct,
        f"zones={len(REQUIRED_NETWORK_ZONES & zones)}/5; controlled conduits={len(conduits)}; direct IT-to-control={forbidden_direct}",
        errors,
    )

    raci = csv_data["raci.template.csv"]
    accountable_counts = {
        row["activity_id"]: sum(row[role].strip().upper() == "A" for role in RACI_ROLES)
        for row in raci
    }
    bad_raci = sorted(key for key, count in accountable_counts.items() if count != 1)
    _check(
        checks,
        "raci_single_accountable_owner",
        not bad_raci,
        "exactly one accountable owner per activity" if not bad_raci else f"invalid activities={bad_raci}",
        errors,
    )

    shadow = csv_data["shadow_acceptance_plan.template.csv"]
    covered_days: set[int] = set()
    shadow_ranges_valid = True
    for row in shadow:
        try:
            start_day = int(row["start_day"])
            end_day = int(row["end_day"])
        except ValueError:
            shadow_ranges_valid = False
            continue
        if start_day < 1 or end_day < start_day or end_day > 730:
            shadow_ranges_valid = False
            continue
        covered_days.update(range(start_day, end_day + 1))
    scenarios = {row["scenario"] for row in shadow}
    _check(
        checks,
        "shadow_180_day_plan",
        shadow_ranges_valid
        and covered_days == set(range(1, 181))
        and REQUIRED_SHADOW_SCENARIOS <= scenarios,
        f"continuous days={len(covered_days)}/180; required scenarios={len(REQUIRED_SHADOW_SCENARIOS & scenarios)}/6",
        errors,
    )

    domains = csv_data["domain_acceptance_register.template.csv"]
    domain_values = [row["domain"] for row in domains]
    _check(
        checks,
        "thirteen_domain_register",
        set(domain_values) == MODULE_DOMAINS and len(domain_values) == len(MODULE_DOMAINS),
        f"unique domains={len(set(domain_values))}/13; rows={len(domain_values)}",
        errors,
    )

    gates = csv_data["cutover_gates.template.csv"]
    expected_gates = {f"GATE-{index:02d}" for index in range(1, 17)}
    gate_ids = {row["gate_id"] for row in gates}
    _check(
        checks,
        "sixteen_gate_register",
        gate_ids == expected_gates and len(gates) == 16,
        f"unique gates={len(gate_ids)}/16; rows={len(gates)}",
        errors,
    )

    approvals = csv_data["approval_register.template.csv"]
    approval_roles = [row["role"] for row in approvals]
    _check(
        checks,
        "six_party_approval_register",
        set(approval_roles) == APPROVAL_ROLES and len(approval_roles) == len(APPROVAL_ROLES),
        f"unique approval roles={len(set(approval_roles))}/6; rows={len(approval_roles)}",
        errors,
    )

    package_payload = json.loads(
        (kit_dir / "site_cutover_package.template.json").read_text(encoding="utf-8")
    )
    try:
        package = SiteCutoverRequest(**package_payload)
    except Exception as exc:  # Pydantic emits a complete field-level error message.
        package = None
        _check(checks, "unsigned_package_schema", False, str(exc), errors)
    else:
        package_domains = [item.domain for item in package.module_evidence]
        package_roles = [item.role for item in package.approvals]
        package_safe = (
            set(package_domains) == MODULE_DOMAINS
            and len(package_domains) == len(MODULE_DOMAINS)
            and set(package_roles) == APPROVAL_ROLES
            and len(package_roles) == len(APPROVAL_ROLES)
            and package.operational_evidence.production_authority_disabled_in_application
        )
        _check(
            checks,
            "unsigned_package_schema",
            package_safe,
            "Pydantic contract valid with 13 domains, six approvals and disabled application authority",
            errors,
        )

    trusted_signers = json.loads(
        (kit_dir / "trusted_signers.template.json").read_text(encoding="utf-8")
    )
    signer_authorities = {
        str(value.get("authority"))
        for value in trusted_signers.values()
        if isinstance(value, dict)
    }
    expected_authorities = MODULE_DOMAINS | APPROVAL_ROLES
    _check(
        checks,
        "trusted_signer_authority_coverage",
        signer_authorities == expected_authorities and len(trusted_signers) == len(expected_authorities),
        f"unique authorities={len(signer_authorities)}/19; keys={len(trusted_signers)}",
        errors,
    )

    machine_files = sorted(name for name in REQUIRED_FILES if name != "README.md")
    placeholder_count = sum(
        len(PLACEHOLDER_PATTERN.findall((kit_dir / name).read_text(encoding="utf-8")))
        for name in machine_files
    )

    if strict:
        zero_material_count = sum(
            (kit_dir / name).read_text(encoding="utf-8").count(ZERO64)
            + (kit_dir / name).read_text(encoding="utf-8").count(ZERO_SIGNATURE)
            + (kit_dir / name).read_text(encoding="utf-8").count(ZERO_PUBLIC_KEY)
            for name in machine_files
        )
        _strict_check(
            checks,
            "site_owned_values_complete",
            placeholder_count == 0 and zero_material_count == 0,
            f"remaining placeholders={placeholder_count}; zeroed hashes/keys/signatures={zero_material_count}",
            blockers,
        )
        _strict_check(
            checks,
            "mapping_and_meter_acceptance",
            all(row["status"] == "accepted" and _has_real_sha256(row["evidence_sha256"]) for row in systems)
            and all(row["status"] == "accepted" and _has_real_sha256(row["evidence_sha256"]) for row in points),
            "all system mappings and meter points must be accepted with nonzero evidence hashes",
            blockers,
        )
        _strict_check(
            checks,
            "network_and_raci_acceptance",
            all(row["status"] == "accepted" and _has_real_sha256(row["evidence_sha256"]) for row in network)
            and all(row["status"] == "accepted" for row in raci),
            "all network records and RACI activities must be accepted",
            blockers,
        )
        _strict_check(
            checks,
            "shadow_evidence_accepted",
            all(
                row["status"] == "accepted"
                and _has_real_sha256(row["evidence_sha256"])
                and "REPLACE_WITH" not in row["operating_season"]
                for row in shadow
            ),
            "all 180 shadow days require accepted evidence and named operating seasons",
            blockers,
        )
        _strict_check(
            checks,
            "domain_and_gate_acceptance",
            all(
                row["status"] == "accepted"
                and _bool(row["independently_verified"])
                and row["acceptance_conclusion"] == "accepted"
                and not row["exception_ids"].strip()
                and _has_real_sha256(row["signed_payload_sha256"])
                for row in domains
            )
            and all(row["status"] == "passed" for row in gates),
            "all 13 domains must be independently accepted without exceptions and all 16 gates passed",
            blockers,
        )
        _strict_check(
            checks,
            "six_party_approval",
            all(
                row["status"] == "approved"
                and row["decision"] == "approved"
                and _has_real_sha256(row["acceptance_package_sha256"])
                and _has_real_sha256(row["approval_record_sha256"])
                for row in approvals
            ),
            "all six roles must approve the same nonzero package digest",
            blockers,
        )
        if package is not None:
            try:
                service_report = SiteCutoverService(
                    trusted_signers=trusted_signers
                ).evaluate(package)
            except Exception as exc:
                _strict_check(
                    checks,
                    "signed_package_external_review_eligibility",
                    False,
                    f"package evaluation failed: {exc}",
                    blockers,
                )
            else:
                _strict_check(
                    checks,
                    "signed_package_external_review_eligibility",
                    service_report.status == "eligible_for_external_cutover_review"
                    and all(gate.get("passed") for gate in service_report.gates),
                    f"site-cutover status={service_report.status}; passed gates={sum(bool(gate.get('passed')) for gate in service_report.gates)}/16",
                    blockers,
                )

    counts = {
        "files": len(REQUIRED_FILES),
        "system_mappings": len(systems),
        "meter_device_points": len(points),
        "network_records": len(network),
        "raci_activities": len(raci),
        "shadow_work_packages": len(shadow),
        "shadow_days": len(covered_days),
        "shadow_scenarios": len(REQUIRED_SHADOW_SCENARIOS & scenarios),
        "domains": len(domains),
        "gates": len(gates),
        "approvals": len(approvals),
    }
    if not strict and placeholder_count:
        warnings.append(
            f"template intentionally contains {placeholder_count} site-owned placeholders; run --strict after controlled completion"
        )
    return _result(
        kit_dir,
        strict,
        checks,
        errors,
        blockers,
        warnings,
        manifest,
        placeholder_count,
        counts,
    )


def _result(
    kit_dir: Path,
    strict: bool,
    checks: list[dict[str, str]],
    errors: list[str],
    blockers: list[str],
    warnings: list[str],
    manifest: dict[str, str],
    placeholder_count: int,
    counts: dict[str, int],
) -> dict[str, Any]:
    template_valid = not errors
    site_delivery_ready = strict and template_valid and not blockers
    if not template_valid:
        status = "invalid"
    elif site_delivery_ready:
        status = "site_delivery_ready"
    elif strict:
        status = "blocked_site_inputs_or_acceptance_incomplete"
    else:
        status = "template_valid_site_inputs_required"
    return {
        "schema_version": SCHEMA_VERSION,
        "kit_path": str(kit_dir),
        "mode": "strict_site_acceptance" if strict else "template_audit",
        "status": status,
        "template_valid": template_valid,
        "site_delivery_ready": site_delivery_ready,
        "production_authority_granted": False,
        "checks": checks,
        "counts": counts,
        "placeholder_count": placeholder_count,
        "errors": errors,
        "blockers": blockers,
        "warnings": warnings,
        "manifest_sha256": manifest,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate the port energy-carbon site-delivery templates or completed site package."
    )
    parser.add_argument(
        "kit_dir",
        nargs="?",
        default=str(ROOT / "deployment" / "site_delivery"),
        help="Directory containing the controlled site-delivery files",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Require completed site inputs, accepted evidence and a valid signed cutover package",
    )
    args = parser.parse_args()
    result = validate_kit(Path(args.kit_dir), strict=args.strict)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    if not result["template_valid"]:
        raise SystemExit(1)
    if args.strict and not result["site_delivery_ready"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
