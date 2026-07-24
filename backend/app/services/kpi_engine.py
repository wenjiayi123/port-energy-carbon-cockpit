from app.schemas.dashboard import (
    CarbonModelSummary,
    CarbonMarket,
    DashboardSnapshot,
    KpiCard,
    OperationalAlert,
    StrategyComparison,
    TimeSeriesPoint,
    TimeSeriesResponse,
)
from app.services.carbon_market import CarbonMarketService
from app.services.carbon_calculator import CarbonCalculator
from app.services.dispatch_simulator import DispatchSimulator
from app.rl.dataset import PortDataset


class KpiEngine:
    def build_snapshot(self, green_preference: float, carbon_price: float = 85.0) -> DashboardSnapshot:
        simulation = DispatchSimulator().simulate(green_preference=green_preference)
        rows = simulation["strategies"]
        strategies = [StrategyComparison(**row) for row in rows]
        traditional, marl = strategies
        reduction = traditional.total_carbon_kg - marl.total_carbon_kg
        emission_ton = marl.total_carbon_kg / 1000
        baseline_emission_ton = traditional.total_carbon_kg / 1000
        # The public benchmark contains no regulated allowance allocation.
        # Use baseline emissions only as an explicitly labelled scenario
        # reference; it must be replaced by a verified registry/TOS adapter in
        # a regulated deployment.
        quota_ton = baseline_emission_ton
        carbon_market = CarbonMarketService().settle(
            optimized_emission_ton=emission_ton,
            baseline_emission_ton=baseline_emission_ton,
            quota_ton=quota_ton,
            carbon_price_cny_per_ton=carbon_price,
            quota_basis="scenario:baseline_emissions_reference",
            price_basis="scenario:user_input",
            optimized_dispatch_cost_cny=marl.total_cost_cny,
            baseline_dispatch_cost_cny=traditional.total_cost_cny,
        )
        dataset_id = str(simulation["rl_environment"]["dataset_id"])
        dataset_path = str(simulation["rl_environment"]["dataset_path"])
        dataset_sha256 = str(simulation["rl_environment"]["dataset_sha256"])
        try:
            dataset = PortDataset.load(dataset_path)
            data_quality = dataset.quality_report()
            data_drift = dataset.drift_report()
        except (FileNotFoundError, ValueError) as exc:
            dataset = None
            data_quality = {
                "status": "unavailable",
                "score": 0,
                "grade": "D",
                "warnings": [f"dataset_evidence_unavailable:{exc}"],
                "evidence_hash": dataset_sha256,
            }
            data_drift = {
                "status": "unavailable",
                "note": "The selected dataset package could not be resolved by this process.",
            }
        carbon_model = self._build_carbon_model(
            marl,
            traditional,
            dataset_id,
            dataset_sha256,
            dataset,
        )
        timeseries = self._timeseries_from_strategies(traditional, marl)
        alerts = self._build_alerts(marl, carbon_model, data_quality, data_drift)
        policy_status = str(simulation["rl_environment"]["status"])

        return DashboardSnapshot(
            scenario_id="port_la_2025_public_benchmark",
            green_preference=green_preference,
            kpis=[
                KpiCard(
                    key="carbon",
                    label="测试轨迹碳排放",
                    value=marl.total_carbon_kg,
                    unit="kgCO2e",
                    delta=-reduction,
                ),
                KpiCard(
                    key="intensity",
                    label="单箱碳强度",
                    value=marl.carbon_intensity_kg_per_teu,
                    unit="kg/TEU",
                    delta=marl.carbon_intensity_kg_per_teu - traditional.carbon_intensity_kg_per_teu,
                ),
                KpiCard(
                    key="shore_power",
                    label="岸电使用率",
                    value=marl.shore_power_usage_rate,
                    unit="%",
                    delta=marl.shore_power_usage_rate - traditional.shore_power_usage_rate,
                ),
                KpiCard(
                    key="cost",
                    label="综合调度成本",
                    value=marl.total_cost_cny,
                    unit="CNY",
                    delta=marl.total_cost_cny - traditional.total_cost_cny,
                ),
            ],
            strategies=strategies,
            carbon_market=CarbonMarket(**carbon_market.__dict__),
            carbon_model=carbon_model,
            timeseries=timeseries,
            rl_environment=simulation["rl_environment"],
            data_quality=data_quality,
            data_drift=data_drift,
            alerts=alerts,
            governance={
                "deployment_mode": "offline_benchmark",
                "production_dispatch_enabled": False,
                "human_approval_required": True,
                "policy_stage": "validated_offline" if policy_status == "trained_policy_test_evidence" else "control_benchmark",
                "policy_evidence": policy_status,
                "dataset_package_sha256": data_quality.get("evidence_hash", dataset_sha256),
                "live_port_adapters": {
                    "tos": "not_connected",
                    "metering": "not_connected",
                    "equipment_telemetry": "not_connected",
                    "allowance_registry": "not_connected",
                },
            },
        )

    def build_timeseries(self, green_preference: float) -> TimeSeriesResponse:
        rows = [StrategyComparison(**row) for row in DispatchSimulator().simulate(green_preference)["strategies"]]
        return TimeSeriesResponse(
            scenario_id="port_la_2025_public_benchmark",
            points=self._timeseries_from_strategies(rows[0], rows[1]),
        )

    def _timeseries_from_strategies(self, baseline: StrategyComparison, optimized: StrategyComparison) -> list[TimeSeriesPoint]:
        return [
            TimeSeriesPoint(
                time=optimized_point.time,
                traditional_carbon_kg=baseline_point.carbon_kg,
                marl_carbon_kg=optimized_point.carbon_kg,
                traditional_energy_kwh=baseline_point.energy_kwh,
                marl_energy_kwh=optimized_point.energy_kwh,
            )
            for baseline_point, optimized_point in zip(baseline.trajectory, optimized.trajectory, strict=False)
        ]

    def _build_carbon_model(
        self,
        optimized: StrategyComparison,
        baseline: StrategyComparison,
        dataset_id: str,
        dataset_sha256: str,
        dataset: PortDataset | None = None,
    ) -> CarbonModelSummary:
        calculator = CarbonCalculator()
        if dataset is not None:
            data_source = str(dataset.metadata.get("name") or dataset.metadata.get("title") or dataset.dataset_id)
            factor_quality = dataset.metadata.get("carbon_factor_quality") or {}
        else:
            data_source = dataset_id
            factor_quality = {}
        total_carbon = optimized.total_carbon_kg
        handled_teu = total_carbon / max(optimized.carbon_intensity_kg_per_teu, 1e-9)
        trajectory_grid = sum(point.grid_carbon_kg for point in optimized.trajectory)
        trajectory_fuel = sum(point.fuel_carbon_kg for point in optimized.trajectory)
        trajectory_total = max(trajectory_grid + trajectory_fuel, 1e-9)
        source_breakdown = {
            "grid_power_egrid_camx": round(total_carbon * trajectory_grid / trajectory_total, 3),
            "auxiliary_fuel": round(total_carbon * trajectory_fuel / trajectory_total, 3),
        }
        reduction = max(0.0, baseline.total_carbon_kg - optimized.total_carbon_kg)
        factor_quality = {
            "method": "location_based",
            "market_based_factor": None,
            "assurance_status": "unassured_benchmark",
            **factor_quality,
        }
        uncertainty_note = str(
            factor_quality.get("uncertainty")
            or "Factor uncertainty is not quantified for this dataset package."
        )
        return CarbonModelSummary(
            model_version="dataset-carbon-accounting-v1.1",
            total_carbon_kg=total_carbon,
            total_carbon_ton=calculator.kg_to_ton(total_carbon),
            handled_teu=handled_teu,
            carbon_intensity_kg_per_teu=optimized.carbon_intensity_kg_per_teu,
            shore_power_reduction_kg=reduction,
            source_breakdown_kg=source_breakdown,
            scope_breakdown_kg={
                "scope_1_auxiliary_fuel": source_breakdown["auxiliary_fuel"],
                "scope_2_location_based_electricity": source_breakdown["grid_power_egrid_camx"],
            },
            scope1_auxiliary_fuel_kg=source_breakdown["auxiliary_fuel"],
            scope2_location_based_kg=source_breakdown["grid_power_egrid_camx"],
            scope2_market_based_kg=None,
            scope2_method="location_based",
            market_based_status="unavailable_no_supplier_or_contractual_instrument_data",
            factor_quality=factor_quality,
            uncertainty_note=uncertainty_note,
            assurance_status=str(factor_quality.get("assurance_status") or "unassured_benchmark"),
            data_source=data_source,
            dataset_sha256=dataset_sha256,
            calculation_method="Held-out environment transition accounting with explicit Scope 1 and location-based Scope 2 mapping",
        )

    @staticmethod
    def _build_alerts(
        optimized: StrategyComparison,
        carbon_model: CarbonModelSummary,
        data_quality: dict[str, object],
        data_drift: dict[str, object],
    ) -> list[OperationalAlert]:
        alerts: list[OperationalAlert] = []
        peak_violations = [point.peak_violation_kw for point in optimized.trajectory if point.peak_violation_kw > 0]
        delay_violations = [point.delay_minutes for point in optimized.trajectory if point.delay_minutes > 120]
        if peak_violations:
            alerts.append(OperationalAlert(
                code="GRID_CAPACITY_EXCEEDED",
                severity="critical",
                title_zh="电网容量约束超限",
                title_en="Grid capacity constraint exceeded",
                detail_zh=f"测试轨迹有 {len(peak_violations)} 个时间步超限。",
                detail_en=f"{len(peak_violations)} held-out steps exceeded the grid limit.",
                source="held_out_trajectory",
                value=round(max(peak_violations), 3),
                threshold=0.0,
            ))
        if delay_violations:
            alerts.append(OperationalAlert(
                code="DELAY_GUARDRAIL_EXCEEDED",
                severity="warning",
                title_zh="延误护栏超限",
                title_en="Delay guardrail exceeded",
                detail_zh=f"测试轨迹有 {len(delay_violations)} 个时间步超过 120 分钟。",
                detail_en=f"{len(delay_violations)} held-out steps exceeded 120 minutes.",
                source="held_out_trajectory",
                value=round(max(delay_violations), 3),
                threshold=120.0,
            ))
        if str(data_quality.get("status")) != "pass":
            alerts.append(OperationalAlert(
                code="DATA_QUALITY_REVIEW",
                severity="warning",
                title_zh="数据质量需要复核",
                title_en="Dataset quality review required",
                detail_zh=f"当前数据质量评分 {data_quality.get('score', 0)}/100。",
                detail_en=f"Current dataset quality score is {data_quality.get('score', 0)}/100.",
                source="dataset_quality_gate",
                value=float(data_quality.get("score") or 0),
                threshold=75.0,
            ))
        if str(data_drift.get("status")) in {"review", "high_shift", "unavailable"}:
            alerts.append(OperationalAlert(
                code="DATA_SHIFT_REVIEW",
                severity="warning" if data_drift.get("status") == "high_shift" else "info",
                title_zh="训练与测试分布偏移",
                title_en="Train-test distribution shift",
                detail_zh=f"离线分布检查状态：{data_drift.get('status')}。",
                detail_en=f"Offline distribution check status: {data_drift.get('status')}.",
                source="dataset_drift_gate",
                value=float(data_drift.get("max_shift") or 0),
                threshold=float(data_drift.get("warning_threshold") or 0.5),
            ))
        if carbon_model.scope2_market_based_kg is None:
            alerts.append(OperationalAlert(
                code="SCOPE2_MARKET_BASED_UNAVAILABLE",
                severity="info",
                title_zh="范围二市场法数据未接入",
                title_en="Scope 2 market-based data unavailable",
                detail_zh="当前只报告基于 eGRID 的所在地法结果，未接入供应商或合同凭证。",
                detail_en="Only the eGRID location-based result is reported; supplier and contractual instruments are not connected.",
                source="carbon_accounting_gate",
            ))
        alerts.append(OperationalAlert(
            code="PRODUCTION_ADAPTERS_NOT_CONNECTED",
            severity="info",
            title_zh="生产港口适配器未接入",
            title_en="Production port adapters not connected",
            detail_zh="TOS、计量、设备遥测和配额登记簿均处于未接入状态。",
            detail_en="TOS, metering, equipment telemetry, and allowance registry adapters are not connected.",
            source="deployment_governance",
        ))
        return alerts
