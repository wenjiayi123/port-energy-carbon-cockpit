# 实港现场交付包

本目录把实港落地所需的系统映射、设备与电表点表、网络分区、职责、180 天影子验收、十三域证据、十六道门禁和六方签字整理为可填写、可校验、可签署的机器模板。

## 使用顺序

1. 复制本目录到港口业主受控的项目空间，不要直接在仓库模板上填写生产秘密。
2. 由数据、计量、运行技术安全、运营、能碳、财务和独立核证责任人分别填写相应 CSV/YAML/JSON。
3. 每次评审前运行：

   ```bash
   backend/.venv/bin/python scripts/validate_site_delivery_kit.py deployment/site_delivery
   ```

4. 模板填完后运行严格校验：

   ```bash
   backend/.venv/bin/python scripts/validate_site_delivery_kit.py deployment/site_delivery --strict
   ```

5. 严格校验通过后，才可在隔离签名环境用 `scripts/sign_site_cutover_package.py` 生成签名包和只含公钥的可信签名者配置。
6. 将签名包提交 `/api/dashboard/site-cutover-readiness/evaluate`。接口返回 `eligible_for_external_cutover_review` 只表示可提交外部变更委员会，不授予自动切换、物理调度或联锁绕过权限。

## 文件清单

| 文件 | 责任方 | 用途 |
| --- | --- | --- |
| `site_profile.template.yaml` | 港口项目负责人 | 绑定港口、租户、发布版本、验收窗口和变更窗口 |
| `system_mapping.template.csv` | 数据与集成负责人 | 定义源系统、协议、字段血缘、时效、回执和只读边界 |
| `meter_device_points.template.csv` | 计量与设备负责人 | 建立资产、馈线、电表、信号、校准和对账组点表 |
| `network_zones.template.csv` | 运行技术安全负责人 | 定义信息技术区、隔离区、运行技术控制区、安全联锁区及受控通道 |
| `raci.template.csv` | 港口项目负责人 | 为关键交付活动指定唯一最终负责方 |
| `shadow_acceptance_plan.template.csv` | 运营与模型风险负责人 | 覆盖连续 180 天、两个运营季节及六类规定场景 |
| `domain_acceptance_register.template.csv` | 十三个域责任人 | 登记现场报告、摘要、例外和独立核证状态 |
| `cutover_gates.template.csv` | 变更经理 | 逐项关闭十六道投产总门禁 |
| `approval_register.template.csv` | 六方批准人 | 记录对同一完整包摘要的批准与签名 |
| `site_cutover_package.template.json` | 变更经理 | 未签名的接口输入骨架；所有占位符必须替换 |
| `trusted_signers.template.json` | 企业公钥基础设施管理员 | 可信公钥配置骨架；禁止存放私钥 |

正式工作簿是跨部门填写界面，CSV/YAML/JSON 是系统导入和自动校验的权威模板。两者内容发生冲突时，应先由数据所有者核对，再重新导出机器模板和生成完整包，禁止手工绕过校验。

## 红线

- 不在仓库、工作簿、工单附件或即时通信中保存私钥、长期令牌、生产密码或现场证书。
- 本应用保持 `production_authority=false`、`production_dispatch_allowed=false` 和 `interlock_bypass_allowed=false`。
- 对外指令只能进入港口独立生产指令网关，并受设备能力检查、独立可编程逻辑控制器联锁、最终设备回执、超时降级和人工接管约束。
- 未完成 180 天影子运行、校准计量、灾备/回滚/网络安全演练及六方绑定签字时，不得把模板完整性结果描述为投产通过。
