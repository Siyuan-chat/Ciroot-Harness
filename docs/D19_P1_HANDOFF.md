# D19-P1 实施任务书

2026-09-14 · 用户已明确授权执行 P1 · 当前唯一实施边界

用户已批准按整体设计进入离线框架实现，Terra/Luna分工、设计者独立验收并直接回传修正。本授权优先于旧AGENTS/D18停止范围。P1独立验收通过后停止；不调用真实论文/专利/生成模型API、不读取公司秘密、不启用计划任务、不改现有aem_rag配置、不推送GitHub。

## 1. 权威输入与交付

先读SYSTEM_DESIGN.md；INVESTIGATION_EXPERIMENT_PLAN.md中的F01–F12、O01–O04/M01–M08对应离线控制部分适用。PRD/ARCHITECTURE/CONTRACTS/ACCEPTANCE及旧D2/D18行为保留。Terra同时读HANDOFF_TERRA.md，历史全量要求不扩张本次范围。

本轮交付三个检查点：C1任务交接/恢复；C2合成调查/双报告；C3多周期监测/人工分流及包、CLI/MCP、三语指南。每个检查点自测形成不可变提交，立即回传根任务；允许继续下一检查点，修正问题直接回传。最终须集成并提供可安装版本及自测记录。

## 2. 文件归属与协作

使用主仓库.local/d19-worktrees/terra与luna隔离工作树，分支codex/d19-p1-terra及codex/d19-p1-luna。共同起点为本任务书与已确认设计的本地提交。只提交各自文件，保持其它文件原样。

- Terra：核心应用服务、LangGraph编排、存储、来源/规范化适配、发现证据、模型结果验证、预算/数据策略、监测、判定和报告；schemas及包内schema、examples/investigation、所有共享文件（含cli.py/pyproject.toml）和最终集成；tests/test_investigation*.py等核心自测；docs/D19_P1_IMPLEMENTATION.md。
- Luna：独占src/research_harness/investigation_mcp.py、investigation_cli.py、prompts/investigation/*.md；scripts/investigation.ps1；tests/test_investigation_mcp.py与test_investigation_entrypoints.py；docs/INVESTIGATION_USAGE.zh-CN.md、.en.md、.ja.md；docs/D19_P1_HOST_IMPLEMENTATION.md。
- 设计者：规范/任务书/独立acceptance脚本与记录；不改产品实现。Luna提出共享schema/依赖/cli注册变更，由Terra集成。不得两人同时修改同一公共文件。
- 双方通过消息同步接口与提交，Luna可先做薄适配及协议测试；不得为了等待核心自行复制业务逻辑。对接确定后无需用户人工传话。

## 3. 公共服务契约（冻结语义，内部布局可简化）

新增research_harness.investigation.InvestigationService(workspace)，不替换旧Harness。workspace是受管理目录，服务可close()；对外返回普通JSON兼容对象，异常继承现有HarnessError安全投影。CLI/MCP共用以下接口：

| 方法 | 参数/结果最低约定 |
|---|---|
| doctor() | 默认无网络；模式与本地能力、缺项，不显示环境变量值 |
| validate_plan(plan) | 验证查询身份、来源语法能力、预算、出处/外发范围，返回结构化结果，不执行查询 |
| create_investigation(spec, runtime, scenario=None) | spec含status/研究问题/报告目标及参照，runtime显式mode=host和data_mode=synthetic；scenario是明确synthetic来源/原文输入，不是固定最终答案。返回run_id及真实阶段/状态 |
| get_pending_tasks(run_id) | 返回任务列表；task_id、task_version、role、task_type、input_refs及经授权的payload、output_schema、allowed_operations明确；不得把秘密传给不合格执行端 |
| submit_model_result(run_id, task_id, result, task_version) | 相同任务相同结果重交幂等；不同结果/过期版本拒绝；输入校验失败不消费下一阶段、不覆盖有效结果 |
| advance_investigation(run_id) | 推进有界的确定性步骤直至模型任务/等待/终点；JSON进度与真实outcome |
| resume_investigation(run_id) | 恢复检查点，不清零预算、不重做已确认成功操作 |
| status(run_id=None), get_result(run_id), get_artifacts(run_id) | 真实阶段、waiting_reason、outcome、coverage、budget、结果与受管文件描述；不暴露DB对象 |
| export_report(run_id, languages=None) | 从冻结ReportData导出/重试，不重搜；三类产物type、version、language、format、path |
| create_monitor(profile, monitor_spec, runtime, scenario=None) | profile/查询/外发策略版本化；返回monitor_id，配置不等于自动启用OS调度 |
| validate_monitor(profile, monitor_spec, runtime), monitor_status(monitor_id=None) | 前者只验证、不建库或触发周期；后者返回逻辑监测状态，独立于调查run状态 |
| run_monitor_once(monitor_id, scenario=None) | 合成新周期可注入不同来源页；返回run_id/监测状态；重复触发/恢复不损坏已有进度 |
| pause_monitor(monitor_id), resume_monitor(monitor_id) | 显式控制逻辑监测状态；resume不暗装定时任务 |
| review_list(monitor_id=None), review_decide(issue_id, decision, note='') | 保留稳定issue与事件；显式人工决定，不隐式改全局规则 |

参数名如需调整先由Terra发出简短契约确认，Luna与根任务同步后按一个版本实现；不要各自猜测。角色ID统一：planning、paper_search、patent_search、evidence_analysis、business_judgment、synthesis、writing、verification。可按来源/章节创建多个同角色任务，仍共用预算。

schemas中的D19输入/任务/结果是权威，包内使用相同内容；旧D2 schema兼容。每个模型任务必须产生实际被下一步消费的结构化输出；自然语言问题和动态来源材料改变结果。禁止在核心以题目匹配表、固定最终报告或固定判定代替模型交接。

## 4. 离线执行与适配边界

P1模型结果由独立合成driver提交；此driver显式是test/replay，不称真实Luna推理或科学效果。模型任务可停下来由外部宿主提交，框架不得后台调用生成模型API。api模式未实现时明确unsupported。权限不合格时等待且领取结果不含受限内容。

来源协议使用可注入的离线响应/transport，覆盖两来源查询、分页、身份、部分失败、获取、PDF/XML/TXT规范化及证据定位；真实HTTP明确不启用。真实来源认证/分页可靠性留P2，用故障注入验证错误和恢复控制。

复用现有RAG原文/证据语义并提供发现库接线边界；离线fixture可以显式使用轻量确定性检索，不宣称是真向量效果。不得修改/重建主仓库.local/rag-acceptance/real-v3/workspace或23篇基准。解析/嵌入适配可注入离线实现，但正常化块保留原文版本和PDF/XML定位，不能将任意最终证据字典直接当作已解析正文而省略入库流程。

LangGraph必须拥有实际有条件推进的调查图与可恢复进度，不用一张装饰性图外加平行手写任务状态机。SQLite业务记录/预算/报告可保留；持久化流程与任务幂等配合。不要每个节点建一个新包/工厂；用现有依赖公开接口，必要依赖变更自测并记录。

## 5. 必须守住的不变量

- draft或非法规范不启动；用户条件不默删，缺值/条件不补造。
- 参照版本冻结，新材料是discovery；重复文本/版本复用，旧证据仍可解析。
- 文献DOI规范化，专利公开文本与族区分；保存所有查询/筛选理由、coverage与失败。
- D19引句必须是正确文档/版本的连续原文子串，PDF物理页/XML段落或权利要求定位有效；核心验证不只信任模型的verified标签。
- 数值/单位/条件保留；缺失不等于0，条件冲突不能输出优势。编排的核查结果应影响正式结论和人工问题。
- company_id和public/confidential限制在任务领取/检索/证据访问前执行；查询外发许可独立，禁止泄漏至不合格模型payload、日志或分享报告。synthetic测试不需要真实秘密。
- 相关性relevant/irrelevant/uncertain与human_review_required独立。未判定不冒充false；补查结束仍uncertain转人工；公司/程序/核查可升级，已有open问题不能被下一轮模型false静默关闭。
- 双报告必须有与输入相关的实质正文、章节主张映射和真元数据书目；合成资料标注synthetic。JSON事实与Markdown/HTML/CSV/BibTeX对应；只改语言或导出不重搜。中英日以各自语言正文测试，不靠标题翻译冒充完整本地化。
- 监测至少三周期涵盖初始化、无变化、延迟收录/正文变化；查询完成位置与判定积压分开，失败不推进完整窗口，新公开和旧记录首次发现分开。
- 调用前中央预留，错误重试有上限，恢复不清零；每轮和跨周期预算同时生效。真实网络调用不在P1，注入uncertain外部结果验证记账。
- 未确认服务调用/失败与真正空成功结果区分；只重试需要的阶段；partial保留成功分支。

## 6. 脚本、指南与包

拟入口：rh investigate doctor/plan-validate/start/tasks/submit/work/resume/status/result/report 与 rh monitor validate/create/run-once/status/pause/resume/review。Luna实现子命令解析模块，Terra在cli.py委派，不复制业务。

investigation_mcp为独立STDIO入口，复用服务，不改变aem_rag已注册工具。stdio stdout仅协议；CLI支持机器可解析JSON，PowerShell薄脚本转交已安装模块。提示词、schema、synthetic示例随wheel分发，不依赖源码cwd或用户私有skill路径。

自测记录必须含提交、可复制命令、实现/已测/待测状态、实际输出路径。非editable安装后跑CLI/MCP和离线闭环；包测试可复用本机已有依赖，但说明是否共享heavy依赖，不宣称干净新机器全隔离。

## 7. 独立验收与停止

设计者使用实现者未见的合成输入、故障及变化，通过公共接口、CLI和MCP验收。自测通过不是独立验收。F01–F12及相关O/M离线控制均有证据，D2/D18受影响的回归通过，安装包可用，无当前启用路径阻断缺陷，才标P1完成。

真实宿主科学质量、OpenAlex/EPO在线、公司真实资料、无人值守调度与API生成模型均留后续阶段。发现离线无法证明的事项如实标pending，不为凑通过调用真实来源。达到P1门槛后停止并汇报，等待P2授权。

## 8. P1实施中的并行拆分

为避免核心串行承担独立模块，报告渲染由Terra报告子任务独占investigation_reporting.py/test_investigation_reporting.py；调查核心负责证据核查和冻结ReportData后接线。Luna完成入口后，追加独占investigation_review.py/test_investigation_review.py，提供ReviewStore(workspace)：record_judgment(monitor_id, company_id, document_id, document_version, rule_version, judgment, evidence_refs, forced_reasons=None)、review_list(monitor_id=None)、review_decide(issue_id, decision, note='')、close。核心负责调用，不重复实现队列。

人工问题按monitor/company/document保持稳定身份；文档/规则版本、原模型判定、程序升级和人工决定均保留事件。uncertain及强制规则升级为人工；模型false不关闭既有open项。人工relevant/irrelevant关闭当前问题，uncertain/defer保留open；新证据/规则需要人工时可重开，同版本重交不抹人工决定。此拆分实现已有P1范围，不新增监测服务或外部动作。

Terra报告子任务完成渲染后，追加独占investigation_monitoring.py/test_investigation_monitoring.py，实现纯持久化MonitorStore；调查图和公共service桥接仍由核心Terra负责。该store持久化profile/规则版本、周期、采集水位、候选版本、判定积压与跨周期预留；不执行网络/模型、不新增agent状态机。采集已完成而判定积压未清不阻止新周期采集。
