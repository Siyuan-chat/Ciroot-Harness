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

已安装产品无需设置 `PYTHONPATH`。先用与 PowerShell 相同的解释器安装：`python -m pip install .[investigation]`，再执行以下命令；源码开发自测时才可选设置 `PYTHONPATH=<worktree>\src`。

## 显式启用的 OpenAlex 实时模式（P2）

将 `data_mode` 设为 `live`、`allow_network` 设为 `true`，且仅配置
`sources.openalex`。使用 `anonymous: true`，或只给出 `api_key_env` 的环境变量名；密钥不能写入 JSON。scenario 必须传入已检索、可审计的 `reference_evidence`；实时采集不会导入或修改本地 RAG 文库。搜索/下载尝试、游标、次数和字节上限、正文缺口及 `synthetic: false` 都由同一服务投影到 CLI 和 MCP。下载原文只保存在调查 workspace。

### 发现库 RAG 事实绑定（P3）

在实时采集结束、`evidence_analysis/extract` 任务仍为 pending 时，宿主可调用
`InvestigationService.attach_discovery_evidence(run_id, evidence, mappings, bibliography=None)`。
`evidence` 必须保留 discovery RAG 返回的 `evidence_id`、`document_id`、`version_id`、原文 `text` 和 `locator`；每个 RAG document/version 都须由 `mappings` 连接到实际下载的 OpenAlex `investigation_document_id`、`investigation_version_id`、DOI 和下载 SHA256。服务据此检查身份后，将基线、已采集页证据与 RAG 证据冻结为同一可引用事实集。相同输入会复用；分析或业务判断结果提交后拒绝变更事实。调用不会重新下载、解析或修改 RAG 索引。

最小输入形状如下；`bibliography` 可为同一 `document_id` 的书目信息：

```json
{"evidence":[{"evidence_id":"ev-rag","document_id":"doc-rag","version_id":"ver-rag","text":"原文摘录","locator":{"page":1}}],"mappings":[{"investigation_document_id":"W123","investigation_version_id":"openalex-oa-pdf","doi":"10.1234/example","sha256":"下载文件哈希","rag_document_id":"doc-rag","rag_version_id":"ver-rag"}]}
```

pending 任务可在附加时更新并递增 `task_version`；已领取任务必须重新调用 `get_pending_tasks` 后再提交最新版本。相同附加返回 `reused` 且不递增版本。analysis 或 business_judgment 已提交后，事实快照不再允许变更。
