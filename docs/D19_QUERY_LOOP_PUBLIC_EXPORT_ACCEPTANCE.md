# D19 公共导出修复验收

日期：2026-09-24。对象仅为 `inv-9aa6df1cfc94` 的既有冻结事实；无新增查询、来源、模型任务或 run。

- 修复：`investigation_reporting._bibtex()` 将冻结书目 `type=paper` 投影为 BibTeX `@article`；canonical ReportData 保留 `paper`。既有 `review` 和 `patent` 投影不变。
- 相关回归：`tests/test_investigation_reporting.py` 共 15 项通过；新增用例核对 `paper` 在 canonical JSON 中不变、在 `.bib` 中为 `@article`。
- 使用 `InvestigationService.export_report()` 对原调查库离线导出并重开重复导出。标准目录 `.local/d19-query-loop/live-3/investigation-workspace/reports/inv-9aa6df1cfc94/run-inv-9aa6df1cfc94/` 含 11 件文件：双报告 Markdown/HTML、canonical JSON、BibTeX、两份 CSV、检索历史、检索策略与 manifest。
- 原冻结事实与 `frozen-report-data.original.json` 逐字节一致，标准 canonical JSON 与原冻结事实相等；两份报告的 Markdown/HTML 与先前派生报告逐字节一致。重复导出的产物清单相同；导出前后 `status()` 中预算、覆盖、阶段状态相同。数据库因报告产物记录更新而变化，原冻结事实未改。
- 验收脚本：`.local/d19-query-loop/live-3/verify-public-export.py`，仅调用本地导出。`git diff --check` 对修改的代码与测试通过。

结论：**同 run 双全文有界闭环及标准公共导出通过；检索与科学覆盖仍为 `partial`。** 每来源仍仅一页五候选，论文是综述，专利化学式图片、表格布局、测量方向及长期耐碱结论仍需人工核查。旧 run、旧快照和派生导出保持原样。本阶段到此停止；不启动扩大检索、GUI、监测或 GitHub 发布。
