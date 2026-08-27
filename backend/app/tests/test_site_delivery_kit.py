from __future__ import annotations

import importlib.util
from pathlib import Path
import shutil


ROOT = Path(__file__).resolve().parents[3]
VALIDATOR_PATH = ROOT / "scripts" / "validate_site_delivery_kit.py"
KIT_PATH = ROOT / "deployment" / "site_delivery"


def _validator_module():
    spec = importlib.util.spec_from_file_location("site_delivery_kit_validator", VALIDATOR_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_site_delivery_template_is_complete_but_not_site_ready() -> None:
    result = _validator_module().validate_kit(KIT_PATH)

    assert result["template_valid"] is True
    assert result["site_delivery_ready"] is False
    assert result["production_authority_granted"] is False
    assert result["status"] == "template_valid_site_inputs_required"
    assert result["counts"] == {
        "files": 11,
        "system_mappings": 13,
        "meter_device_points": 14,
        "network_records": 11,
        "raci_activities": 11,
        "shadow_work_packages": 12,
        "shadow_days": 180,
        "shadow_scenarios": 6,
        "domains": 13,
        "gates": 16,
        "approvals": 6,
    }
    assert result["errors"] == []
    assert result["placeholder_count"] > 0


def test_site_delivery_strict_mode_fails_closed_on_unsigned_templates() -> None:
    result = _validator_module().validate_kit(KIT_PATH, strict=True)

    assert result["template_valid"] is True
    assert result["site_delivery_ready"] is False
    assert result["production_authority_granted"] is False
    assert result["status"] == "blocked_site_inputs_or_acceptance_incomplete"
    assert any("site_owned_values_complete" in item for item in result["blockers"])
    assert any("six_party_approval" in item for item in result["blockers"])
    assert any(
        "signed_package_external_review_eligibility" in item
        for item in result["blockers"]
    )


def test_site_delivery_validator_rejects_application_write_path(tmp_path: Path) -> None:
    copied_kit = tmp_path / "site_delivery"
    shutil.copytree(KIT_PATH, copied_kit)
    mapping = copied_kit / "system_mapping.template.csv"
    mapping.write_text(
        mapping.read_text(encoding="utf-8").replace(
            "IT_DMZ,inbound,false,", "IT_DMZ,inbound,true,", 1
        ),
        encoding="utf-8",
    )

    result = _validator_module().validate_kit(copied_kit)

    assert result["template_valid"] is False
    assert result["site_delivery_ready"] is False
    assert any("live_adapter_coverage" in item for item in result["errors"])


def test_site_delivery_validator_rejects_ambiguous_raci(tmp_path: Path) -> None:
    copied_kit = tmp_path / "site_delivery"
    shutil.copytree(KIT_PATH, copied_kit)
    raci = copied_kit / "raci.template.csv"
    raci.write_text(
        raci.read_text(encoding="utf-8").replace(
            "RACI-001,冻结现场范围与目标发布,A,C,",
            "RACI-001,冻结现场范围与目标发布,A,A,",
            1,
        ),
        encoding="utf-8",
    )

    result = _validator_module().validate_kit(copied_kit)

    assert result["template_valid"] is False
    assert any("raci_single_accountable_owner" in item for item in result["errors"])
