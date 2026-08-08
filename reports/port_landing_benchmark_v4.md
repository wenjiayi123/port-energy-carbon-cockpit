# Port landing robustness benchmark v4

Evidence label: `CAUSAL_OFFLINE_ROBUSTNESS_BENCHMARK_NOT_FIELD_KPI`

This report is public-data held-out scenario evidence, not a real-terminal KPI or production authorization.

## Protocol

- Dataset: `port_la_2020_2024_vessel_activity_hourly`
- Package SHA-256: `fbb3d1c34ccad61214119b600f09e8a6c37c13826fad6e4dde0c33cdc821758e`
- Test windows / steps: 48 / 1152
- Forecast: causal persistence; later held-out rows are unavailable to the decision
- Policy: six-step, eight-beam risk-aware MPC safety layer with a 12% reserve target

## Business metrics versus fixed full resources

| Metric | Result |
| --- | ---: |
| Energy reduction | 8.726% |
| Carbon reduction | 8.792% |
| Cost reduction | 8.094% |
| Peak reduction | 2.983% |
| Throughput change | -0.017% |
| Constraint-success rate | 100.000% |
| Carbon reduction 95% CI | [8.387%, 9.249%] |

## Algorithm increment versus causal legacy MPC

| Metric | Result |
| --- | ---: |
| Carbon reduction | -0.156% |
| Cost reduction | -0.191% |
| Peak reduction | -0.394% |
| Mean-delay reduction | 43.880% |
| P95 queue reduction | 47.858% |
| Action-variation reduction | 25.444% |
| Constraint-success rate | 100.000% |

The risk-aware layer trades a small amount of mean carbon/cost performance for
lower delay, queue tail and action variation. Negative entries are retained as
measured and must not be described as an across-the-board improvement.

## CVaR95 tail evidence

| Metric | Risk-aware MPC | Causal legacy MPC |
| --- | ---: | ---: |
| Carbon CVaR95 (kg) | 138142.802 | 138142.802 |
| Cost CVaR95 | 712577.387 | 710570.573 |
| Peak CVaR95 (kW) | 14249.905 | 14249.905 |

## Deterministic stress evidence versus causal legacy MPC

| Scenario | Windows | Risk zero violations | Legacy zero violations | Carbon reduction | Cost reduction | Reserve-breach reduction | Action-variation reduction |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| demand_surge_15pct | 12 | 100.000% | 100.000% | -0.188% | -0.202% | 0.000% | 25.170% |
| grid_derating_10pct | 12 | 100.000% | 100.000% | -0.119% | -0.152% | -7.692% | 26.191% |
| equipment_derating_15pct | 12 | 100.000% | 100.000% | -0.346% | -0.319% | 0.000% | 21.528% |

Negative reductions mean the risk-aware layer performed worse on that measure.
In particular, the grid-derating case increases soft reserve-breach steps by
7.692% even though both policies have zero modelled hard safety violations. This
adverse result is retained and blocks any claim of universal stress superiority.

## Reproduce

```bash
PYTHONPATH=backend backend/.venv/bin/python -m app.rl.landing_benchmark run
PYTHONPATH=backend backend/.venv/bin/python -m app.rl.landing_benchmark verify reports/port_landing_benchmark_v4.json
```
