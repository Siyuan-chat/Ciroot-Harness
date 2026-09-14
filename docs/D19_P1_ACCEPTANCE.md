# D19-P1 独立验收记录

2026-09-14 · 状态：D19-P1 离线框架独立验收通过

范围以[D19_P1_HANDOFF](D19_P1_HANDOFF.md)为准。设计基线af414b3；实现检查点由Terra/Luna分阶段提交。本记录在取得独立结果后更新，不以实现者自测替代验收。

## 本轮结论

验收实现提交：`8f0895fad11d1ebb81b27cd8c0209510c49a1efd`。Terra/Luna 实现，设计任务从 Git 不可变归档及非 editable wheel 独立验证。C1、C2、C3 的本轮离线边界均通过；本轮停止，不自动进入 P2。

| 最终检查 | 结果 | 本地证据（位于 .local/d19-acceptance） |
|---|---|---|
| 全部项目回归 | 72 passed | pytest-8f0895f.xml |
| 安装版调查公共服务 | 4/4，通过实际 PDF/XML 证据、八角色、6份三语双报告、引用拒绝、部分失败与恢复 | service-installed-8f0895f.json |
| 安装版监测公共服务 | 6/6，通过四周期、变化/迟到、实际采集、累计预算、人工历史、规则和基准继承 | monitor-installed-8f0895f.json |
| 真实 CLI / PowerShell | native rh、模块入口、status、冻结导出、monitor create/profile-update 通过 | installed-8f0895f/acceptance.json |
| 真实 SDK STDIO MCP | 初始化、工具发现、任务交接、非法提交拒绝及第二进程恢复通过 | mcp-installed-8f0895f.json |
| 包资源 | 5 schemas、9 prompts、7 examples；项目从安装目录导入，无 PYTHONPATH | installed-8f0895f/acceptance.json |

完整源码测试均为离线夹具。旧 RAG prepare 测试显式 stub 版本元数据，验证缓存行为，不证明真实重型 RAG 环境；本轮没有重建或改动已验收的 23 篇库。来源分页/故障 10 项、合同 6 项、ReportData 8 项及未改动的 store 不变量复用下方已记录的有效证据。

安装环境位于 `.local/d19-installed/venv`，项目为真正 wheel 安装，依赖通过 `site.addsitedir` 共享 `.local/d19-runtime/venv`，以正确加载 Windows SDK 的 pywin32 初始化；不是全新机器全隔离证明。wheel 位于 `.local/d19-acceptance/dist-8f0895f/research_harness-0.1.0-py3-none-any.whl`，SHA256 为 `80ee8d1e4fd4082a17fa5521e9138c50ec1fbb796ce2a9edeb0b6862285284c3`。

本轮成立的是：显式合成来源和宿主任务/replay 驱动下，调查、监测、人审及报告的工程闭环。真实生成模型/订阅宿主的判断质量、真实论文/专利 API、真实公司资料策略与无人值守调度仍属于后续阶段。既有文献下载和 D18 RAG 服务保留；没有启用新后台任务或推送 GitHub。

## 验收方式

使用独立合成资料，经公开应用服务、安装包CLI和MCP执行。合成来源/模型任务不等于真实检索服务或科学判断；进程禁止外网连接（MCP仅本地STDIO）。不访问当前23篇RAG运行库，不读取公司资料，不修改Codex已注册工具。

| 检查组 | 关键观察 | 对应方案 |
|---|---|---|
| 需求与任务 | draft拒绝、host无需生成key、任务实际被消费、重复/冲突/过期提交、中断恢复 | F01–F03、F11 |
| 来源与正文 | 两来源分页、稳定身份、族/文本、正文解析定位、失败/空结果/截断区分 | F04–F06、F08 |
| 证据与报告 | 冻结基准、增量/版本、不正确引用、条件冲突、动态双报告、三语及导出重试 | F09–F10、O01–O04离线控制 |
| 预算与恢复 | 预留、故障/uncertain记账、累计预算、部分结果、恢复不重置 | F07、F11 |
| 企业隔离 | 公司身份、模型payload、查询外发、日志与报告，策略不合格时等待 | M01–M02 |
| 持续监测 | 初始化/无变化/迟到与正文变化、采集与判定积压、去重与窗口恢复 | M03–M04、M06 |
| 人工分流 | 相关/不相关均可需人工；uncertain强制转；漏转升级；人工历史与open问题 | M05、M07离线控制 |
| 分发与接入 | 非editable wheel、schema/提示词/示例、CLI/PowerShell/STDIO MCP、旧行为回归 | F12 |

## 证据与环境

独立输入、运行输出和机器检查记录放.local/d19-acceptance，受Git忽略。可公开且无私有路径依赖的独立探针放acceptance/。检查点和测试命令、通过/失败/修正原因在本记录归档。对于未改变的D18重型解析/索引能力复用旧验收，不重跑全库。

本机2026-09-14的桌面运行时已更新，旧RAG venv依赖部分来自系统目录，当前jsonschema/langgraph不可导入。P1新建.local/d19-runtime/venv，不修改旧RAG环境；新环境与全新机器安装证据区分。

## 检查点历史

C1初始骨架42e028a/23c8ac1尚未通过。对23c8ac1的独立公共接口探针在模型任务上限1时提交8个不符合角色语义的非空对象，全部被接受并到达completed；没有产生真实来源/证据/报告。这证明schema、配额和结果消费尚未落实，不能以可调用接口或LangGraph导入代表完成。失败证据为.local/d19-acceptance/c1-initial-diagnostic.json，已回传Terra从编排与结果契约重设计，不覆盖初始失败记录。

独立P1环境核心依赖已安装并实际导入成功。P2实际API认证/服务覆盖、真实宿主科学质量、企业保密执行器和无人值守调度均不在本轮通过声明范围内。

检查点21148be的独立数据链探针：真实8角色交接、2份入选资料、5个图节点trace及重启恢复通过；预算2但计划需要2个来源任务时，系统只抛错而保留无待办的waiting_model，预算终止状态未通过。结果为.local/d19-acceptance/c1-21148be-chain.json，已回传修正。

报告首提交3e117dd（包含在21148be快照）独立6项探针均未通过：普通双出口误要求监测摘要、无claim正文绕过、重复证据身份、非法语言路径错误、缺失导出文件假成功、增加语言改写旧文件。失败结果为.local/d19-acceptance/reports-21148be.json，正在由报告实现者修正；保留初始失败记录。

Luna接口5474c53自测使用真实SDK子进程STDIO（5项通过），尚待与真实核心联测及安装包独立验收。独立D2回归在P1新环境下运行tests/test_harness.py，12 passed；此结果仅覆盖未修改的旧核心行为，不是D18全库复测。

修正检查点c3eef60：独立C1数据链、预算耗尽恢复、晚期预算耗尽保留证据三项均通过。8角色交接、5图节点trace和重启恢复可见；max_tasks=2持久partial而无虚假待办；max_tasks=7保留2条已取得证据及findings。结果.local/d19-acceptance/c1-c3eef60-chain.json。本检查点通过C1链路范围，C2/C3与整体P1仍未验收。

报告修正4feaa13经根任务从Git归档重新运行独立探针，6/6通过：双出口、无支持正文阻断、身份/路径验证、导出重建、语言扩展旧hash保留。结果.local/d19-acceptance/reports-4feaa13-independent.json，仅代表渲染模块通过，核心报告链仍待集成。

C1检查点c3eef60追加独立边界10/10通过（draft/mode/schema/跨run/版本/幂等/重启/unknownrun/外网0请求），记录.local/d19-acceptance/c1-c3eef60-boundaries.json。

来源c5a1f8f独立5项中3通过，PDF页2被标页1及XML后续段落丢失未过；结果.local/d19-acceptance/sources-c5a1f8f-independent.json。ReviewStore首63b6bf7独立5项全部未过：跨公司/文档幂等身份、有效人工标记、人工权威、事件重复、结构化错误；结果.local/d19-acceptance/review-63b6bf7-independent.json。两模块均已回传修正，未计入完成。

来源e40cb11经根Git快照独立复测5/5通过（当时测试范围）；后续审查另发现doc/version直接拼接有歧义碰撞，已加入身份元组探针，随B修复。ReviewStore015e034独立5/5通过；MonitorStore4500d5c独立4/4通过（三周期、冻结规则、失败/幂等与累计预算），两者均待图/公共服务接线。

C2-B首5a79b99独立7/7未通过：同source多query任务身份冲突、失败误completed、源预算无可恢复partial、拒绝基准被静默删、派生查询外发未拦、transport元数据绕过保密、循环cursor超时。已单独委派Terra来源任务修复，结果.local/d19-acceptance/queries-5a79b99-independent.json。

ReportData builder首7983e96组合探针3失败/4通过，未接受：supported状态与内部verified不一致、无支持报告无法导出诊断、无支持章节状态错误；若负例因为所有正常claim均被错误拒绝而通过，不视为引用边界的有效验收。记录.local/d19-acceptance/report-data-7983e96-independent.json。

ReportData修正efef397经根独立组合复测7/7通过：实际6份三语双报告、CSV证据映射、跨finding引用绑定、无支持可导诊断、章节与条件边界、上游partial传播。结果.local/d19-acceptance/report-data-efef397-independent.json。

来源修正bb0e011经根独立公共服务B探针7/7及来源模块5/5通过，后者含新增doc/version身份元组碰撞测试。结果.local/d19-acceptance/queries-bb0e011-independent.json与sources-bb0e011-independent.json。尚未覆盖最终整合包或真实API；更完整故障/契约/监测接线仍在后续验收。

已准备独立非editable安装验收环境.local/d19-installed/venv：复用桌面系统库，并通过明确的d19-shared-dependencies.pth复用本轮d19-runtime依赖；不是完全隔离新机器。安装项目前检查langgraph/jsonschema/mcp/pypdf可导入，research_harness不可导入。后续wheel安装将检验实际包来源和资源，不使用源码PYTHONPATH。

contracts首fabb1a8因整项/结果envelope不匹配拒绝。149e105初始五项通过，但静态复核发现内层约束被覆盖；扩展nested-fields后重现缺document_id仍可提交，撤回严格合同通过。修正c5b3fc0归档独立6/6通过，结果contracts-c5b3fc0-independent.json。该快照完整公共服务探针仍失败：无效引句提交消费了任务，已回传核心修正；模块通过不能覆盖服务层失败。

扩展来源查询探针包含10项，覆盖429/timeout/5xx实际重试序列、401/uncertain/invalid_json不重做、无身份candidate及未定义来源引用。c5b3fc0下9通过，partial链因核心仍使用旧角色schema拒绝新结果形状未通过；等待核心统一新契约后复测。FileLock3.32.6已安装到本轮验收环境，未修改旧D18环境。

C2检查点88d4f26归档独立复跑：公共服务完整8角色、6份三语双报告、3种伪造claim拒绝与冻结重启通过；扩展来源queries10/10通过；真实SDK子进程STDIO初始化、创建、非法提交拒绝及第二进程恢复通过。扩展service权限读取通过，混合正常TXT/非法PDF失败传播仍未通过，回传修正。记录service-88d4f26-independent.json、queries-88d4f26-independent.json、mcp-88d4f26-independent.json及service-88d4f26-expanded.json。

修正ba25f33归档独立验收：service4/4通过，包含2页实际PDF与2个XML定位、8角色/6份三语报告、有效任务幂等、伪造引用拒绝、正文获取失败partial、发现库公司权限及任务上限2/7恢复。ReportData扩展8/8通过，增加缺失目标正文/零证据结果不能completed。结果service-ba25f33-independent.json与report-data-ba25f33-independent.json。C3与最终安装包仍在接线验收。

C3初版e003622独立公共service探针：四周期/规则和人工历史、积压与失败窗口的初步接口检查通过，但累计任务预算抛未处理PreflightError，未接受C3。静态复核发现更重要路径问题：run_monitor_once在实际planning/transport前直接从scenario.sources登记采集且any(page.error)决定完整性，会把未检索材料和临时错误当最终事实。已要求改为实际查询账本驱动，并扩展actual-collection探针及冻结digest业务事实检查。记录monitor-service-e003622-independent.json保留原初步结果，不能作为C3通过声明。

最终安装验收补记：0608806 的 72 项回归通过，但安装版普通报告因 `monitor=None` 触发 renderer 空值回归；已由 8f0895f 修复并重新构建、安装、验收。独立环境最初因共享依赖未处理 pywin32.pth 而无法启动 MCP，改用 site.addsitedir 后正确加载 Windows DLL；产品仍从独立安装目录导入。最终 8f0895f 的 72 项回归、安装调查4项、监测6项、CLI/PowerShell和真实STDIO全部通过，早期失败输出保留。
