# Sol 监督、Luna/Terra 执行：GUI 开发交接

日期：2026-09-24。当前交付是方案与 handoff；本对话未启动开发代理、未修改产品代码、未调用研究 API。

新对话执行更新：用户已要求本地 GUI 开发，并选择只借鉴 Zotero 交互、不复制 AGPL 源码。A 阶段审计见 GUI_FRONTEND_REUSE_AUDIT.md 与 GUI_BACKEND_AUDIT.md；GUI_API_CONTRACT.md 为 B 阶段共同合同。上面的原始启动词保留为历史交接文本。

## 目标与授权

用户已确认：借鉴开源前端源码，改造为本项目 harness 的使用方式；指定另一个对话由 Sol 监督、Luna 与 Terra 执行。完整范围和验收见 [GUI_FRONTEND_PLAN.md](GUI_FRONTEND_PLAN.md)。本文件可作为另一个对话的执行指令，但实际启动以用户在该对话下达的开发请求为准。

首选 Zotero Web Library 源码复用；先评估再实现。允许范围内本地开发、依赖安装、公开上游源码读取、离线测试与浏览器验收；无新增研究 API、模型付费、监测、部署或 GitHub 推送授权。

## 恢复顺序

1. Sol 读取本文件、GUI_FRONTEND_PLAN.md、AGENTS.md，以及 SYSTEM_DESIGN.md/CONTRACTS.md 的相关业务边界。
2. 读取 D19_QUERY_LOOP_PUBLIC_EXPORT_ACCEPTANCE.md、D19_MODEL_API_STAGE.md，核对当前源码。公共导出已有通过记录，不重复修复旧 handoff 中已关闭的问题；API 模式已有实现，不能再次当作空白能力开发。
3. `git status --short` 确认已有未提交工作；当前目录含此前调查/API工作，不 reset、不覆盖、不提交无关修改。若创建隔离工作区，必须显式包含所需未提交权威代码；不能从旧 HEAD 开始后声称缺失功能。
4. 确认 Sol、Luna、Terra 的实际可用模型标识及用户选定档位。监督者不默默替换模型。Luna/Terra 通过子代理承担工作，不创建额外用户任务。
5. Sol 分派 A 阶段：Luna 评估前端源码；Terra 评估后端能力与接口，二者只在各自报告写入。Sol 在两份固定候选完成后冻结合同，再下达 B 阶段实现。

## 分工与文件所有权

下表路径是本阶段拟建路径；已有同名文件则先读并保留已有内容。Sol 冻结的接口文件只能由 Sol 写，执行者提交建议，不抢写。

| 负责人 | 工作与允许写入 | 不得写入 |
| --- | --- | --- |
| Sol | docs/GUI_API_CONTRACT.md、docs/GUI_ACCEPTANCE.md、docs/GUI_HANDOFF_SOL.md、docs/GUI_FRONTEND_PLAN.md；阶段记录与最终文档入口；必要范围内 docs/DECISIONS.md | 产品代码；不代替执行者边写边修 |
| Luna | frontend/；docs/GUI_FRONTEND_REUSE_AUDIT.md；docs/GUI_FRONTEND_IMPLEMENTATION.md；前端许可证清单与前端测试 | Python、根 pyproject.toml、后端合同、冻结数据 |
| Terra | src/research_harness/gui/；tests/test_gui_*.py；pyproject.toml 的 GUI 可选依赖；docs/GUI_BACKEND_AUDIT.md、docs/GUI_BACKEND_IMPLEMENTATION.md、docs/GUI_RUNTIME.md | frontend/、冻结科学资料和无关源码 |

现有核心文件默认保护。Terra 审计若发现需要最小只读方法、合作停止或执行器接线，可提出精确文件/方法/原因/回归要求；Sol 在本方案范围内批准白名单后，由 Terra 单写。不要为例行的范围内接口补齐反复问用户；改变科学算法、数据模型语义或扩大产品范围才升级。

README/PRD/ARCHITECTURE/CONTRACTS/ACCEPTANCE 的 GUI 入口与阶段状态由 Sol 在收尾时按实际完成情况最小更新，历史验收原文保留。根锁文件与依赖配置按所属前后端单写；不能两方同时执行全仓格式化。

## 给 Luna 的 A 阶段任务

目标：证明哪些 Zotero Web Library 源码值得复用，给出一个可落地的前端改造边界。

输入：GUI_FRONTEND_PLAN.md 第 3–4 节、上游 README/源码/许可；无需项目私有 PDF、数据库或凭据。

操作：只读获取上游到本地忽略目录，固定 commit；检查集合/列表/详情/阅读组件的依赖与 Zotero API 耦合，核对构建入口和许可。提交 GUI_FRONTEND_REUSE_AUDIT.md，列准确源码位置、保留/改造/排除项、阻断和建议。必要最小构建验证只在上游隔离副本进行，不提前大规模复制产品代码。

完成条件：Sol 能据报告决定复用路径和构建方式；不能只给截图或“看起来可以”。若上游获取受阻，说明具体阻断，不编造源码结论。

## 给 Terra 的 A 阶段任务

目标：将现有服务映射到 GUI 所需能力，避免重复实现。

输入：GUI_FRONTEND_PLAN.md 第 5–6 节、InvestigationService、RagLibrary、investigation_model_api，以及两个最新阶段验收文件。

操作：只读核对公开返回值、线程/锁、角色任务、人工清单作用域、停止/恢复、文件服务和凭据策略。提交 GUI_BACKEND_AUDIT.md，逐项区分 existing/adapter-needed/core-gap/unsupported，并给最小修改白名单与接口样例。A 阶段不改核心代码，不调用真实模型/来源。

完成条件：每项操作有真实方法依据或明确缺口；特别核对 resume 不等于 cancel，不能把尚无事件当作可直接 SSE 转发。

## Sol 的 A→B 放行

合并两份审计后冻结 GUI_API_CONTRACT.md，至少包含：能力标识、workspace/run 身份、分页、错误、事件快照与序号、附件定位、写入/幂等、停止恢复、fixture 示例和字段空值语义。并记录实际前端底座、后端薄封装选择及核心文件白名单。

符合原方案的可逆技术选择由 Sol 决定并继续；仅在源码复用方向需要实质变更时，向用户呈现审计依据和替代方案。

B 阶段一次性下发完整任务：Luna 按合同实现界面与共享 fixture；Terra 实现服务与合同测试。合同内示例由 Sol 维护，Luna/Terra 使用同一版本。两者自检后交固定候选，说明 changed_paths、检查结果、错误、未解问题与下一步；不得只报“代码完成”。

## 集成、验收与协调纪律

- Sol 不在执行者写入期间审查不稳定文件；等两份固定候选后做一次整合验收，按 GUI_FRONTEND_PLAN.md G01–G08 验证用户可见结果。
- 前端问题回 Luna，后端问题回 Terra；共享问题由 Sol 明确根因层和合同变更，再由对应唯一写入者修正。每轮合并反馈，不逐行遥控。
- 等待完成通知或有界等待，不进行无变化轮询。连续两轮同症状无进展时 Sol 诊断后重新下达任务。
- 活动开发环境若工具不可用，使用可用的浏览器/测试机制验证；缺真实浏览器操作时标验收缺口，不能仅构建即宣称 GUI 完成。
- 本地真实材料仅在已有授权工作区使用。默认用隔离运行副本做可能写入的 UI 测试，原 inv-9aa6df1cfc94、旧 run、参照库、密文与冻结事实保持原样。不要导出私有原文到上游仓库或第三方设计服务。
- 无新真实调用预算；synthetic 数据配真实 API 仍会计费，测试应显式注入无网络执行器。不得把 allow_network=true 的合成示例当免费 fixture。

## 最终交付与停止

交付：前端、本地封装、源码复用/许可清单、API 合同、Windows 启动指南、独立验收报告、局限与下一步。启动指南必须给出实际验证的安装/运行/停止命令和工作区参数，不沿用未经验证的假命令。

GUI_ACCEPTANCE.md 区分源码构建、离线联调、既有真实结果浏览和新增在线调查；最后一项本轮不运行。只引用最终候选有效检查。记录 scope 内问题全闭合后停止，不自动接在线模型试用、扩大检索、企业监测或发布。

## 可直接粘贴到新 Sol 对话的启动词

> 请由 Sol 监督，按 docs/GUI_HANDOFF_SOL.md 和 docs/GUI_FRONTEND_PLAN.md 开发 harness GUI。请先核对当前未提交改动与最新验收记录，再分别派 Luna 做前端源码复用审计、Terra 做后端接口审计。两份固定候选完成后由你冻结接口合同，在既定范围内直接推进并行实现、集成和独立验收。Luna 单写 frontend，Terra 单写 Python 封装与获批的最小核心修改，你只负责协调、设计与验收。优先复用 Zotero Web Library 源码，按我们的 harness 工作流改造。仅本地工程开发和无网络测试，不调用新的研究模型/EPO/OpenAlex，不改冻结科学资料，不推送 GitHub。完成后交付可运行 GUI、启动指南、复用清单和独立验收报告并停止。
