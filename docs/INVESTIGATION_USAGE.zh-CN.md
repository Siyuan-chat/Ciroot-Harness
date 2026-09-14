# 离线调查宿主

安装项目的调查依赖后，可用 `rh investigate ...` 调用本地
`InvestigationService`。例如：

```powershell
rh investigate doctor --workspace .local/d19-workspace
rh investigate start --workspace .local/d19-workspace --spec spec.json --runtime runtime.json
rh investigate tasks --workspace .local/d19-workspace RUN_ID
```

也可启动 MCP：`python -m research_harness.investigation_mcp --workspace PATH`。
MCP 只支持离线 host 模式和显式 synthetic/replay 输入，不调用实时来源、生成模型或系统调度器。模型任务必须提交对应版本的结构化结果；保留缺失值、不确定性、原文连续引句和定位。首次加载可能阻塞单进程，CLI 写入与打开的 MCP 库不可并行。
