# 9b5d6ea 独立复验

日期：2026-09-09。对象：`9b5d6ea` 及自 `ceb6aff` 后累计三个阶段提交。结论：**部分修复通过，完整框架 G1/G2 未通过；自动修正继续。**

## 验证边界与结果

将指定 Git 提交归档至 `.local/acceptance/9b5d6ea/source`，没有从实现者可变工作树运行。复用上轮已安装 jsonschema/requests 的隔离 Python 3.12 环境，通过 PYTHONPATH 指向本轮源码快照；本次是源码行为复验，没有重新声称新 wheel 安装通过。没有真实 API 请求或科学案例输入。

- 实现者现有 unittest：9/9 通过。
- F08：重复 criterion ID 被拒绝，关闭该具体问题。
- F09：doctor 的缺组件反例修复有效；实际 run 仍绕过该检查，保持未关闭。
- 基准限定的关键词检索、文本/XML 证据写入和会话文件已存在。这些局部能力不等于生产多语言 RAG、完整证据契约或 LLM 需求整理通过。

## 本轮具体问题

### F09 续：运行绕过 hybrid 能力预检（P1，A01/A09/A10）

配置 hybrid、本地模型标记、虚构 embedding 模型名，关闭来源；验收环境无 FastEmbed/Qdrant/LlamaIndex。相同 runtime 的 doctor 返回 `ok=false`，但 `Harness.run` 返回报告：`status=completed`、`execution_mode=local`、`synthetic=false`、`retrieval.mode=lexical`。调用方无需先运行 doctor，因而当前保护可被正常使用路径绕过。

修正：doctor 与所有运行入口复用能力检查；用户要求 hybrid 时，缺依赖或无效模型必须在运行前报错，不能静默替换为关键词检索。完成生产 RAG 后验证真实模型选择及本地组件通信。缺失环境与完整环境都应覆盖，避免把测试写成依赖必须不存在。

### F10：对话丢失明确约束，不能修改或执行（P1，A02–A04/A33）

三语分别输入“聚合物设计、只要论文、排除专利、定性比较”，再回答调查对象，最后要求开始调查。观察一致：

- 第一轮重复问已经给出的对象；第二轮把 topic 替换为新回答。
- ready spec 仍含 `paper,patent` 和 `openalex,epo`，未保留排除专利要求。
- “开始调查”仍返回 `intent=clarify`，没有调用运行服务。
- ready 后要求更改报告语言不更新规格，revision 仍为 1。

`intake.respond` 没有模型适配、公共语义校验和 intent 路由；固定问答不能满足用户已确认的 LLM 整理需求路径。请按既定架构接入实际模型适配器、结构化 JSON/有界修复、累计约束与版本保存、执行意图路由。协议夹具可以独立验证这些路径；不能只为上述三句话加关键词特例或把 LLM 改为可选的未来功能。真实模型质量依旧单独标 online pending。

### F11：解析结果不能保持原文结构和失败状态（P1，A06/A07）

`<article><p id="p1">First</p><p id="p2">Second</p></article>` 产生根 evidence quote `FirstSecond`，并将合并文本和每个子段落重复放入索引文本。跨块文字边界被移除，父级包裹节点还混合不同章节角色。应以有语义的段落、claim、表格单元及其上下文提取，保留来源结构和可解定位；不能用统一追加空格修复所有 inline 标记，以免反过来改变原词。

损坏 XML 的导入响应包含 parse_errors，但数据库没有保存解析错误/coverage，且 content 保留未解析原 XML。导入命令结束后，下游无法从持久记录判断这次失败。请持久化解析状态与覆盖信息，供后续筛选、人工清单和报告使用。

静态补充：PDF 分支虽然调用 Docling，却把导出 Markdown 行号作为 `parsed_line` locator，丢弃 Docling 页码/bbox/table provenance。这仍不满足 PDF 可定位证据契约；本次没有运行 Docling，不声称 PDF 集成已验证。

## 复现命令

在设计仓库根目录，先把该提交导出到上述 snapshot 目录；本地验收依赖环境已存在。

```powershell
$env:PYTHONPATH = (Resolve-Path '.local/acceptance/9b5d6ea/source/src').Path
& '.local/acceptance/ceb6aff/venv/Scripts/python.exe' -m unittest discover -s '.local/acceptance/9b5d6ea/source/tests' -v
& '.local/acceptance/ceb6aff/venv/Scripts/python.exe' 'acceptance/probe_9b5d6ea.py'
```

独立探针退出 1 表示观察到验收违例，完整机器结果位于 `.local/acceptance/9b5d6ea/acceptance-probes.json`。文本均为合成数据，不含科学测量。此探针为指定提交的诊断，不代替完整验收矩阵。

## 后续

F01 生产核心流程仍待实现；F09、F10、F11 已明确可执行，不需要用户参与。实现报告仍写“dependency-free / stdlib core”和旧阶段状态，须随实际依赖与功能更新。Terra 继续已授权 M1–M5，设计任务验收后续不可变提交。完整框架达到独立验收标准后停止；不自动进入 G3/G4。
