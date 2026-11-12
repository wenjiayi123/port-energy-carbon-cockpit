"""Traceable offline trial facts; no runtime telemetry is substituted for a trial.

The service percentage is window throughput completion, not an SLA, vessel
punctuality, equipment availability or a measured production-port service rate.
"""

from datetime import datetime, timedelta, timezone
import math

from app.services.agent_comparisons import digest


def finite(value):
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def project_trial(raw, dataset):
    result = {
        "schema": "expert-energy-trial.v1",
        "status": "needs_evidence",
        "issues": [],
        "dataset_sha256": None,
        "site_id": None,
        "window_id": None,
        "scenario_id": raw.get("scenario_id"),
        "carbon_kg": None,
        "cost_cny": None,
        "service_pct": None,
        "units": {"carbon_kg": "kgCO2e", "cost_cny": "CNY", "service_pct": "%"},
        "scope": "public-data calibrated offline simulation; not live port operations",
        "production_authority": False,
        "service_definition": "cumulative processed TEU / arriving TEU in one zero-initial-queue trial window",
        "service_not_equivalent_to": [
            "on-time SLA",
            "vessel service availability",
            "live runtime fulfillment",
        ],
        "raw_snapshot_sha256": digest(raw),
    }
    issues = result["issues"]
    environment = raw.get("rl_environment", {})
    if environment.get("dataset_sha256") != dataset.package_sha256:
        issues.append("dataset_content_hash_mismatch")
        return result
    result["dataset_sha256"] = dataset.package_sha256
    result["dataset_id"] = environment.get("dataset_id")
    # Explicit, scoped mapping, not a guess based on a runtime API's site label.
    if (
        environment.get("dataset_id") == "port_la_2020_2025_hourly"
        and dataset.metadata.get("id") == environment["dataset_id"]
    ):
        result["site_id"] = "USLAX-PUBLIC-OFFLINE-BENCHMARK"
        result["site_mapping_basis"] = (
            "registered dataset id and metadata attribution to Port of Los Angeles"
        )
    else:
        issues.append("unregistered_dataset_site_mapping")
    strategies = raw.get("strategies", [])
    if len(strategies) != 2:
        issues.append("expected_reference_and_selected_strategy")
        return result
    selected = strategies[1]
    result["policy"] = selected.get("strategy")
    for target, key in [("carbon_kg", "total_carbon_kg"), ("cost_cny", "total_cost_cny")]:
        value = selected.get(key)
        if finite(value) and value >= 0:
            result[target] = value
        else:
            issues.append("missing_or_invalid:" + key)
    result["cost_definition"] = (
        "selected strategy total_cost_cny; excludes separate carbon allowance scenario settlement"
    )
    points = selected.get("trajectory", [])
    ids = [point.get("source_id") for point in points]
    if not points or any(not isinstance(s, str) or not s for s in ids) or len(set(ids)) != len(ids):
        issues.append("missing_or_repeated_trial_source_rows")
        return result
    if [point.get("step") for point in points] != list(range(1, len(points) + 1)):
        issues.append("trial_step_sequence_not_single_episode")
        return result
    if environment.get("episode_steps") != len(points):
        issues.append("trial_length_disagrees_with_environment")
        return result
    metadata = dataset.metadata
    time_column = metadata.get("time_column")
    if (
        metadata.get("temporal_mode") != "sequential_rows"
        or time_column not in dataset.frame.columns
    ):
        issues.append("trial_clock_not_explicit_sequential_rows")
        return result
    frame = dataset.frame[dataset.frame["source_id"].isin(ids)]
    if frame["source_id"].duplicated().any() or len(frame) != len(ids):
        issues.append("trial_rows_not_uniquely_resolved_in_dataset")
        return result
    rows = frame.set_index("source_id").loc[ids]
    try:
        stamps = [datetime.fromisoformat(str(v).replace("Z", "+00:00")) for v in rows[time_column]]
        if any(stamp.tzinfo is None for stamp in stamps):
            raise ValueError("missing timezone")
        stamps = [stamp.astimezone(timezone.utc) for stamp in stamps]
        if any(b - a != timedelta(hours=1) for a, b in zip(stamps, stamps[1:])):
            raise ValueError("noncontiguous hour rows")
    except (ValueError, TypeError):
        issues.append("invalid_or_noncontiguous_trial_clock")
        return result
    if any(
        point.get("period") != str(row["period"])
        for point, (_, row) in zip(points, rows.iterrows())
    ):
        issues.append("trajectory_period_disagrees_with_source_row")
        return result
    window = {
        "start_inclusive": stamps[0].isoformat(),
        "end_exclusive": (stamps[-1] + timedelta(hours=1)).isoformat(),
        "timezone": "UTC",
        "step_hours": 1,
        "steps": len(points),
        "source_rows_sha256": digest(ids),
        "clock_basis": "dataset timestamp_utc, not request completion time or live simulation clock",
    }
    result["window"] = window
    result["window_id"] = digest({"dataset_sha256": dataset.package_sha256, "window": window})
    result["source_row_ids"] = ids
    # This derivation is admitted only for the known zero-queue v1 MPC rollout.
    # Multi-episode stored evaluations and other environments need their own
    # measured arrivals/initial backlog evidence; never infer them as zero.
    if (
        environment.get("status") != "public_dataset_control_benchmark"
        or environment.get("environment_id") != "PortEnergyDispatchEnv-v1"
        or environment.get("action_policy") != "MPC"
        or selected.get("strategy") != "MPC"
    ):
        issues.append("service_arrivals_and_initial_backlog_not_proven_for_policy")
        return result
    if "observation_hours" not in rows or any(float(v) != 1 for v in rows["observation_hours"]):
        issues.append("hourly_arrival_denominator_not_proven")
        return result
    demand = rows["total_teu"].tolist()
    processed = [p.get("processed_teu") for p in points]
    queues = [p.get("queue_teu") for p in points]
    if any(not finite(v) or v < 0 for v in demand + processed + queues):
        issues.append("invalid_throughput_or_queue_metric")
        return result
    arrivals = sum(demand)
    completed = sum(processed)
    # The public API rounds each trajectory field to 0.001 TEU. Verify the
    # conservation law and use its conservative lower bound for acceptance.
    tolerance = (len(points) + 1) * 0.0005 + 1e-8
    previous_queue = 0.0
    for arriving, done, queue in zip(demand, processed, queues):
        if abs(previous_queue + arriving - done - queue) > 0.0015 + 1e-8:
            issues.append("per_step_mass_balance_mismatch")
            return result
        previous_queue = queue
    if arrivals <= 0 or abs(arrivals - completed - queues[-1]) > tolerance:
        issues.append("zero_demand_or_trial_mass_balance_mismatch")
        return result
    lower = max(0.0, completed - len(points) * 0.0005) / arrivals * 100
    upper = min(100.0, (completed + len(points) * 0.0005) / arrivals * 100)
    result["service_pct"] = min(100.0, lower)
    result["service_evidence"] = {
        "arrivals_teu": arrivals,
        "processed_teu_from_rounded_trajectory": completed,
        "initial_queue_teu": 0.0,
        "ending_queue_teu": queues[-1],
        "quantization_interval_pct": [lower, upper],
        "acceptance_value": "lower bound accounting for 0.001 TEU rounding",
        "initial_queue_basis": "PortEnergyDispatchEnv-v1 reset, single MPC episode",
    }
    result["status"] = "ready" if not issues else "needs_evidence"
    return result
