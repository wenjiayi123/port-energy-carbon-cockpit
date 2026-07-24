class ShorePowerService:
    def estimate_reduction_kg(self, baseline_fuel_carbon_kg: float, shore_power_carbon_kg: float) -> float:
        return max(0.0, baseline_fuel_carbon_kg - shore_power_carbon_kg)

