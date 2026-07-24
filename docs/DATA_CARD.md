# Data card: Port of Los Angeles 2020–2025 hourly dispatch benchmark

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
