# D19-P1 Luna host implementation

本记录覆盖 Luna 独占的入口、replay 资源、PowerShell 薄适配和三语指南。所有结果均为本地 synthetic/replay 验证；没有真实来源、生成模型 API 或 OS 调度。

## 已实现

- `rh monitor profile-update MONITOR_ID --profile PROFILE_JSON` 直接转发 `InvestigationService.update_monitor_profile`。
- MCP `update_monitor_profile(monitor_id, profile)` 使用同一薄适配。
- `scripts/investigation.ps1` 支持 `-Monitor`、`-ProfileMonitorId`，status 的 RunId 可选，report 语言仅在显式提供时转发。
- `scripts/investigation_replay.py` 消费 `get_pending_tasks` 保存的一个或多个 JSON task，输出 deterministic replay 结果并标注 `synthetic=true`。结果包含 zh/en/ja writing sections；它不表示真实模型推理或科学效果。
- `examples/investigation/planning-result.json` 与 `pending-planning.json` 符合严格 role schema；schemas/prompts/examples 已列入 wheel package data。
- `pip install -e .[investigation]` 提供轻量 host 的 pypdf 与 MCP 依赖。

## 可复现验证

在 Terra 工作树执行：

```powershell
$env:PYTHONPATH='C:\Users\Siyuan_ye\Documents\ChatGPT\AEM\.local\d19-worktrees\terra\src'
& 'C:\Users\Siyuan_ye\Documents\ChatGPT\AEM\.local\d19-runtime\venv\Scripts\python.exe' -m pytest -q tests/test_investigation_entrypoints.py tests/test_investigation_mcp.py
& 'C:\Users\Siyuan_ye\Documents\ChatGPT\AEM\.local\d19-runtime\venv\Scripts\python.exe' scripts/investigation_replay.py --pending examples/investigation/pending-planning.json --output .local/replay-result.json
& 'C:\Users\Siyuan_ye\Documents\ChatGPT\AEM\.local\d19-runtime\venv\Scripts\python.exe' -m pip wheel . --no-deps --no-build-isolation --wheel-dir .local/wheel
```

结果：host tests `10 passed`；公共 `InvestigationService` 使用 `result_for` 实际完成 planning、paper_search、patent_search、evidence_analysis、business_judgment、synthesis、writing、verification 八角色，状态为 `completed`，并导出 technical_report/literature_review 各 zh/en/ja 的 Markdown/HTML 双报告；对象 target `technical_report` 且 languages=`["en"]` 仅导出英文；无 evidence 分支返回空 claims 与 verification `insufficient`；replay 输出 `.local/replay-result.json`；planning result schema errors `0`；wheel `research_harness-0.1.0-py3-none-any.whl` 构建成功，检查到 schemas 5、investigation prompts 9、investigation examples 5。

## PowerShell 实调

在已安装项目（或 wheel 安装）并使用同一 Python 解释器时，无需设置 `PYTHONPATH`，即可实际执行 `investigation.ps1` 的 `doctor`、带 `RunId` 的 `status` 和 `-Monitor profile-update`：doctor 返回 offline/synthetic，status 返回对应 run，profile-update 返回 monitor active/profile_revision。源码树开发自测时可选设置 PYTHONPATH；此前未安装项目且未设置 PYTHONPATH 的失败仅属于临时开发环境。

## 边界

这些是 code/integration 层证据。真实 API、真实模型质量、无人值守调度和独立验收仍为 pending，由根任务按 D19-P1 acceptance 执行。

## 最终独立验收

2026-09-14：设计任务已完成8f0895f的非editable wheel验收。native rh、模块CLI、PowerShell doctor/status/report/profile-update、真实SDK STDIO及进程恢复通过；项目从独立安装目录导入且未设置PYTHONPATH。依赖共享与Windows pywin32初始化条件、完整结果见[D19_P1_ACCEPTANCE](D19_P1_ACCEPTANCE.md)。前文为实现者自测历史，最终状态以独立记录为准。
