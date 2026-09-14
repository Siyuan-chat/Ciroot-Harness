# D19-P1 独立验收记录

2026-09-14 · 状态：实施中，尚未验收通过

范围以[D19_P1_HANDOFF](D19_P1_HANDOFF.md)为准。设计基线af414b3；实现检查点由Terra/Luna分阶段提交。本记录在取得独立结果后更新，不以实现者自测替代验收。

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

## 当前结果

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
