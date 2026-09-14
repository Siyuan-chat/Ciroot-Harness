# 离线调查宿主

安装项目的调查依赖后，可用 `rh investigate ...` 调用本地
`InvestigationService`。例如：

```powershell
rh investigate --workspace .local/d19-workspace doctor
rh investigate --workspace .local/d19-workspace start --spec .\examples\investigation\synthetic-spec.json --runtime .\examples\investigation\synthetic-runtime.json --scenario .\examples\investigation\synthetic-scenario.json
rh investigate --workspace .local/d19-workspace tasks RUN_ID
```

也可启动 MCP：`python -m research_harness.investigation_mcp --workspace PATH`。
MCP 只支持离线 host 模式和显式 synthetic/replay 输入，不调用实时来源、生成模型或系统调度器。模型任务必须提交对应版本的结构化结果；保留缺失值、不确定性、原文连续引句和定位。首次加载可能阻塞单进程，CLI 写入与打开的 MCP 库不可并行。

监测配置可先无副作用校验，再创建和读取状态：

```powershell
rh monitor --workspace .local/d19-workspace validate --profile profile.json --spec monitor.json --runtime runtime.json
rh monitor --workspace .local/d19-workspace status MONITOR_ID
rh monitor --workspace .local/d19-workspace create --profile profile.json --spec monitor.json --runtime runtime.json --scenario .\examples\investigation\synthetic-scenario.json
```
完整一次调查流程：安装项目（例如 `pip install -e .[investigation]`），准备 examples/investigation 下的 spec/runtime/scenario JSON；`start` 返回 RUN_ID 后领取任务、提交结构化结果、推进、恢复并导出：

```powershell
rh investigate --workspace .local/d19-workspace start --spec .\examples\investigation\synthetic-spec.json --runtime .\examples\investigation\synthetic-runtime.json --scenario .\examples\investigation\synthetic-scenario.json
rh investigate --workspace .local/d19-workspace tasks RUN_ID
rh investigate --workspace .local/d19-workspace submit RUN_ID TASK_ID --result result.json --task-version 1
rh investigate --workspace .local/d19-workspace work RUN_ID
rh investigate --workspace .local/d19-workspace resume RUN_ID
rh investigate --workspace .local/d19-workspace report RUN_ID
```

`spec.json`、`runtime.json` 和 synthetic scenario 是用户提供的离线输入；本入口不会访问实时来源或生成模型。监测单轮执行和人工分流：

```powershell
rh monitor --workspace .local/d19-workspace run-once MONITOR_ID --scenario .\examples\investigation\synthetic-scenario.json
rh monitor --workspace .local/d19-workspace review --monitor-id MONITOR_ID
rh monitor --workspace .local/d19-workspace decide ISSUE_ID --decision relevant --note note
```
## 监测字段与确定性 replay

`profile.json` 至少包含 `company_id`、`rule_version`、`scope`；监测规范至少包含 `name`、`report_languages`。每个 synthetic 周期的 scenario 必须显式提供 `cycle_key`、`window_start`、`window_end`，时间窗不会从系统时钟推断。更新 profile 使用：

```powershell
./scripts/investigation.ps1 -Monitor -Command profile-update -Workspace .local/d19-workspace -RunId MONITOR_ID -Profile profile-v2.json
```

该脚本只转发到应用服务，不安装 OS 监测、不启用计划任务，也不访问真实 API。`scripts/investigation_replay.py` 可消费 `get_pending_tasks` 保存的 JSON，生成标记为 `synthetic=true` 的中英日结构化结果；它是确定性测试驱动，不代表真实模型或科学效果：

```powershell
python scripts/investigation_replay.py --pending pending.json --output replay-result.json
```

PowerShell 中先设置源码路径：`$env:PYTHONPATH='C:\path\to\terra\src'`，再执行以下命令。

安装轻量宿主依赖：`pip install -e .[investigation]`。

