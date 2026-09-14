# D19-P1 离线实现记录

当前实现仅支持 synthetic/offline replay，不调用真实论文、专利或生成模型 API，也不安装调度器。

核心模块：`investigation.py` 提供可恢复调查及监测公共服务；`investigation_sources.py` 执行注入来源查询和规范化；`investigation_monitoring.py` 与 `investigation_review.py` 保存周期、水位、预算和人工判定；`investigation_report_data.py` 冻结事实；`investigation_reporting.py` 导出双报告和监测简报。

已验：公共调查、来源失败 partial、预算恢复、监测多周期/变化/积压/失败窗口、冻结 digest 与人工队列均以 synthetic probe 验证。待最终 wheel 独立安装验收；真实来源、真实模型和无人值守调度未实现。

```powershell
$env:PYTHONPATH='src'
& 'C:\Users\Siyuan_ye\Documents\ChatGPT\AEM\.local\d19-runtime\venv\Scripts\python.exe' ..\..\acceptance\probe_investigation_service.py --source-root . --checkpoint local --output .local\service.json
& 'C:\Users\Siyuan_ye\Documents\ChatGPT\AEM\.local\d19-runtime\venv\Scripts\python.exe' ..\..\acceptance\probe_investigation_monitor_service.py --source-root . --checkpoint local --output .local\monitor.json
```
