from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Any
from urllib.error import URLError
from urllib.request import Request as UrlRequest, urlopen

from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import JSONResponse

from app.services.kpi_engine import KpiEngine
from app.rl.dataset import DEFAULT_DATASET_ID, registered_dataset_id
from app.rl.policy_selection import resolve_requested_strategy
from app.rl.scenarios import resolve_training_scenario
from app.rl.training import training_service
from app.integration.gateway import integration_gateway
from app.services.runtime_decision import runtime_decision_service
from app.services.runtime_forecast import runtime_forecast_model
from app.services.runtime_simulator import runtime_simulator


router = APIRouter(tags=["assistant-linkage"])
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
XIAOYI_PROJECT = Path(os.getenv("XIAOYI_AI_PROJECT", str(PROJECT_ROOT / "integrations" / "xiaoyi"))).expanduser()
XIAOYI_BASE_URL = os.getenv("XIAOYI_AI_BASE_URL", "http://127.0.0.1:8010").rstrip("/")
SAILING_PROJECT = Path(os.getenv("SAILING_SIM_PROJECT", str(PROJECT_ROOT / "integrations" / "sailing-simulator"))).expanduser()
GODOT_EXECUTABLE = Path(os.getenv("SAILING_SIM_GODOT", shutil.which("godot4") or shutil.which("godot") or "__godot_not_configured__")).expanduser()
MAIN_SCENE = "res://main.tscn"
SMOKE_SCRIPT = "res://tools/ship_rl_smoke_test.gd"

_xiaoyi_process: subprocess.Popen[Any] | None = None
_sailing_process: subprocess.Popen[Any] | None = None
_last_xiaoyi_launch: dict[str, Any] = {}
_last_sailing_launch: dict[str, Any] = {}
_action_log: list[dict[str, Any]] = []


TRAINING_OBJECTIVES: dict[str, dict[str, Any]] = {
    "carbon_min": {
        "label": "碳排最低目标",
        "algorithm": "sac",
        "total_steps": 220_000,
        "horizon_min": 720,
        "reward_weights": {"carbon": 0.42, "shore_power": 0.24, "cost": 0.14, "safety": 0.20},
        "reason": "SAC 适合连续权重调度，优先压低碳排并保留安全护栏。",
    },
    "cost_carbon_balance": {
        "label": "能耗成本与碳排均衡目标",
        "algorithm": "td3",
        "total_steps": 180_000,
        "horizon_min": 540,
        "reward_weights": {"cost": 0.32, "carbon": 0.30, "delay": 0.18, "safety": 0.20},
        "reason": "TD3 通过双评论家和延迟策略更新学习连续资源配比。",
    },
    "shore_power_priority": {
        "label": "岸电优先接入目标",
        "algorithm": "sac",
        "total_steps": 200_000,
        "horizon_min": 720,
        "reward_weights": {"shore_power": 0.44, "carbon": 0.24, "delay": 0.12, "safety": 0.20},
        "reason": "优先把靠泊窗口和岸电窗口匹配起来，适合港口低碳展示。",
    },
    "peak_smoothing": {
        "label": "峰值负荷平滑目标",
        "algorithm": "ppo",
        "total_steps": 160_000,
        "horizon_min": 360,
        "reward_weights": {"peak": 0.40, "cost": 0.20, "carbon": 0.18, "safety": 0.22},
        "reason": "PPO 参数可解释性强，适合给操作员展示峰值削减策略。",
    },
    "low_risk_validation": {
        "label": "低风险试运行目标",
        "algorithm": "dqn",
        "total_steps": 90_000,
        "horizon_min": 240,
        "reward_weights": {"safety": 0.42, "carbon": 0.22, "cost": 0.18, "delay": 0.18},
        "reason": "DQN 在 81 个可审计的岸电、岸桥、场内车辆与储能组合中学习，适合做离散动作对照。",
    },
}

PREFERENCE_ACTIONS: dict[str, dict[str, Any]] = {
    "set_efficiency_priority": {"label": "效率优先", "green_preference": 0.25, "panel": "carbon"},
    "set_balanced_dispatch": {"label": "均衡调度", "green_preference": 0.50, "panel": "carbon"},
    "set_low_carbon_priority": {"label": "低碳优先", "green_preference": 0.82, "panel": "carbon"},
    "set_shore_power_preference": {"label": "岸电优先", "green_preference": 0.88, "panel": "shore"},
}

TOP_PANEL_ACTIONS: dict[str, dict[str, str]] = {
    "open_runtime_panel": {"panel": "runtime", "label": "实时闭环面板"},
    "open_simulation_panel": {"panel": "simulation", "label": "仿真在线面板"},
    "open_marl_panel": {"panel": "marl", "label": "RL 策略面板"},
    "open_carbon_panel": {"panel": "carbon", "label": "低碳优先面板"},
    "open_shore_panel": {"panel": "shore", "label": "岸电联动面板"},
    "open_api_panel": {"panel": "api", "label": "API 同步面板"},
}


ACTION_REGISTRY: list[dict[str, Any]] = [
    {
        "id": "open_runtime_panel",
        "label": "打开实时闭环面板",
        "category": "runtime_closed_loop",
        "description": "打开公开数据校准实时模拟、预测、建议、人工审批、模拟执行和回滚面板。",
        "intent_aliases": ["open_runtime_panel", "打开实时闭环", "打开实时态势面板"],
        "keywords": ["实时闭环", "实时态势", "运行闭环", "打开实时", "闭环面板"],
        "button_selector": "#btnXiaoyiOpenRuntimePanel",
        "button_label": "打开实时闭环",
        "backend_request": {"method": "LOCAL", "path": "front-end:open-top-panel", "body": {"panel": "runtime"}},
        "linked_system": "runtime_closed_loop",
        "requires_human_confirm": False,
    },
    {
        "id": "summarize_runtime_state",
        "label": "总结实时态势",
        "category": "runtime_closed_loop",
        "description": "读取当前 51 字段快照、质量门禁和 1/3/6 小时模型预测，生成有来源边界的态势摘要。",
        "intent_aliases": ["summarize_runtime_state", "总结实时态势", "实时态势摘要"],
        "keywords": ["总结实时", "态势摘要", "现在什么情况", "当前能碳态势", "实时状态"],
        "button_selector": "#btnXiaoyiRuntimeSummary",
        "button_label": "实时态势摘要",
        "backend_request": {"method": "POST", "path": "/api/assistant/actions/execute"},
        "linked_system": "runtime_closed_loop",
        "requires_human_confirm": False,
    },
    {
        "id": "prepare_runtime_handover",
        "label": "生成实时交班摘要",
        "category": "runtime_closed_loop",
        "description": "整理场景、数据质量、能碳指标、模型预测、最新建议和生产权限边界，供人工交班复核。",
        "intent_aliases": ["prepare_runtime_handover", "生成交班摘要", "实时交班"],
        "keywords": ["交班", "交接班", "值班摘要", "班组交接", "运行简报"],
        "button_selector": "#btnXiaoyiRuntimeHandover",
        "button_label": "实时交班摘要",
        "backend_request": {"method": "POST", "path": "/api/assistant/actions/execute"},
        "linked_system": "runtime_closed_loop",
        "requires_human_confirm": False,
    },
    {
        "id": "triage_runtime_alerts",
        "label": "研判实时异常",
        "category": "runtime_closed_loop",
        "description": "读取质量门禁、异常字段和当前工程场景，给出 fail-closed 的人工处置顺序。",
        "intent_aliases": ["triage_runtime_alerts", "研判实时异常", "异常研判"],
        "keywords": ["异常研判", "告警", "质量门禁", "哪里异常", "故障处置"],
        "button_selector": "#btnXiaoyiRuntimeTriage",
        "button_label": "实时异常研判",
        "backend_request": {"method": "POST", "path": "/api/assistant/actions/execute"},
        "linked_system": "runtime_closed_loop",
        "requires_human_confirm": False,
    },
    {
        "id": "create_runtime_recommendation",
        "label": "生成当前运行建议",
        "category": "runtime_closed_loop",
        "description": "经人工确认后调用运行 MPC 生成建议；小懿不能审批、执行或绕过质量门禁。",
        "intent_aliases": ["create_runtime_recommendation", "生成当前运行建议", "生成实时建议"],
        "keywords": ["生成建议", "运行建议", "实时推荐", "生成推荐", "mcp建议"],
        "button_selector": "#btnRuntimeCreateDecision",
        "button_label": "生成当前推荐",
        "backend_request": {"method": "POST", "path": "/api/runtime/decisions"},
        "linked_system": "runtime_closed_loop",
        "requires_human_confirm": True,
    },
    {
        "id": "explain_runtime_recommendation",
        "label": "解释最新运行建议",
        "category": "runtime_closed_loop",
        "description": "只读解释最新 MPC 建议、安全投影、约束、审批状态和强基线对比，不代替人工授权。",
        "intent_aliases": ["explain_runtime_recommendation", "解释最新运行建议", "解释实时推荐"],
        "keywords": ["解释建议", "解释推荐", "为什么这样调", "安全投影", "审批状态"],
        "button_selector": "#btnXiaoyiRuntimeExplain",
        "button_label": "解释最新建议",
        "backend_request": {"method": "POST", "path": "/api/assistant/actions/execute"},
        "linked_system": "runtime_closed_loop",
        "requires_human_confirm": False,
    },
    {
        "id": "start_xiaoyi_ai",
        "label": "启动小懿AI",
        "category": "assistant_linkage",
        "description": "启动桌面小懿AI本地服务，并让 /health 与 /api/chat 可用。",
        "intent_aliases": ["start_xiaoyi_ai", "start_xiaoyi", "启动小懿", "打开小懿AI", "启动小懿AI"],
        "keywords": ["启动小懿", "打开小懿", "启动小懿ai", "打开小懿ai", "小懿服务", "拉起小懿"],
        "button_selector": "#btnXiaoyiStart",
        "button_label": "启动小懿AI",
        "backend_request": {"method": "POST", "path": "/api/xiaoyi/launch", "body": {"confirm": True}},
        "linked_system": "xiaoyi_ai",
        "requires_human_confirm": True,
    },
    {
        "id": "open_simulation_panel",
        "label": "打开仿真在线面板",
        "category": "top_ai_panel",
        "description": "打开AI决策面板里的仿真状态、Gymnasium 状态和模拟器入口。",
        "intent_aliases": ["open_simulation_panel", "打开仿真面板", "打开仿真在线面板"],
        "keywords": ["仿真面板", "仿真在线", "打开仿真", "看仿真", "仿真状态"],
        "button_selector": "#btnXiaoyiOpenSimulationPanel",
        "button_label": "打开仿真面板",
        "backend_request": {"method": "LOCAL", "path": "front-end:open-top-panel", "body": {"panel": "simulation"}},
        "linked_system": "top_ai_decision_panel",
        "requires_human_confirm": False,
    },
    {
        "id": "open_marl_panel",
        "label": "打开 RL 策略面板",
        "category": "top_ai_panel",
        "description": "打开 AI 决策面板里的 RL 策略测试与训练状态区。",
        "intent_aliases": ["open_marl_panel", "打开MARL面板", "打开策略面板"],
        "keywords": ["marl面板", "策略面板", "打开策略", "训练状态面板", "强化学习面板"],
        "button_selector": "#btnXiaoyiOpenMarlPanel",
        "button_label": "打开 RL 面板",
        "backend_request": {"method": "LOCAL", "path": "front-end:open-top-panel", "body": {"panel": "marl"}},
        "linked_system": "top_ai_decision_panel",
        "requires_human_confirm": False,
    },
    {
        "id": "open_carbon_panel",
        "label": "打开低碳优先面板",
        "category": "top_ai_panel",
        "description": "打开AI决策面板里的低碳偏好、碳价和减排量区。",
        "intent_aliases": ["open_carbon_panel", "打开低碳面板", "打开碳排面板"],
        "keywords": ["低碳面板", "碳排面板", "打开低碳", "碳价面板", "碳排决策"],
        "button_selector": "#btnXiaoyiOpenCarbonPanel",
        "button_label": "打开低碳面板",
        "backend_request": {"method": "LOCAL", "path": "front-end:open-top-panel", "body": {"panel": "carbon"}},
        "linked_system": "top_ai_decision_panel",
        "requires_human_confirm": False,
    },
    {
        "id": "open_shore_panel",
        "label": "打开岸电联动面板",
        "category": "top_ai_panel",
        "description": "打开AI决策面板里的岸电窗口、替代减排和岸电训练区。",
        "intent_aliases": ["open_shore_panel", "打开岸电面板", "打开岸电联动面板"],
        "keywords": ["岸电面板", "岸电联动", "打开岸电", "岸电窗口", "岸电决策"],
        "button_selector": "#btnXiaoyiOpenShorePanel",
        "button_label": "打开岸电面板",
        "backend_request": {"method": "LOCAL", "path": "front-end:open-top-panel", "body": {"panel": "shore"}},
        "linked_system": "top_ai_decision_panel",
        "requires_human_confirm": False,
    },
    {
        "id": "open_api_panel",
        "label": "打开 API 同步面板",
        "category": "top_ai_panel",
        "description": "打开AI决策面板里的 API 同步与联动健康检查区。",
        "intent_aliases": ["open_api_panel", "打开API面板", "打开健康检查面板"],
        "keywords": ["api面板", "健康检查面板", "同步面板", "打开api", "联动健康"],
        "button_selector": "#btnXiaoyiOpenApiPanel",
        "button_label": "打开 API 面板",
        "backend_request": {"method": "LOCAL", "path": "front-end:open-top-panel", "body": {"panel": "api"}},
        "linked_system": "top_ai_decision_panel",
        "requires_human_confirm": False,
    },
    {
        "id": "refresh_dashboard_snapshot",
        "label": "刷新仿真 / 重新同步仪表盘",
        "category": "top_ai_panel",
        "description": "按当前绿色偏好和碳价重算能碳驾驶舱快照。",
        "intent_aliases": ["refresh_dashboard_snapshot", "刷新仿真", "重新同步", "同步仪表盘"],
        "keywords": ["刷新仿真", "重新同步", "同步仪表盘", "刷新仪表盘", "重算", "重算能碳", "刷新数据"],
        "button_selector": "#btnXiaoyiRefreshDashboard",
        "button_label": "刷新仿真",
        "backend_request": {"method": "POST", "path": "/api/optimization/recompute"},
        "linked_system": "top_ai_decision_panel",
        "requires_human_confirm": False,
    },
    {
        "id": "run_linkage_health_check",
        "label": "联动健康检查",
        "category": "top_ai_panel",
        "description": "检查驾驶舱、小懿、RL 接口和航行模拟器联动状态。",
        "intent_aliases": ["run_linkage_health_check", "健康检查", "检查联动状态"],
        "keywords": ["健康检查", "检查接口", "联动状态", "api健康", "系统状态", "小懿状态", "接口状态"],
        "button_selector": "#btnXiaoyiHealthCheck",
        "button_label": "健康检查",
        "backend_request": {"method": "GET", "path": "/api/linkage/health"},
        "linked_system": "top_ai_decision_panel",
        "requires_human_confirm": False,
    },
    {
        "id": "check_sailing_status",
        "label": "检查航行模拟器状态",
        "category": "top_ai_panel",
        "description": "读取航行模拟器项目、Godot 可执行文件和进程状态。",
        "intent_aliases": ["check_sailing_status", "检查模拟器", "查看模拟器状态"],
        "keywords": ["检查模拟器", "模拟器状态", "查看模拟器", "godot状态", "航行模拟器状态"],
        "button_selector": "#btnXiaoyiCheckSailingStatus",
        "button_label": "检查模拟器",
        "backend_request": {"method": "GET", "path": "/api/sailing/status"},
        "linked_system": "sailing_simulator",
        "requires_human_confirm": False,
    },
    {
        "id": "set_efficiency_priority",
        "label": "切到效率优先",
        "category": "top_ai_panel",
        "description": "把绿色偏好切到 0.25，对应顶层低碳面板的效率优先按钮。",
        "intent_aliases": ["set_efficiency_priority", "效率优先", "切到效率优先"],
        "keywords": ["效率优先", "偏效率", "效率模式", "提高效率", "少延误"],
        "button_selector": "#btnXiaoyiPreferenceEfficiency",
        "button_label": "效率优先",
        "backend_request": {"method": "POST", "path": "/api/optimization/recompute", "body": {"green_preference": 0.25}},
        "linked_system": "top_ai_decision_panel",
        "requires_human_confirm": False,
    },
    {
        "id": "set_balanced_dispatch",
        "label": "切到均衡调度",
        "category": "top_ai_panel",
        "description": "把绿色偏好切到 0.50，对应顶层低碳面板的均衡调度按钮。",
        "intent_aliases": ["set_balanced_dispatch", "均衡调度", "切到均衡调度"],
        "keywords": ["均衡调度", "平衡调度", "成本碳排均衡", "均衡模式", "折中"],
        "button_selector": "#btnXiaoyiPreferenceBalanced",
        "button_label": "均衡调度",
        "backend_request": {"method": "POST", "path": "/api/optimization/recompute", "body": {"green_preference": 0.50}},
        "linked_system": "top_ai_decision_panel",
        "requires_human_confirm": False,
    },
    {
        "id": "set_low_carbon_priority",
        "label": "切到低碳优先",
        "category": "top_ai_panel",
        "description": "把绿色偏好切到 0.82，对应顶层低碳面板的低碳优先按钮。",
        "intent_aliases": ["set_low_carbon_priority", "低碳优先", "切到低碳优先"],
        "keywords": ["低碳优先", "低碳模式", "减排优先", "碳排最低", "绿色优先"],
        "button_selector": "#btnXiaoyiPreferenceLowCarbon",
        "button_label": "低碳优先",
        "backend_request": {"method": "POST", "path": "/api/optimization/recompute", "body": {"green_preference": 0.82}},
        "linked_system": "top_ai_decision_panel",
        "requires_human_confirm": False,
    },
    {
        "id": "set_shore_power_preference",
        "label": "切到岸电优先",
        "category": "top_ai_panel",
        "description": "把绿色偏好切到 0.88，对应顶层岸电联动面板的切到岸电优先按钮。",
        "intent_aliases": ["set_shore_power_preference", "岸电优先", "切到岸电优先"],
        "keywords": ["岸电优先", "切到岸电", "岸电模式", "优先岸电", "岸电接入优先"],
        "button_selector": "#btnXiaoyiPreferenceShorePower",
        "button_label": "岸电优先",
        "backend_request": {"method": "POST", "path": "/api/optimization/recompute", "body": {"green_preference": 0.88}},
        "linked_system": "top_ai_decision_panel",
        "requires_human_confirm": False,
    },
    {
        "id": "start_rl_training",
        "label": "启动 RL 训练",
        "category": "rl_training",
        "description": "按能碳目标生成推荐参数，启动训练进度、日志和策略产物。",
        "intent_aliases": ["start_rl_training", "开始训练", "启动训练", "开始MARL训练", "启动RL训练"],
        "keywords": ["开始训练", "启动训练", "rl训练", "marl训练", "强化学习训练", "训练低碳策略", "训练碳排", "训练岸电", "低风险训练"],
        "button_selector": "#btnStartTraining",
        "button_label": "启动训练",
        "backend_request": {"method": "POST", "path": "/api/rl/train/start"},
        "linked_system": "energy_carbon_rl",
        "requires_human_confirm": True,
    },
    {
        "id": "view_rl_training_status",
        "label": "查看训练状态",
        "category": "rl_training",
        "description": "返回 step、reward、entropy、policy 版本和训练日志。",
        "intent_aliases": ["view_rl_training_status", "查看训练状态", "查询训练状态"],
        "keywords": ["训练状态", "查看训练", "训练指标", "训练日志", "reward", "entropy", "policy版本"],
        "button_selector": "#btnTrainingStatus",
        "button_label": "查看训练状态",
        "backend_request": {"method": "GET", "path": "/api/rl/train/status"},
        "linked_system": "energy_carbon_rl",
        "requires_human_confirm": False,
    },
    {
        "id": "pause_rl_training",
        "label": "暂停 RL 训练",
        "category": "rl_training",
        "description": "冻结当前训练步数、进度和计时，保留任务与检查点以便继续。",
        "intent_aliases": ["pause_rl_training", "暂停训练", "暂停MARL训练", "暂停RL训练"],
        "keywords": ["暂停训练", "训练暂停", "停一下训练", "暂停marl", "暂停rl"],
        "button_selector": "#btnPauseTraining",
        "button_label": "暂停训练",
        "backend_request": {"method": "POST", "path": "/api/rl/train/pause"},
        "linked_system": "energy_carbon_rl",
        "requires_human_confirm": False,
    },
    {
        "id": "resume_rl_training",
        "label": "继续 RL 训练",
        "category": "rl_training",
        "description": "从暂停位置继续累计训练进度和计时。",
        "intent_aliases": ["resume_rl_training", "继续训练", "恢复训练", "继续MARL训练"],
        "keywords": ["继续训练", "恢复训练", "接着训练", "继续marl", "继续rl"],
        "button_selector": "#btnPauseTraining",
        "button_label": "继续训练",
        "backend_request": {"method": "POST", "path": "/api/rl/train/resume"},
        "linked_system": "energy_carbon_rl",
        "requires_human_confirm": False,
    },
    {
        "id": "stop_rl_training",
        "label": "停止 RL 训练",
        "category": "rl_training",
        "description": "结束当前训练任务，停止进度增长并保留当前检查点。",
        "intent_aliases": ["stop_rl_training", "停止训练", "终止训练", "停止MARL训练"],
        "keywords": ["停止训练", "终止训练", "结束训练", "停止marl", "停止rl"],
        "button_selector": "#btnStopTraining",
        "button_label": "停止训练",
        "backend_request": {"method": "POST", "path": "/api/rl/train/stop"},
        "linked_system": "energy_carbon_rl",
        "requires_human_confirm": False,
    },
    {
        "id": "run_policy_test",
        "label": "读取登记策略测试",
        "category": "policy_test",
        "description": "读取通过完整性、数据一致性与安全门禁的登记留出集评估。",
        "intent_aliases": ["run_policy_test", "策略测试", "读取登记策略测试", "训练后策略测试"],
        "keywords": ["策略测试", "训练后测试", "测试策略", "登记证据", "留出集评估", "最新policy"],
        "button_selector": "#btnPolicyTest",
        "button_label": "登记策略测试",
        "backend_request": {"method": "GET", "path": "/api/rl/registry"},
        "linked_system": "energy_carbon_rl",
        "requires_human_confirm": False,
    },
    {
        "id": "verify_policy_for_online",
        "label": "验证策略能否上线",
        "category": "safety_dry_run",
        "description": "先校验策略，再执行 dispatch dry-run，不直接生产下发。",
        "intent_aliases": ["verify_policy_for_online", "验证策略上线", "验证这个策略能不能上线"],
        "keywords": ["验证这个策略能不能上线", "上线验证", "安全校验", "dry-run", "dry run", "能上线吗"],
        "button_selector": "#btnVerifyPolicy",
        "button_label": "上线验证 dry-run",
        "backend_request": {"method": "POST", "path": "/api/rl/dispatch", "body": {"dry_run": True}},
        "linked_system": "energy_carbon_rl",
        "requires_human_confirm": False,
    },
    {
        "id": "open_sailing_simulator",
        "label": "打开航行模拟器",
        "category": "desktop_linkage",
        "description": "启动 SAILING_SIM_PROJECT 配置的 Godot 主场景。",
        "intent_aliases": ["open_sailing_simulator", "打开航行模拟器", "启动航行模拟器", "打开模拟器", "启动模拟器"],
        "keywords": ["打开航行模拟器", "启动航行模拟器", "打开模拟器", "启动模拟器", "godot模拟器", "船舶模拟器", "航行沙盘"],
        "button_selector": "#btnSailingLaunch",
        "button_label": "启动航行模拟器",
        "backend_request": {"method": "POST", "path": "/api/sailing/launch", "body": {"confirm": True}},
        "linked_system": "sailing_simulator",
        "requires_human_confirm": True,
    },
    {
        "id": "start_navigation_demo",
        "label": "启动航线演示",
        "category": "desktop_linkage",
        "description": "启动 Godot 航行模拟器并加载航线演示预设。",
        "intent_aliases": ["start_navigation_demo", "启动航线演示", "开始航线演示", "启动航行演示"],
        "keywords": ["启动航线演示", "开始航线演示", "演示航线", "路线演示", "自动航行", "导航演示"],
        "button_selector": "#btnSailingDemo",
        "button_label": "启动航线演示",
        "backend_request": {"method": "POST", "path": "/api/sailing/actions/execute", "body": {"action_id": "start_navigation_demo", "confirm": True}},
        "linked_system": "sailing_simulator",
        "requires_human_confirm": True,
    },
    {
        "id": "switch_ship_view",
        "label": "切换船舶视角",
        "category": "desktop_linkage",
        "description": "Godot 端无 HTTP 控制入口时，先启动模拟器并标记视角动作。",
        "intent_aliases": ["switch_ship_view", "切换船舶视角", "切换视角", "换船"],
        "keywords": ["切换船舶视角", "查看船舶视角", "跟随船舶", "切换视角", "换船", "切换船"],
        "button_selector": "#btnShipView",
        "button_label": "切换船舶视角",
        "backend_request": {"method": "POST", "path": "/api/sailing/actions/execute", "body": {"action_id": "switch_ship_view", "confirm": True}},
        "linked_system": "sailing_simulator",
        "requires_human_confirm": True,
    },
    {
        "id": "run_sailing_rl_smoke_test",
        "label": "运行航行 RL smoke test",
        "category": "desktop_linkage",
        "description": "用 Godot headless 执行航行场景 smoke test。",
        "intent_aliases": ["run_sailing_rl_smoke_test", "运行航行测试", "运行模拟器测试"],
        "keywords": ["运行航行测试", "运行模拟器测试", "航行smoke", "模拟器smoke", "rl航行测试", "烟雾测试"],
        "button_selector": "#btnSailingSmoke",
        "button_label": "运行 smoke test",
        "backend_request": {"method": "POST", "path": "/api/sailing/actions/execute", "body": {"action_id": "run_sailing_rl_smoke_test", "confirm": True}},
        "linked_system": "sailing_simulator",
        "requires_human_confirm": True,
    },
]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _append_log(kind: str, status: str, detail: dict[str, Any]) -> None:
    _action_log.insert(0, {"ts": _utc_now(), "kind": kind, "status": status, "detail": detail})
    del _action_log[100:]


def _probe_http(url: str, timeout_sec: float = 0.6) -> dict[str, Any]:
    try:
        request = UrlRequest(url, headers={"User-Agent": "energy-carbon-linkage/1.0"})
        with urlopen(request, timeout=timeout_sec) as response:
            status_code = int(getattr(response, "status", 200))
            return {"ok": 200 <= status_code < 300, "status_code": status_code, "error": None}
    except URLError:
        logger.info("Linked HTTP service is unreachable: %s", url)
        return {"ok": False, "status_code": None, "error": "connection_failed"}
    except Exception:
        logger.exception("Linked HTTP service probe failed: %s", url)
        return {"ok": False, "status_code": None, "error": "probe_failed"}


def _post_json(url: str, payload: dict[str, Any], timeout_sec: float = 12.0) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    request = UrlRequest(
        url,
        data=data,
        headers={"Content-Type": "application/json", "User-Agent": "energy-carbon-linkage/1.0"},
        method="POST",
    )
    with urlopen(request, timeout=timeout_sec) as response:
        return json.loads(response.read().decode("utf-8") or "{}")


def _process_state(process: subprocess.Popen[Any] | None) -> dict[str, Any]:
    if process is None:
        return {"tracked": False, "running": False, "pid": None, "returncode": None}
    returncode = process.poll()
    return {
        "tracked": True,
        "running": returncode is None,
        "pid": process.pid,
        "returncode": returncode,
    }


def _public_path_ref(path: Path) -> str:
    """Return a portable integration reference without exposing a host path."""
    try:
        return path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
    except (OSError, ValueError):
        return f"external-integration/{path.name or 'configured-target'}"


def _sanitize_integration_output(value: str) -> str:
    sanitized = str(value)
    replacements = {
        str(PROJECT_ROOT): "<repository-root>",
        str(XIAOYI_PROJECT): "<xiaoyi-integration>",
        str(SAILING_PROJECT): "<sailing-integration>",
        str(GODOT_EXECUTABLE): f"<godot:{GODOT_EXECUTABLE.name}>",
    }
    for local_path, portable_label in sorted(
        replacements.items(), key=lambda item: len(item[0]), reverse=True
    ):
        if local_path:
            sanitized = sanitized.replace(local_path, portable_label)
    return sanitized


def _python_for_xiaoyi() -> str:
    candidates = [
        PROJECT_ROOT / "backend" / ".venv" / "bin" / "python",
        Path(sys.executable),
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return "python"


def _xiaoyi_start_command() -> str:
    return (
        f"cd {XIAOYI_PROJECT} && python scripts/build_index.py && "
        f"{_python_for_xiaoyi()} -m uvicorn app.main:app --host 127.0.0.1 --port 8010"
    )


def xiaoyi_status() -> dict[str, Any]:
    health_url = f"{XIAOYI_BASE_URL}/health"
    probe = _probe_http(health_url)
    return {
        "ok": bool(probe["ok"]),
        "updated_at": _utc_now(),
        "name": "小懿AI",
        "online": bool(probe["ok"]),
        "label": "小懿在线" if probe["ok"] else ("小懿可启动" if XIAOYI_PROJECT.exists() else "小懿不可启动"),
        "base_url": XIAOYI_BASE_URL,
        "health_url": health_url,
        "chat_url": f"{XIAOYI_BASE_URL}/api/chat",
        "project": {"path": _public_path_ref(XIAOYI_PROJECT), "exists": XIAOYI_PROJECT.exists()},
        "run_script": {"path": _public_path_ref(XIAOYI_PROJECT / "run.sh"), "exists": (XIAOYI_PROJECT / "run.sh").exists()},
        "launcher": "configured-local-integration",
        "probe": probe,
        "process": _process_state(_xiaoyi_process),
        "last_launch": _last_xiaoyi_launch,
    }


def launch_xiaoyi(payload: dict[str, Any] | None = None, dry_run: bool = False) -> dict[str, Any]:
    global _last_xiaoyi_launch, _xiaoyi_process
    payload = payload or {}
    status = xiaoyi_status()
    packet = {
        "type": "xiaoyi_service_launch",
        "dry_run": dry_run,
        "launcher": "configured-local-integration",
        "health_url": status["health_url"],
        "chat_url": status["chat_url"],
    }
    if status["online"]:
        packet.update({"status": "already_online", "health": status})
        return packet
    if not XIAOYI_PROJECT.exists():
        packet.update({"status": "failed", "error": "小懿AI项目目录不存在", "health": status})
        return packet
    if dry_run:
        packet["status"] = "ready_to_launch"
        return packet

    _xiaoyi_process = subprocess.Popen(
        ["bash", "-lc", _xiaoyi_start_command()],
        cwd=str(XIAOYI_PROJECT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        env={**os.environ, "ENERGY_CARBON_LINKAGE_SOURCE": str(payload.get("source") or "energy-carbon-cockpit")},
    )
    _last_xiaoyi_launch = {"ts": _utc_now(), "pid": _xiaoyi_process.pid, "source": payload.get("source") or "energy-carbon-cockpit"}
    packet.update({"status": "launched", "pid": _xiaoyi_process.pid})
    for _ in range(20):
        health = xiaoyi_status()
        if health["online"]:
            packet.update({"status": "online", "health": health})
            break
        time.sleep(0.35)
    _append_log("start_xiaoyi_ai", str(packet["status"]), packet)
    return packet


def sailing_status() -> dict[str, Any]:
    project_file = SAILING_PROJECT / "project.godot"
    smoke_script = SAILING_PROJECT / "tools" / "ship_rl_smoke_test.gd"
    launchable = SAILING_PROJECT.exists() and project_file.exists() and GODOT_EXECUTABLE.exists()
    return {
        "ok": launchable,
        "updated_at": _utc_now(),
        "name": "航行模拟器",
        "launchable": launchable,
        "label": "航行模拟器可启动" if launchable else "航行模拟器不可启动",
        "control_mode": "launch_and_preset_scene",
        "project_root": {"path": _public_path_ref(SAILING_PROJECT), "exists": SAILING_PROJECT.exists()},
        "project_file": {"path": _public_path_ref(project_file), "exists": project_file.exists()},
        "godot_executable": {"name": GODOT_EXECUTABLE.name, "exists": GODOT_EXECUTABLE.exists()},
        "main_scene": MAIN_SCENE,
        "smoke_script": {"path": _public_path_ref(smoke_script), "exists": smoke_script.exists()},
        "process": _process_state(_sailing_process),
        "last_launch": _last_sailing_launch,
    }


def launch_sailing(payload: dict[str, Any] | None = None, dry_run: bool = False) -> dict[str, Any]:
    global _last_sailing_launch, _sailing_process
    payload = payload or {}
    status = sailing_status()
    preset = str(payload.get("preset") or "main_scene")
    command = [str(GODOT_EXECUTABLE), "--path", str(SAILING_PROJECT), MAIN_SCENE]
    packet = {
        "type": "godot_launch",
        "dry_run": dry_run,
        "preset": preset,
        "scene": MAIN_SCENE,
        "launcher": "configured-local-integration",
        "note": "Godot 端暂未开放 HTTP 控制；当前联动执行启动和预设主场景加载。",
    }
    if not status["launchable"]:
        packet.update({"status": "failed", "error": "航行模拟器项目或 Godot 可执行文件不存在", "status_detail": status})
        return packet
    if dry_run:
        packet["status"] = "ready_to_launch"
        return packet
    running = _process_state(_sailing_process)
    if running["running"] and not payload.get("force_new"):
        packet.update({"status": "already_running", "pid": running["pid"]})
        return packet
    _sailing_process = subprocess.Popen(
        command,
        cwd=str(SAILING_PROJECT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        env={**os.environ, "ENERGY_CARBON_SAILING_PRESET": preset},
    )
    _last_sailing_launch = {"ts": _utc_now(), "pid": _sailing_process.pid, "preset": preset, "source": payload.get("source") or "energy-carbon-cockpit"}
    packet.update({"status": "launched", "pid": _sailing_process.pid})
    _append_log("open_sailing_simulator", "launched", packet)
    return packet


def run_sailing_smoke(payload: dict[str, Any] | None = None, dry_run: bool = False) -> dict[str, Any]:
    payload = payload or {}
    command = [str(GODOT_EXECUTABLE), "--headless", "--path", str(SAILING_PROJECT), "--script", SMOKE_SCRIPT]
    packet = {"type": "godot_headless_smoke_test", "dry_run": dry_run, "launcher": "configured-local-integration", "script": SMOKE_SCRIPT}
    if not sailing_status()["launchable"]:
        packet.update({"status": "failed", "error": "航行模拟器项目或 Godot 可执行文件不存在"})
        return packet
    if dry_run:
        packet["status"] = "ready_to_run"
        return packet
    try:
        completed = subprocess.run(command, cwd=str(SAILING_PROJECT), capture_output=True, text=True, timeout=35, check=False)
        output = (completed.stdout or "") + ("\n" + completed.stderr if completed.stderr else "")
        ok = completed.returncode == 0 and "SHIP_RL_OK" in output
        packet.update({"status": "passed" if ok else "failed", "returncode": completed.returncode, "ok_marker": "SHIP_RL_OK" in output, "output_tail": _sanitize_integration_output(output[-1600:])})
    except subprocess.TimeoutExpired:
        logger.warning("Sailing smoke test timed out")
        packet.update({"status": "timeout", "error": "smoke_test_timeout"})
    _append_log("run_sailing_rl_smoke_test", str(packet["status"]), packet)
    return packet


def _objective_from_instruction(text: str, requested: str | None = None) -> str:
    q = text.replace(" ", "").lower()
    if requested in TRAINING_OBJECTIVES:
        return str(requested)
    if "岸电" in q:
        return "shore_power_priority"
    if "峰值" in q or "负荷" in q or "削峰" in q:
        return "peak_smoothing"
    if "成本" in q or "电费" in q or "均衡" in q:
        return "cost_carbon_balance"
    if "低风险" in q or "试运行" in q or "安全" in q:
        return "low_risk_validation"
    if "碳" in q or "低碳" in q or "减排" in q:
        return "carbon_min"
    return "cost_carbon_balance"


def _build_training_config(instruction: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    submitted = dict(payload.get("config") or {})
    requested = {**payload, **submitted}

    def selected(name: str, fallback: Any) -> Any:
        value = requested.get(name)
        return fallback if value is None else value

    objective_id = _objective_from_instruction(instruction, requested.get("objective_id"))
    profile = TRAINING_OBJECTIVES[objective_id]
    try:
        dataset_id = registered_dataset_id(
            str(requested.get("dataset_id") or requested.get("data_file") or DEFAULT_DATASET_ID)
        )
    except ValueError as exc:
        logger.info("Assistant dataset selection rejected", exc_info=exc)
        raise HTTPException(status_code=422, detail="dataset_reference_invalid") from None
    try:
        scenario = resolve_training_scenario(
            str(requested.get("scenario") or "") or None,
            dataset_id,
        )
    except ValueError as exc:
        logger.info("Assistant scenario selection rejected", exc_info=exc)
        raise HTTPException(status_code=422, detail="scenario_configuration_invalid") from None
    return {
        "objective_id": objective_id,
        "objective_label": requested.get("objective_label") or profile["label"],
        "algorithm": requested.get("algorithm") or profile["algorithm"],
        "dataset_id": dataset_id,
        "data_file": dataset_id,
        **scenario,
        "asset_group": requested.get("asset_group") or "berth_shore_power_yard_truck",
        "horizon_min": selected("horizon_min", profile["horizon_min"]),
        "step_min": 60,
        "total_steps": selected("total_steps", profile["total_steps"]),
        "batch_size": selected("batch_size", 256),
        "learning_rate": selected("learning_rate", 0.0003 if profile["algorithm"] != "ppo" else 0.00025),
        "gamma": selected("gamma", 0.995),
        "tau": selected("tau", 0.005),
        "entropy_coef": selected("entropy_coef", 0.0),
        "guardrail_mode": requested.get("guardrail_mode") or "strict",
        "reward_weights": requested.get("reward_weights") or profile["reward_weights"],
        "reason": requested.get("objective_reason") or profile["reason"],
        "seed": int(requested.get("seed") or 20260720),
        "eval_interval": selected("eval_interval", 5_000),
        "checkpoint_interval": selected("checkpoint_interval", 20_000),
        "render_during_training": False,
    }


def _historical_training_run() -> dict[str, Any]:
    return training_service.history()


def _training_status() -> dict[str, Any]:
    return training_service.status()


def _control_training(action: str) -> dict[str, Any]:
    return training_service.control(action)


def _action_score(action: dict[str, Any], instruction: str, action_id: str | None) -> tuple[int, list[str]]:
    if action_id and action_id == action["id"]:
        return 10_000, ["action_id"]
    q = instruction.replace(" ", "").lower()
    score = 0
    reasons: list[str] = []
    for alias in action.get("intent_aliases", []):
        if str(alias).replace(" ", "").lower() in q:
            score += 80
            reasons.append("alias_in_instruction")
    for keyword in action.get("keywords", []):
        key = str(keyword).replace(" ", "").lower()
        if key and key in q:
            score += 30 + min(len(key), 20)
            reasons.append(f"keyword:{keyword}")
    return score, reasons


def _resolve_action(instruction: str, action_id: str | None = None) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    candidates: list[dict[str, Any]] = []
    for action in ACTION_REGISTRY:
        score, reasons = _action_score(action, instruction, action_id)
        if score > 0:
            candidates.append({**action, "score": score, "match_reasons": reasons})
    candidates.sort(key=lambda item: int(item["score"]), reverse=True)
    return (candidates[0] if candidates else None), candidates


def _coerce_float(value: Any, default: float, minimum: float | None = None, maximum: float | None = None) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    if minimum is not None:
        number = max(minimum, number)
    if maximum is not None:
        number = min(maximum, number)
    return number


def _snapshot_summary(green_preference: float, carbon_price: float) -> dict[str, Any]:
    snapshot = KpiEngine().build_snapshot(green_preference=green_preference, carbon_price=carbon_price)
    data = snapshot.model_dump()
    baseline, optimized = data["strategies"]
    carbon_reduction_ton = round((baseline["total_carbon_kg"] - optimized["total_carbon_kg"]) / 1000, 2)
    shore_power_gain = round(optimized["shore_power_usage_rate"] - baseline["shore_power_usage_rate"], 1)
    kpis = {
        item["key"]: {"label": item["label"], "value": item["value"], "unit": item["unit"], "delta": item["delta"]}
        for item in data["kpis"]
    }
    return {
        "scenario_id": data["scenario_id"],
        "green_preference": data["green_preference"],
        "carbon_price_cny_per_ton": data["carbon_market"]["carbon_price_cny_per_ton"],
        "kpis": kpis,
        "carbon_reduction_ton": carbon_reduction_ton,
        "shore_power_gain_pct": shore_power_gain,
        "optimized_policy": {
            "strategy": optimized["strategy"],
            "total_carbon_kg": optimized["total_carbon_kg"],
            "shore_power_usage_rate": optimized["shore_power_usage_rate"],
            "total_cost_cny": optimized["total_cost_cny"],
        },
        "carbon_market": {
            "total_cost_saving_cny": data["carbon_market"]["total_cost_saving_cny"],
            "abatement_ton": data["carbon_market"]["abatement_ton"],
            "abatement_value_cny": data["carbon_market"]["abatement_value_cny"],
        },
        "summary": f"重算完成：减排 {carbon_reduction_ton} t，岸电提升 {shore_power_gain} 个百分点。",
    }


def _dashboard_refresh(payload: dict[str, Any], dry_run: bool) -> dict[str, Any]:
    green_preference = _coerce_float(payload.get("green_preference"), 0.5, 0, 1)
    carbon_price = _coerce_float(payload.get("carbon_price_cny_per_ton"), 85.0, 0, None)
    if dry_run:
        return {
            "status": "ready_to_recompute",
            "green_preference": green_preference,
            "carbon_price_cny_per_ton": carbon_price,
            "target": "/api/optimization/recompute",
        }
    summary = _snapshot_summary(green_preference, carbon_price)
    _append_log("refresh_dashboard_snapshot", "recomputed", summary)
    return {"status": "recomputed", **summary}


def _preference_action_result(action_id: str, payload: dict[str, Any], dry_run: bool) -> dict[str, Any]:
    preference = PREFERENCE_ACTIONS[action_id]
    green_preference = float(preference["green_preference"])
    carbon_price = _coerce_float(payload.get("carbon_price_cny_per_ton"), 85.0, 0, None)
    if dry_run:
        return {
            "status": "ready_to_apply_preference",
            "action_id": action_id,
            "label": preference["label"],
            "green_preference": green_preference,
            "panel": preference["panel"],
        }
    summary = _snapshot_summary(green_preference, carbon_price)
    result = {
        "status": "preference_applied",
        "action_id": action_id,
        "label": preference["label"],
        "panel": preference["panel"],
        **summary,
    }
    _append_log(action_id, "preference_applied", result)
    return result


def _top_panel_result(action_id: str, dry_run: bool) -> dict[str, Any]:
    panel = TOP_PANEL_ACTIONS[action_id]
    return {
        "status": "front_end_panel_ready" if dry_run else "front_end_panel_opened",
        "panel": panel["panel"],
        "label": panel["label"],
        "note": "该动作由前端打开对应AI决策面板。",
    }


def _runtime_signal(snapshot: dict[str, Any], field_id: str) -> dict[str, Any]:
    item = snapshot.get("signals", {}).get(field_id, {})
    return {
        "value": item.get("value"),
        "unit": item.get("unit"),
        "source_type": item.get("source_type"),
        "quality_status": item.get("quality_status"),
    }


def _latest_runtime_decision() -> dict[str, Any] | None:
    items = runtime_decision_service.list(limit=1).get("items", [])
    return items[0] if items else None


def _runtime_state_summary() -> dict[str, Any]:
    snapshot = runtime_simulator.snapshot(advance=False)
    forecast: dict[str, Any] | None = None
    forecast_error: str | None = None
    if snapshot.get("decision_allowed"):
        try:
            forecast = runtime_forecast_model.predict(snapshot)
        except RuntimeError as exc:
            forecast_error = str(exc)
    else:
        forecast_error = "runtime_quality_gate_failed"
    quality = snapshot.get("quality", {})
    current_kpis = snapshot.get("kpis", {}).get("current", {})
    forecast_points = []
    if forecast:
        for point in forecast.get("points", []):
            predictions = point.get("predictions", {})
            forecast_points.append(
                {
                    "horizon_hours": point.get("horizon_hours"),
                    "terminal_load_kw": predictions.get("terminal_load_kw"),
                    "grid_carbon_kg_per_kwh": predictions.get("grid_carbon_kg_per_kwh"),
                    "electricity_price_cny_per_kwh": predictions.get("electricity_price_cny_per_kwh"),
                    "throughput_demand_teu_h": predictions.get("throughput_demand_teu_h"),
                }
            )
    state = {
        "status": "grounded_runtime_summary",
        "data_mode": snapshot.get("data_mode"),
        "simulator_state": snapshot.get("simulator_state"),
        "scenario_id": snapshot.get("active_scenario", {}).get("scenario_id"),
        "step": snapshot.get("step"),
        "virtual_event_time": snapshot.get("virtual_event_time"),
        "field_count": len(snapshot.get("signals", {})),
        "quality_gate": {
            "status": quality.get("status"),
            "critical_reasons": quality.get("critical_reasons", []),
            "decision_allowed": bool(snapshot.get("decision_allowed")),
            "classification_pct": quality.get("classification_pct", {}),
        },
        "signals": {
            "grid_import": _runtime_signal(snapshot, "grid.import_power_kw"),
            "transformer_loading": _runtime_signal(snapshot, "transformer.loading_pct"),
            "battery_soc": _runtime_signal(snapshot, "battery.soc_pct"),
            "battery_temperature": _runtime_signal(snapshot, "battery.temperature_c"),
            "solar_available": _runtime_signal(snapshot, "solar.available_power_kw"),
            "shore_power_load": _runtime_signal(snapshot, "shore_power.load_kw"),
            "operation_queue": _runtime_signal(snapshot, "operations.queue_teu"),
        },
        "current_kpis": current_kpis,
        "forecast": {
            "available": forecast is not None,
            "true_model_inference": bool(forecast and forecast.get("true_model_inference")),
            "model_id": forecast.get("model", {}).get("model_id") if forecast else None,
            "points": forecast_points,
            "error": forecast_error,
        },
        "trace": {
            "snapshot_sha256": snapshot.get("snapshot_sha256"),
            "dataset_id": snapshot.get("dataset", {}).get("dataset_id"),
            "dataset_sha256": snapshot.get("dataset", {}).get("dataset_sha256"),
        },
        "production_boundary": {
            "simulation_mode": True,
            "live_data_verified": False,
            "dispatch_allowed": False,
            "production_authority": False,
        },
    }
    state["summary"] = (
        f"实时模拟器 {state['simulator_state']}，场景 {state['scenario_id']}，"
        f"质量门禁 {str(state['quality_gate']['status']).upper()}，"
        f"电网进口 {state['signals']['grid_import']['value']} kW，"
        f"变压器负载率 {state['signals']['transformer_loading']['value']}%，"
        f"储能 SOC {state['signals']['battery_soc']['value']}%。"
    )
    return state


def _runtime_handover_summary() -> dict[str, Any]:
    state = _runtime_state_summary()
    latest = _latest_runtime_decision()
    latest_summary = None
    if latest:
        latest_summary = {
            "decision_id": latest.get("decision_id"),
            "status": latest.get("status"),
            "risk_level": latest.get("risk_level"),
            "approval_count": len(latest.get("approvals", [])),
            "required_approvals": latest.get("required_approvals"),
            "created_at": latest.get("created_at"),
            "objective": latest.get("objective"),
        }
    return {
        "status": "grounded_runtime_handover",
        "summary": state["summary"],
        "shift_handover": {
            "runtime": {
                "simulator_state": state["simulator_state"],
                "scenario_id": state["scenario_id"],
                "step": state["step"],
                "virtual_event_time": state["virtual_event_time"],
            },
            "quality_gate": state["quality_gate"],
            "signals": state["signals"],
            "current_kpis": state["current_kpis"],
            "forecast": state["forecast"],
            "latest_decision": latest_summary,
            "operator_note": "交班内容来自当前模拟快照与模型推理；任何建议仍须由独立人工角色审批后才能模拟执行。",
        },
        "production_boundary": state["production_boundary"],
    }


def _runtime_alert_triage() -> dict[str, Any]:
    snapshot = runtime_simulator.snapshot(advance=False)
    quality = snapshot.get("quality", {})
    abnormal = [
        {
            "field_id": field_id,
            "quality_status": item.get("quality_status"),
            "value": item.get("value"),
            "unit": item.get("unit"),
            "source_type": item.get("source_type"),
        }
        for field_id, item in snapshot.get("signals", {}).items()
        if item.get("quality_status") not in {"正常", "插值"}
    ]
    blocked = not bool(snapshot.get("decision_allowed"))
    actions = (
        [
            "保持 fail-closed，不生成或执行新建议。",
            "按异常字段的 source_id 与 trace_id 核验数据源、时间戳和质量规则。",
            "质量恢复后重新刷新快照与预测，再由人工复核建议。",
        ]
        if blocked or abnormal
        else [
            "当前无阻断级异常；继续监控变压器负载率、储能温度和作业队列。",
            "如需改变运行参数，只生成建议并保留独立人工审批。",
        ]
    )
    return {
        "status": "grounded_runtime_alert_triage",
        "scenario_id": snapshot.get("active_scenario", {}).get("scenario_id"),
        "quality_status": quality.get("status"),
        "decision_allowed": not blocked,
        "critical_reasons": quality.get("critical_reasons", []),
        "abnormal_fields": abnormal,
        "operator_actions": actions,
        "summary": (
            f"质量门禁 {'FAIL-CLOSED' if blocked else 'PASS'}，"
            f"阻断原因 {len(quality.get('critical_reasons', []))} 项，"
            f"异常字段 {len(abnormal)} 项。"
        ),
        "production_boundary": {
            "live_data_verified": False,
            "dispatch_allowed": False,
            "production_authority": False,
        },
    }


def _runtime_recommendation_explanation() -> dict[str, Any]:
    latest = _latest_runtime_decision()
    if latest is None:
        return {
            "status": "no_runtime_recommendation",
            "summary": "尚无运行建议；可先经人工确认生成当前推荐。",
            "production_authority": False,
        }
    policy = latest.get("policy", {})
    impact = latest.get("predicted_impact", {})
    return {
        "status": "grounded_runtime_recommendation_explanation",
        "summary": (
            f"最新建议 {latest.get('decision_id')} 状态 {latest.get('status')}，"
            f"风险 {latest.get('risk_level')}，审批 "
            f"{len(latest.get('approvals', []))}/{latest.get('required_approvals')}。"
        ),
        "decision": {
            "decision_id": latest.get("decision_id"),
            "status": latest.get("status"),
            "risk_level": latest.get("risk_level"),
            "objective": latest.get("objective"),
            "recommended_action": latest.get("recommended_action", {}),
            "projected_action": latest.get("projected_action", {}),
            "triggered_constraints": latest.get("safety_projection", {}).get("triggered_constraints", []),
            "predicted_impact": impact,
            "strong_baseline": policy.get("strong_baseline"),
            "approval_count": len(latest.get("approvals", [])),
            "required_approvals": latest.get("required_approvals"),
            "production_authority": False,
            "dispatch_allowed": False,
        },
        "operator_note": "小懿只解释建议，不具备审批、生产下发或绕过质量门禁的权限。",
    }


def _runtime_recommendation_trigger(dry_run: bool) -> dict[str, Any]:
    snapshot = runtime_simulator.snapshot(advance=False)
    allowed = bool(snapshot.get("decision_allowed"))
    return {
        "status": (
            "ready_for_human_confirmation"
            if dry_run and allowed
            else "front_end_recommendation_trigger_ready"
            if allowed
            else "blocked_by_runtime_quality_gate"
        ),
        "decision_allowed": allowed,
        "target_button": "#btnRuntimeCreateDecision",
        "note": "仅生成 MPC 建议；审批、模拟执行和回滚由独立人工按钮完成。",
        "production_authority": False,
        "dispatch_allowed": False,
    }


def _linkage_health_summary() -> dict[str, Any]:
    xiaoyi = xiaoyi_status()
    sailing = sailing_status()
    training = _training_status()
    runtime = _runtime_state_summary()
    return {
        "status": "checked",
        "summary": {
            "xiaoyi": xiaoyi["label"],
            "rl": training["summary"],
            "sailing": sailing["label"],
            "runtime": f"实时闭环{str(runtime['quality_gate']['status']).upper()} / 生产权限关闭",
        },
        "systems": {
            "xiaoyi_ai": xiaoyi,
            "rl_training": training,
            "sailing_simulator": sailing,
            "runtime_closed_loop": runtime,
        },
    }


def _execute_action(action: dict[str, Any], payload: dict[str, Any], dry_run: bool) -> dict[str, Any]:
    action_id = action["id"]
    if action_id in TOP_PANEL_ACTIONS:
        return _top_panel_result(action_id, dry_run=dry_run)
    if action_id == "summarize_runtime_state":
        return _runtime_state_summary()
    if action_id == "prepare_runtime_handover":
        return _runtime_handover_summary()
    if action_id == "triage_runtime_alerts":
        return _runtime_alert_triage()
    if action_id == "create_runtime_recommendation":
        return _runtime_recommendation_trigger(dry_run=dry_run)
    if action_id == "explain_runtime_recommendation":
        return _runtime_recommendation_explanation()
    if action_id == "refresh_dashboard_snapshot":
        return _dashboard_refresh(payload, dry_run=dry_run)
    if action_id == "run_linkage_health_check":
        result = _linkage_health_summary()
        if not dry_run:
            _append_log("run_linkage_health_check", "checked", result)
        return {**result, "status": "ready_to_check" if dry_run else "checked"}
    if action_id == "check_sailing_status":
        status = sailing_status()
        result = {"status": "checked" if not dry_run else "ready_to_check", "sailing_status": status}
        if not dry_run:
            _append_log("check_sailing_status", "checked", result)
        return result
    if action_id in PREFERENCE_ACTIONS:
        return _preference_action_result(action_id, payload, dry_run=dry_run)
    if action_id == "start_xiaoyi_ai":
        return launch_xiaoyi(payload, dry_run=dry_run)
    if action_id == "open_sailing_simulator":
        return launch_sailing({**payload, "preset": "main_scene"}, dry_run=dry_run)
    if action_id == "start_navigation_demo":
        result = launch_sailing({**payload, "preset": "route_demo"}, dry_run=dry_run)
        result["action_id"] = action_id
        result["preset_note"] = "已加载主场景；Godot 端无 HTTP 控制时先展示航线演示意图。"
        return result
    if action_id == "switch_ship_view":
        launch = launch_sailing({**payload, "preset": "ship_view"}, dry_run=dry_run)
        return {
            "type": "sailing_staged_control",
            "status": launch.get("status") if dry_run else ("staged_no_http_control" if launch.get("status") in {"launched", "already_running"} else launch.get("status")),
            "launch": launch,
            "godot_side_needed": True,
            "manual_fallback": "在 Godot 航行模拟器内切换船队/受控船舶视角。",
        }
    if action_id == "run_sailing_rl_smoke_test":
        return run_sailing_smoke(payload, dry_run=dry_run)
    if action_id == "start_rl_training":
        if dry_run:
            cfg = _build_training_config(str(payload.get("instruction") or ""), payload)
            return {"status": "ready_to_train", "config": cfg, "recommendation": _training_recommendation(cfg)}
        return _start_training(payload)
    if action_id == "view_rl_training_status":
        return _training_status()
    if action_id == "pause_rl_training":
        return _control_training("pause")
    if action_id == "resume_rl_training":
        return _control_training("resume")
    if action_id == "stop_rl_training":
        return _control_training("stop")
    if action_id == "run_policy_test":
        return _simulate_policy(payload)
    if action_id == "verify_policy_for_online":
        verify = _verify_policy(payload)
        dispatch = _dispatch_policy({**payload, "dry_run": True})
        return {"status": "dry_run_ready" if verify["ok"] else "blocked", "verify": verify, "dispatch": dispatch}
    return {"status": "not_implemented", "action_id": action_id}


def _training_recommendation(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": f"{config['objective_label']} 推荐参数",
        "objective_id": config["objective_id"],
        "objective_label": config["objective_label"],
        "algorithm": config["algorithm"].upper(),
        "config": config,
        "reason": config["reason"],
        "risk_note": "训练只读取 train split 且 render_mode=None；完成后需单独运行 test split 评估才会生成可视化轨迹。",
    }


def _start_training(payload: dict[str, Any]) -> dict[str, Any]:
    instruction = str(payload.get("instruction") or "")
    raw_config = (
        dict(payload["config"])
        if isinstance(payload.get("config"), dict)
        else _build_training_config(instruction, payload)
    )
    try:
        raw_config["dataset_id"] = registered_dataset_id(
            str(raw_config.get("dataset_id") or raw_config.get("data_file") or DEFAULT_DATASET_ID)
        )
    except ValueError as exc:
        logger.info("Assistant training dataset rejected", exc_info=exc)
        raise HTTPException(status_code=422, detail="dataset_reference_invalid") from None
    raw_config["data_file"] = raw_config["dataset_id"]
    try:
        raw_config.update(
            resolve_training_scenario(
                str(raw_config.get("scenario") or "") or None,
                str(raw_config["dataset_id"]),
            )
        )
    except ValueError as exc:
        logger.info("Assistant training scenario rejected", exc_info=exc)
        raise HTTPException(status_code=422, detail="scenario_configuration_invalid") from None
    return training_service.start(raw_config)


def _strategies() -> list[dict[str, Any]]:
    return training_service.strategies()


def _simulate_policy(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    return training_service.evaluate(
        resolve_requested_strategy(payload.get("strategy_id"))
    )


def _verify_policy(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    from app.api.routes_rl import verify_policy as verify_policy_route

    result = verify_policy_route(payload or {})
    _append_log("verify_policy_for_online", result["status"], result)
    return result


def _dispatch_policy(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    dry_run = bool(payload.get("dry_run", True))
    requested = str(payload.get("strategy_id") or "auto:latest")
    resolved = resolve_requested_strategy(requested)
    registry = training_service.registry()
    admitted = next(
        (
            item
            for item in registry["policies"]
            if item["policy_id"] == resolved and item["stage"] == "verified_offline"
        ),
        None,
    )
    if resolved == "auto:no-admitted-policy":
        report_path = PROJECT_ROOT / "reports" / "offline_benchmark_v3.json"
        policy_id = "published:offline-mpc-v3"
        policy_stage = "control_benchmark"
        artifact_sha256 = (
            hashlib.sha256(report_path.read_bytes()).hexdigest() if report_path.exists() else None
        )
    elif admitted:
        policy_id = resolved
        policy_stage = "verified_offline"
        artifact_sha256 = admitted.get("artifact_sha256")
    else:
        return {
            "status": "blocked_policy_not_admitted",
            "dry_run": True,
            "requested_policy_id": requested,
            "resolved_policy_id": resolved,
            "execution_authorized": False,
            "production_dispatch_enabled": False,
            "note": "Explicit policies require persisted verified offline admission evidence.",
        }
    integration = integration_gateway.status()
    created_at = datetime.now(timezone.utc)
    idempotency_key = str(
        payload.get("idempotency_key")
        or hashlib.sha256(
            json.dumps(
                {
                    "policy_id": policy_id,
                    "artifact_sha256": artifact_sha256,
                    "source": payload.get("source", "cockpit"),
                    "request": payload.get("request") or {},
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
    )
    decision_id = "shadow-" + hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()[:24]
    return {
        "status": "shadow_decision_recorded" if dry_run else "blocked_physical_dispatch_not_available",
        "dry_run": True,
        "decision_id": decision_id,
        "idempotency_key": idempotency_key,
        "created_at": created_at.isoformat().replace("+00:00", "Z"),
        "expires_at": (created_at + timedelta(minutes=5)).isoformat().replace("+00:00", "Z"),
        "target": "energy_carbon_dispatch",
        "policy_id": policy_id,
        "policy_stage": policy_stage,
        "artifact_sha256": artifact_sha256,
        "rollback_target": "published:offline-mpc-v3",
        "read_only_shadow_ready": integration["read_only_shadow_ready"],
        "input_snapshot_digests": {
            item["adapter_id"]: item["payload_sha256"]
            for item in integration["adapters"]
            if item["ready"] and item["payload_sha256"]
        },
        "execution_authorized": False,
        "production_dispatch_enabled": False,
        "note": "Shadow recommendation only; physical dispatch is not implemented in this repository.",
    }


@router.get("/linkage/health")
def linkage_health() -> dict[str, Any]:
    xiaoyi = xiaoyi_status()
    sailing = sailing_status()
    rl_capabilities = training_service.capabilities()
    rl_status = training_service.status()
    rl_online = bool(rl_capabilities["runtime"].get("available"))
    runtime = _runtime_state_summary()
    return {
        "ok": True,
        "updated_at": _utc_now(),
        "scope": "energy-carbon cockpit xiaoyi linkage",
        "summary": {
            "xiaoyi": xiaoyi["label"],
            "rl": rl_status["summary"] if rl_online else "RL运行时不可用",
            "sailing": sailing["label"],
            "runtime": f"实时闭环{str(runtime['quality_gate']['status']).upper()} / 生产权限关闭",
        },
        "systems": {
            "energy_carbon_cockpit": {"online": True, "label": "能碳驾驶舱在线", "project_root": "."},
            "xiaoyi_ai": xiaoyi,
            "rl_interface": {
                "online": rl_online,
                "label": "真实RL训练运行时就绪" if rl_online else "RL依赖缺失",
                "algorithms": [item["id"] for item in rl_capabilities["algorithms"]],
                "datasets": [item["id"] for item in rl_capabilities["datasets"] if item.get("valid")],
                "runtime": rl_capabilities["runtime"],
                "routes": {
                    "/api/assistant/actions/execute": True,
                    "/api/rl/actions/registry": True,
                    "/api/rl/train/start": True,
                    "/api/rl/train/status": True,
                    "/api/rl/train/pause": True,
                    "/api/rl/train/resume": True,
                    "/api/rl/train/stop": True,
                    "/api/rl/train/metrics": True,
                    "/api/rl/training/history": True,
                    "/api/rl/strategies": True,
                    "/api/rl/simulate": True,
                    "/api/rl/dispatch": True,
                },
            },
            "sailing_simulator": sailing,
            "runtime_closed_loop": runtime,
        },
    }


@router.get("/xiaoyi/status")
def get_xiaoyi_status() -> dict[str, Any]:
    return xiaoyi_status()


@router.post("/xiaoyi/launch")
def post_xiaoyi_launch(payload: dict[str, Any] = Body(default={})) -> JSONResponse:
    if not bool(payload.get("dry_run", False)) and not bool(payload.get("confirm", False)):
        return JSONResponse({"ok": False, "status": "confirmation_required", "preview": launch_xiaoyi(payload, dry_run=True)})
    result = launch_xiaoyi(payload, dry_run=bool(payload.get("dry_run", False)))
    return JSONResponse({"ok": result.get("status") != "failed", "result": result, "status": xiaoyi_status()})


@router.post("/xiaoyi/chat")
def post_xiaoyi_chat(payload: dict[str, Any] = Body(default={})) -> JSONResponse:
    question = str(payload.get("question") or payload.get("instruction") or "").strip()
    if len(question) < 2:
        raise HTTPException(status_code=400, detail="缺少 question")
    if not xiaoyi_status()["online"]:
        launch_xiaoyi({"confirm": True, "source": "energy-carbon-chat"}, dry_run=False)
    try:
        result = _post_json(f"{XIAOYI_BASE_URL}/api/chat", {"question": question, "mode": payload.get("mode") or "brief", "top_k": int(payload.get("top_k") or 5)})
        return JSONResponse({"ok": True, "engine": "xiaoyi_ai", "result": result})
    except Exception:
        logger.exception("Xiaoyi chat request failed")
        return JSONResponse(
            {
                "ok": False,
                "engine": "local_fallback",
                "answer": (
                    f"小懿暂不可达，能碳驾驶舱本地判断：{question} "
                    "可先进入联动中枢确认动作，再执行 dry-run。"
                ),
                "error": "xiaoyi_unreachable",
            }
        )


@router.get("/xiaoyi/logs")
def get_xiaoyi_logs(limit: int = 30) -> dict[str, Any]:
    return {"updated_at": _utc_now(), "items": _action_log[: max(1, min(limit, 100))]}


@router.get("/rl/actions/registry")
def action_registry() -> dict[str, Any]:
    return {"updated_at": _utc_now(), "count": len(ACTION_REGISTRY), "actions": ACTION_REGISTRY, "training_objectives": TRAINING_OBJECTIVES}


@router.post("/assistant/actions/execute")
def assistant_execute(payload: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    instruction = str(payload.get("instruction") or "")
    action_id = str(payload.get("action_id") or "").strip() or None
    dry_run = bool(payload.get("dry_run", True))
    action, candidates = _resolve_action(instruction, action_id)
    if not action:
        return {
            "ok": True,
            "matched": False,
            "updated_at": _utc_now(),
            "input": {"instruction": instruction, "action_id": action_id},
            "candidates": [],
            "message": "未匹配到可执行动作，可作为普通问答交给小懿。",
        }
    if action["id"] == "start_rl_training":
        config = _build_training_config(instruction, payload)
        recommendation = _training_recommendation(config)
        payload = {**payload, "instruction": instruction, "config": config}
    else:
        recommendation = None
    confirm_required = bool(action.get("requires_human_confirm"))
    confirm_provided = bool(payload.get("confirm"))
    execution = _execute_action(action, payload, dry_run=dry_run or (confirm_required and not confirm_provided))
    confirmation_reason = (
        "该动作会生成新的运行建议，但不会代替值班主管与能源经理审批，也不会执行调度。"
        if action["id"] == "create_runtime_recommendation"
        else "该动作会启动训练、测试或桌面程序，需要人工确认。"
    )
    return {
        "ok": True,
        "updated_at": _utc_now(),
        "gateway": "energy_carbon_xiaoyi_action_gateway",
        "input": {"instruction": instruction, "action_id": action_id},
        "matched": True,
        "action": action,
        "candidates": candidates,
        "will_execute": {
            "action_id": action["id"],
            "action_label": action["label"],
            "button": {"selector": action.get("button_selector"), "label": action.get("button_label"), "sequence": [action.get("button_selector")] if action.get("button_selector") else []},
            "backend_request": action.get("backend_request"),
        },
        "recommendation": recommendation,
        "required_parameters": [{"name": "confirm", "required": confirm_required, "source": "payload.confirm", "description": "启动训练、桌面程序或 smoke test 前需要人工确认。"}] if confirm_required else [],
        "human_confirmation": {
            "required": confirm_required,
            "provided": confirm_provided,
            "needed_before_execution": confirm_required and not confirm_provided,
            "reason": confirmation_reason if confirm_required else "该动作可查询或 dry-run。",
        },
        "execution_result": {"status": execution.get("status", "done"), "mode": "dry_run" if dry_run or (confirm_required and not confirm_provided) else "executed", "executed": not dry_run and (not confirm_required or confirm_provided), "result": execution},
    }


@router.post("/legacy/rl/train/start", include_in_schema=False)
def train_start(payload: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    if not bool(payload.get("confirm", False)):
        config = _build_training_config(str(payload.get("instruction") or ""), payload)
        return {"ok": False, "status": "confirmation_required", "preview": _training_recommendation(config)}
    return {"ok": True, "result": _start_training(payload)}


@router.get("/legacy/rl/train/status", include_in_schema=False)
def train_status() -> dict[str, Any]:
    return _training_status()


@router.post("/legacy/rl/train/pause", include_in_schema=False)
def train_pause() -> dict[str, Any]:
    return _control_training("pause")


@router.post("/legacy/rl/train/resume", include_in_schema=False)
def train_resume() -> dict[str, Any]:
    return _control_training("resume")


@router.post("/legacy/rl/train/stop", include_in_schema=False)
def train_stop() -> dict[str, Any]:
    return _control_training("stop")


@router.get("/legacy/rl/train/metrics", include_in_schema=False)
def train_metrics() -> dict[str, Any]:
    status = _training_status()
    return {
        "updated_at": _utc_now(),
        "metrics": {
            "step": status["step"],
            "reward": status["reward"],
            "entropy": status["entropy"],
            "actor_loss": status["actor_loss"],
            "critic_loss": status["critic_loss"],
            "kl_divergence": status["kl_divergence"],
            "success_rate": status["success_rate"],
            "samples_per_sec": status["samples_per_sec"],
            "policy_version": status["policy_version"],
        },
        "recent_metrics": status["recent_metrics"],
        "logs": status["logs"],
    }


@router.get("/legacy/rl/training/history", include_in_schema=False)
def training_history() -> dict[str, Any]:
    return {"updated_at": _utc_now(), "run": _historical_training_run()}


@router.get("/legacy/rl/strategies", include_in_schema=False)
def strategies() -> dict[str, Any]:
    return {"updated_at": _utc_now(), "items": _strategies()}


@router.post("/legacy/rl/simulate", include_in_schema=False)
def simulate(payload: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    return _simulate_policy(payload)


@router.post("/legacy/rlops/policies/verify", include_in_schema=False)
def verify_policy(payload: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    return _verify_policy(payload)


@router.post("/rl/dispatch")
def dispatch_policy(payload: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    return _dispatch_policy(payload)


@router.get("/sailing/status")
def get_sailing_status() -> dict[str, Any]:
    return sailing_status()


@router.post("/sailing/launch")
def post_sailing_launch(payload: dict[str, Any] = Body(default={})) -> JSONResponse:
    if not bool(payload.get("dry_run", False)) and not bool(payload.get("confirm", False)):
        return JSONResponse({"ok": False, "status": "confirmation_required", "preview": launch_sailing(payload, dry_run=True)})
    result = launch_sailing(payload, dry_run=bool(payload.get("dry_run", False)))
    return JSONResponse({"ok": result.get("status") != "failed", "result": result, "status": sailing_status()})


@router.post("/sailing/actions/execute")
def post_sailing_action(payload: dict[str, Any] = Body(default={})) -> JSONResponse:
    action_id = str(payload.get("action_id") or "")
    dry_run = bool(payload.get("dry_run", True))
    action = next((item for item in ACTION_REGISTRY if item["id"] == action_id), None)
    if not action:
        raise HTTPException(status_code=404, detail=f"未知航行模拟器动作：{action_id}")
    if not dry_run and not bool(payload.get("confirm", False)):
        return JSONResponse({"ok": False, "status": "confirmation_required", "preview": _execute_action(action, payload, dry_run=True)})
    result = _execute_action(action, payload, dry_run=dry_run)
    return JSONResponse({"ok": result.get("status") not in {"failed", "timeout"}, "action": action, "execution": result, "status": sailing_status()})


@router.get("/sailing/logs")
def get_sailing_logs(limit: int = 30) -> dict[str, Any]:
    return {"updated_at": _utc_now(), "items": _action_log[: max(1, min(limit, 100))]}
