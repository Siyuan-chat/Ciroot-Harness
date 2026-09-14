# 离线调查宿主

安装项目的调查依赖后，可用 `rh investigate ...` 调用本地
`InvestigationService`。例如：

```powershell
rh investigate --workspace .local/d19-workspace doctor
rh investigate --workspace .local/d19-workspace start --spec spec.json --runtime runtime.json
rh investigate --workspace .local/d19-workspace tasks RUN_ID
```

也可启动 MCP：`python -m research_harness.investigation_mcp --workspace PATH`。
MCP 只支持离线 host 模式和显式 synthetic/replay 输入，不调用实时来源、生成模型或系统调度器。模型任务必须提交对应版本的结构化结果；保留缺失值、不确定性、原文连续引句和定位。首次加载可能阻塞单进程，CLI 写入与打开的 MCP 库不可并行。

监测配置可先无副作用校验，再创建和读取状态：

```powershell
rh monitor --workspace .local/d19-workspace validate --profile profile.json --spec monitor.json --runtime runtime.json
rh monitor --workspace .local/d19-workspace status MONITOR_ID
```
完整一次调查流程：安装项目（例如 `pip install -e .[test,mcp]`），准备 spec.json/runtime.json；`start` 返回 RUN_ID 后领取任务、提交结构化结果、推进、恢复并导出：

```powershell
rh investigate --workspace .local/d19-workspace start --spec spec.json --runtime runtime.json
rh investigate --workspace .local/d19-workspace tasks RUN_ID
rh investigate --workspace .local/d19-workspace submit RUN_ID TASK_ID --result result.json --task-version 1
rh investigate --workspace .local/d19-workspace work RUN_ID
rh investigate --workspace .local/d19-workspace resume RUN_ID
rh investigate --workspace .local/d19-workspace report RUN_ID
```

`spec.json`、`runtime.json` 和 synthetic scenario 是用户提供的离线输入；本入口不会访问实时来源或生成模型。监测单轮执行和人工分流：

```powershell
rh monitor --workspace .local/d19-workspace run-once MONITOR_ID --scenario cycle.json
rh monitor --workspace .local/d19-workspace review --monitor-id MONITOR_ID
rh monitor --workspace .local/d19-workspace decide ISSUE_ID --decision accept --note note
```
