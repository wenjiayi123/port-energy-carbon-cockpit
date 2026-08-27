from __future__ import annotations

import base64
import binascii
import hashlib
import json
import math
from pathlib import Path
import random
from statistics import mean
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from app.core.config import settings
from app.schemas.algorithm_production import (
    SOURCE_DOMAINS,
    AlgorithmProductionQualificationReport,
    AlgorithmProductionQualificationRequest,
)


REPORT_SCHEMA_VERSION = "algorithm-production-qualification.v1"
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def source_domain_payload(
    request: AlgorithmProductionQualificationRequest,
    domain: str,
) -> dict[str, Any]:
    """Return the exact source-owned payload covered by one Ed25519 signature."""
    if domain == "experiment_registry":
        payload: Any = {
            "artifacts": [item.model_dump(mode="json") for item in request.artifacts],
            "evaluation_pairs": [item.model_dump(mode="json") for item in request.evaluation_pairs],
            "shadow_runs": [item.model_dump(mode="json") for item in request.shadow_runs],
        }
    elif domain == "forecast_calibration":
        payload = [item.model_dump(mode="json") for item in request.probabilistic_forecasts]
    elif domain == "runtime_monitoring":
        payload = {
            "ood_events": [item.model_dump(mode="json") for item in request.ood_events],
            "explanations": [item.model_dump(mode="json") for item in request.explanations],
            "latency_samples": [item.model_dump(mode="json") for item in request.latency_samples],
        }
    elif domain == "execution_receipts":
        payload = [item.model_dump(mode="json") for item in request.action_receipts]
    elif domain == "fault_campaign":
        payload = [item.model_dump(mode="json") for item in request.fault_injections]
    elif domain == "human_review_log":
        payload = [item.model_dump(mode="json") for item in request.human_reviews]
    else:
        raise ValueError(f"unknown algorithm evidence domain: {domain}")
    return {"domain": domain, "payload": payload}


def _gate(gate_id: str, label_zh: str, passed: bool, evidence: Any) -> dict[str, Any]:
    return {
        "gate_id": gate_id,
        "label_zh": label_zh,
        "passed": bool(passed),
        "evidence": evidence,
    }


def _percentile(values: list[float], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(probability * len(ordered)) - 1))
    return float(ordered[index])


def _paired_bootstrap_interval(values: list[float], *, seed: int = 20260827) -> dict[str, Any]:
    if not values:
        return {
            "estimate_pct": None,
            "ci95_low_pct": None,
            "ci95_high_pct": None,
            "paired_samples": 0,
            "bootstrap_samples": 0,
        }
    generator = random.Random(seed)
    bootstrap = [
        mean(values[generator.randrange(len(values))] for _ in values) for _ in range(4000)
    ]
    return {
        "estimate_pct": round(mean(values), 6),
        "ci95_low_pct": round(float(_percentile(bootstrap, 0.025)), 6),
        "ci95_high_pct": round(float(_percentile(bootstrap, 0.975)), 6),
        "paired_samples": len(values),
        "bootstrap_samples": len(bootstrap),
    }


def _improvement(candidate: float, baseline: float) -> float:
    return (baseline - candidate) / max(abs(baseline), 1e-12) * 100.0


def _throughput_change(candidate: float, baseline: float) -> float:
    return (candidate - baseline) / max(abs(baseline), 1e-12) * 100.0


class AlgorithmProductionQualificationService:
    """Qualify a candidate from signed shadow evidence without promoting it.

    This service deliberately evaluates evidence and returns a release gate. It
    never trains a new algorithm, changes the champion, or dispatches equipment.
    """

    def __init__(self, *, source_public_keys: dict[str, str] | None = None) -> None:
        self.source_public_keys = dict(
            settings.algorithm_evidence_public_keys
            if source_public_keys is None
            else source_public_keys
        )

    @staticmethod
    def _known_offline_evidence() -> dict[str, Any]:
        path = REPOSITORY_ROOT / "reports" / "port_landing_benchmark_v4.json"
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return {
                "status": "unavailable",
                "report_path": "reports/port_landing_benchmark_v4.json",
                "preserved_algorithms": ["dqn", "ppo", "sac", "td3", "mpc"],
                "additional_algorithm_required": False,
            }
        increment = report.get("algorithm_increment_vs_causal_legacy_mpc", {})
        derating = report.get("stress_tests", {}).get("grid_derating_10pct", {})
        comparison = derating.get("comparison", {})
        return {
            "status": report.get("status", "unknown"),
            "report_path": "reports/port_landing_benchmark_v4.json",
            "report_evidence_sha256": report.get("evidence_sha256"),
            "preserved_algorithms": [
                "dqn",
                "ppo",
                "sac",
                "td3",
                "causal_legacy_mpc",
                "risk_aware_mpc",
            ],
            "multi_seed_research_evidence": True,
            "multi_seed_production_qualified": False,
            "approximate_prediction_intervals_available": True,
            "probability_calibration_verified": False,
            "offline_drift_report_available": True,
            "runtime_ood_fallback_verified": False,
            "risk_aware_vs_causal_legacy_mpc": {
                "carbon_reduction_pct": increment.get("carbon_reduction_pct"),
                "cost_reduction_pct": increment.get("cost_reduction_pct"),
                "peak_reduction_pct": increment.get("peak_reduction_pct"),
                "delay_reduction_pct": increment.get("delay_reduction_pct"),
                "p95_queue_reduction_pct": increment.get("p95_queue_reduction_pct"),
            },
            "grid_derating_10pct": {
                "reserve_breach_reduction_pct": comparison.get("reserve_breach_reduction_pct"),
                "carbon_reduction_pct": comparison.get("carbon_reduction_pct"),
                "cost_reduction_pct": comparison.get("cost_reduction_pct"),
            },
            "negative_results_preserved": True,
            "additional_algorithm_required": False,
            "field_kpi_claim_allowed": False,
        }

    def build_default(self) -> AlgorithmProductionQualificationReport:
        gate_definitions = [
            ("source_domain_coverage", "六类生产证据源覆盖", "现场证据源尚未接入"),
            ("source_trust_and_time", "逐源验签、新鲜度与对齐", "未配置可信公钥和现场时钟证据"),
            ("immutable_provenance", "模型、数据、代码与契约溯源", "没有不可变候选与基线制品"),
            ("multi_seed_validation", "多随机种子验证", "仓库训练记录不是现场生产资格试验"),
            ("cross_season_validation", "跨四季共同协议", "没有四季现场影子配对样本"),
            ("probabilistic_calibration", "概率预测校准", "只有近似区间，没有经验覆盖率"),
            ("ood_detection_fallback", "分布外检测与安全回退", "没有现场混淆矩阵和逐次回退回执"),
            ("policy_explainability", "策略解释与局部保真", "没有决策前解释、归因和反事实证据"),
            ("action_reachability", "动作可达性与网关回执", "模拟回执不能代替现场影子网关确认"),
            ("realtime_latency", "实时计算时限", "没有端到端 P95/P99 现场时延"),
            ("fault_injection", "影子故障注入", "没有覆盖规定故障的失效关闭演练"),
            ("human_veto_statistics", "人工审批与否决统计", "没有足量独立复核记录"),
            ("champion_challenger", "冠军/挑战者配对置信区间", "尚未证明候选优于强工程基线"),
            ("safety_non_regression", "安全与备用裕度不退化", "现有电网降额证据显示软备用越界增加"),
            ("shadow_duration", "长周期实港只读影子", "没有达到最低时长和决策量的现场运行"),
        ]
        gates = [
            _gate(gate_id, label, False, reason) for gate_id, label, reason in gate_definitions
        ]
        payload: dict[str, Any] = {
            "schema_version": REPORT_SCHEMA_VERSION,
            "report_id": "algorithm-production:repository-offline-evidence-incomplete",
            "mode": "repository_offline_evidence",
            "status": "blocked",
            "source_readiness": {
                "required_domains": sorted(SOURCE_DOMAINS),
                "received_domains": [],
                "signed_domains": [],
                "live_verified_domains": [],
                "domain_count": 0,
                "required_domain_count": len(SOURCE_DOMAINS),
                "maximum_observation_skew_seconds": None,
            },
            "qualification_summary": {
                "candidate_policy_id": "risk-aware-mpc-v4-candidate",
                "baseline_policy_id": "causal-legacy-mpc-v3",
                "passed_gate_count": 0,
                "required_gate_count": len(gates),
                "production_qualified": False,
                "qualification_evidence_ready": False,
            },
            "multi_seed_cross_season": {
                "distinct_seeds": 0,
                "covered_seasons": [],
                "paired_samples": 0,
            },
            "probabilistic_forecast": {
                "sample_count": 0,
                "empirical_interval_coverage": None,
                "median_mae": None,
                "calibration_verified": False,
            },
            "ood_monitoring": {
                "ood_samples": 0,
                "in_distribution_samples": 0,
                "true_positive_rate": None,
                "false_positive_rate": None,
                "fallback_coverage": None,
            },
            "explainability": {
                "record_count": 0,
                "mean_local_fidelity": None,
                "complete_record_rate": None,
            },
            "action_reachability": {
                "receipt_count": 0,
                "maximum_tracking_error": None,
                "acknowledged_rate": None,
            },
            "realtime_performance": {
                "sample_count": 0,
                "p50_ms": None,
                "p95_ms": None,
                "p99_ms": None,
                "timeout_count": None,
            },
            "fault_campaign": {
                "required_fault_types": [],
                "covered_fault_types": [],
                "passed_fault_types": [],
            },
            "human_oversight": {
                "review_count": 0,
                "veto_count": 0,
                "veto_rate": None,
                "distinct_reviewers": 0,
            },
            "champion_challenger": {
                "paired_samples": 0,
                "carbon_reduction_ci95": None,
                "cost_reduction_ci95": None,
                "peak_reduction_ci95": None,
                "throughput_change_ci95": None,
            },
            "known_offline_evidence": self._known_offline_evidence(),
            "gates": gates,
            "assurance": {
                "status": "blocked",
                "blocker_codes": [item[0] for item in gate_definitions],
                "claim": "offline evidence retained; production qualification not established",
            },
            "production_boundary": {
                "advisory_only": True,
                "automatic_policy_promotion_allowed": False,
                "autonomous_dispatch_allowed": False,
                "production_authority": False,
                "algorithm_expansion_recommended": False,
                "human_release_required": True,
            },
            "input_evidence_sha256": None,
        }
        payload["evidence_sha256"] = canonical_sha256(payload)
        return AlgorithmProductionQualificationReport(**payload)

    def _verify_signatures(
        self,
        request: AlgorithmProductionQualificationRequest,
    ) -> dict[str, bool]:
        results: dict[str, bool] = {}
        for attestation in request.source_attestations:
            payload_digest = canonical_sha256(source_domain_payload(request, attestation.domain))
            public_key_b64 = self.source_public_keys.get(attestation.key_id)
            verified = False
            if public_key_b64 and payload_digest == attestation.signed_payload_sha256:
                try:
                    public_key = Ed25519PublicKey.from_public_bytes(
                        base64.b64decode(public_key_b64, validate=True)
                    )
                    signature = base64.b64decode(attestation.signature, validate=True)
                    public_key.verify(signature, bytes.fromhex(payload_digest))
                    verified = True
                except (ValueError, binascii.Error, InvalidSignature):
                    verified = False
            results[attestation.domain] = verified
        return results

    def evaluate(
        self,
        request: AlgorithmProductionQualificationRequest,
    ) -> AlgorithmProductionQualificationReport:
        policy = request.policy
        received_domains = [item.domain for item in request.source_attestations]
        unique_domains = set(received_domains)
        coverage_ready = unique_domains == SOURCE_DOMAINS and len(received_domains) == len(
            SOURCE_DOMAINS
        )
        signature_results = self._verify_signatures(request)
        signature_ready = coverage_ready and all(
            signature_results.get(domain, False) for domain in SOURCE_DOMAINS
        )
        ages = [
            (request.evaluated_at - item.observed_at).total_seconds()
            for item in request.source_attestations
        ]
        observed_timestamps = [item.observed_at.timestamp() for item in request.source_attestations]
        observation_skew = (
            max(observed_timestamps) - min(observed_timestamps) if observed_timestamps else math.inf
        )
        time_ready = (
            bool(ages)
            and all(0 <= age <= policy.maximum_source_age_seconds for age in ages)
            and observation_skew <= policy.maximum_source_alignment_seconds
        )
        live_ready = coverage_ready and all(
            item.live_data_verified for item in request.source_attestations
        )
        source_ready = coverage_ready and signature_ready and time_ready and live_ready

        artifacts_by_role = {item.role: item for item in request.artifacts}
        candidate_artifact = artifacts_by_role.get("candidate")
        baseline_artifact = artifacts_by_role.get("baseline")
        pair_ids = [item.pair_id for item in request.evaluation_pairs]
        provenance_ready = bool(
            len(request.artifacts) == 2
            and candidate_artifact
            and baseline_artifact
            and candidate_artifact.policy_id == policy.candidate_policy_id
            and baseline_artifact.policy_id == policy.baseline_policy_id
            and candidate_artifact.immutable
            and baseline_artifact.immutable
            and len(pair_ids) == len(set(pair_ids))
            and all(
                item.candidate_policy_id == policy.candidate_policy_id
                and item.baseline_policy_id == policy.baseline_policy_id
                for item in request.evaluation_pairs
            )
        )

        seeds = sorted({item.seed for item in request.evaluation_pairs})
        seasons = sorted({item.season for item in request.evaluation_pairs})
        valid_splits = all(
            item.split in {"test", "read_only_shadow"} for item in request.evaluation_pairs
        )
        multi_seed_ready = len(seeds) >= policy.minimum_distinct_seeds and valid_splits
        pair_counts = {
            (seed, season): sum(
                item.seed == seed and item.season == season for item in request.evaluation_pairs
            )
            for seed in seeds
            for season in policy.required_seasons
        }
        cross_season_ready = (
            set(seasons) == set(policy.required_seasons)
            and all(count >= policy.minimum_pairs_per_seed_season for count in pair_counts.values())
            and len(seeds) >= policy.minimum_distinct_seeds
        )
        multi_seed_summary = {
            "distinct_seeds": len(seeds),
            "seeds": seeds,
            "covered_seasons": seasons,
            "required_seasons": policy.required_seasons,
            "paired_samples": len(request.evaluation_pairs),
            "pairs_per_seed_season": {
                f"{seed}:{season}": count for (seed, season), count in sorted(pair_counts.items())
            },
        }

        forecast_count = len(request.probabilistic_forecasts)
        covered = sum(
            item.lower <= item.actual <= item.upper for item in request.probabilistic_forecasts
        )
        forecast_coverage = covered / max(1, forecast_count)
        median_mae = mean(
            abs(item.actual - item.median) for item in request.probabilistic_forecasts
        )
        forecast_ready = (
            forecast_count >= policy.minimum_forecast_samples
            and policy.minimum_interval_coverage
            <= forecast_coverage
            <= policy.maximum_interval_coverage
            and median_mae <= policy.maximum_median_mae
            and len({item.decision_id for item in request.probabilistic_forecasts})
            == forecast_count
        )
        forecast_summary = {
            "sample_count": forecast_count,
            "nominal_interval_coverage": policy.nominal_interval_coverage,
            "empirical_interval_coverage": round(forecast_coverage, 6),
            "accepted_coverage_band": [
                policy.minimum_interval_coverage,
                policy.maximum_interval_coverage,
            ],
            "median_mae": round(median_mae, 6),
            "maximum_median_mae": policy.maximum_median_mae,
            "calibration_verified": forecast_ready,
        }

        ood_items = [item for item in request.ood_events if item.expected_ood]
        in_distribution = [item for item in request.ood_events if not item.expected_ood]
        true_positive_rate = sum(item.detected for item in ood_items) / max(1, len(ood_items))
        false_positive_rate = sum(item.detected for item in in_distribution) / max(
            1, len(in_distribution)
        )
        detected_ood = [item for item in ood_items if item.detected]
        fallback_coverage = sum(
            item.fallback_activated
            and item.recommendation_suppressed
            and bool(item.fallback_policy_id)
            for item in detected_ood
        ) / max(1, len(detected_ood))
        detector_coherent = all(
            item.detected == (item.score >= item.threshold) for item in request.ood_events
        )
        ood_ready = (
            len(ood_items) >= policy.minimum_ood_samples_per_class
            and len(in_distribution) >= policy.minimum_ood_samples_per_class
            and true_positive_rate >= policy.minimum_ood_true_positive_rate
            and false_positive_rate <= policy.maximum_ood_false_positive_rate
            and fallback_coverage == 1.0
            and detector_coherent
        )
        ood_summary = {
            "ood_samples": len(ood_items),
            "in_distribution_samples": len(in_distribution),
            "true_positive_rate": round(true_positive_rate, 6),
            "false_positive_rate": round(false_positive_rate, 6),
            "fallback_coverage": round(fallback_coverage, 6),
            "detector_threshold_coherent": detector_coherent,
        }

        complete_explanations = [
            item
            for item in request.explanations
            if item.reason_codes
            and item.feature_attributions
            and item.counterfactual_action
            and item.generated_before_human_review
        ]
        explanation_fidelity = mean(item.local_fidelity for item in request.explanations)
        explanation_complete_rate = len(complete_explanations) / max(1, len(request.explanations))
        explanation_ready = (
            len(request.explanations) >= policy.minimum_explanation_records
            and len({item.decision_id for item in request.explanations})
            == len(request.explanations)
            and explanation_complete_rate == 1.0
            and explanation_fidelity >= policy.minimum_explanation_fidelity
        )
        explanation_summary = {
            "record_count": len(request.explanations),
            "mean_local_fidelity": round(explanation_fidelity, 6),
            "complete_record_rate": round(explanation_complete_rate, 6),
            "generated_before_review_rate": round(
                sum(item.generated_before_human_review for item in request.explanations)
                / max(1, len(request.explanations)),
                6,
            ),
        }

        maximum_tracking_error = 0.0
        reachable_receipts = 0
        for receipt in request.action_receipts:
            fields = set(receipt.limits)
            coherent_fields = fields and all(
                set(action) == fields
                for action in (
                    receipt.current_action,
                    receipt.requested_action,
                    receipt.projected_action,
                    receipt.acknowledged_action,
                )
            )
            within_envelope = bool(coherent_fields) and all(
                limit.minimum <= receipt.projected_action[field] <= limit.maximum
                and abs(receipt.projected_action[field] - receipt.current_action[field])
                <= limit.maximum_delta
                for field, limit in receipt.limits.items()
            )
            errors = (
                [
                    abs(receipt.acknowledged_action[field] - receipt.projected_action[field])
                    for field in fields
                ]
                if coherent_fields
                else [math.inf]
            )
            receipt_error = max(errors, default=math.inf)
            maximum_tracking_error = max(maximum_tracking_error, receipt_error)
            if (
                coherent_fields
                and within_envelope
                and receipt_error <= policy.maximum_action_tracking_error
                and receipt.ack_latency_ms <= policy.maximum_ack_latency_ms
                and receipt.interlocks_satisfied
            ):
                reachable_receipts += 1
        action_ready = (
            len(request.action_receipts) >= policy.minimum_action_receipts
            and len({item.command_id for item in request.action_receipts})
            == len(request.action_receipts)
            and reachable_receipts == len(request.action_receipts)
        )
        action_summary = {
            "receipt_count": len(request.action_receipts),
            "reachable_receipt_count": reachable_receipts,
            "acknowledged_rate": round(
                reachable_receipts / max(1, len(request.action_receipts)), 6
            ),
            "maximum_tracking_error": (
                round(maximum_tracking_error, 6) if math.isfinite(maximum_tracking_error) else None
            ),
            "maximum_allowed_tracking_error": policy.maximum_action_tracking_error,
            "mode": "read_only_shadow",
        }

        latency_values = [item.end_to_end_ms for item in request.latency_samples]
        p50 = _percentile(latency_values, 0.5)
        p95 = _percentile(latency_values, 0.95)
        p99 = _percentile(latency_values, 0.99)
        timeout_count = sum(item.timed_out for item in request.latency_samples)
        timeout_fallback_ready = all(
            not item.timed_out or item.fallback_activated for item in request.latency_samples
        )
        component_coherent = all(
            item.forecast_ms + item.policy_ms + item.safety_projection_ms
            <= item.end_to_end_ms + 1e-9
            for item in request.latency_samples
        )
        latency_ready = (
            len(latency_values) >= policy.minimum_latency_samples
            and p95 is not None
            and p99 is not None
            and p95 <= policy.maximum_p95_latency_ms
            and p99 <= policy.maximum_p99_latency_ms
            and timeout_fallback_ready
            and component_coherent
        )
        latency_summary = {
            "sample_count": len(latency_values),
            "p50_ms": round(float(p50), 6) if p50 is not None else None,
            "p95_ms": round(float(p95), 6) if p95 is not None else None,
            "p99_ms": round(float(p99), 6) if p99 is not None else None,
            "timeout_count": timeout_count,
            "timeout_fallback_rate": round(
                sum(item.timed_out and item.fallback_activated for item in request.latency_samples)
                / max(1, timeout_count),
                6,
            )
            if timeout_count
            else 1.0,
        }

        required_faults = set(policy.required_fault_types)
        covered_faults = {item.fault_type for item in request.fault_injections}
        passed_faults = {
            fault_type
            for fault_type in required_faults
            if any(
                item.fault_type == fault_type
                and item.detected
                and item.failed_closed
                and item.fallback_activated
                and item.unsafe_action_count == 0
                and item.recovery_ms <= policy.maximum_fault_recovery_ms
                for item in request.fault_injections
            )
        }
        fault_ready = required_faults <= passed_faults
        fault_summary = {
            "required_fault_types": sorted(required_faults),
            "covered_fault_types": sorted(covered_faults),
            "passed_fault_types": sorted(passed_faults),
            "unsafe_action_count": sum(
                item.unsafe_action_count for item in request.fault_injections
            ),
            "maximum_recovery_ms": max(
                (item.recovery_ms for item in request.fault_injections), default=None
            ),
        }

        review_count = len(request.human_reviews)
        veto_count = sum(item.outcome in {"reject", "veto"} for item in request.human_reviews)
        distinct_reviewers = {item.reviewer_id for item in request.human_reviews}
        review_ids_unique = (
            len({item.decision_id for item in request.human_reviews}) == review_count
        )
        human_ready = (
            review_count >= policy.minimum_human_reviews
            and len(distinct_reviewers) >= policy.minimum_distinct_reviewers
            and review_ids_unique
            and all(item.reason_code and item.comment for item in request.human_reviews)
        )
        human_summary = {
            "review_count": review_count,
            "approve_count": sum(item.outcome == "approve" for item in request.human_reviews),
            "modify_count": sum(item.outcome == "modify" for item in request.human_reviews),
            "veto_count": veto_count,
            "veto_rate": round(veto_count / max(1, review_count), 6),
            "distinct_reviewers": len(distinct_reviewers),
            "reason_complete_rate": round(
                sum(bool(item.reason_code and item.comment) for item in request.human_reviews)
                / max(1, review_count),
                6,
            ),
        }

        carbon_changes = [
            _improvement(item.candidate.carbon_kg, item.baseline.carbon_kg)
            for item in request.evaluation_pairs
        ]
        cost_changes = [
            _improvement(item.candidate.cost_cny, item.baseline.cost_cny)
            for item in request.evaluation_pairs
        ]
        peak_changes = [
            _improvement(item.candidate.peak_kw, item.baseline.peak_kw)
            for item in request.evaluation_pairs
        ]
        throughput_changes = [
            _throughput_change(item.candidate.throughput_teu, item.baseline.throughput_teu)
            for item in request.evaluation_pairs
        ]
        carbon_ci = _paired_bootstrap_interval(carbon_changes, seed=101)
        cost_ci = _paired_bootstrap_interval(cost_changes, seed=103)
        peak_ci = _paired_bootstrap_interval(peak_changes, seed=107)
        throughput_ci = _paired_bootstrap_interval(throughput_changes, seed=109)
        comparison_ready = (
            provenance_ready
            and cross_season_ready
            and float(carbon_ci["ci95_low_pct"]) >= policy.minimum_carbon_improvement_pct
            and float(cost_ci["ci95_low_pct"]) >= -policy.maximum_cost_regression_pct
            and float(peak_ci["ci95_low_pct"]) >= -policy.maximum_peak_regression_pct
            and float(throughput_ci["ci95_low_pct"]) >= -policy.maximum_throughput_regression_pct
        )
        reserve_changes = []
        safety_ready = True
        for item in request.evaluation_pairs:
            if item.candidate.safety_violations > item.baseline.safety_violations:
                safety_ready = False
            if item.baseline.reserve_breach_steps == 0:
                reserve_change = 0.0 if item.candidate.reserve_breach_steps == 0 else math.inf
            else:
                reserve_change = (
                    (item.candidate.reserve_breach_steps - item.baseline.reserve_breach_steps)
                    / item.baseline.reserve_breach_steps
                    * 100.0
                )
            reserve_changes.append(reserve_change)
            if reserve_change > policy.maximum_reserve_breach_increase_pct:
                safety_ready = False
        champion_summary = {
            "candidate_policy_id": policy.candidate_policy_id,
            "baseline_policy_id": policy.baseline_policy_id,
            "paired_samples": len(request.evaluation_pairs),
            "carbon_reduction_ci95": carbon_ci,
            "cost_reduction_ci95": cost_ci,
            "peak_reduction_ci95": peak_ci,
            "throughput_change_ci95": throughput_ci,
            "safety_violation_delta": sum(
                item.candidate.safety_violations - item.baseline.safety_violations
                for item in request.evaluation_pairs
            ),
            "maximum_reserve_breach_increase_pct": (
                round(max(reserve_changes), 6)
                if reserve_changes and all(math.isfinite(value) for value in reserve_changes)
                else None
            ),
        }

        shadow_hours = sum(
            (item.ended_at - item.started_at).total_seconds() / 3600.0
            for item in request.shadow_runs
        )
        shadow_decisions = sum(item.decision_count for item in request.shadow_runs)
        shadow_ready = (
            shadow_hours >= policy.minimum_shadow_hours
            and shadow_decisions >= policy.minimum_shadow_decisions
            and all(item.live_data_verified for item in request.shadow_runs)
            and len({item.run_id for item in request.shadow_runs}) == len(request.shadow_runs)
        )

        gates = [
            _gate(
                "source_domain_coverage",
                "六类生产证据源覆盖",
                coverage_ready,
                {"received": sorted(unique_domains), "required": sorted(SOURCE_DOMAINS)},
            ),
            _gate(
                "source_trust_and_time",
                "逐源验签、新鲜度与对齐",
                source_ready,
                {
                    "signature_results": signature_results,
                    "all_live_verified": live_ready,
                    "maximum_age_seconds": max(ages, default=None),
                    "observation_skew_seconds": observation_skew,
                },
            ),
            _gate(
                "immutable_provenance",
                "模型、数据、代码与契约溯源",
                provenance_ready,
                {
                    "candidate_artifact": candidate_artifact.model_dump(mode="json")
                    if candidate_artifact
                    else None,
                    "baseline_artifact": baseline_artifact.model_dump(mode="json")
                    if baseline_artifact
                    else None,
                },
            ),
            _gate("multi_seed_validation", "多随机种子验证", multi_seed_ready, multi_seed_summary),
            _gate(
                "cross_season_validation", "跨四季共同协议", cross_season_ready, multi_seed_summary
            ),
            _gate("probabilistic_calibration", "概率预测校准", forecast_ready, forecast_summary),
            _gate("ood_detection_fallback", "分布外检测与安全回退", ood_ready, ood_summary),
            _gate(
                "policy_explainability",
                "策略解释与局部保真",
                explanation_ready,
                explanation_summary,
            ),
            _gate("action_reachability", "动作可达性与网关回执", action_ready, action_summary),
            _gate("realtime_latency", "实时计算时限", latency_ready, latency_summary),
            _gate("fault_injection", "影子故障注入", fault_ready, fault_summary),
            _gate("human_veto_statistics", "人工审批与否决统计", human_ready, human_summary),
            _gate(
                "champion_challenger", "冠军/挑战者配对置信区间", comparison_ready, champion_summary
            ),
            _gate("safety_non_regression", "安全与备用裕度不退化", safety_ready, champion_summary),
            _gate(
                "shadow_duration",
                "长周期实港只读影子",
                shadow_ready,
                {
                    "run_count": len(request.shadow_runs),
                    "total_hours": round(shadow_hours, 6),
                    "decision_count": shadow_decisions,
                    "minimum_hours": policy.minimum_shadow_hours,
                    "minimum_decisions": policy.minimum_shadow_decisions,
                },
            ),
        ]
        passed_gate_count = sum(item["passed"] for item in gates)
        all_gates_ready = passed_gate_count == len(gates)
        status = (
            "blocked"
            if not source_ready
            else "qualification_ready"
            if all_gates_ready
            else "not_qualified"
        )
        input_evidence_sha256 = canonical_sha256(request.model_dump(mode="json"))
        report_payload: dict[str, Any] = {
            "schema_version": REPORT_SCHEMA_VERSION,
            "report_id": f"algorithm-production:{request.qualification_id}",
            "mode": "signed_site_shadow_qualification",
            "status": status,
            "source_readiness": {
                "required_domains": sorted(SOURCE_DOMAINS),
                "received_domains": sorted(unique_domains),
                "signed_domains": sorted(
                    domain for domain, passed in signature_results.items() if passed
                ),
                "live_verified_domains": sorted(
                    item.domain for item in request.source_attestations if item.live_data_verified
                ),
                "domain_count": len(unique_domains),
                "required_domain_count": len(SOURCE_DOMAINS),
                "maximum_observation_skew_seconds": observation_skew,
            },
            "qualification_summary": {
                "candidate_policy_id": policy.candidate_policy_id,
                "baseline_policy_id": policy.baseline_policy_id,
                "passed_gate_count": passed_gate_count,
                "required_gate_count": len(gates),
                "qualification_evidence_ready": all_gates_ready,
                "production_qualified": False,
                "automatic_promotion": False,
                "pending_independent_human_release": all_gates_ready,
                "human_release_required": True,
            },
            "multi_seed_cross_season": multi_seed_summary,
            "probabilistic_forecast": forecast_summary,
            "ood_monitoring": ood_summary,
            "explainability": explanation_summary,
            "action_reachability": action_summary,
            "realtime_performance": latency_summary,
            "fault_campaign": fault_summary,
            "human_oversight": human_summary,
            "champion_challenger": champion_summary,
            "known_offline_evidence": self._known_offline_evidence(),
            "gates": gates,
            "assurance": {
                "status": status,
                "blocker_codes": [item["gate_id"] for item in gates if not item["passed"]],
                "claim": (
                    "signed shadow evidence passed; independent human release still required"
                    if all_gates_ready
                    else "candidate is not admitted to production"
                ),
            },
            "production_boundary": {
                "advisory_only": True,
                "automatic_policy_promotion_allowed": False,
                "autonomous_dispatch_allowed": False,
                "production_authority": False,
                "algorithm_expansion_recommended": False,
                "human_release_required": True,
            },
            "input_evidence_sha256": input_evidence_sha256,
        }
        report_payload["evidence_sha256"] = canonical_sha256(report_payload)
        return AlgorithmProductionQualificationReport(**report_payload)


algorithm_production_qualification_service = AlgorithmProductionQualificationService()
