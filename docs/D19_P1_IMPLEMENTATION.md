# D19-P1 离线实现记录

2026-09-14：实现提交 `8f0895f` 已通过设计任务独立验收，包含源码回归和非 editable wheel 的实际 CLI/PowerShell/STDIO 调用。详见 [独立验收记录](D19_P1_ACCEPTANCE.md)。本轮在 P1 停止。

## 实现范围

- `investigation.py`：八角色宿主任务、LangGraph 推进、SQLite 结果/预算/证据，以及调查与监测公共服务。
- `investigation_sources.py`：显式合成 transport、分页/重试、PDF/XML/文本规范化与位置、来源和派生查询策略。
- `investigation_monitoring.py` / `investigation_review.py`：周期、水位、判定积压、规则版本、累计预算和人工决定历史。
- `investigation_report_data.py` / `investigation_reporting.py`：核查事实、冻结快照、三语双报告、监测简报和证据/人工 CSV。
- `investigation_cli.py` / `investigation_mcp.py`：共用公共服务的 CLI 与独立 STDIO；PowerShell 和显式 synthetic replay 脚本位于 `scripts/`。

监测初始 scenario 会保存为默认输入；新周期仅覆盖显式提供的字段，未覆盖的基准资料继续继承。只有实际执行查询后才能记录采集完整性；采集与判定积压分开。修改 profile 后重新检查其模型访问策略，旧周期和报告保留旧快照。

## 复现

在仓库根目录，使用同一个 Python 环境安装并运行（测试额外依赖仅用于离线验收）：

```powershell
python -m pip install ".[investigation]" pytest reportlab
python -m pytest -q tests
python acceptance/probe_investigation_service.py --checkpoint local-installed --output .local/service-check.json
python acceptance/probe_investigation_monitor_service.py --checkpoint local-installed --output .local/monitor-check.json
```

源码模式可显式加 `--source-root .`；安装包验收不设置 PYTHONPATH。Windows 实测72项回归通过，安装版调查4项、监测6项、CLI/PowerShell和真实SDK STDIO均通过。版本/哈希和本机共享依赖条件见独立记录。

本实现使用 synthetic/offline 来源与宿主或确定性 replay 结果；没有调用真实论文/专利/生成模型 API、处理真实公司保密材料或启用操作系统调度。真实模型质量与业务 API 调试属于后续阶段；既有 D18 RAG 验收不由本轮替代。
