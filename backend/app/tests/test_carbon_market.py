from app.services.carbon_market import CarbonMarketService


def test_market_settlement_prices_quota_gap_and_abatement_value() -> None:
    settlement = CarbonMarketService().settle(
        optimized_emission_ton=23.6,
        baseline_emission_ton=28.4,
        quota_ton=22.0,
        carbon_price_cny_per_ton=160.0,
        optimized_dispatch_cost_cny=174000.0,
        baseline_dispatch_cost_cny=186500.0,
    )

    assert settlement.quota_gap_ton == 1.6
    assert settlement.baseline_quota_gap_ton == 6.4
    assert settlement.carbon_cost_cny == 256.0
    assert settlement.baseline_carbon_cost_cny == 1024.0
    assert settlement.carbon_cost_saving_cny == 768.0
    assert settlement.abatement_ton == 4.8
    assert settlement.abatement_value_cny == 768.0
    assert settlement.total_cost_saving_cny == 13268.0
