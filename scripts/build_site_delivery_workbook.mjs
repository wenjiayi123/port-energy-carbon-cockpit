import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";


const repoRoot = process.env.SITE_DELIVERY_REPO_ROOT
  ? path.resolve(process.env.SITE_DELIVERY_REPO_ROOT)
  : path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");
const kitDir = path.join(repoRoot, "deployment", "site_delivery");
const outputDir = process.argv[2]
  ? path.resolve(process.argv[2])
  : path.join(repoRoot, "outputs", "site-delivery-20260827");
const outputPath = path.join(outputDir, "港口能碳驾驶舱_实港交付包.xlsx");
const previewDir = path.join(outputDir, "previews");

const COLORS = {
  navy: "#0B1F33",
  teal: "#0E7490",
  cyan: "#DDF4F8",
  lightBlue: "#E8F1F8",
  white: "#FFFFFF",
  ink: "#172B3A",
  muted: "#5B6B78",
  line: "#C8D5DE",
  input: "#FFF4CC",
  green: "#DCFCE7",
  greenText: "#166534",
  amber: "#FEF3C7",
  amberText: "#92400E",
  red: "#FEE2E2",
  redText: "#991B1B",
  gray: "#F3F6F8",
};

const workbook = Workbook.create();
const sheetNames = [
  "使用说明",
  "现场概况",
  "系统映射",
  "设备电表点表",
  "网络分区",
  "RACI",
  "180天影子计划",
  "13域状态",
  "16门禁",
  "六方签字",
];
for (const name of sheetNames) workbook.worksheets.add(name);

function columnName(index) {
  let value = index + 1;
  let result = "";
  while (value > 0) {
    const remainder = (value - 1) % 26;
    result = String.fromCharCode(65 + remainder) + result;
    value = Math.floor((value - 1) / 26);
  }
  return result;
}

function setBaseSheetStyle(sheet) {
  sheet.showGridLines = false;
  const used = sheet.getUsedRange();
  if (used) {
    used.format.verticalAlignment = "center";
  }
}

function setTitle(sheet, lastColumn, title, subtitle) {
  const last = columnName(lastColumn - 1);
  sheet.getRange(`A1:${last}1`).merge();
  sheet.getRange("A1").values = [[title]];
  sheet.getRange(`A1:${last}1`).format = {
    fill: COLORS.navy,
    font: { name: "Aptos Display", size: 18, bold: true, color: COLORS.white },
    rowHeight: 34,
    verticalAlignment: "center",
  };
  sheet.getRange(`A2:${last}2`).merge();
  sheet.getRange("A2").values = [[subtitle]];
  sheet.getRange(`A2:${last}2`).format = {
    fill: COLORS.lightBlue,
    font: { name: "Aptos", size: 10, color: COLORS.muted },
    rowHeight: 30,
    wrapText: true,
    verticalAlignment: "center",
  };
}

function styleSummaryRow(sheet, lastColumn) {
  const last = columnName(Math.min(lastColumn - 1, 7));
  sheet.getRange(`A3:${last}3`).format = {
    fill: COLORS.cyan,
    font: { name: "Aptos", size: 10, bold: true, color: COLORS.ink },
    rowHeight: 25,
    borders: { preset: "outside", style: "thin", color: COLORS.line },
  };
  sheet.getRange("F3").format.numberFormat = "0.0%";
}

function addStatusFormatting(range) {
  range.conditionalFormats.add("containsText", {
    text: "accepted",
    format: { fill: COLORS.green, font: { color: COLORS.greenText, bold: true } },
  });
  range.conditionalFormats.add("containsText", {
    text: "approved",
    format: { fill: COLORS.green, font: { color: COLORS.greenText, bold: true } },
  });
  range.conditionalFormats.add("containsText", {
    text: "passed",
    format: { fill: COLORS.green, font: { color: COLORS.greenText, bold: true } },
  });
  range.conditionalFormats.add("containsText", {
    text: "not_started",
    format: { fill: COLORS.amber, font: { color: COLORS.amberText, bold: true } },
  });
  range.conditionalFormats.add("containsText", {
    text: "blocked",
    format: { fill: COLORS.red, font: { color: COLORS.redText, bold: true } },
  });
  range.conditionalFormats.add("containsText", {
    text: "rejected",
    format: { fill: COLORS.red, font: { color: COLORS.redText, bold: true } },
  });
}

function styleTableSheet(sheet, values, config) {
  const rowCount = values.length;
  const colCount = values[0].length;
  const lastColumn = columnName(colCount - 1);
  const lastDataRow = 4 + rowCount;
  setTitle(sheet, colCount, config.title, config.subtitle);
  sheet.getRange("A3:H3").values = [[
    config.acceptedLabel ?? "已接受",
    null,
    "总数",
    null,
    "完成率",
    null,
    "现场状态",
    null,
  ]];
  sheet.getRange("B3").formulas = [[`=COUNTIF(${config.statusColumn}6:${config.statusColumn}${lastDataRow},\"${config.acceptedValue}\")`]];
  sheet.getRange("D3").formulas = [[`=COUNTA(A6:A${lastDataRow})`]];
  sheet.getRange("F3").formulas = [["=IF(D3=0,0,B3/D3)"]];
  sheet.getRange("H3").formulas = [["=IF(F3=1,\"完整\",\"待补齐\")"]];
  styleSummaryRow(sheet, colCount);

  sheet.getRangeByIndexes(4, 0, rowCount, colCount).values = values;
  const header = sheet.getRange(`A5:${lastColumn}5`);
  header.format = {
    fill: COLORS.teal,
    font: { name: "Aptos", size: 10, bold: true, color: COLORS.white },
    rowHeight: 36,
    wrapText: true,
    horizontalAlignment: "center",
    verticalAlignment: "center",
    borders: { preset: "outside", style: "thin", color: COLORS.line },
  };
  const data = sheet.getRange(`A6:${lastColumn}${lastDataRow}`);
  data.format = {
    font: { name: "Aptos", size: 9, color: COLORS.ink },
    rowHeight: 25,
    wrapText: true,
    verticalAlignment: "center",
    borders: {
      insideHorizontal: { style: "thin", color: "#E5EBEF" },
      bottom: { style: "thin", color: COLORS.line },
    },
  };
  data.conditionalFormats.add("containsText", {
    text: "REPLACE_WITH",
    format: { fill: COLORS.input, font: { color: COLORS.amberText } },
  });
  const statusRange = sheet.getRange(`${config.statusColumn}6:${config.statusColumn}${lastDataRow}`);
  statusRange.dataValidation = {
    rule: { type: "list", values: config.statusValues },
  };
  addStatusFormatting(statusRange);
  sheet.tables.add(`A5:${lastColumn}${lastDataRow}`, true, config.tableName).style = "TableStyleMedium2";
  sheet.freezePanes.freezeRows(5);
  sheet.freezePanes.freezeColumns(2);

  for (let index = 0; index < colCount; index += 1) {
    const headerText = String(values[0][index] ?? "");
    let maxLength = headerText.length;
    for (let row = 1; row < values.length; row += 1) {
      maxLength = Math.max(maxLength, String(values[row][index] ?? "").length);
    }
    const width = Math.max(11, Math.min(config.wideColumns?.includes(index) ? 38 : 25, maxLength * 1.25 + 2));
    sheet.getRange(`${columnName(index)}:${columnName(index)}`).format.columnWidth = width;
  }
  setBaseSheetStyle(sheet);
}

async function csvValues(fileName) {
  const csvText = await fs.readFile(path.join(kitDir, fileName), "utf8");
  const imported = await Workbook.fromCSV(csvText, { sheetName: "Source" });
  return imported.worksheets.getItemAt(0).getUsedRange().values;
}

const instructions = workbook.worksheets.getItem("使用说明");
setTitle(
  instructions,
  10,
  "港口能碳驾驶舱｜实港现场交付包",
  "用途：跨部门完成现场接入、180 天影子验收与外部变更委员会审查材料；黄色单元格为港口业主输入，红色状态表示阻断。",
);
instructions.getRange("A4:J4").merge();
instructions.getRange("A4").values = [["结论边界：本工作簿是现场实施与验收载体，不授予生产权限。应用必须始终保持 production_authority=false、production_dispatch_allowed=false、interlock_bypass_allowed=false。"]];
instructions.getRange("A4:J4").format = {
  fill: COLORS.red,
  font: { bold: true, color: COLORS.redText, size: 11 },
  rowHeight: 42,
  wrapText: true,
  verticalAlignment: "center",
  borders: { preset: "outside", style: "medium", color: "#DC2626" },
};
instructions.getRange("A6:D6").values = [["阶段", "现场动作", "责任输出", "通过条件"]];
instructions.getRange("A7:D11").values = [
  ["A 基础设施", "冻结站点、租户、发布、环境和控制边界", "现场概况、网络分区、RACI", "外部网关和独立联锁持有控制权"],
  ["B 只读接入", "接入六类实时源并完成设备电表点表", "系统映射、设备电表点表", "字段血缘、时效、回执、校准和对账通过"],
  ["C 影子验证", "连续 180 天只读运行与故障注入", "180天影子计划", "两个运营季节、六类场景、演练和人工否决闭环"],
  ["D 预生产验收", "冻结十三域报告、十六门禁和完整包摘要", "13域状态、16门禁、六方签字", "无例外、无一级二级缺陷、同包签字"],
  ["E 外部切换", "外部变更委员会在获批窗口操作现场网关", "变更单、在岗记录、回滚记录", "应用仍为建议和评估角色"],
];
instructions.getRange("A6:D6").format = {
  fill: COLORS.teal,
  font: { bold: true, color: COLORS.white },
  rowHeight: 28,
};
instructions.getRange("A7:D11").format = {
  wrapText: true,
  rowHeight: 42,
  borders: { preset: "inside", style: "thin", color: COLORS.line },
};
instructions.getRange("F6:J6").merge();
instructions.getRange("F6").values = [["填写与签署规则"]];
instructions.getRange("F6:J6").format = {
  fill: COLORS.teal,
  font: { bold: true, color: COLORS.white },
  rowHeight: 28,
};
instructions.getRange("F7:J12").merge();
instructions.getRange("F7").values = [[
  "1. 在港口受控空间填写，不录入私钥、密码、长期令牌或现场证书。\n" +
  "2. 工作簿便于协作；CSV/YAML/JSON 是自动校验与接口导入的权威模板。\n" +
  "3. 模板检查：make site-delivery-check。\n" +
  "4. 现场严格检查：backend/.venv/bin/python scripts/validate_site_delivery_kit.py deployment/site_delivery --strict。\n" +
  "5. 严格检查通过后，在隔离签名环境签署完整包；签后禁止替换附件。\n" +
  "6. eligible_for_external_cutover_review 仅表示材料可送审，不等于自动投产。",
]];
instructions.getRange("F7:J12").format = {
  fill: COLORS.gray,
  wrapText: true,
  rowHeight: 34,
  verticalAlignment: "top",
  borders: { preset: "outside", style: "thin", color: COLORS.line },
};
instructions.getRange("A14:J14").merge();
instructions.getRange("A14").values = [["状态颜色：绿色=已接受/已通过/已批准；黄色=待填写或待开始；红色=阻断或拒绝。任何红色项存在时均不得宣称现场可投产。"]];
instructions.getRange("A14:J14").format = {
  fill: COLORS.amber,
  font: { bold: true, color: COLORS.amberText },
  rowHeight: 30,
  wrapText: true,
};
instructions.getRange("A:J").format.columnWidth = 17;
instructions.getRange("B:D").format.columnWidth = 25;
instructions.getRange("F:J").format.columnWidth = 18;
instructions.freezePanes.freezeRows(2);
setBaseSheetStyle(instructions);

const profile = workbook.worksheets.getItem("现场概况");
setTitle(profile, 10, "现场概况与总就绪度", "所有关键标识和摘要必须绑定同一站点、租户、窗口、截止点和不可变发布版本。工作簿计算只用于协作跟踪，接口复算才是审查依据。");
profile.getRange("A4:B4").values = [["现场输入", "值"]];
profile.getRange("A5:B19").values = [
  ["site_id", "REPLACE_WITH_SITE_ID"],
  ["site_name", "REPLACE_WITH_SITE_NAME"],
  ["terminal_id", "REPLACE_WITH_TERMINAL_ID"],
  ["tenant_id", "REPLACE_WITH_TENANT_ID"],
  ["target_release", "REPLACE_WITH_IMMUTABLE_RELEASE"],
  ["assessment_window_id", "REPLACE_WITH_ASSESSMENT_WINDOW_ID"],
  ["assessment_start_at", "REPLACE_WITH_TIMEZONE_AWARE_ISO8601"],
  ["assessment_end_at", "REPLACE_WITH_TIMEZONE_AWARE_ISO8601"],
  ["data_cutoff_at", "REPLACE_WITH_TIMEZONE_AWARE_ISO8601"],
  ["change_ticket_id", "REPLACE_WITH_CHANGE_TICKET_ID"],
  ["change_window_start_at", "REPLACE_WITH_TIMEZONE_AWARE_ISO8601"],
  ["change_window_end_at", "REPLACE_WITH_TIMEZONE_AWARE_ISO8601"],
  ["configuration_sha256", "REPLACE_WITH_64_HEX_SHA256"],
  ["infrastructure_as_code_sha256", "REPLACE_WITH_64_HEX_SHA256"],
  ["project_owner_organization", "REPLACE_WITH_OWNER_ORGANIZATION"],
];
profile.getRange("D4:G4").values = [["交付域", "已完成", "总数", "完成率"]];
const summaryRows = [
  ["系统映射", "=COUNTIF('系统映射'!W6:W18,\"accepted\")", "=COUNTA('系统映射'!A6:A18)", "=IF(F5=0,0,E5/F5)"],
  ["设备电表点表", "=COUNTIF('设备电表点表'!Z6:Z19,\"accepted\")", "=COUNTA('设备电表点表'!A6:A19)", "=IF(F6=0,0,E6/F6)"],
  ["网络分区", "=COUNTIF('网络分区'!R6:R16,\"accepted\")", "=COUNTA('网络分区'!A6:A16)", "=IF(F7=0,0,E7/F7)"],
  ["RACI", "=COUNTIF('RACI'!M6:M16,\"accepted\")", "=COUNTA('RACI'!A6:A16)", "=IF(F8=0,0,E8/F8)"],
  ["180天影子", "=COUNTIF('180天影子计划'!L6:L17,\"accepted\")", "=COUNTA('180天影子计划'!A6:A17)", "=IF(F9=0,0,E9/F9)"],
  ["13域", "=COUNTIF('13域状态'!V6:V18,\"accepted\")", "=COUNTA('13域状态'!A6:A18)", "=IF(F10=0,0,E10/F10)"],
  ["16门禁", "=COUNTIF('16门禁'!F6:F21,\"passed\")", "=COUNTA('16门禁'!A6:A21)", "=IF(F11=0,0,E11/F11)"],
  ["六方签字", "=COUNTIF('六方签字'!J6:J11,\"approved\")", "=COUNTA('六方签字'!A6:A11)", "=IF(F12=0,0,E12/F12)"],
];
profile.getRange("D5:D12").values = summaryRows.map((row) => [row[0]]);
profile.getRange("E5:G12").formulas = summaryRows.map((row) => row.slice(1));
profile.getRange("D14:F17").values = [
  ["总完成率", null, null],
  ["外部评审状态", null, null],
  ["应用生产授权", false, null],
  ["自动物理切换", false, null],
];
profile.getRange("E14").formulas = [["=MIN(G5:G12)"]];
profile.getRange("E15").formulas = [["=IF(E14=1,\"仅可提交外部变更委员会审查\",\"阻断：现场输入或验收未完成\")"]];
profile.getRange("A4:B4").format = { fill: COLORS.teal, font: { bold: true, color: COLORS.white }, rowHeight: 28 };
profile.getRange("D4:G4").format = { fill: COLORS.teal, font: { bold: true, color: COLORS.white }, rowHeight: 28 };
profile.getRange("A5:A19").format = { fill: COLORS.gray, font: { bold: true } };
profile.getRange("B5:B19").format = { fill: COLORS.input, font: { color: COLORS.amberText }, wrapText: true };
profile.getRange("D5:G12").format = { borders: { preset: "inside", style: "thin", color: COLORS.line }, rowHeight: 25 };
profile.getRange("G5:G12").format.numberFormat = "0.0%";
profile.getRange("D14:F17").format = { fill: COLORS.lightBlue, font: { bold: true }, rowHeight: 28, wrapText: true };
profile.getRange("E14").format.numberFormat = "0.0%";
profile.getRange("E15:F15").merge();
profile.getRange("E15:F15").conditionalFormats.add("containsText", { text: "阻断", format: { fill: COLORS.red, font: { color: COLORS.redText, bold: true } } });
profile.getRange("A:A").format.columnWidth = 28;
profile.getRange("B:B").format.columnWidth = 37;
profile.getRange("D:D").format.columnWidth = 22;
profile.getRange("E:G").format.columnWidth = 18;
profile.freezePanes.freezeRows(4);
setBaseSheetStyle(profile);

const tableDefinitions = [
  { sheet: "系统映射", file: "system_mapping.template.csv", title: "系统映射与数据血缘", subtitle: "六类实时源及支撑系统均为只读或建议交接；write_allowed 必须保持 false。", statusColumn: "W", acceptedValue: "accepted", statusValues: ["not_started", "in_progress", "accepted", "rejected"], tableName: "SystemMappingTable", wideColumns: [3, 4, 10, 11, 12, 13, 24] },
  { sheet: "设备电表点表", file: "meter_device_points.template.csv", title: "设备与电表点表", subtitle: "分钟级或秒级分路计量必须绑定资产、馈线、电表、外部点号、校准证书、质量码、时间和对账组。", statusColumn: "Z", acceptedValue: "accepted", statusValues: ["not_started", "mapped", "calibrating", "accepted", "rejected"], tableName: "MeterPointTable", wideColumns: [1, 6, 12, 13, 14, 15, 26, 27] },
  { sheet: "网络分区", file: "network_zones.template.csv", title: "网络分区与受控通道", subtitle: "默认拒绝、双向传输层安全、会话记录与独立联锁；禁止信息技术区直连运行技术控制区。", statusColumn: "R", acceptedValue: "accepted", statusValues: ["not_started", "designed", "tested", "accepted", "rejected"], tableName: "NetworkZoneTable", wideColumns: [4, 5, 6, 12, 18, 19] },
  { sheet: "RACI", file: "raci.template.csv", title: "现场职责分工矩阵", subtitle: "每项活动必须恰好有一个最终负责方 A；R=执行，C=协商，I=知会。六方签字的独立批准在六方签字表逐一记录。", statusColumn: "M", acceptedValue: "accepted", statusValues: ["not_started", "assigned", "accepted", "rejected"], tableName: "RaciTable", wideColumns: [1, 11, 13] },
  { sheet: "180天影子计划", file: "shadow_acceptance_plan.template.csv", title: "180 天影子运行与验收计划", subtitle: "连续覆盖第 1–180 天、至少两个运营季节及旺季、淡季、极端天气、设备故障、电网降额和计划检修。", statusColumn: "L", acceptedValue: "accepted", statusValues: ["not_started", "running", "accepted", "rejected"], tableName: "ShadowPlanTable", wideColumns: [6, 8, 9, 12, 13] },
  { sheet: "13域状态", file: "domain_acceptance_register.template.csv", title: "十三域现场验收登记", subtitle: "每个域必须绑定同一站点、租户、窗口和截止点，由独立责任方接受、无开放例外并提供有效签名。", statusColumn: "V", acceptedValue: "accepted", statusValues: ["not_started", "in_review", "accepted", "rejected"], tableName: "DomainAcceptanceTable", wideColumns: [2, 4, 5, 6, 7, 14, 17, 20, 22] },
  { sheet: "16门禁", file: "cutover_gates.template.csv", title: "十六道投产总门禁", subtitle: "全部门禁通过时仅达到 eligible_for_external_cutover_review；生产权限仍固定为假。", statusColumn: "F", acceptedValue: "passed", acceptedLabel: "已通过", statusValues: ["blocked", "in_review", "passed", "rejected"], tableName: "CutoverGateTable", wideColumns: [1, 2, 3, 8] },
  { sheet: "六方签字", file: "approval_register.template.csv", title: "六方完整包批准与签字", subtitle: "港口、运营、能碳、运行技术安全、首席信息安全官和独立核证人必须对同一完整包摘要签署。", statusColumn: "J", acceptedValue: "approved", acceptedLabel: "已批准", statusValues: ["not_started", "pending", "approved", "rejected"], tableName: "ApprovalRegisterTable", wideColumns: [1, 2, 4, 5, 6, 7, 8, 10] },
];

for (const definition of tableDefinitions) {
  const values = await csvValues(definition.file);
  const sheet = workbook.worksheets.getItem(definition.sheet);
  styleTableSheet(sheet, values, definition);
}

await fs.mkdir(previewDir, { recursive: true });

const summaryInspection = await workbook.inspect({
  kind: "table",
  range: "现场概况!A1:G19",
  include: "values,formulas",
  tableMaxRows: 19,
  tableMaxCols: 7,
  maxChars: 5000,
});
console.log("SUMMARY_INSPECTION");
console.log(summaryInspection.ndjson);

const formulaErrors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 300 },
  summary: "final formula error scan",
});
console.log("FORMULA_ERROR_SCAN");
console.log(formulaErrors.ndjson);

for (let index = 0; index < sheetNames.length; index += 1) {
  const name = sheetNames[index];
  const preview = await workbook.render({
    sheetName: name,
    autoCrop: "all",
    scale: 1,
    format: "png",
  });
  const bytes = new Uint8Array(await preview.arrayBuffer());
  await fs.writeFile(path.join(previewDir, `${String(index + 1).padStart(2, "0")}-${name}.png`), bytes);
}

await fs.mkdir(outputDir, { recursive: true });
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);
console.log(`OUTPUT=${outputPath}`);
console.log(`PREVIEWS=${previewDir}`);
