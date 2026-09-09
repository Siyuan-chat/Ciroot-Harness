# Research Harness

中文 · [English](README.md) · [日本語](README.ja.md)

一个本地优先的论文／专利调查 harness。用户用自然语言描述需求，LLM 逐步澄清关键歧义，生成带版本的 JSON。用户主动发起更新后，系统自动检索和获取资料，与冻结的本地参照库比较，并生成报告及累计人工判断清单。

**当前状态：设计交接，尚未实现发布版。** 本仓库提供需求、架构、数据契约和验收标准。另一个 Terra 任务负责实现；随后在设计任务中进行测试、聚合物设计案例验收和 demo 准备。指南中的命令是待实现接口，当前不能视为可运行功能。

## 已确定的产品行为

- 需求对话、检索、报告和人工清单支持中英日。
- 首版本地运行，由用户不定时发出更新指令；不默认后台定时执行。
- 原文、索引和 Embedding 留在本地，相关证据片段可发送到所配置的模型 API。
- 模型 API 与论文／专利数据源 API 分开配置；已支持的服务通过配置接入。
- 证据不足或冲突时继续运行，标为观察项并进入人工清单。
- 人工判断只影响单条资料；明确要求推广时才修改全局规则。
- 每份报告保留原文位置、测试条件、配置版本和参照库版本。

## 文档入口

| 文档 | 用途 |
|---|---|
| [需求规格](docs/PRD.md) | 功能范围、需求编号、默认行为 |
| [架构设计](docs/ARCHITECTURE.md) | 模块职责、调查流程、恢复与依赖 |
| [数据契约](docs/CONTRACTS.md) | JSON、证据、判定和人工清单的精确定义 |
| [验收方案](docs/ACCEPTANCE.md) | 框架自测、真实集成、案例与发布门槛 |
| [Terra 交接](docs/HANDOFF_TERRA.md) | 实现顺序、交付内容和停止位置 |
| [决策记录](docs/DECISIONS.md) | 已确认事项、工程默认值和案例待定项 |
| [中文使用指南](docs/USER_GUIDE.zh-CN.md) | 目标用户流程与命令接口 |

[调查 JSON Schema](schemas/research-spec.schema.json) · [运行配置 Schema](schemas/runtime.schema.json) · [聚合物设计草案](examples/polymer-design.draft.json)

首个案例为**聚合物设计**。领域知识放在调查配置里，不写死到通用引擎。草案没有实验数值、指定目标聚合物或科学结论。

拟采用 Python、LangGraph、Docling、按需使用的 LlamaIndex 模块、Qdrant 和 SQLite。首版数据源为 OpenAlex 与 EPO OPS；Lens 留作后续可选接入。依据和接入边界见架构文档。

最终交付目标是带可复现 demo 的 GitHub 开源项目。仓库归属、最终许可证和 demo 材料的再分发条件在发布阶段确定；目前尚未发布。
