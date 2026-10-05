# D19-P4 单族实现与交付记录

2026-09-24。实现者自检；尚待独立验收。执行边界以 `D19_P4_HANDOFF_6_SOL.md` 和 `D19_P4_TASKS_6_SOL.md` 为准。原有未提交的计划、决策及交接文档和 P3 冻结证据均保留；未做 GitHub 同步。

## 固定候选

- 运行 ID：`inv-f9883119d113`。EPO OPS 实际 CQL：`ta="anion exchange" and ta=membrane`；两页，10 个候选，筛出 `WO2026182370A1` 作为相关文本。Q1 因两页上限为 `partial`，未宣称穷尽检索。
- 只取得一个族的一个公开文本：`WO2026182370A1`，包括 INPADOC extended family、全文可得性、claims 和 description XML。原始响应和独立 RAG 库保存在忽略目录 `.local/d19-p4/`，未修改 P3 运行库。
- 正式事实快照包含 11 条 P3 冻结论文证据及 35 条经身份和内容指纹绑定的专利 RAG 证据。8 条主张的原文片段、文档版本、定位和 findings 引用均通过确定性校验。
- 调查结果为 `partial`：申请文本中的化学式为图片引用，OPS XML 表格被拆成短段；5 小时电解槽测试不足以证明长期化学耐碱稳定性。未将权利要求视为实测，未跨研究给材料排名。

## 交付物

本地固定目录：`.local/d19-p4/investigation-workspace/reports/inv-f9883119d113/run-inv-f9883119d113/`。其中包含 `technical_report.zh-CN.md`、`literature_review.zh-CN.md`、各自 HTML、`report-data.canonical.json`、`comparison.csv`、`human-review.csv`、`bibliography.bib`、`search-history.json`、`search-strategy.zh-CN.md`，共 10 个标准文件。`.local/d19-p4/acceptance-manifest.json` 列出路径与指纹。

可查追溯例：`search-history.json` 的 Q1 → 两条成功 search 请求 → 候选 `WO2026182370A1` 的筛选决定 → claims/description 原始 XML → RAG 文档 `doc-c9a9a98e7dd3462a22dd3449` / 版本 `ver-f8773965c378d28795536a5a` → 原文 XPath `/world-patent-data[1]/fulltext-documents[1]/fulltext-document[1]/description[1]/p[336]` → 主张 C8 → 中文技术报告“膨胀与短时电解槽结果”。C8 的试验条件另见同一说明书 `p[328]`；独立验收宜逐一核对两个段落。

## 预算与验收

- OPS HTTP 共 8 次，含两次认证；收到 239,568 字节。认证额度已用尽，后续未再联网。服务角色任务 6/10，宿主答案尝试 7/14（其中一次写作答案因 schema 被拒，修正后接受）。未调用 Jev；本轮凭据未发送给第三方。
- 最终 wheel 安装在 `.local/d19-p4/target-host/`。由该安装包运行受影响的 EPO、OpenAlex、RAG 绑定、合同和报告测试：60 passed。实际身份独立 RAG 库导入 1 个 XML 文档、394 条证据；重新导出同一固定报告后 HTTP 次数和接收字节数保持不变。
- 独立验收入口：只读查看 `acceptance-manifest.json`、两个中文 Markdown、`search-history.json` 和规范化报告；逐条核对原始 XML 与 C1–C8 原文、条件和定位。实施者自测不算独立验收。后续若需另取公开文本、补 PDF 或扩大来源，须另行授权。
