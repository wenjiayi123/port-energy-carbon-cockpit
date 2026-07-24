from dataclasses import dataclass, field
from typing import Literal


EnergySource = Literal["grid_power", "shore_power", "diesel", "marine_fuel"]


@dataclass(frozen=True)
class EmissionFactor:
    unit: str
    kg_co2e_per_unit: float


@dataclass(frozen=True)
class EnergyUse:
    source: EnergySource
    amount: float
    label: str
    scope: str = "operation"


@dataclass(frozen=True)
class CarbonLineItem:
    source: EnergySource
    label: str
    scope: str
    amount: float
    unit: str
    carbon_kg: float


@dataclass(frozen=True)
class CarbonBreakdown:
    total_carbon_kg: float
    line_items: list[CarbonLineItem] = field(default_factory=list)
    by_source: dict[str, float] = field(default_factory=dict)
    by_scope: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class ShorePowerResult:
    shore_power_ratio: float
    shore_power_energy_kwh: float
    baseline_fuel_amount: float
    remaining_fuel_amount: float
    baseline_carbon_kg: float
    actual_carbon_kg: float
    shore_power_carbon_kg: float
    remaining_fuel_carbon_kg: float
    reduction_kg: float


DEFAULT_FACTORS: dict[str, EmissionFactor] = {
    # Default public benchmark: EPA eGRID 2023 CAMX CO2e output rate,
    # 429.983 lb/MWh converted to kg/kWh. Port datasets can override it.
    "grid_power": EmissionFactor(unit="kWh", kg_co2e_per_unit=0.19504),
    "shore_power": EmissionFactor(unit="kWh", kg_co2e_per_unit=0.19504),
    "diesel": EmissionFactor(unit="liter", kg_co2e_per_unit=2.68),
    "marine_fuel": EmissionFactor(unit="ton", kg_co2e_per_unit=3114.0),
}


class CarbonCalculator:
    def __init__(self, factors: dict[str, EmissionFactor] | None = None) -> None:
        self.factors = factors or DEFAULT_FACTORS

    def calculate(self, source: str, amount: float) -> float:
        self._validate_amount(amount)
        if source not in self.factors:
            raise ValueError(f"Unsupported emission source: {source}")
        factor = self.factors[source]
        return amount * factor.kg_co2e_per_unit

    def calculate_entry(self, entry: EnergyUse) -> CarbonLineItem:
        factor = self.factors[entry.source]
        carbon_kg = self.calculate(entry.source, entry.amount)
        return CarbonLineItem(
            source=entry.source,
            label=entry.label,
            scope=entry.scope,
            amount=entry.amount,
            unit=factor.unit,
            carbon_kg=carbon_kg,
        )

    def calculate_breakdown(self, entries: list[EnergyUse]) -> CarbonBreakdown:
        line_items = [self.calculate_entry(entry) for entry in entries]
        by_source: dict[str, float] = {}
        by_scope: dict[str, float] = {}
        for item in line_items:
            by_source[item.source] = by_source.get(item.source, 0.0) + item.carbon_kg
            by_scope[item.scope] = by_scope.get(item.scope, 0.0) + item.carbon_kg
        return CarbonBreakdown(
            total_carbon_kg=sum(item.carbon_kg for item in line_items),
            line_items=line_items,
            by_source=by_source,
            by_scope=by_scope,
        )

    def vessel_voyage_emissions(self, fuel_ton: float, label: str = "vessel_voyage") -> CarbonLineItem:
        return self.calculate_entry(
            EnergyUse(source="marine_fuel", amount=fuel_ton, label=label, scope="vessel")
        )

    def berth_operation_emissions(
        self,
        hoteling_power_kw: float,
        duration_hours: float,
        source: EnergySource = "grid_power",
        label: str = "berth_hoteling",
    ) -> CarbonLineItem:
        self._validate_amount(hoteling_power_kw)
        self._validate_amount(duration_hours)
        return self.calculate_entry(
            EnergyUse(
                source=source,
                amount=hoteling_power_kw * duration_hours,
                label=label,
                scope="berth",
            )
        )

    def equipment_energy_emissions(
        self,
        electricity_kwh: float = 0.0,
        diesel_liter: float = 0.0,
        label: str = "terminal_equipment",
    ) -> CarbonBreakdown:
        entries: list[EnergyUse] = []
        if electricity_kwh:
            entries.append(
                EnergyUse(
                    source="grid_power",
                    amount=electricity_kwh,
                    label=f"{label}_electric",
                    scope="equipment",
                )
            )
        if diesel_liter:
            entries.append(
                EnergyUse(
                    source="diesel",
                    amount=diesel_liter,
                    label=f"{label}_diesel",
                    scope="equipment",
                )
            )
        return self.calculate_breakdown(entries)

    def shore_power_substitution(
        self,
        hoteling_power_kw: float,
        duration_hours: float,
        shore_power_ratio: float,
        auxiliary_fuel_ton_per_hour: float,
    ) -> ShorePowerResult:
        self._validate_amount(hoteling_power_kw)
        self._validate_amount(duration_hours)
        self._validate_amount(auxiliary_fuel_ton_per_hour)
        if not 0 <= shore_power_ratio <= 1:
            raise ValueError("shore_power_ratio must be between 0 and 1")

        shore_power_energy_kwh = hoteling_power_kw * duration_hours * shore_power_ratio
        baseline_fuel_amount = auxiliary_fuel_ton_per_hour * duration_hours
        remaining_fuel_amount = baseline_fuel_amount * (1 - shore_power_ratio)
        baseline_carbon_kg = self.calculate("marine_fuel", baseline_fuel_amount)
        shore_power_carbon_kg = self.calculate("shore_power", shore_power_energy_kwh)
        remaining_fuel_carbon_kg = self.calculate("marine_fuel", remaining_fuel_amount)
        actual_carbon_kg = shore_power_carbon_kg + remaining_fuel_carbon_kg
        return ShorePowerResult(
            shore_power_ratio=shore_power_ratio,
            shore_power_energy_kwh=shore_power_energy_kwh,
            baseline_fuel_amount=baseline_fuel_amount,
            remaining_fuel_amount=remaining_fuel_amount,
            baseline_carbon_kg=baseline_carbon_kg,
            actual_carbon_kg=actual_carbon_kg,
            shore_power_carbon_kg=shore_power_carbon_kg,
            remaining_fuel_carbon_kg=remaining_fuel_carbon_kg,
            reduction_kg=max(0.0, baseline_carbon_kg - actual_carbon_kg),
        )

    def carbon_intensity(self, total_carbon_kg: float, handled_teu: float) -> float:
        self._validate_amount(total_carbon_kg)
        if handled_teu <= 0:
            return 0.0
        return total_carbon_kg / handled_teu

    def kg_to_ton(self, value_kg: float) -> float:
        self._validate_amount(value_kg)
        return value_kg / 1000

    def ton_to_kg(self, value_ton: float) -> float:
        self._validate_amount(value_ton)
        return value_ton * 1000

    def imo_transport_intensity(
        self,
        total_carbon_kg: float,
        cargo_capacity_ton: float,
        distance_nm: float,
    ) -> float:
        """Simplified EEDI/EEXI-style intensity: gCO2 per ton nautical mile."""
        self._validate_amount(total_carbon_kg)
        self._validate_positive(cargo_capacity_ton, "cargo_capacity_ton")
        self._validate_positive(distance_nm, "distance_nm")
        return total_carbon_kg * 1000 / (cargo_capacity_ton * distance_nm)

    def eexi_proxy(
        self,
        engine_power_kw: float,
        specific_fuel_consumption_g_per_kwh: float,
        fuel_carbon_factor_g_co2_per_g_fuel: float,
        capacity_ton: float,
        reference_speed_kn: float,
    ) -> float:
        """Simplified EEXI proxy: engine emissions over transport work at reference speed."""
        self._validate_positive(engine_power_kw, "engine_power_kw")
        self._validate_positive(specific_fuel_consumption_g_per_kwh, "specific_fuel_consumption")
        self._validate_positive(fuel_carbon_factor_g_co2_per_g_fuel, "fuel_carbon_factor")
        self._validate_positive(capacity_ton, "capacity_ton")
        self._validate_positive(reference_speed_kn, "reference_speed_kn")
        hourly_emission_g = (
            engine_power_kw
            * specific_fuel_consumption_g_per_kwh
            * fuel_carbon_factor_g_co2_per_g_fuel
        )
        return hourly_emission_g / (capacity_ton * reference_speed_kn)

    def _validate_amount(self, amount: float) -> None:
        if amount < 0:
            raise ValueError("amount must be non-negative")

    def _validate_positive(self, amount: float, name: str) -> None:
        if amount <= 0:
            raise ValueError(f"{name} must be positive")
