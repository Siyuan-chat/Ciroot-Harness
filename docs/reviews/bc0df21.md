# bc0df21 独立验收与返工意见

日期：2026-09-09

对象：`codex/research-harness-alpha` / `bc0df218db22f876960a63f55fe186228b4877d5`

结论：**G1 未通过，不进入聚合物设计案例或 GitHub demo 发布。** 可以保留为阶段性基础提交，继续完成既定 M1–M5。

## 1. 独立核验结果

| 检查 | 结果 |
|---|---|
| 从指定提交导出隔离快照并运行原有 unittest | 4/4 通过，与自测一致 |
| 构建普通 wheel | 通过，无依赖、无网络构建 |
| 项目内隔离 venv 安装 wheel、真实 rh.exe --help | 通过；已安装包由 venv/site-packages 加载 |
| editable 安装 | 本轮未复测；普通 wheel 路径已证明不必写受控解释器的用户 site-packages |
| 核心调查/真实组件/真实 API | 未实现或未验证，不能以 fixture 通过代替 |
| 独立反例和用户流程检查 | 发现下列可复现缺陷 |
| 产品源码改动 | 本验收没有修改 Terra 实现；仅新增验收文档与诊断脚本 |

原报告对“基础实现”和待完成范围的说明是准确的，但该范围远小于交接要求的可安装运行完整框架。没有凭据只阻止真实在线验收，不能作为跳过对话、解析、RAG、适配器、编排和恢复实现的理由。

## 2. 必须返工的问题

### F01 — G1 阻断：核心工作流尚未实现

缺少 chat/需求澄清、实际模型适配、Docling/XML 证据解析、多语言本地 RAG、LangGraph 编排、OpenAlex/EPO 查询和正文获取、分析/核查、问题创建/reopen、预算/锁及真正恢复。完整的技术地图和三语解释也没有实现。

独立 CLI 检查：`rh chat --help` 返回 2，提示 invalid choice。现有 report 只是标题变化，正文的 Coverage、Limits、说明仍为英文，technical_map 恒为空。

位置：`src/research_harness/cli.py:9` 起的命令注册；`service.py:33` 起的 run；`pyproject.toml:10` 起的依赖。
涉及：M1–M5，尤其 A02、A06、A09–A15、A17–A24、A26–A29、A31–A34。

要求：按原交接完成核心真实本地组件与可调用服务。fixture 可保留作测试，但不能作为默认调查实现。报告须据实更新每项状态，避免把“已声明依赖”当作完成集成。

### F02 — P1：手写校验器与公开 Schema 不一致

六个违反现有 Schema 的输入均被接受：
1. max_candidates = -1。
2. global_rule_updates = automatic。
3. publication_date_from = 2026-02-30。
4. reports = []。
5. threshold criterion 的 target = {}，没有 operator/value/unit。
6. runtime.llm 包含 api_key 明文值字段（探针使用无效合成哨兵，不是真实密钥）。

位置：`src/research_harness/contracts.py:22`、`:41`、`:52`。
涉及：R05、R15、R18、R22；A03、A05、A18、A19。

要求：复用 JSON Schema/Pydantic 等成熟校验机制，并测试其与公开 Schema 的等价边界；Schema 后再做语义/能力检查。不能继续维护一套只检查少量字段的平行验证规则。加入上述回归反例。

### F03 — P1：运行时忽略用户的参照库选择

导入两份 baseline 文档，spec 明确 collection_ids=[]、document_ids=[第一份]；运行 manifest 却包含两份。原因是 run 硬编码查询全部 baseline collection，没有读取 reference_library 的选择。

位置：`src/research_harness/service.py:35`。
涉及：R07、R14；A08、A11、A34。

要求：解析 spec 的实际参照选择，冻结精确 document version IDs，而非仅当前 document IDs；缺失指定对象要给出明确结果。测试子集选择、集合与显式 ID 组合、版本更新和 discovery 隔离。

### F04 — P1：重新导出旧报告会改写历史事实

完成一轮后导入第三份 discovery 文档，再 report 同一 run_id；report.json 在同一路径被覆盖，documents 从 2 变 3，新增文档出现在早已完成的调查中。人工清单也直接读取当前全局列表，有相同跨时点/跨范围风险。

位置：`src/research_harness/service.py:44`、`:46`。
涉及：R07、R20、R21；A08、A24、A25、A34。

要求：从本轮冻结 ReportData/明确关联的 finding、evidence、review snapshot 渲染。后来的人工决定可产生新视图，但必须有新时间标识，不能改写历史运行快照。补充“完成后追加资料、修改人工状态、重新导出”的回归测试。

### F05 — P1：预检查、恢复及退出状态不满足命令契约

清除全部测试来源/模型凭据后，配置任意非空模型及 Embedding 名称，run 仍生成 partial 报告并返回 0。resume nonexistent-run 返回 run:null 且退出 0；对有效 run 也只是读取记录，没有恢复执行。

位置：`src/research_harness/service.py:28`、`:40`；`src/research_harness/cli.py:24`、`:29`。
涉及：R02、R21、R23；A05、A15、A26、A28。

要求：preflight 统一覆盖必需凭据、依赖、模型能力及来源启用范围。未知 run 返回有效错误；真实 resume 继续持久化任务而不重置预算。partial 使用明确的非零机器状态（设计为 4），failed/cancelled 与成功区分。尚不支持的命令不能以成功退出伪装执行。

### F06 — P2：只读校验会创建工作区文件

在空目录中执行 validate --spec <合法文件>，即创建 raw/、reports/、research.sqlite。原因是所有命令都先实例化带写入副作用的 Harness；validate 没有 workspace 参数便默认写当前目录。doctor 也通过同一有副作用入口。

位置：`src/research_harness/cli.py:19` 和 `storage.py:8` 起。
涉及：R05、R22；A01、A03。

要求：纯配置校验/本地诊断保持只读；只在真正需要存储的操作中初始化工作区。补充运行前后目录比较。

### F07 — P2：wheel 缺少公开 Schema 与运行资源

安装成功的 wheel 只有六个 Python 模块和 dist-info，没有任何 .schema.json。语言/报告资源尚未独立实现；未来安装态不能依赖仓库根目录资源路径。

位置：`pyproject.toml:19` 起的 setuptools 配置；`contracts.py:8` 的 ROOT 也不是安装态仓库定位方式。
涉及：R24；A32。

要求：将公开 Schema、实际模板/语言资源纳入包数据，通过 importlib.resources 等安装态方式访问；从非源码目录验证。锁定真实验证的依赖，并提供完整安装步骤。这里是包内资源问题，不是用户目录权限问题。

## 3. 原有四项测试的证明范围

它们证明 draft 可被特定前置条件拒绝、文件可写、测试模式能输出文件、doctor 声称未联网。它们没有测试全文解析、索引/检索、科学引用、来源通信、实际恢复、人工问题生命周期或完整三语行为。

“生成三份不同文件名的报告”不等于三语产品完成；“保存一组 baseline IDs”不等于服从用户基准选择；“记录预算”不等于执行预算控制。

## 4. 可复现检查

所有输入是明确标注的合成契约文本，没有真实科学数据，也没有发起模型/来源 API 调用。

从项目根目录执行，先准备指定提交的隔离快照：

```powershell
New-Item -ItemType Directory -Force .local/acceptance/bc0df21 | Out-Null
git archive --format=zip --output=.local/acceptance/bc0df21/snapshot.zip bc0df218db22f876960a63f55fe186228b4877d5
Expand-Archive .local/acceptance/bc0df21/snapshot.zip .local/acceptance/bc0df21/source
python acceptance/probe_bc0df21.py
```

如快照已存在，无需重复解压。探针为该提交编写，使用已有内部接口作诊断，不限制后续合理重构。它每次创建新的测试数据目录；当前提交预期退出 1，JSON 列出违例。后续实现者应将这些行为回归迁移到正式测试。

本机验证使用随应用提供的 Python 3.12.14。wheel 安装路径：

```powershell
python -m pip wheel .local/acceptance/bc0df21/source --no-deps --no-build-isolation --no-index --wheel-dir .local/acceptance/bc0df21/dist
python -m venv .local/acceptance/bc0df21/venv
.local/acceptance/bc0df21/venv/Scripts/python.exe -m pip install --no-index --no-deps .local/acceptance/bc0df21/dist/research_harness-0.1.0-py3-none-any.whl
.local/acceptance/bc0df21/venv/Scripts/rh.exe --help
```

构建 Python 需有 setuptools>=68；本机已有，因此无网络构建通过。干净机器按实现者最终文档安装构建依赖，不能假设 --no-build-isolation 会自动准备它们。

原始探针结果：`.local/acceptance/bc0df21/acceptance-probes.json`。临时工作区和安装环境不提交 Git。

## 5. 发回 Terra 的任务

继续同一实现分支完成 M1–M5，不更改原始需求来适配当前骨架。先修复 F02–F07 的数据契约与持久化问题，再完成需求入口、真实本地文档/RAG、来源适配、编排/分析/恢复和三语输出。需要时可按模块分批提交，但最终交接标准仍是完整框架。

使用项目内 venv 安装依赖；用户 site-packages 无写权限不是本地安装的阻断条件。真实 API 凭据暂缺时完成协议测试及真实本地组件集成，在线项明确 pending。返回更新的实施报告、对应验收 ID、自测命令、分支/提交和待验收项。

此轮不合并实现分支，不开始科学案例，也不发布 GitHub demo。
