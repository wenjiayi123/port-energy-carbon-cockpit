import pytest

from app.services.carbon_calculator import CarbonCalculator, EnergyUse
from app.services.port_emissions_inventory import PortEmissionsInventoryService


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


def test_port_inventory_covers_all_required_sources_without_fabricating_missing_values() -> None:
    inventory = PortEmissionsInventoryService().build(
        grid_carbon_kg=1200.0,
        auxiliary_fuel_carbon_kg=300.0,
        dataset_id="test_port_dataset",
        dataset_sha256="a" * 64,
        dataset_metadata={
            "version": "test.1",
            "source_urls": ["https://www.eia.gov/electricity/gridmonitor/about/"],
            "environment_parameters": {"fuel_carbon_kg_per_liter": 2.68},
        },
        trajectory_steps=24,
    )

    sources = {item.source_id: item for item in inventory.source_categories}
    assert set(sources) == {
        "ocean_going_vessels_at_berth",
        "harbor_craft",
        "cargo_handling_equipment",
        "heavy_duty_vehicles",
        "rail_locomotives",
        "purchased_electricity",
        "stationary_combustion",
    }
    assert sources["purchased_electricity"].co2e_kg == pytest.approx(1200.0)
    assert sources["ocean_going_vessels_at_berth"].co2e_kg == pytest.approx(300.0)
    assert sources["harbor_craft"].co2e_kg is None
    assert all(value is None for value in sources["harbor_craft"].pollutants_kg.values())
    assert inventory.totals["port_related_activity_co2e_kg"] == pytest.approx(1500.0)
    assert inventory.totals["scope_1_kg"] is None
    assert inventory.coverage["co2e_calculated_count"] == 2
    assert inventory.coverage["source_category_count"] == 7
    assert inventory.coverage["inventory_complete"] is False
    assert inventory.assurance["status"] == "blocked"
    assert inventory.production_boundary["regulatory_submission_allowed"] is False
    assert len(inventory.evidence_sha256) == 64
