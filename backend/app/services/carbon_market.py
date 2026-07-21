from dataclasses import dataclass


@dataclass(frozen=True)
class CarbonMarketSettlement:
    carbon_price_cny_per_ton: float
    quota_ton: float
    emission_ton: float
    baseline_emission_ton: float
    quota_gap_ton: float
    baseline_quota_gap_ton: float
    carbon_cost_cny: float
    baseline_carbon_cost_cny: float
    carbon_cost_saving_cny: float
    abatement_ton: float
    abatement_value_cny: float
    quota_utilization_rate: float
    baseline_quota_utilization_rate: float
    optimized_total_cost_cny: float
    baseline_total_cost_cny: float
    total_cost_saving_cny: float
    optimization_advice: str
    quota_basis: str
    price_basis: str


class CarbonMarketService:
    def cost(self, emission_ton: float, quota_ton: float, carbon_price_cny_per_ton: float) -> float:
        return round(max(0.0, emission_ton - quota_ton) * carbon_price_cny_per_ton, 2)

    def settle(
        self,
        *,
        optimized_emission_ton: float,
        baseline_emission_ton: float,
        quota_ton: float,
        carbon_price_cny_per_ton: float,
        optimized_dispatch_cost_cny: float,
        baseline_dispatch_cost_cny: float,
        quota_basis: str = "caller_supplied",
        price_basis: str = "caller_supplied",
    ) -> CarbonMarketSettlement:
        quota_gap = optimized_emission_ton - quota_ton
        baseline_quota_gap = baseline_emission_ton - quota_ton
        carbon_cost = self.cost(optimized_emission_ton, quota_ton, carbon_price_cny_per_ton)
        baseline_carbon_cost = self.cost(
            baseline_emission_ton,
            quota_ton,
            carbon_price_cny_per_ton,
        )
        abatement_ton = max(0.0, baseline_emission_ton - optimized_emission_ton)
        abatement_value = abatement_ton * carbon_price_cny_per_ton
        optimized_total_cost = optimized_dispatch_cost_cny + carbon_cost
        baseline_total_cost = baseline_dispatch_cost_cny + baseline_carbon_cost
        total_cost_saving = baseline_total_cost - optimized_total_cost

        return CarbonMarketSettlement(
            carbon_price_cny_per_ton=carbon_price_cny_per_ton,
            quota_ton=round(quota_ton, 2),
            emission_ton=round(optimized_emission_ton, 2),
            baseline_emission_ton=round(baseline_emission_ton, 2),
            quota_gap_ton=round(quota_gap, 2),
            baseline_quota_gap_ton=round(baseline_quota_gap, 2),
            carbon_cost_cny=round(carbon_cost, 2),
            baseline_carbon_cost_cny=round(baseline_carbon_cost, 2),
            carbon_cost_saving_cny=round(baseline_carbon_cost - carbon_cost, 2),
            abatement_ton=round(abatement_ton, 2),
            abatement_value_cny=round(abatement_value, 2),
            quota_utilization_rate=round(optimized_emission_ton / quota_ton * 100, 1),
            baseline_quota_utilization_rate=round(baseline_emission_ton / quota_ton * 100, 1),
            optimized_total_cost_cny=round(optimized_total_cost, 2),
            baseline_total_cost_cny=round(baseline_total_cost, 2),
            total_cost_saving_cny=round(total_cost_saving, 2),
            optimization_advice=self._advice(quota_gap, total_cost_saving, carbon_price_cny_per_ton),
            quota_basis=quota_basis,
            price_basis=price_basis,
        )

    def _advice(
        self,
        quota_gap_ton: float,
        total_cost_saving_cny: float,
        carbon_price_cny_per_ton: float,
    ) -> str:
        if quota_gap_ton <= 0:
            return "配额内运行，可保留剩余配额或进入交易。"
        if total_cost_saving_cny > 0 and carbon_price_cny_per_ton >= 120:
            return "高碳价下低碳调度仍保持总成本优势。"
        if total_cost_saving_cny > 0:
            return "低碳调度抵消超额碳成本，建议保持当前权重。"
        return "碳价压力偏高，建议继续提高岸电与低碳作业权重。"
