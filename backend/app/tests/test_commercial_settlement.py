from __future__ import annotations

import base64
from copy import deepcopy

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
import pytest

from app.main import app
from app.schemas.commercial_settlement import SOURCE_DOMAINS, CommercialSettlementRequest
from app.services.commercial_settlement import (
    CommercialSettlementService,
    canonical_sha256,
    source_domain_payload,
)


HASH = "a" * 64
SIGNATURE_PLACEHOLDER = base64.b64encode(b"0" * 64).decode("ascii")


def _payload() -> dict:
    return {
        "schema_version": "commercial-settlement-input.v1",
        "case_id": "commercial-2026-01",
        "evaluated_at": "2026-02-02T10:30:00+08:00",
        "policy": {
            "policy_id": "commercial-policy-v1",
            "reporting_entity": "Port Example Ltd",
            "site_id": "terminal-a",
            "currency": "CNY",
            "settlement_period": {
                "period_id": "2026-01",
                "start_at": "2026-01-01T00:00:00+08:00",
                "end_at": "2026-02-01T00:00:00+08:00",
            },
            "expected_meter_intervals": 2,
            "minimum_measured_coverage_pct": 100.0,
            "maximum_energy_variance_pct": 0.1,
            "maximum_demand_variance_pct": 0.1,
            "maximum_amount_variance_pct": 0.1,
            "maximum_tenant_allocation_variance_pct": 0.1,
            "maximum_source_age_seconds": 86400,
            "maximum_source_alignment_seconds": 60,
            "annualization_factor": 12.0,
            "discount_rate": 0.06,
            "calculation_rule_sha256": "b" * 64,
            "approved_by": "commercial-policy-owner",
            "approval_record_sha256": "c" * 64,
        },
        "tariff": {
            "utility_id": "utility-a",
            "tariff_id": "tou-2026-a",
            "tariff_version": "2026.1",
            "effective_from": "2025-12-01T00:00:00+08:00",
            "effective_through": "2026-12-01T00:00:00+08:00",
            "currency": "CNY",
            "period_rates": [
                {"period_code": "peak", "energy_rate_per_kwh": 0.8},
                {"period_code": "offpeak", "energy_rate_per_kwh": 0.4},
            ],
            "demand_charge_per_kw": 2.0,
            "fixed_charge": 10.0,
            "tax_rate_pct": 10.0,
            "tariff_document_sha256": "d" * 64,
        },
        "meter_intervals": [
            {
                "interval_id": "meter-interval-1",
                "meter_id": "revenue-meter-1",
                "start_at": "2026-01-01T00:00:00+08:00",
                "end_at": "2026-01-16T00:00:00+08:00",
                "tariff_period": "peak",
                "energy_kwh": 100.0,
                "demand_kw": 50.0,
                "quality": "measured",
                "source_record_id": "meter-record-1",
                "source_payload_sha256": "e" * 64,
            },
            {
                "interval_id": "meter-interval-2",
                "meter_id": "revenue-meter-1",
                "start_at": "2026-01-16T00:00:00+08:00",
                "end_at": "2026-02-01T00:00:00+08:00",
                "tariff_period": "offpeak",
                "energy_kwh": 200.0,
                "demand_kw": 40.0,
                "quality": "measured",
                "source_record_id": "meter-record-2",
                "source_payload_sha256": "f" * 64,
            },
        ],
        "utility_invoice": {
            "invoice_id": "utility-invoice-2026-01",
            "revenue_meter_id": "revenue-meter-1",
            "billing_start_at": "2026-01-01T00:00:00+08:00",
            "billing_end_at": "2026-02-01T00:00:00+08:00",
            "currency": "CNY",
            "billed_energy_kwh": 300.0,
            "billed_peak_demand_kw": 50.0,
            "energy_charge": 160.0,
            "demand_charge": 100.0,
            "fixed_charge": 10.0,
            "tax_charge": 27.0,
            "total_amount": 297.0,
            "status": "paid",
            "invoice_sha256": "1" * 64,
            "payment_receipt_sha256": "2" * 64,
        },
        "demand_response_settlements": [
            {
                "event_id": "dr-event-1",
                "baseline_method": "approved-ten-of-ten-baseline",
                "baseline_approved": True,
                "committed_kw": 10.0,
                "metered_reduction_kw": 8.0,
                "event_hours": 1.0,
                "capacity_rate_per_kw": 2.0,
                "energy_rate_per_kwh": 1.0,
                "performance_factor": 1.0,
                "penalties": 3.0,
                "statement_amount": 25.0,
                "currency": "CNY",
                "status": "paid",
                "operator_statement_sha256": "3" * 64,
                "payment_receipt_sha256": "4" * 64,
            }
        ],
        "ancillary_service_settlements": [
            {
                "settlement_id": "as-settlement-1",
                "product": "frequency-response-test-product",
                "cleared_capacity_kw": 5.0,
                "service_hours": 2.0,
                "availability_rate_per_kw_hour": 2.0,
                "performance_score": 0.9,
                "penalties": 3.0,
                "statement_amount": 15.0,
                "currency": "CNY",
                "status": "paid",
                "operator_statement_sha256": "5" * 64,
                "payment_receipt_sha256": "6" * 64,
            }
        ],
        "ppa": {
            "contract_id": "ppa-2026-a",
            "supplier_id": "supplier-a",
            "delivery_energy_kwh": 100.0,
            "contract_rate_per_kwh": 0.3,
            "fixed_fee": 5.0,
            "invoice_amount": 35.0,
            "currency": "CNY",
            "status": "paid",
            "contract_sha256": "7" * 64,
            "delivery_statement_sha256": "8" * 64,
            "invoice_sha256": "9" * 64,
            "payment_receipt_sha256": "0" * 64,
        },
        "renewable_certificates": [
            {
                "certificate_id": "rec-2026-001",
                "serial_range": "REC-2026-000001:000300",
                "energy_mwh": 0.3,
                "vintage": 2026,
                "technology": "solar",
                "registry_account_id": "registry-account-a",
                "beneficiary": "Port Example Ltd",
                "retirement_period_id": "2026-01",
                "status": "retired",
                "acquisition_cost": 3.0,
                "currency": "CNY",
                "registry_record_sha256": "1" * 64,
                "retirement_receipt_sha256": "2" * 64,
            }
        ],
        "tenant_allocations": [
            {
                "tenant_id": "tenant-a",
                "meter_ids": ["tenant-meter-a"],
                "energy_kwh": 180.0,
                "coincident_demand_kw": 30.0,
                "energy_charge": 100.0,
                "demand_charge": 60.0,
                "fixed_tax_charge": 20.0,
                "ppa_charge": 18.0,
                "certificate_charge": 2.0,
                "allocated_total": 200.0,
                "invoice_id": "tenant-invoice-a",
                "invoice_status": "issued",
                "allocation_rule_sha256": "3" * 64,
                "tenant_invoice_sha256": "4" * 64,
            },
            {
                "tenant_id": "tenant-b",
                "meter_ids": ["tenant-meter-b"],
                "energy_kwh": 120.0,
                "coincident_demand_kw": 20.0,
                "energy_charge": 60.0,
                "demand_charge": 40.0,
                "fixed_tax_charge": 17.0,
                "ppa_charge": 17.0,
                "certificate_charge": 1.0,
                "allocated_total": 135.0,
                "invoice_id": "tenant-invoice-b",
                "invoice_status": "paid",
                "allocation_rule_sha256": "3" * 64,
                "tenant_invoice_sha256": "5" * 64,
            },
        ],
        "measurement_verification": {
            "project_id": "energy-project-a",
            "report_id": "mv-report-2026-01",
            "report_sha256": "6" * 64,
            "status": "independently_reviewed",
            "period_id": "2026-01",
            "verified_energy_savings_kwh": 30.0,
            "verified_carbon_reduction_tco2e": 3.0,
            "evidence_owner": "independent-mv-reviewer",
        },
        "investment_measures": [
            {
                "measure_id": "measure-peak-control",
                "savings_claim_id": "claim-peak-2026",
                "energy_savings_by_period_kwh": {"peak": 10.0},
                "annual_demand_savings_kw": 2.0,
                "verified_carbon_reduction_tco2e": 1.0,
                "capex": 300.0,
                "annual_om_delta": 4.0,
                "annual_settled_incentive": 10.0,
                "lifetime_years": 10,
                "currency": "CNY",
                "approved": True,
                "investment_approval_sha256": "7" * 64,
            },
            {
                "measure_id": "measure-offpeak-efficiency",
                "savings_claim_id": "claim-offpeak-2026",
                "energy_savings_by_period_kwh": {"offpeak": 20.0},
                "annual_demand_savings_kw": 1.0,
                "verified_carbon_reduction_tco2e": 2.0,
                "capex": 120.0,
                "annual_om_delta": 0.0,
                "annual_settled_incentive": 0.0,
                "lifetime_years": 8,
                "currency": "CNY",
                "approved": True,
                "investment_approval_sha256": "8" * 64,
            },
        ],
        "approvals": [
            {
                "approval_id": "approval-finance",
                "role": "finance",
                "approver_id": "finance-officer",
                "decision": "approved",
                "approved_at": "2026-02-02T09:00:00+08:00",
                "calculation_rule_sha256": "b" * 64,
                "approval_record_sha256": "9" * 64,
            },
            {
                "approval_id": "approval-energy",
                "role": "energy_manager",
                "approver_id": "energy-manager",
                "decision": "approved",
                "approved_at": "2026-02-02T09:15:00+08:00",
                "calculation_rule_sha256": "b" * 64,
                "approval_record_sha256": "0" * 64,
            },
        ],
        "source_attestations": [
            {
                "domain": domain,
                "source_system": f"{domain}-system",
                "source_record_ids": [f"{domain}-record"],
                "observed_at": "2026-02-02T10:00:00+08:00",
                "live_data_verified": True,
                "key_id": f"{domain}-key",
                "signed_payload_sha256": "0" * 64,
                "signature": SIGNATURE_PLACEHOLDER,
            }
            for domain in sorted(SOURCE_DOMAINS)
        ],
    }


def _service_and_keys() -> tuple[CommercialSettlementService, dict[str, Ed25519PrivateKey]]:
    private_keys = {domain: Ed25519PrivateKey.generate() for domain in SOURCE_DOMAINS}
    public_keys = {
        f"{domain}-key": base64.b64encode(
            key.public_key().public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw,
            )
        ).decode("ascii")
        for domain, key in private_keys.items()
    }
    return CommercialSettlementService(source_public_keys=public_keys), private_keys


def _signed_request(
    payload: dict,
    private_keys: dict[str, Ed25519PrivateKey],
) -> CommercialSettlementRequest:
    request = CommercialSettlementRequest(**deepcopy(payload))
    normalized = request.model_dump(mode="json")
    attestations = {item["domain"]: item for item in normalized["source_attestations"]}
    for domain in SOURCE_DOMAINS:
        digest = canonical_sha256(source_domain_payload(request, domain))
        attestations[domain]["signed_payload_sha256"] = digest
        attestations[domain]["signature"] = base64.b64encode(
            private_keys[domain].sign(bytes.fromhex(digest))
        ).decode("ascii")
    normalized["source_attestations"] = [attestations[domain] for domain in sorted(SOURCE_DOMAINS)]
    return CommercialSettlementRequest(**normalized)


def test_default_separates_scenario_value_from_verified_settlement() -> None:
    report = CommercialSettlementService(source_public_keys={}).build_default(
        scenario_cost_difference_cny=123.45,
        scenario_carbon_price_cny_per_ton=85.0,
    )

    assert report.status == "blocked"
    assert len(report.gates) == 16
    assert not any(gate["passed"] for gate in report.gates)
    assert report.source_readiness["domain_count"] == 0
    assert report.billing["scenario_cost_difference_cny"] == 123.45
    assert report.billing["verified_utility_invoice_total"] is None
    assert report.market_settlements["verified_demand_response_revenue"] is None
    assert report.investment_economics["verified_macc"] == []
    assert report.production_boundary["payment_instruction_allowed"] is False


def test_eight_signed_domains_close_all_sixteen_commercial_gates() -> None:
    service, private_keys = _service_and_keys()
    report = service.evaluate(_signed_request(_payload(), private_keys))

    assert report.status == "evidence_package_passed"
    assert all(gate["passed"] for gate in report.gates)
    assert report.source_readiness["domain_count"] == 8
    assert len(report.source_readiness["signed_domains"]) == 8
    assert report.billing["verified_utility_invoice_total"] == 297.0
    assert report.billing["verified_meter_energy_kwh"] == 300.0
    assert report.billing["verified_peak_demand_kw"] == 50.0
    assert report.market_settlements["verified_demand_response_revenue"] == 25.0
    assert report.market_settlements["verified_ancillary_service_revenue"] == 15.0
    assert report.market_settlements["verified_ppa_cost"] == 35.0
    assert report.renewable_procurement["verified_retired_certificate_mwh"] == 0.3
    assert report.tenant_allocation["verified_allocated_total"] == 335.0
    assert report.measurement_verification["verified_energy_savings_kwh"] == 30.0
    assert report.investment_economics["verified_portfolio_simple_payback_years"] is not None
    assert len(report.investment_economics["verified_macc"]) == 2
    assert report.production_boundary["payment_instruction_allowed"] is False
    assert report.production_boundary["tenant_invoice_issue_allowed"] is False


def test_tampering_one_source_invalidates_only_trust_release() -> None:
    service, private_keys = _service_and_keys()
    request = _signed_request(_payload(), private_keys)
    tampered = request.model_copy(
        update={
            "utility_invoice": request.utility_invoice.model_copy(
                update={"invoice_sha256": "f" * 64}
            )
        }
    )
    report = service.evaluate(tampered)

    assert report.status == "reconciled_pending_source_attestation"
    assert report.assurance["calculation_ready"] is True
    assert report.assurance["commercial_settlement_verified"] is False
    assert report.billing["calculated_invoice_total"] == 297.0
    assert report.billing["verified_utility_invoice_total"] is None
    gate = next(item for item in report.gates if item["gate_id"] == "source_signatures")
    assert gate["passed"] is False


@pytest.mark.parametrize(
    ("mutation", "gate_id"),
    [
        (lambda payload: payload["utility_invoice"].update(total_amount=310.0), "utility_invoice_reconciliation"),
        (lambda payload: payload["demand_response_settlements"][0].update(statement_amount=30.0), "demand_response_settlement"),
        (lambda payload: payload["ancillary_service_settlements"][0].update(status="pending"), "ancillary_service_settlement"),
        (lambda payload: payload["ppa"].update(invoice_amount=40.0), "ppa_settlement"),
        (lambda payload: payload["renewable_certificates"][0].update(status="active"), "renewable_certificate_registry"),
        (lambda payload: payload["tenant_allocations"][0].update(allocated_total=201.0), "tenant_allocation"),
        (lambda payload: payload["measurement_verification"].update(status="calculated_only"), "measurement_verification_link"),
        (lambda payload: payload["investment_measures"][1].update(savings_claim_id="claim-peak-2026"), "investment_approval"),
        (lambda payload: payload["investment_measures"][0].update(annual_om_delta=1000.0), "payback_and_macc"),
        (lambda payload: payload["approvals"][1].update(approver_id="finance-officer"), "dual_approval_audit"),
    ],
)
def test_business_reconciliation_failures_close_the_named_gate(mutation, gate_id: str) -> None:
    service, private_keys = _service_and_keys()
    payload = _payload()
    mutation(payload)
    report = service.evaluate(_signed_request(payload, private_keys))

    assert report.status == "blocked"
    gate = next(item for item in report.gates if item["gate_id"] == gate_id)
    assert gate["passed"] is False
    assert report.billing["verified_utility_invoice_total"] is None
    assert report.investment_economics["verified_macc"] == []


def test_dashboard_api_exposes_claim_safe_commercial_default() -> None:
    response = TestClient(app).get("/api/dashboard/commercial-settlement")
    payload = response.json()

    assert response.status_code == 200
    assert payload["schema_version"] == "commercial-settlement-assessment.v1"
    assert payload["status"] == "blocked"
    assert payload["source_readiness"]["domain_count"] == 0
    assert len(payload["gates"]) == 16
    assert payload["billing"]["verified_utility_invoice_total"] is None
    assert payload["production_boundary"]["accounting_posting_allowed"] is False
    assert len(payload["evidence_sha256"]) == 64


def test_api_with_unconfigured_keys_keeps_calculations_unverified() -> None:
    _, private_keys = _service_and_keys()
    request = _signed_request(_payload(), private_keys)
    response = TestClient(app).post(
        "/api/dashboard/commercial-settlement/evaluate",
        json=request.model_dump(mode="json"),
    )
    payload = response.json()

    assert response.status_code == 200
    assert payload["status"] == "reconciled_pending_source_attestation"
    assert payload["assurance"]["calculation_ready"] is True
    assert payload["assurance"]["commercial_settlement_verified"] is False
    assert payload["billing"]["calculated_invoice_total"] == 297.0
    assert payload["billing"]["verified_utility_invoice_total"] is None
