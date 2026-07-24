import pytest

from app.services.carbon_calculator import CarbonCalculator, EnergyUse


def test_calculate_grid_power_carbon() -> None:
    calculator = CarbonCalculator()
    assert calculator.calculate("grid_power", 100) == pytest.approx(19.504)


def test_carbon_intensity_handles_zero_teu() -> None:
    calculator = CarbonCalculator()
    assert calculator.carbon_intensity(1000, 0) == 0


def test_calculate_breakdown_groups_by_source_and_scope() -> None:
    calculator = CarbonCalculator()
    breakdown = calculator.calculate_breakdown(
        [
            EnergyUse(source="grid_power", amount=100, label="yard_crane", scope="equipment"),
            EnergyUse(source="diesel", amount=10, label="truck", scope="equipment"),
            EnergyUse(source="marine_fuel", amount=1, label="vessel", scope="vessel"),
        ]
    )

    assert breakdown.total_carbon_kg == pytest.approx(3160.304)
    assert breakdown.by_source["grid_power"] == pytest.approx(19.504)
    assert breakdown.by_scope["equipment"] == pytest.approx(46.304)


def test_shore_power_substitution_calculates_reduction() -> None:
    calculator = CarbonCalculator()
    result = calculator.shore_power_substitution(
        hoteling_power_kw=1000,
        duration_hours=4,
        shore_power_ratio=0.5,
        auxiliary_fuel_ton_per_hour=0.5,
    )

    assert result.shore_power_energy_kwh == 2000
    assert result.baseline_carbon_kg == pytest.approx(6228.0)
    assert result.actual_carbon_kg == pytest.approx(3504.08)
    assert result.reduction_kg == pytest.approx(2723.92)


def test_imo_intensity_uses_transport_work() -> None:
    calculator = CarbonCalculator()
    assert calculator.imo_transport_intensity(12000, 20000, 30) == pytest.approx(20.0)


def test_eexi_proxy_returns_grams_per_ton_nm() -> None:
    calculator = CarbonCalculator()
    value = calculator.eexi_proxy(
        engine_power_kw=5000,
        specific_fuel_consumption_g_per_kwh=170,
        fuel_carbon_factor_g_co2_per_g_fuel=3.114,
        capacity_ton=18000,
        reference_speed_kn=14,
    )
    assert value == pytest.approx(10.502, rel=0.001)


def test_negative_amount_is_rejected() -> None:
    calculator = CarbonCalculator()
    with pytest.raises(ValueError):
        calculator.calculate("diesel", -1)
