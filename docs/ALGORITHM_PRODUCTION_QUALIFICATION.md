# 算法生产资格与冠军/挑战者放行

本模块不新增算法，而是把已有 DQN、PPO、SAC、TD3、因果 MPC 和风险感知 MPC 放到同一个可签名、可否决、可追溯的生产资格合同中。它只给出「资格就绪」或「未通过」，不自动把挑战者提升为冠军，也不下发任何设备指令。

## 默认边界

`GET /api/dashboard/algorithm-production` 默认返回 `status=blocked`、0/6 生产证据源和 0/15 资格门禁。`automatic_policy_promotion_allowed`、`autonomous_dispatch_allowed` 与 `production_authority` 均为 `false`，`algorithm_expansion_recommended=false`。

仓库现有离线报告仅作已知证据展示，不会自动通过任一生产门禁。风险感知 MPC 相对因果旧 MPC 的碳、成本和峰值负向结果，以及电网降额场景的软备用越界退化，均保留原数值。

## 六类独立证据源

| 证据域 | 必备内容 |
| --- | --- |
| `experiment_registry` | 候选与基线制品，数据/代码/观测/动作契约哈希，种子—季节配对评测及影子运行 |
| `forecast_calibration` | 决策级下分位、中位、上分位与最终真值 |
| `runtime_monitoring` | 分布外样本与回退、解释/反事实/保真、端到端时延 |
| `execution_receipts` | 当前、请求、安全投影和确认动作，能力边界、联锁和网关回执 |
| `fault_campaign` | 通信丢失、漂移、降额、过温、过期数据和未知分布故障演练 |
| `human_review_log` | 职责分离的批准/修改/驳回/否决、原因代码、意见和审计哈希 |

每个证据域由源系统 Ed25519 密钥独立签名。服务端同时校验载荷 SHA-256、公钥、时效、跨源对齐和 `live_data_verified`。任一源缺失、超时、重复或被篡改，整个报告即 `blocked`。

## 十五道放行门禁

1. 六类生产证据源完整覆盖。
2. 所有证据域逐源验签、新鲜、对齐且实时已核实。
3. 候选与基线的模型、数据、代码、观测契约和动作契约不可变。
4. 同一冻结协议下至少三个独立随机种子。
5. 每个随机种子都覆盖春、夏、秋、冬配对评测。
6. 概率区间经验覆盖率在批准带内，中位预测误差不超限。
7. 分布外检测同时满足真阳性率、假阳性率及逐次回退/抑制覆盖。
8. 所有样本在人工复核前生成理由码、特征归因、反事实和局部保真度。
9. 影子动作经限幅、速率和联锁检查后获得网关确认，跟踪误差不超限。
10. 单调时钟端到端 P95/P99 在时限内，超时必须回退。
11. 必须故障全覆盖，且全部检出、失效关闭、回退、零危险动作。
12. 达到最小人工复核量和复核人数，完整统计否决率和原因完整率。
13. 候选与强工程基线的碳、成本、峰值和吞吐配对 bootstrap 95% 区间达标。
14. 候选的安全越界和备用缺口不得相对基线退化。
15. 现场只读影子运行达到批准的最小小时数和决策量。

## 状态语义

| 状态 | 含义 |
| --- | --- |
| `blocked` | 证据源覆盖、签名、时效、对齐或实时属性不合格。 |
| `not_qualified` | 六源可信，但至少一项生产门禁失败。 |
| `qualification_ready` | 十五项均通过；仅表示可提交独立人工放行，不表示已生产授权。 |

## 接入与签名

1. 按 `algorithm-production-qualification-input.v1` 生成完整 JSON。
2. 用源系统密钥逐域签名：

   ```bash
   python scripts/sign_algorithm_production_evidence.py \
     --input qualification.json \
     --domain forecast_calibration \
     --private-key forecast-owner.pem \
     --key-id terminal-a-forecast-2026 \
     --output qualification.signed.json
   ```

3. 把六个 Base64 Ed25519 公钥配置到 `ALGORITHM_EVIDENCE_PUBLIC_KEYS_JSON`。
4. 向 `POST /api/dashboard/algorithm-production/evaluate` 提交六源签名包。
5. 固化返回的输入/报告哈希、十五项门禁与人工放行记录。

## 现场验收最小条件

- 数据、代码、模型、观测和动作契约必须冻结且哈希对齐。
- 候选和强工程基线必须在完全相同的种子、季节、时窗和服务约束下配对运行。
- 分布外、时延、故障、动作和人工证据必须来自真实只读影子环境，不得用本地模拟回执替代。
- 人工放行由组织、运行、安全与模型风险责任人共同签字；系统不代替该决定。
- 现场指令网关、PLC 联锁、超时降级、回滚和人工接管仍属于独立的生产执行通道验收。
