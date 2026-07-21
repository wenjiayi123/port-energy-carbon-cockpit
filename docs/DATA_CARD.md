# Data card: Port of Los Angeles 2025 public benchmark

## Purpose

The default dataset supports reproducible offline comparison of four reinforcement-learning
algorithms and one constrained MPC baseline. It is not live terminal telemetry and must not be
used to infer a real vessel schedule or dispatch equipment.

## Sources and transformation

- Monthly container throughput: Port of Los Angeles 2025 historical TEU statistics.
- Grid emission factor: U.S. EPA eGRID 2023 CAMX total output rate.
- Monthly observations are expanded into deterministic hourly profiles for benchmark episodes.
- Prices, equipment capacity, delay costs, and safety limits are declared scenario assumptions.

The adjacent metadata JSON contains attribution, units, assumptions, factor quality, split dates,
and the intended-use restriction. The API returns CSV, metadata, and combined package hashes.

## Splits

- Training: January through September 2025.
- Test: October through December 2025.
- A period is forbidden from appearing in both splits.

## Quality gates

Validation rejects missing required columns, empty identity values, non-numeric or non-finite
measurements, negative values, overlapping splits, and invalid environment metadata. The quality
report also checks duplicates, missing cells, source links, units, and metadata completeness.

The drift report compares numeric train/test features using absolute standardized mean
differences. This is an offline split check, not live drift monitoring.

## Known limitations

There is no weather, AIS identity, TOS berth plan, meter telemetry, equipment availability,
yard occupancy, AGV battery state, time-varying electricity mix, supplier contract, or allowance
registry allocation. These fields remain unavailable in the UI.

## License boundary

Repository code uses the MIT License. Source data remains subject to publisher terms. Verify those
terms before redistributing a derived dataset or publishing benchmark artifacts.
