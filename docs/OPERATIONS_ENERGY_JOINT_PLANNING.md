# 业务—能量细粒度联合计划

本模块把具名船舶、泊位、岸桥、堆场箱位、外集卡预约、冷藏箱、岸电和储能放在同一时间轴上联合求解。它输出可复算的只读建议计划，不向码头操作系统（TOS）回写，不向设备发送指令，也不具有生产授权。

## 版本化数据合同

- 输入：`operations-energy-plan-input.v1`
- 输出：`operations-energy-joint-plan.v1`
- 时间粒度：15、30 或 60 分钟；最多 96 个时段
- 源数据必须带时区时间、源系统、源记录编号、实时核验标记、密钥编号、载荷 SHA-256 和 Ed25519 签名
- 请求和报告均生成稳定 SHA-256，便于重算、修订和审计

八个必需数据域：

| 数据域 | 关键业务对象 | 建议现场来源 |
| --- | --- | --- |
| `ais_and_vessel_calls` | 具名船舶、预计到港、要求离港、船长、进出口箱量 | 自动识别系统、船舶交通服务系统、TOS |
| `berth_plan` | 泊位时窗、船长上限、岸桥上限、岸电容量 | 泊位计划系统、TOS |
| `crane_work_orders` | 具名岸桥、兼容泊位、可用时窗、作业率和功率 | TOS、设备管理系统 |
| `yard_inventory` | 具名堆场区块、初始库存、容量、插座和单箱能耗 | TOS、堆场管理系统 |
| `truck_appointments` | 具名预约、进出场方向、箱量、闸口时段能力 | 车辆预约系统、TOS |
| `reefer_monitoring` | 冷藏箱批次、连接时窗、箱量、单箱功率 | 冷藏箱监控系统 |
| `shore_power_registry` | 逐船兼容、酒店负荷、最低服务量与泊位容量 | 岸电平台、泊位计划系统 |
| `energy_management_system` | 基础负荷、可再生能源、电网限额、电价、碳因子、储能状态 | 能源管理系统、监控与数据采集系统、电表、电池管理系统 |

## 求解与硬约束

1. 有限宽度搜索在预计到港和要求离港窗口内，联合分配船舶、泊位、具名岸桥和堆场区块。
2. 预约调度检查闸口时段能力，并约束出口送箱在船舶作业前、进口提箱在卸船后。
3. 堆场计划逐时段执行进出库守恒与容量检查，冷藏箱计划检查连续供电时窗和插座容量。
4. 岸电计划同时检查船、泊位兼容性、容量和最低岸电服务量。
5. 储能动态规划在电网备用容量、充放电功率、效率、荷电状态和期末荷电状态约束下，联合最小化电费、碳排放与电池退化代价。
6. 每个时段都输出负荷分解、可再生能源利用、储能功率、电网输入、能量平衡误差、成本和碳排放。

## 12 项发布门禁

`source_domain_coverage`、`source_signatures`、`source_freshness_alignment`、`vessel_schedule`、`berth_compatibility`、`crane_task_capacity`、`yard_inventory_capacity`、`truck_appointments`、`reefer_safety`、`shore_power_service`、`energy_balance_and_grid`、`storage_soc_and_terminal` 必须全部通过。

状态语义：

- `blocked`：源域、签名、实时标记、时效或跨源对齐未通过。即使求解器计算出数学方案，也不发布。
- `infeasible`：源数据可信，但业务或能量硬约束无法满足。
- `advisory_plan_ready`：八源可信且 12 门禁全通过，可供人工复核和影子运行，仍不代表生产执行授权。

## 接口与签名

- `GET /api/dashboard/operations-energy-plan`：返回当前可信准备状态。公开离线数据默认为 0/8 源域、0/12 门禁。
- `POST /api/dashboard/operations-energy-plan/evaluate`：校验完整请求、验签、求解并返回建议计划及哈希回执。

每个源系统所有者应使用独立私钥对自己的数据域签名：

```bash
backend/.venv/bin/python scripts/sign_operations_energy_source.py \
  --input site-plan.json \
  --domain truck_appointments \
  --private-key /secure/keys/truck-source-ed25519.pem \
  --key-id truck-source-2026q3 \
  --output site-plan.truck-signed.json
```

把各源输出的 `public_key_base64` 按密钥编号写入 `OPERATIONS_SOURCE_PUBLIC_KEYS_JSON`。私钥不得写入代码库、环境示例或 API 请求。

## 实港验收边界

本项已补齐软件内的合同、求解、门禁、签名、回执和可视化能力。实港仍需港方提供八源连接、字段映射、时钟同步、设备与电表标定、责任人批准，并通过跨日期影子运行验收。在完成生产指令网关、联锁、人工接管和回滚演练前，`tos_writeback_allowed`、`equipment_dispatch_allowed` 和 `production_authority` 恒为 `false`。
