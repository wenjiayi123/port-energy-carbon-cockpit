from typing import Annotated

from fastapi import APIRouter, Query

from app.schemas.algorithm_production import (
    AlgorithmProductionQualificationReport,
    AlgorithmProductionQualificationRequest,
)
from app.schemas.carbon_assets import (
    CarbonAssetComplianceReport,
    CarbonAssetComplianceRequest,
)
from app.schemas.commercial_settlement import (
    CommercialSettlementReport,
    CommercialSettlementRequest,
)
from app.schemas.dashboard import DashboardSnapshot, PortEmissionsInventory, TimeSeriesResponse
from app.schemas.energy_carbon_management import (
    EnergyCarbonManagementReport,
    EnergyCarbonManagementRequest,
)
from app.schemas.electrical_network import (
    ElectricalNetworkAssessmentReport,
    ElectricalNetworkAssessmentRequest,
)
from app.schemas.enterprise_security import (
    EnterpriseSecurityReport,
    EnterpriseSecurityRequest,
)
from app.schemas.measurement_verification import (
    MeasurementVerificationReport,
    MeasurementVerificationRequest,
)
from app.schemas.operations_energy_planning import (
    OperationsEnergyPlanningReport,
    OperationsEnergyPlanningRequest,
)
from app.schemas.port_collaboration import (
    PortCollaborationReport,
    PortCollaborationRequest,
)
from app.schemas.site_cutover import SiteCutoverReport, SiteCutoverRequest
from app.services.kpi_engine import KpiEngine
from app.services.algorithm_production import algorithm_production_qualification_service
from app.services.carbon_assets import carbon_asset_compliance_service
from app.services.commercial_settlement import commercial_settlement_service
from app.services.energy_carbon_management import energy_carbon_management_service
from app.services.electrical_network import electrical_network_assessment_service
from app.services.enterprise_security import enterprise_security_service
from app.services.measurement_verification import measurement_verification_service
from app.services.operations_energy_planning import operations_energy_planning_service
from app.services.port_collaboration import port_collaboration_service
from app.services.site_cutover import site_cutover_service

router = APIRouter(tags=["dashboard"])


@router.get("/snapshot", response_model=DashboardSnapshot)
def get_snapshot(
    green_preference: Annotated[float, Query(ge=0, le=1)] = 0.5,
    carbon_price_cny_per_ton: Annotated[float, Query(ge=0)] = 85.0,
) -> DashboardSnapshot:
    return KpiEngine().build_snapshot(
        green_preference=green_preference,
        carbon_price=carbon_price_cny_per_ton,
    )


@router.get("/timeseries", response_model=TimeSeriesResponse)
def get_timeseries(
    green_preference: Annotated[float, Query(ge=0, le=1)] = 0.5,
) -> TimeSeriesResponse:
    return KpiEngine().build_timeseries(green_preference=green_preference)


@router.get("/carbon-inventory", response_model=PortEmissionsInventory)
def get_carbon_inventory(
    green_preference: Annotated[float, Query(ge=0, le=1)] = 0.5,
) -> PortEmissionsInventory:
    """Return the source-complete inventory contract without fabricating missing values."""
    return KpiEngine().build_snapshot(green_preference=green_preference).carbon_inventory


@router.get("/measurement-verification", response_model=MeasurementVerificationReport)
def get_measurement_verification(
    green_preference: Annotated[float, Query(ge=0, le=1)] = 0.5,
) -> MeasurementVerificationReport:
    """Return the current claim-safe M&V state for the cockpit scenario."""
    return KpiEngine().build_snapshot(green_preference=green_preference).measurement_verification


@router.post(
    "/measurement-verification/evaluate",
    response_model=MeasurementVerificationReport,
)
def evaluate_measurement_verification(
    request: MeasurementVerificationRequest,
) -> MeasurementVerificationReport:
    """Evaluate a site-approved evidence package without certifying it."""
    return measurement_verification_service.evaluate(request)


@router.get("/carbon-assets", response_model=CarbonAssetComplianceReport)
def get_carbon_assets(
    green_preference: Annotated[float, Query(ge=0, le=1)] = 0.5,
    carbon_price_cny_per_ton: Annotated[float, Query(ge=0)] = 85.0,
) -> CarbonAssetComplianceReport:
    """Return scenario valuation separately from verified carbon-asset positions."""
    return (
        KpiEngine()
        .build_snapshot(
            green_preference=green_preference,
            carbon_price=carbon_price_cny_per_ton,
        )
        .carbon_assets
    )


@router.post(
    "/carbon-assets/evaluate",
    response_model=CarbonAssetComplianceReport,
)
def evaluate_carbon_assets(
    request: CarbonAssetComplianceRequest,
) -> CarbonAssetComplianceReport:
    """Reconcile signed registry evidence without executing a trade or filing."""
    return carbon_asset_compliance_service.evaluate(request)


@router.get("/commercial-settlement", response_model=CommercialSettlementReport)
def get_commercial_settlement(
    green_preference: Annotated[float, Query(ge=0, le=1)] = 0.5,
    carbon_price_cny_per_ton: Annotated[float, Query(ge=0)] = 85.0,
) -> CommercialSettlementReport:
    """Keep engineering value separate from signed bills and market settlements."""
    return (
        KpiEngine()
        .build_snapshot(
            green_preference=green_preference,
            carbon_price=carbon_price_cny_per_ton,
        )
        .commercial_settlement
    )


@router.post(
    "/commercial-settlement/evaluate",
    response_model=CommercialSettlementReport,
)
def evaluate_commercial_settlement(
    request: CommercialSettlementRequest,
) -> CommercialSettlementReport:
    """Reconcile signed commercial evidence without moving money or issuing invoices."""
    return commercial_settlement_service.evaluate(request)


@router.get("/port-collaboration", response_model=PortCollaborationReport)
def get_port_collaboration(
    green_preference: Annotated[float, Query(ge=0, le=1)] = 0.5,
) -> PortCollaborationReport:
    """Return the fail-closed ship-port collaboration readiness state."""
    return KpiEngine().build_snapshot(green_preference=green_preference).port_collaboration


@router.post(
    "/port-collaboration/evaluate",
    response_model=PortCollaborationReport,
)
def evaluate_port_collaboration(
    request: PortCollaborationRequest,
) -> PortCollaborationReport:
    """Reconcile signed ship-port evidence without issuing operational commands."""
    return port_collaboration_service.evaluate(request)


@router.get("/enterprise-security", response_model=EnterpriseSecurityReport)
def get_enterprise_security() -> EnterpriseSecurityReport:
    """Return repository controls separately from verified site security evidence."""
    return enterprise_security_service.build_default()


@router.post(
    "/enterprise-security/evaluate",
    response_model=EnterpriseSecurityReport,
)
def evaluate_enterprise_security(
    request: EnterpriseSecurityRequest,
) -> EnterpriseSecurityReport:
    """Evaluate signed enterprise and OT evidence without authorizing cutover."""
    return enterprise_security_service.evaluate(request)


@router.get("/site-cutover-readiness", response_model=SiteCutoverReport)
def get_site_cutover_readiness() -> SiteCutoverReport:
    """Return the unified fail-closed cutover state across all implementation domains."""
    return KpiEngine().build_snapshot(green_preference=0.5).site_cutover_readiness


@router.post(
    "/site-cutover-readiness/evaluate",
    response_model=SiteCutoverReport,
)
def evaluate_site_cutover_readiness(
    request: SiteCutoverRequest,
) -> SiteCutoverReport:
    """Evaluate a signed site package without granting software production authority."""
    return site_cutover_service.evaluate(request)


@router.get(
    "/energy-carbon-management",
    response_model=EnergyCarbonManagementReport,
)
def get_energy_carbon_management(
    green_preference: Annotated[float, Query(ge=0, le=1)] = 0.5,
) -> EnergyCarbonManagementReport:
    """Return the claim-safe management-system evidence readiness state."""
    return KpiEngine().build_snapshot(green_preference=green_preference).energy_carbon_management


@router.post(
    "/energy-carbon-management/evaluate",
    response_model=EnergyCarbonManagementReport,
)
def evaluate_energy_carbon_management(
    request: EnergyCarbonManagementRequest,
) -> EnergyCarbonManagementReport:
    """Evaluate a signed PDCA evidence cycle without issuing certification."""
    return energy_carbon_management_service.evaluate(request)


@router.get(
    "/operations-energy-plan",
    response_model=OperationsEnergyPlanningReport,
)
def get_operations_energy_plan() -> OperationsEnergyPlanningReport:
    """Return the fail-closed readiness state for joint operations-energy planning."""
    return operations_energy_planning_service.build_default()


@router.post(
    "/operations-energy-plan/evaluate",
    response_model=OperationsEnergyPlanningReport,
)
def evaluate_operations_energy_plan(
    request: OperationsEnergyPlanningRequest,
) -> OperationsEnergyPlanningReport:
    """Solve a signed site package as an advisory plan with no TOS writeback."""
    return operations_energy_planning_service.evaluate(request)


@router.get(
    "/electrical-network",
    response_model=ElectricalNetworkAssessmentReport,
)
def get_electrical_network() -> ElectricalNetworkAssessmentReport:
    """Return the fail-closed electrical-network evidence readiness state."""
    return electrical_network_assessment_service.build_default()


@router.post(
    "/electrical-network/evaluate",
    response_model=ElectricalNetworkAssessmentReport,
)
def evaluate_electrical_network(
    request: ElectricalNetworkAssessmentRequest,
) -> ElectricalNetworkAssessmentReport:
    """Assess a signed site network without issuing switch or protection commands."""
    return electrical_network_assessment_service.evaluate(request)


@router.get(
    "/algorithm-production",
    response_model=AlgorithmProductionQualificationReport,
)
def get_algorithm_production() -> AlgorithmProductionQualificationReport:
    """Return the fail-closed algorithm production-qualification state."""
    return algorithm_production_qualification_service.build_default()


@router.post(
    "/algorithm-production/evaluate",
    response_model=AlgorithmProductionQualificationReport,
)
def evaluate_algorithm_production(
    request: AlgorithmProductionQualificationRequest,
) -> AlgorithmProductionQualificationReport:
    """Evaluate signed shadow evidence without promoting or dispatching a policy."""
    return algorithm_production_qualification_service.evaluate(request)
