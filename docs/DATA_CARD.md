# Data card: Port of Los Angeles public dispatch benchmarks

> v0.3.0 protocol erratum: the frozen v0.2.0 environment populated its
> three-hour forecast features and MPC look-ahead from later rows inside the
> evaluation window. Those reports are preserved as legacy perfect-forecast
> scenario evidence. All new training and the v4 landing benchmark use
> `causal_persistence_v1`, which cannot read a later held-out row at decision
> time. The frozen dataset metadata is not rewritten because doing so would
> invalidate its published package SHA-256.

## Intended use

This package supports reproducible offline comparison of four reinforcement-learning learners
and a constrained MPC controller. It is not terminal telemetry, a real vessel schedule, a
verified electricity bill or evidence of field savings.

## Public sources

- Port of Los Angeles 2020–2025 historical container statistics: 72 official monthly TEU
  anchors obtained from six annual Port pages.
- U.S. EIA California commercial monthly retail price: monthly price anchor.
- EIA Hourly Electric Grid Monitor LADWP workbook: reported hourly demand and consumed
  electricity carbon intensity.
- LADWP published commercial time-of-use periods: intraday price-period shape only.
- U.S. EPA eGRID CAMX: annual regional factor cross-check.

The downloader stores response and generated-package SHA-256 values. Source URLs, units,
transformation notes and physical assumptions are committed in the adjacent metadata.

## Construction and quality

The canonical dataset contains 52,608 continuous hours from 2020-01-01 through
2025-12-31, with no missing cells or duplicate timestamps. Of these, 51,726 EIA carbon
observations are reported values and 882 are month-hour median imputations carrying an explicit
quality code, yielding 98.32% raw source coverage.

Monthly TEU is allocated to hours with a fixed normalized profile. Intraday prices are formed
from disclosed base/low/high multipliers over LADWP commercial time periods and then rescaled
to each official EIA monthly mean. These transformations create model inputs; they do not turn
monthly throughput or a regional mean price into observed terminal-hour measurements.

## Splits and evaluation

- Train: 2020–2023, 35,064 hours.
- Validation: 2024, 8,784 hours.
- Test: 2025, 8,760 hours.
- Public benchmark: 48 deterministic uniformly spaced 24-hour windows per validation/test
  year, with the 1,152 test steps and start indices stored in the report.

Normalizers use train data only. Validation selects candidates. Test is reserved for the
final report. Any change in CSV, metadata, environment or report changes a bound SHA-256.

## Known limitations

The package has no terminal TOS berth plan, actual crane/yard telemetry, vessel identity,
contract tariff, meter-grade energy data, renewable procurement certificate, equipment
maintenance state or field-calibrated delay cost. Port throughput remains monthly resolution.
Storage, terminal capacity, equipment load and delay coefficients are declared scenario
parameters. EIA consumed intensity is a grid-region estimate, not a marginal-emissions signal.

Code is MIT-licensed; source data retains publisher attribution and terms.

## Vessel-activity enhanced package

`port_la_2020_2024_vessel_activity_hourly` joins the 2020–2024 portion of the
versioned hourly energy-carbon series with five official Port of Los Angeles
Wharfinger Division vessel-activity summaries.

- 43,848 contiguous hourly rows.
- 1,238 official business-day activity rows.
- Anchor, berth, departure, average berth dwell and average total port dwell.
- 67.7243% of local calendar days have a reported Port row; other days are
  explicitly linear interpolations and carry `port_activity_observed=0`.
- Train: 2020–2022, 26,304 hours.
- Validation: 2023, 8,760 hours.
- Test: 2024, 8,784 hours.
- Environment: `PortEnergyDispatchEnv-v2`, 25 observations, the same four
  continuous controls or 81 DQN combinations.

The adjacent metadata records the SHA-256 of every source PDF and the derived
source snapshot. Four malformed values in the official PDF text are corrected
through declared deterministic rules; each original value, corrected value and
reason is persisted.

This package is preferred for new RL experiments because the operational
information is daily rather than monthly. The original 52,608-hour package and
its benchmark remain the longer energy-carbon evidence baseline.

It still has no terminal TOS events, equipment telemetry, meter-grade terminal
energy, verified hourly TEU or field outcome. Repeated daily values are not
presented as hourly measurements.

## Real-port v3 contract

`PortEnergyDispatchEnv-v3` is the production connector contract. It adds ten
required weather, berth/equipment/grid availability, shore-compatibility and
onsite-renewable fields for a total of 35 observations. Missing fields or
adapters block production readiness. See
[`PORT_INTEGRATION_BLUEPRINT.md`](PORT_INTEGRATION_BLUEPRINT.md).
