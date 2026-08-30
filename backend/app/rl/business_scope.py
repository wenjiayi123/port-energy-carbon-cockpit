from __future__ import annotations

from typing import Any

from app.rl.environment import (
    DEFAULT_FLEX_REWARD_WEIGHTS,
    FLEXIBLE_OPERATIONS_OBSERVATION_KEYS,
    observation_keys_for_environment,
)


V5_DATASET_ID = "port_la_2020_2024_operational_flex_hourly"


def _item(
    domain: str,
    label_zh: str,
    owner: str,
    implementation: str,
    status: str,
    production_input: str,
) -> dict[str, str]:
    return {
        "domain": domain,
        "label_zh": label_zh,
        "decision_owner": owner,
        "implementation": implementation,
        "status": status,
        "production_input": production_input,
    }


def business_scope_contract() -> dict[str, Any]:
    """Return the executable ownership boundary for the complete port workflow.

    A complete product does not imply that every decision belongs in one RL
    policy. This contract is consumed by the API/UI and audited in tests so a
    later integration cannot silently move accounting, authority or safety
    decisions into a learned action.
    """

    domains = [
        _item("shore_power_dispatch", "逐船岸电柔性调度", "rl_with_hard_projection", "v5 action 1", "implemented_offline", "岸电预约、兼容、分表与开关回执"),
        _item("crane_resource_envelope", "岸桥资源包络", "rl_with_tos_envelope", "v5 action 2", "implemented_offline", "具名岸桥任务、能力、健康与联锁"),
        _item("yard_resource_envelope", "堆场资源包络", "rl_with_tos_envelope", "v5 action 3", "implemented_offline", "箱位、场桥任务、堆存容量与联锁"),
        _item("battery_dispatch", "储能充放电", "rl_with_bms_projection", "v5 action 4", "implemented_offline", "电池管理系统状态、质保、温度与功率回执"),
        _item("inspection_readiness", "检查准备资源", "rl_terminal_resources_only", "v5 action 5", "implemented_offline", "海事/海关事件与现场资源状态"),
        _item("release_recovery", "放行后恢复优先级", "rl_terminal_resources_only", "v5 action 6", "implemented_offline", "外生放行事件与堆场恢复队列"),
        _item("agv_charging", "自动导引车充电", "rl_with_departure_energy_projection", "v5 action 7", "implemented_offline", "逐车荷电状态、任务、充电桩、离场时限"),
        _item("reefer_flex", "冷藏箱柔性负荷", "rl_with_thermal_projection", "v5 action 8", "implemented_offline", "逐箱温度、设定值、插座、告警与货类"),
        _item("building_flex", "楼宇柔性负荷", "rl_with_critical_load_floor", "v5 action 9", "implemented_offline", "楼宇自控分路、舒适度和关键负荷清单"),
        _item("demand_response", "需求响应承诺", "rl_advisory_plus_settlement_rule", "v5 action 10", "implemented_offline", "真实事件、基线、计量与结算回执"),
        _item("vessel_jit_arrival", "船舶准时到港", "joint_optimizer_human_approval", "port_collaboration + operations_energy_planning", "implemented_advisory", "船东同意、预计到港、引航拖轮和泊位里程碑"),
        _item("berth_assignment", "具名泊位分配", "operations_research", "operations_energy_planning", "implemented_advisory", "船舶尺度、泊位窗口、互斥和终端操作系统回执"),
        _item("crane_task_schedule", "具名岸桥任务", "operations_research", "operations_energy_planning", "implemented_advisory", "工作指令、作业率、维护和终端操作系统回执"),
        _item("yard_slotting", "堆场箱位与库存", "operations_research", "operations_energy_planning", "implemented_advisory", "逐箱/箱组库存、箱位与容量"),
        _item("truck_appointments", "外集卡预约与闸口", "operations_research", "operations_energy_planning", "implemented_advisory", "预约、闸口能力和实际到离场"),
        _item("alternative_fuel_corridor", "替代燃料与绿色航运走廊", "safety_and_corridor_governance", "port_collaboration", "implemented_fail_closed", "燃料许可、库存、输送能力、兼容设备、人员、安全论证、风险评估、应急演练和服务回执"),
        _item("electrical_power_flow", "配电潮流与故障", "physics_and_rules", "electrical_network", "implemented_assessment", "单线图、开关、阻抗、保护、实时监控与电能质量"),
        _item("emissions_inventory", "港口排放清单", "deterministic_ledger", "port_emissions_inventory", "implemented_fail_closed", "七源活动数据、因子、范围边界与核证"),
        _item("energy_management", "能源管理体系", "management_workflow", "energy_carbon_management", "implemented_fail_closed", "方针、基准、能源绩效参数、内审和管理评审"),
        _item("measurement_verification", "节能量测量与验证", "deterministic_assurance", "measurement_verification", "implemented_fail_closed", "收入表、分表、账单、调整项和独立核证"),
        _item("commercial_settlement", "电费/需求响应/绿证结算", "deterministic_settlement", "commercial_settlement", "implemented_fail_closed", "账单、费率、合同、结算和租户分摊"),
        _item("carbon_assets", "碳资产与履约", "deterministic_compliance", "carbon_assets", "implemented_fail_closed", "登记簿、序列号、交易、现金与注销证明"),
        _item("authority_release", "海事/海关扣放行", "external_authority", "exogenous observation only", "prohibited_for_rl", "主管机关权威事件与回执"),
        _item("physical_interlock", "设备/可编程逻辑控制器联锁", "independent_ot_safety", "outside application process", "site_required", "能力检查、硬联锁、人工接管和回滚演练"),
        _item("identity_and_tenancy", "身份、多租户与最小权限", "enterprise_security", "enterprise_security", "implemented_fail_closed", "企业身份、租户、消息、双向传输层安全与密钥"),
        _item("production_cutover", "生产切换与验收", "site_acceptance_board", "site_cutover", "implemented_fail_closed", "180天影子运行、四季/故障覆盖、六方签字与回退演练"),
    ]
    counts: dict[str, int] = {}
    for item in domains:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    return {
        "schema_version": "port-energy-business-scope.v1",
        "dataset_id": V5_DATASET_ID,
        "environment_id": "PortEnergyDispatchEnv-v5",
        "observation_count": len(observation_keys_for_environment("PortEnergyDispatchEnv-v5")),
        "flexible_observation_count": len(FLEXIBLE_OPERATIONS_OBSERVATION_KEYS),
        "continuous_action_count": 10,
        "dqn_template_count": 243,
        "reward_weights": DEFAULT_FLEX_REWARD_WEIGHTS,
        "domain_count": len(domains),
        "status_counts": counts,
        "domains": domains,
        "hard_constraints": [
            "grid_capacity",
            "battery_soc_and_terminal_reachability",
            "agv_departure_energy",
            "reefer_thermal_safety",
            "critical_building_load",
            "authority_release_exogenous",
            "physical_dispatch_disabled",
        ],
        "claim_boundary": {
            "simulation_mode": True,
            "live_data_verified": False,
            "dispatch_allowed": False,
            "production_authority": False,
        },
    }
