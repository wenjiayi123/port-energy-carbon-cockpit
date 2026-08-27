from __future__ import annotations

import base64
import hashlib
import json
from copy import deepcopy

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.carbon_assets import CarbonAssetComplianceRequest
from app.services.carbon_assets import CarbonAssetComplianceService


HASH = "a" * 64


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _payload() -> dict:
    return {
        "schema_version": "carbon-asset-compliance-input.v1",
        "case_id": "case-2025",
        "program": {
            "program_id": "program-a",
            "program_version": "2025.1",
            "jurisdiction": "site-approved-test-program",
            "compliance_period": {
                "start_at": "2025-01-01T00:00:00+08:00",
                "end_at": "2025-12-31T23:59:59+08:00",
                "surrender_deadline": "2026-03-31T23:59:59+08:00",
            },
            "surrender_ratio": 1.0,
            "eligible_vintages": [2025],
            "approved_by": "program-owner",
            "approval_record_sha256": HASH,
            "rules_document_sha256": "b" * 64,
        },
        "account": {
            "registry_id": "registry-a",
            "account_id": "account-001",
            "account_holder": "Port Example Ltd",
            "legal_entity_id": "lei-example-001",
            "status": "active",
            "ownership_evidence_sha256": "c" * 64,
            "approved_by": "registry-admin",
        },
        "verified_emissions": {
            "inventory_report_id": "inventory-2025",
            "reporting_entity": "Port Example Ltd",
            "period_start": "2025-01-01T00:00:00+08:00",
            "period_end": "2025-12-31T23:59:59+08:00",
            "verified_emissions_tco2e": 100.0,
            "assurance_conclusion": "accepted",
            "verifier_id": "independent-verifier",
            "verified_at": "2026-01-15T10:00:00+08:00",
            "report_sha256": "d" * 64,
        },
        "allowance_lots": [
            {
                "instrument_id": "instrument-2025-a",
                "serial_batch_id": "serial-batch-2025-a",
                "vintage": 2025,
                "quantity_tco2e": 20.0,
                "status": "active",
                "beneficial_owner": "Port Example Ltd",
                "registry_record_sha256": "e" * 64,
            }
        ],
        "trades": [
            {
                "transaction_id": "trade-buy-001",
                "side": "buy",
                "instrument_id": "instrument-2025-a",
                "quantity_tco2e": 20.0,
                "unit_price": 80.0,
                "currency": "CNY",
                "fees": 10.0,
                "venue": "approved-market-venue",
                "counterparty_id": "counterparty-001",
                "executed_at": "2025-12-20T10:00:00+08:00",
                "settled_at": "2025-12-22T10:00:00+08:00",
                "registry_transfer_id": "transfer-001",
                "status": "settled",
                "trade_confirmation_sha256": "f" * 64,
                "cash_settlement_sha256": "1" * 64,
            }
        ],
        "retirements": [
            {
                "retirement_id": "retirement-001",
                "quantity_tco2e": 100.0,
                "retired_at": "2026-02-10T10:00:00+08:00",
                "compliance_period_id": "case-2025",
                "registry_confirmation_sha256": "2" * 64,
                "status": "confirmed",
            }
        ],
        "reconciliation": {
            "reconciliation_id": "reconciliation-2025",
            "as_of": "2026-02-11T10:00:00+08:00",
            "opening_balance_tco2e": 100.0,
            "acquisitions_tco2e": 20.0,
            "disposals_tco2e": 0.0,
            "retirements_tco2e": 100.0,
            "registry_closing_balance_tco2e": 20.0,
            "internal_closing_balance_tco2e": 20.0,
            "registry_statement_sha256": "3" * 64,
            "status": "reconciled",
        },
        "approvals": [
            {
                "approval_id": "approval-compliance-001",
                "role": "compliance",
                "approver_id": "compliance-officer",
                "decision": "approved",
                "approved_at": "2026-02-01T10:00:00+08:00",
                "approval_record_sha256": "4" * 64,
            },
            {
                "approval_id": "approval-finance-001",
                "role": "finance",
                "approver_id": "finance-officer",
                "decision": "approved",
                "approved_at": "2026-02-02T10:00:00+08:00",
                "approval_record_sha256": "5" * 64,
            },
        ],
        "registry_attestation": {
            "attester_id": "registry-attester",
            "organization": "Registry Operator",
            "issued_at": "2026-02-12T10:00:00+08:00",
            "conclusion": "confirmed",
            "key_id": "registry-test-key",
            "signed_evidence_sha256": "0" * 64,
            "signature": base64.b64encode(b"0" * 64).decode("ascii"),
        },
    }


def _signed_request(
    payload: dict,
    private_key: Ed25519PrivateKey,
) -> CarbonAssetComplianceRequest:
    normalized = CarbonAssetComplianceRequest(**deepcopy(payload)).model_dump(mode="json")
    unsigned = deepcopy(normalized)
    attestation = unsigned["registry_attestation"]
    attestation.pop("signature", None)
    attestation.pop("signed_evidence_sha256", None)
    evidence_sha256 = _canonical_sha256(unsigned)
    normalized["registry_attestation"]["signed_evidence_sha256"] = evidence_sha256
    normalized["registry_attestation"]["signature"] = base64.b64encode(
        private_key.sign(bytes.fromhex(evidence_sha256))
    ).decode("ascii")
    return CarbonAssetComplianceRequest(**normalized)


def _service_and_private_key() -> tuple[CarbonAssetComplianceService, Ed25519PrivateKey]:
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    service = CarbonAssetComplianceService(
        registry_public_keys={
            "registry-test-key": base64.b64encode(public_key).decode("ascii")
        }
    )
    return service, private_key


def test_default_keeps_scenario_valuation_out_of_verified_positions() -> None:
    report = CarbonAssetComplianceService(registry_public_keys={}).build_default(
        scenario_emission_ton=118.39,
        scenario_quota_reference_ton=167.95,
        scenario_quota_gap_ton=-49.56,
        scenario_carbon_cost_cny=0.0,
        scenario_carbon_price_cny_per_ton=85.0,
    )

    assert report.status == "blocked"
    assert len(report.gates) == 12
    assert not any(gate["passed"] for gate in report.gates)
    assert report.positions["scenario_emission_ton"] == 118.39
    assert report.positions["verified_emissions_tco2e"] is None
    assert report.positions["verified_registry_balance_tco2e"] is None
    assert report.settlement["verified_net_cash_outflow_cny"] is None
    assert report.production_boundary["trade_execution_allowed"] is False
    assert report.production_boundary["regulatory_submission_allowed"] is False


def test_signed_registry_package_closes_compliance_and_cash_reconciliation() -> None:
    service, private_key = _service_and_private_key()
    report = service.evaluate(_signed_request(_payload(), private_key))

    assert report.status == "evidence_package_passed"
    assert all(gate["passed"] for gate in report.gates)
    assert report.positions["verified_emissions_tco2e"] == 100.0
    assert report.positions["verified_obligation_tco2e"] == 100.0
    assert report.positions["verified_retired_tco2e"] == 100.0
    assert report.positions["verified_registry_balance_tco2e"] == 20.0
    assert report.positions["verified_deficit_tco2e"] == 0.0
    assert report.settlement["verified_net_cash_outflow_cny"] == 1610.0
    assert report.assurance["financial_settlement_verified"] is True
    assert report.assurance["software_is_registry"] is False
    assert report.production_boundary["compliance_claim_allowed"] is True
    assert report.production_boundary["trade_execution_allowed"] is False
    assert len(report.ledger) == 3
    assert report.ledger[0]["previous_hash"] == "0" * 64
    assert report.ledger[1]["previous_hash"] == report.ledger[0]["entry_hash"]
    assert report.ledger[2]["previous_hash"] == report.ledger[1]["entry_hash"]


def test_registry_reconciliation_mismatch_fails_closed_with_valid_signature() -> None:
    service, private_key = _service_and_private_key()
    payload = _payload()
    payload["reconciliation"]["internal_closing_balance_tco2e"] = 19.0
    report = service.evaluate(_signed_request(payload, private_key))

    assert report.status == "blocked"
    gate = next(item for item in report.gates if item["gate_id"] == "registry_reconciliation")
    assert gate["passed"] is False
    assert report.positions["verified_registry_balance_tco2e"] is None
    assert report.settlement["verified_net_cash_outflow_cny"] is None
    assert report.production_boundary["compliance_claim_allowed"] is False


def test_tampered_package_invalidates_registry_signature() -> None:
    service, private_key = _service_and_private_key()
    request = _signed_request(_payload(), private_key)
    tampered = request.model_copy(
        update={
            "program": request.program.model_copy(
                update={"jurisdiction": "tampered-jurisdiction"}
            )
        }
    )
    report = service.evaluate(tampered)

    assert report.status == "reconciled_pending_registry_attestation"
    gate = next(item for item in report.gates if item["gate_id"] == "registry_attestation")
    assert gate["passed"] is False
    assert report.assurance["registry_attestation_accepted"] is False
    assert report.positions["verified_emissions_tco2e"] is None


def test_dashboard_api_exposes_claim_safe_default_carbon_asset_state() -> None:
    response = TestClient(app).get("/api/dashboard/carbon-assets")
    payload = response.json()

    assert response.status_code == 200
    assert payload["schema_version"] == "carbon-asset-compliance.v1"
    assert payload["status"] == "blocked"
    assert len(payload["gates"]) == 12
    assert payload["positions"]["verified_emissions_tco2e"] is None
    assert payload["positions"]["scenario_emission_ton"] > 0
    assert payload["production_boundary"]["trade_execution_allowed"] is False
    assert len(payload["evidence_sha256"]) == 64


def test_api_does_not_accept_unconfigured_registry_key() -> None:
    _, private_key = _service_and_private_key()
    request = _signed_request(_payload(), private_key)
    response = TestClient(app).post(
        "/api/dashboard/carbon-assets/evaluate",
        json=request.model_dump(mode="json"),
    )
    payload = response.json()

    assert response.status_code == 200
    assert payload["status"] == "reconciled_pending_registry_attestation"
    assert payload["assurance"]["calculation_ready"] is True
    assert payload["assurance"]["registry_attestation_accepted"] is False
    assert payload["positions"]["calculated_obligation_tco2e"] == 100.0
    assert payload["positions"]["verified_obligation_tco2e"] is None
    assert payload["settlement"]["verified_net_cash_outflow_cny"] is None
