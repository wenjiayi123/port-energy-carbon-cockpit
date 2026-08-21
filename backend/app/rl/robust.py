from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from app.rl.environment import MPCPolicy, PortEnergyDispatchEnv


class CausalForecastPortEnv(PortEnergyDispatchEnv):
    """Port environment whose planning forecasts cannot read future test rows.

    The legacy environment remains unchanged so published evidence keeps its
    original hash. This additive wrapper uses a persistence forecast: at a
    decision timestamp, planning and observation features may use the current
    row, but never a later held-out row. Actual transitions still advance
    through the chronological dataset.
    """

    def __init__(
        self,
        *args: Any,
        demand_multiplier: float = 1.0,
        parameter_multipliers: dict[str, float] | None = None,
        **kwargs: Any,
    ) -> None:
        self._preview_origin_hour: int | None = None
        self.demand_multiplier = float(demand_multiplier)
        self.parameter_multipliers = dict(parameter_multipliers or {})
        super().__init__(*args, **kwargs)

    def _row_at(self, hour_offset: int):
        if self.temporal_mode != "sequential_rows":
            return super()._row_at(hour_offset)
        if self._preview_origin_hour is not None:
            index = min(len(self.frame) - 1, self._row_index + self._preview_origin_hour)
            return self.frame.iloc[index]
        if int(hour_offset) > 0:
            index = min(len(self.frame) - 1, self._row_index + self._hour)
            return self.frame.iloc[index]
        return super()._row_at(hour_offset)

    def _demand_teu(self) -> float:
        return super()._demand_teu() * self.demand_multiplier

    def _parameter(self, name: str) -> float:
        return super()._parameter(name) * float(self.parameter_multipliers.get(name, 1.0))

    def preview_transition(
        self,
        controls: dict[str, float],
        *,
        hour_offset: int = 0,
        queue_teu: float | None = None,
        battery_soc: float | None = None,
    ) -> dict[str, Any]:
        original_hour = self._hour
        original_queue = self._queue_teu
        original_soc = self._battery_soc
        original_maritime_hold = self._maritime_hold_teu
        original_customs_hold = self._customs_hold_teu
        original_recovery = self._released_recovery_teu
        try:
            self._preview_origin_hour = original_hour
            self._hour = original_hour + int(hour_offset)
            self._queue_teu = original_queue if queue_teu is None else float(queue_teu)
            self._battery_soc = original_soc if battery_soc is None else float(battery_soc)
            return self._calculate_transition(controls)
        finally:
            self._preview_origin_hour = None
            self._hour = original_hour
            self._queue_teu = original_queue
            self._battery_soc = original_soc
            self._maritime_hold_teu = original_maritime_hold
            self._customs_hold_teu = original_customs_hold
            self._released_recovery_teu = original_recovery


@dataclass(frozen=True)
class RiskConfiguration:
    reserve_margin_ratio: float = 0.12
    reserve_weight: float = 18.0
    queue_tail_weight: float = 0.35
    delay_tail_weight: float = 2.0
    action_slew_weight: float = 0.12
    soc_reserve_weight: float = 1.5
    projection_weight: float = 0.10


@dataclass(frozen=True)
class _BeamState:
    cost: float
    queue_teu: float
    battery_soc: float
    first_controls: dict[str, float]
    last_controls: dict[str, float]


class RiskAwareMPCPolicy(MPCPolicy):
    """Causal, risk-aware safety layer around the established MPC comparator.

    It does not replace the five published algorithms. It is a deployment
    qualification layer that penalizes low grid reserve, tail queues, delayed
    service, battery reserve depletion and abrupt control changes.
    """

    def __init__(
        self,
        horizon: int = 6,
        beam_width: int = 8,
        discount: float = 0.97,
        terminal_soc_weight: float = 3.0,
        risk: RiskConfiguration | None = None,
    ) -> None:
        super().__init__(
            horizon=horizon,
            beam_width=beam_width,
            discount=discount,
            terminal_soc_weight=terminal_soc_weight,
        )
        self.risk = risk or RiskConfiguration()
        self._last_controls = {
            "shore_power_ratio": 1.0,
            "crane_ratio": 1.0,
            "yard_ratio": 1.0,
            "battery_power_ratio": 0.0,
        }
        self.last_certificate: dict[str, Any] = {}

    @staticmethod
    def _action_distance(first: dict[str, float], second: dict[str, float]) -> float:
        return float(sum(abs(float(first[name]) - float(second[name])) for name in first))

    def _risk_cost(
        self,
        transition: dict[str, Any],
        controls: dict[str, float],
        previous_controls: dict[str, float],
        env: PortEnergyDispatchEnv,
    ) -> float:
        if float(transition["safety_violations"]):
            return 1_000_000.0
        reserve_shortfall = max(
            0.0,
            float(transition["peak_load_ratio"]) - (1.0 - self.risk.reserve_margin_ratio),
        )
        queue_ratio = float(transition["queue_teu"]) / max(
            1.0, float(transition["demand_teu"])
        )
        delay_ratio = float(transition["delay_minutes"]) / max(
            1.0, env._parameter("delay_limit_minutes")
        )
        soc_error = abs(
            float(transition["battery_soc"]) - env._parameter("battery_initial_soc")
        )
        battery_power = max(1.0, env._parameter("battery_power_kw"))
        projection_ratio = float(transition["battery_constraint_projection_kwh"]) / battery_power
        return (
            -float(transition["reward"])
            + self.risk.reserve_weight * reserve_shortfall**2
            + self.risk.queue_tail_weight * queue_ratio**2
            + self.risk.delay_tail_weight * max(0.0, delay_ratio - 0.75) ** 2
            + self.risk.action_slew_weight
            * self._action_distance(controls, previous_controls)
            + self.risk.soc_reserve_weight * soc_error**2
            + self.risk.projection_weight * projection_ratio
        )

    def predict(self, env: PortEnergyDispatchEnv) -> dict[str, float]:
        actions = self.candidates()
        target_soc = env._parameter("battery_initial_soc")

        def rank(item: _BeamState) -> float:
            return item.cost + self.terminal_soc_weight * abs(item.battery_soc - target_soc)

        beam: list[_BeamState] = []
        for controls in actions:
            transition = env.preview_transition(
                controls,
                queue_teu=env._queue_teu,
                battery_soc=env._battery_soc,
            )
            beam.append(
                _BeamState(
                    cost=self._risk_cost(transition, controls, self._last_controls, env),
                    queue_teu=float(transition["queue_teu"]),
                    battery_soc=float(transition["battery_soc"]),
                    first_controls=controls,
                    last_controls=controls,
                )
            )
        beam = sorted(beam, key=rank)[: self.beam_width]

        for hour_offset in range(1, self.horizon):
            expanded: list[_BeamState] = []
            for state in beam:
                for controls in actions:
                    transition = env.preview_transition(
                        controls,
                        hour_offset=hour_offset,
                        queue_teu=state.queue_teu,
                        battery_soc=state.battery_soc,
                    )
                    expanded.append(
                        _BeamState(
                            cost=state.cost
                            + self.discount**hour_offset
                            * self._risk_cost(transition, controls, state.last_controls, env),
                            queue_teu=float(transition["queue_teu"]),
                            battery_soc=float(transition["battery_soc"]),
                            first_controls=state.first_controls,
                            last_controls=controls,
                        )
                    )
            beam = sorted(expanded, key=rank)[: self.beam_width]

        selected = min(beam, key=rank).first_controls
        transition = env.preview_transition(selected)
        self.last_certificate = {
            "forecast_source": "causal_current-observation_persistence",
            "future_test_rows_accessed": False,
            "horizon": self.horizon,
            "beam_width": self.beam_width,
            "candidate_actions": len(actions),
            "reserve_margin_target_pct": self.risk.reserve_margin_ratio * 100.0,
            "predicted_peak_load_ratio": round(float(transition["peak_load_ratio"]), 6),
            "predicted_queue_teu": round(float(transition["queue_teu"]), 6),
            "predicted_safety_violations": int(transition["safety_violations"]),
        }
        self._last_controls = dict(selected)
        return dict(selected)


def paired_bootstrap_interval(
    candidate: list[float],
    reference: list[float],
    *,
    samples: int = 4_000,
    seed: int = 20260808,
) -> dict[str, float]:
    if len(candidate) != len(reference) or not candidate:
        raise ValueError("Paired bootstrap requires equal non-empty samples")
    candidate_array = np.asarray(candidate, dtype=np.float64)
    reference_array = np.asarray(reference, dtype=np.float64)
    rng = np.random.default_rng(seed)
    estimates = np.empty(samples, dtype=np.float64)
    for index in range(samples):
        selected = rng.integers(0, len(candidate_array), len(candidate_array))
        candidate_mean = float(candidate_array[selected].mean())
        reference_mean = float(reference_array[selected].mean())
        estimates[index] = (reference_mean - candidate_mean) / max(abs(reference_mean), 1e-9) * 100.0
    return {
        "estimate_pct": round(
            (float(reference_array.mean()) - float(candidate_array.mean()))
            / max(abs(float(reference_array.mean())), 1e-9)
            * 100.0,
            4,
        ),
        "ci95_low_pct": round(float(np.quantile(estimates, 0.025)), 4),
        "ci95_high_pct": round(float(np.quantile(estimates, 0.975)), 4),
        "bootstrap_samples": samples,
        "paired_windows": len(candidate),
    }


def cvar(values: list[float], alpha: float = 0.95) -> float:
    if not values:
        raise ValueError("CVaR requires at least one value")
    ordered = np.sort(np.asarray(values, dtype=np.float64))
    start = min(len(ordered) - 1, int(np.floor(alpha * len(ordered))))
    return round(float(ordered[start:].mean()), 6)
