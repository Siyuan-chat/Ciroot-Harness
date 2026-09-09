# Project working agreement

- 用户沟通默认中文。产品、用户指南与 README 支持中文、英文、日文。
- 先读 `docs/PRD.md`、`docs/ARCHITECTURE.md`、`docs/CONTRACTS.md`、`docs/ACCEPTANCE.md`。Terra 从 `docs/HANDOFF_TERRA.md` 开始。
- 任务提示词决定分工：设计任务负责需求、设计、独立测试和验收；Terra 实现任务负责产品实现和自测。不要在设计任务中继续开发产品代码。
- 明确的用户新要求优先；把变化记录到 `docs/DECISIONS.md`，更新受影响的规范。普通可逆实现选择由实现者决定。
- 先用成熟库公开接口。LangGraph 负责调查编排；LlamaIndex 仅复用 RAG 所需模块；不要叠加第二套任务状态机。
- 科学数据、原文、条件和引文不得补造。测试夹具、真实材料与发布 demo 必须明确区分。
- 原始资料、运行库、API 密钥和用户会话放在被忽略的工作区；不要提交到 Git。
- 实现者必须自测并提交可复现记录；本任务独立验收前不得声称真实调查或开源发布已完成。
- 不主动创建子 agent；实现的产品内部检索子 agent 不受此开发协作规则限制。
- 到达交接阶段后停止改动产品代码，等待验收反馈。GitHub 发布在案例验收和 demo 准备之后执行。
