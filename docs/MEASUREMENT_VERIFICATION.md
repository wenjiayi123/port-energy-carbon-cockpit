# 节能减排计量与核证合同

本项目将离线策略对照与现场节能量严格分开。公开数据留出集中的能耗、碳排和成本差值继续作为可复现的情景证据保存，但在缺少现场计量与核证证据时，`verified_energy_savings_kwh`、`verified_carbon_reduction_kg` 和 `verified_financial_savings_cny` 必须为空。

## 两级门禁

`POST /api/dashboard/measurement-verification/evaluate` 接收
`energy-carbon-mv-input.v1` 证据包并返回
`energy-carbon-measurement-verification.v1` 回执：

1. **计算门禁**：现场计划、计量边界、冻结基线、区间覆盖、估算率、仪表校准、账单对账、基线模型质量、非例行调整声明、不确定性和排放因子登记簿必须全部通过。通过后可产生 `calculated_*` 数值。
2. **独立复核门禁**：复核人必须与计划、边界、基线和调整审批人分离，在报告期结束后签署整个证据包；服务端必须使用预先配置的受信 Ed25519 公钥验签。通过后才释放 `verified_*` 节能与减排值。

软件只验证证据包合同、计算和数字签名，不是独立核证机构。即使两个门禁均通过，财务结算与监管报送仍保持禁止，必须走港方、财务和监管方另行批准的流程。

## 必需证据

- 经批准的计量与核证计划及项目专属阈值；系统不内置所谓通用合格阈值；
- 具名报告主体、场站、计量边界、纳入/排除资产和会计仪表；
- 时间上早于报告期并已冻结的基线模型，以及训练量、验证量、独立变量、变异系数均方根误差（CV(RMSE)）和归一化平均偏差（NMBE）；
- 报告期区间电量、调整后基线电量、对应碳排、质量标记、源记录号与 SHA-256；
- 每块会计仪表覆盖完整报告期的有效校准证书；
- 收入电表区间合计与公用事业账单对账；
- 经批准的非例行调整台账，或“本期无非例行调整”的哈希声明；
- 计量和基线模型的标准不确定度、计划批准的置信度和覆盖因子；
- 版本化排放因子登记簿；
- 独立复核人的结论、身份分离声明、受信密钥 ID 和 Ed25519 签名。

## 独立复核签名

服务端仅信任环境变量中预登记的原始 Ed25519 公钥：

```bash
export MV_VERIFIER_PUBLIC_KEYS_JSON='{"independent-verifier-2026":"<base64-raw-32-byte-public-key>"}'
```

私钥不得提交到仓库。复核方在隔离环境中准备证据 JSON，并使用辅助脚本签名：

```bash
PYTHONPATH=backend backend/.venv/bin/python scripts/sign_mv_evidence.py \
  --input /secure/review/mv-evidence-unsigned.json \
  --private-key /secure/keys/verifier-ed25519.pem \
  --key-id independent-verifier-2026 \
  --output /secure/review/mv-evidence-signed.json
```

签名覆盖完整规范化证据包，但排除签名值和 `signed_evidence_sha256` 自身。任何区间值、阈值、边界、调整或复核元数据改变后，签名都会失效。随后由获授权的集成方提交签名文件：

```bash
curl --fail-with-body \
  -H "X-API-Key: $OPERATOR_API_KEY" \
  -H "Content-Type: application/json" \
  --data-binary @/secure/review/mv-evidence-signed.json \
  http://127.0.0.1:8808/api/dashboard/measurement-verification/evaluate
```

完整字段和格式以运行时 OpenAPI 为准。仓库不附带任何受信复核公钥、现场计量值、账单、校准证书或核证结论。
