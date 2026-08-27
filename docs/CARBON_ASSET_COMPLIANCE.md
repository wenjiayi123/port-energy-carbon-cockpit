# 碳资产、配额履约与交易结算合同

现有驾驶舱中的碳价、配额缺口和减排价值来自公开数据离线情景。其中“配额”是控制基线排放参考值，碳价是用户输入，不能作为监管分配、账户持仓、真实交易或资金结算记录。

本合同新增独立的 `carbon-asset-compliance-input.v1` 证据包和
`carbon-asset-compliance.v1` 回执。默认驾驶舱保留情景估值，但所有 `verified_*` 字段为空，状态为 `blocked`。

## 十二项门禁

`POST /api/dashboard/carbon-assets/evaluate` 依次验证：

1. 经批准的计划规则、适用辖区、履约期、履约截止日和合格年份；
2. 具名登记簿、账户、账户持有人、法律实体和权属证据；
3. 与履约期完全一致且结论为接受的独立核证排放清单；
4. 每个配额批次的工具编号、序列批次、年份、数量、状态和受益所有人；
5. 工具编号与序列批次全局唯一；
6. 每笔交易的方向、数量、价格、币种、场所、对手方、成交和登记簿转移回执，或带哈希的无交易声明；
7. 每笔交易的资金结算凭证，且一个证据包只能使用一种结算币种；
8. 期初余额、买入、卖出、注销、登记簿期末余额和内部账余额完全对账；
9. 合规与财务两名不同责任人的审批，且与计划审批人和独立核证人分离；
10. 注销数量覆盖核证排放量乘以计划规定的履约比例；
11. 注销发生在报告期结束后、截止日前，并具有登记簿确认编号；
12. 登记簿或获授权证明方对完整证据包作 Ed25519 签名。

前十一项通过时只能得到 `calculated_*` 对账结果；第十二项可信签名也通过后，才释放 `verified_*` 持仓、履约和资金结算字段。账本中的期初、交易和注销记录按时间排列，并通过 `previous_hash` 与 `entry_hash` 形成 SHA-256 链。

## 密钥和提交

服务端只信任预登记的原始 Ed25519 公钥：

```bash
export CARBON_REGISTRY_PUBLIC_KEYS_JSON='{"registry-operator-2026":"<base64-raw-32-byte-public-key>"}'
```

私钥不得提交到仓库。获授权的登记簿或证明方可在隔离环境中签名：

```bash
PYTHONPATH=backend backend/.venv/bin/python scripts/sign_carbon_asset_evidence.py \
  --input /secure/carbon-assets/evidence-unsigned.json \
  --private-key /secure/keys/registry-ed25519.pem \
  --key-id registry-operator-2026 \
  --output /secure/carbon-assets/evidence-signed.json
```

随后由获授权的集成方提交：

```bash
curl --fail-with-body \
  -H "X-API-Key: $OPERATOR_API_KEY" \
  -H "Content-Type: application/json" \
  --data-binary @/secure/carbon-assets/evidence-signed.json \
  http://127.0.0.1:8808/api/dashboard/carbon-assets/evaluate
```

签名覆盖整个规范化证据包，但不包含签名值和 `signed_evidence_sha256` 本身。任何规则、账户、核证排放、批次、交易、审批、注销或对账字段变化都会使签名失效。

## 权限边界

本软件仅验证外部证据、计算履约头寸和生成可审计回执，不是登记簿、交易所、清算机构、银行或监管报送通道。因此即使证据包全部通过，`trade_execution_allowed`、`cash_movement_allowed` 和 `regulatory_submission_allowed` 仍为 `false`。真实下单、资金划转、配额转移和监管报送必须由持牌或获授权系统完成。

仓库不附带真实账户、配额序列、交易、资金、注销数据、私钥或受信公钥。
