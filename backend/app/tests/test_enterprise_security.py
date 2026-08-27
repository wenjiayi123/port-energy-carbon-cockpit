from __future__ import annotations

import base64
from copy import deepcopy
from datetime import datetime, timedelta, timezone

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
import pytest

from app.main import create_app
from app.schemas.enterprise_security import SOURCE_DOMAINS, EnterpriseSecurityRequest
from app.services.enterprise_security import (
    EnterpriseSecurityService,
    canonical_sha256,
    source_domain_payload,
)


HASH = "a" * 64


def _payload() -> dict:
    evaluated_at = datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc)
    observed_at = evaluated_at - timedelta(minutes=5)
    return {
        "schema_version": "enterprise-security-input.v1",
        "case_id": "enterprise-security-case-001",
        "evaluated_at": evaluated_at.isoformat(),
        "policy": {
            "policy_id": "enterprise-security-policy-001",
            "organization_id": "port-authority-001",
            "site_id": "terminal-001",
            "window": {
                "window_id": "security-assessment-2026-08",
                "start_at": "2026-08-01T00:00:00+00:00",
                "end_at": "2026-08-31T23:59:59+00:00",
            },
            "framework_versions": [
                "NIST SP 800-82 Rev.3",
                "NIST SP 800-207",
                "NIST SP 800-63C-4",
            ],
            "availability_slo_pct": 99.9,
            "maximum_rpo_minutes": 15,
            "maximum_rto_minutes": 30,
            "minimum_audit_retention_days": 2555,
            "maximum_key_age_days": 90,
            "maximum_source_age_seconds": 86400,
            "maximum_source_alignment_seconds": 3600,
            "minimum_tls_version": "TLS1.2",
            "security_architecture_sha256": HASH,
            "tenant_policy_sha256": "b" * 64,
            "ot_risk_assessment_sha256": "c" * 64,
            "approved_by": "security-board-001",
            "approval_record_sha256": "d" * 64,
        },
        "identity": {
            "issuer": "https://idp.port.example",
            "audience": "port-energy-api",
            "discovery_document_sha256": "e" * 64,
            "active_signing_key_ids": ["idp-key-current", "idp-key-next"],
            "sampled_successful_logins": 120,
            "rejected_invalid_token_tests": 25,
            "mfa_enforced": True,
            "phishing_resistant_mfa_for_privileged_users": True,
            "automated_deprovisioning": True,
            "maximum_deprovisioning_minutes": 15,
            "dormant_accounts_disabled": True,
            "break_glass_accounts_monitored_and_tested": True,
            "identity_test_report_sha256": "f" * 64,
        },
        "authorization_and_tenant": {
            "named_user_count": 20,
            "organization_ids": ["tenant-a", "tenant-b"],
            "role_binding_count": 24,
            "least_privilege_review_completed": True,
            "privileged_access_review_completed": True,
            "segregation_of_duties_test_count": 12,
            "denied_unauthorized_test_count": 30,
            "cross_tenant_test_count": 50,
            "cross_tenant_rejected_count": 50,
            "row_level_security_enforced": True,
            "tenant_partition_keys_enforced": True,
            "tenant_encryption_key_ids": {
                "tenant-a": "kms-tenant-a",
                "tenant-b": "kms-tenant-b",
            },
            "authorization_policy_sha256": "1" * 64,
            "tenant_isolation_report_sha256": "2" * 64,
        },
        "messaging_and_timeseries": {
            "broker_cluster_nodes": 3,
            "broker_quorum_enabled": True,
            "durable_messages_enabled": True,
            "producer_idempotency_enabled": True,
            "consumer_acknowledgements_enabled": True,
            "schema_registry_enforced": True,
            "dead_letter_queue_enabled": True,
            "replay_drill_passed": True,
            "published_message_count": 10000,
            "acknowledged_message_count": 10000,
            "duplicate_effect_count": 0,
            "timeseries_cluster_nodes": 3,
            "timeseries_replication_factor": 3,
            "timeseries_retention_days": 730,
            "timeseries_point_count": 1000000,
            "timeseries_backup_export_verified": True,
            "tenant_partition_enforced": True,
            "platform_test_report_sha256": "3" * 64,
        },
        "high_availability": {
            "api_replica_count": 3,
            "worker_replica_count": 3,
            "availability_zone_count": 3,
            "database_replica_count": 3,
            "load_balancer_health_checks_enabled": True,
            "automatic_failover_enabled": True,
            "split_brain_prevention_enabled": True,
            "failover_drill_passed": True,
            "measured_failover_minutes": 2,
            "measured_availability_pct": 99.99,
            "capacity_after_single_failure_pct": 120,
            "failover_report_sha256": "4" * 64,
        },
        "backup_and_dr": {
            "backup_ids": ["backup-primary-001", "backup-offline-001"],
            "encrypted_backups": True,
            "immutable_backups": True,
            "geographically_separate_copy": True,
            "offline_recovery_copy": True,
            "restore_drill_passed": True,
            "restored_data_hash_matches": True,
            "measured_rpo_minutes": 5,
            "measured_rto_minutes": 20,
            "backup_retention_days": 365,
            "recovery_runbook_sha256": "5" * 64,
            "restore_report_sha256": "6" * 64,
        },
        "audit_and_siem": {
            "external_worm_sink_enabled": True,
            "retention_lock_enabled": True,
            "retention_days": 2555,
            "hash_chain_verified": True,
            "generated_event_count": 10000,
            "delivered_event_count": 10000,
            "clock_synchronization_verified": True,
            "sensitive_field_redaction_verified": True,
            "siem_detection_rule_count": 12,
            "detection_drill_passed": True,
            "tested_incident_ticket_id": "SEC-2026-001",
            "maximum_detection_minutes": 4,
            "audit_export_sha256": "7" * 64,
            "siem_test_report_sha256": "8" * 64,
        },
        "pki_and_keys": {
            "minimum_tls_version": "TLS1.3",
            "mtls_user_to_api": True,
            "mtls_service_to_service": True,
            "mtls_it_dmz_boundary": True,
            "mtls_dmz_ot_boundary": True,
            "certificate_inventory_count": 42,
            "expired_certificate_count": 0,
            "maximum_certificate_days_remaining": 90,
            "maximum_active_key_age_days": 30,
            "key_rotation_drill_passed": True,
            "revocation_drill_passed": True,
            "secrets_manager_enabled": True,
            "root_keys_hardware_protected": True,
            "repository_secret_scan_clean": True,
            "pki_inventory_sha256": "9" * 64,
            "rotation_report_sha256": "0" * 64,
        },
        "ot_security": {
            "security_zones": [
                "enterprise_it",
                "industrial_dmz",
                "ot_control",
                "safety_system",
            ],
            "allowlisted_conduit_count": 12,
            "default_deny_between_zones": True,
            "direct_internet_to_ot_blocked": True,
            "read_only_it_ot_gateway": True,
            "outbound_ot_egress_allowlisted": True,
            "remote_access_jump_host_enforced": True,
            "remote_access_mfa_enforced": True,
            "remote_sessions_recorded": True,
            "vendor_access_just_in_time": True,
            "asset_inventory_coverage_pct": 100,
            "vulnerability_remediation_within_policy_pct": 98,
            "ot_incident_exercise_passed": True,
            "independent_safety_interlock_tested": True,
            "local_manual_control_retained": True,
            "application_command_authority_disabled": True,
            "ot_architecture_sha256": "a" * 64,
            "exercise_report_sha256": "b" * 64,
        },
        "approvals": [
            {
                "approval_id": "approval-enterprise-owner",
                "role": "enterprise_owner",
                "approver_id": "enterprise-owner-001",
                "decision": "approved",
                "approved_at": observed_at.isoformat(),
                "security_architecture_sha256": HASH,
                "approval_record_sha256": "c" * 64,
            },
            {
                "approval_id": "approval-ciso",
                "role": "chief_information_security_officer",
                "approver_id": "ciso-001",
                "decision": "approved",
                "approved_at": observed_at.isoformat(),
                "security_architecture_sha256": HASH,
                "approval_record_sha256": "d" * 64,
            },
            {
                "approval_id": "approval-ot-owner",
                "role": "ot_security_owner",
                "approver_id": "ot-security-owner-001",
                "decision": "approved",
                "approved_at": observed_at.isoformat(),
                "security_architecture_sha256": HASH,
                "approval_record_sha256": "e" * 64,
            },
        ],
        "source_attestations": [
            {
                "domain": domain,
                "source_system": f"{domain}-system",
                "source_record_ids": [f"{domain}-record-001"],
                "observed_at": observed_at.isoformat(),
                "live_data_verified": True,
                "key_id": f"key-{domain}",
                "signed_payload_sha256": "0" * 64,
                "signature": base64.b64encode(b"0" * 64).decode("ascii"),
            }
            for domain in sorted(SOURCE_DOMAINS)
        ],
    }


def _sign(payload: dict) -> tuple[EnterpriseSecurityRequest, dict[str, str]]:
    provisional = EnterpriseSecurityRequest(**payload)
    public_keys: dict[str, str] = {}
    private_keys: dict[str, Ed25519PrivateKey] = {}
    for domain in SOURCE_DOMAINS:
        key = Ed25519PrivateKey.generate()
        private_keys[domain] = key
        public_keys[f"key-{domain}"] = base64.b64encode(
            key.public_key().public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw,
            )
        ).decode("ascii")
    attestations = {item["domain"]: item for item in payload["source_attestations"]}
    for domain in SOURCE_DOMAINS:
        digest = canonical_sha256(source_domain_payload(provisional, domain))
        attestations[domain]["signed_payload_sha256"] = digest
        attestations[domain]["signature"] = base64.b64encode(
            private_keys[domain].sign(bytes.fromhex(digest))
        ).decode("ascii")
    return EnterpriseSecurityRequest(**payload), public_keys


def test_default_exposes_repository_controls_but_keeps_site_claim_blocked() -> None:
    report = EnterpriseSecurityService(source_public_keys={}).build_default()

    assert report.status == "blocked"
    assert report.source_readiness["domain_count"] == 0
    assert report.assurance["passed_gate_count"] == 0
    assert report.current_repository_controls["oidc_eddsa_validation_available"] is True
    assert report.identity_and_access["verified_identity_provider"] is None
    assert report.production_boundary["production_authority"] is False


def test_nine_signed_domains_close_all_twenty_enterprise_security_gates() -> None:
    request, public_keys = _sign(_payload())
    report = EnterpriseSecurityService(source_public_keys=public_keys).evaluate(request)

    assert report.status == "evidence_package_passed"
    assert report.source_readiness["domain_count"] == 9
    assert report.assurance["passed_gate_count"] == 20
    assert report.identity_and_access["verified_named_user_count"] == 20
    assert report.tenant_isolation["verified_cross_tenant_rejection_rate_pct"] == 100
    assert report.messaging_and_timeseries["verified_broker_nodes"] == 3
    assert report.availability_and_recovery["verified_rto_minutes"] == 20
    assert report.audit_and_monitoring["verified_worm_retention_days"] == 2555
    assert report.pki_and_key_management["verified_mtls_boundaries"] == 4
    assert report.ot_security["verified_independent_safety_interlock"] is True
    assert report.production_boundary["enterprise_cutover_authorized"] is False


def test_tampered_identity_domain_withholds_all_verified_security_values() -> None:
    payload = _payload()
    request, public_keys = _sign(payload)
    tampered = request.model_dump(mode="json")
    tampered["identity"]["sampled_successful_logins"] += 1

    report = EnterpriseSecurityService(source_public_keys=public_keys).evaluate(
        EnterpriseSecurityRequest(**tampered)
    )

    assert report.status == "reconciled_pending_source_attestation"
    assert next(gate for gate in report.gates if gate["gate_id"] == "source_signatures")[
        "passed"
    ] is False
    assert report.identity_and_access["verified_identity_provider"] is None
    assert report.ot_security["verified_independent_safety_interlock"] is None


@pytest.mark.parametrize(
    ("mutation", "gate_id"),
    [
        (lambda value: value["identity"].update(mfa_enforced=False), "mfa_and_identity_lifecycle"),
        (lambda value: value["authorization_and_tenant"].update(cross_tenant_rejected_count=49), "tenant_isolation"),
        (lambda value: value["messaging_and_timeseries"].update(acknowledged_message_count=9900), "durable_messaging"),
        (lambda value: value["messaging_and_timeseries"].update(timeseries_backup_export_verified=False), "timeseries_resilience"),
        (lambda value: value["high_availability"].update(automatic_failover_enabled=False), "ha_topology"),
        (lambda value: value["backup_and_dr"].update(restore_drill_passed=False), "restore_rpo_rto"),
        (lambda value: value["audit_and_siem"].update(external_worm_sink_enabled=False), "worm_audit_retention"),
        (lambda value: value["pki_and_keys"].update(mtls_dmz_ot_boundary=False), "mtls_and_key_rotation"),
        (lambda value: value["ot_security"].update(direct_internet_to_ot_blocked=False), "ot_segmentation_remote_access"),
        (lambda value: value["ot_security"].update(independent_safety_interlock_tested=False), "ot_safety_and_approvals"),
    ],
)
def test_enterprise_security_failures_close_named_gate(mutation, gate_id: str) -> None:
    payload = deepcopy(_payload())
    mutation(payload)
    request, public_keys = _sign(payload)

    report = EnterpriseSecurityService(source_public_keys=public_keys).evaluate(request)

    assert report.status == "blocked"
    assert next(gate for gate in report.gates if gate["gate_id"] == gate_id)["passed"] is False
    assert report.production_boundary["production_authority"] is False


def test_dashboard_api_exposes_fail_closed_enterprise_security_default() -> None:
    response = TestClient(create_app()).get("/api/dashboard/enterprise-security")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "blocked"
    assert payload["source_readiness"]["required_domain_count"] == 9
    assert len(payload["gates"]) == 20


def test_api_without_configured_keys_keeps_calculations_unverified() -> None:
    request, _ = _sign(_payload())
    response = TestClient(create_app()).post(
        "/api/dashboard/enterprise-security/evaluate",
        json=request.model_dump(mode="json"),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "reconciled_pending_source_attestation"
    assert payload["assurance"]["passed_gate_count"] == 19
    assert payload["identity_and_access"]["verified_identity_provider"] is None
