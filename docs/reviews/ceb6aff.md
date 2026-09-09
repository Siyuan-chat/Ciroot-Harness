# ceb6aff 独立复验

日期：2026-09-09。对象：`ceb6aff9797305d7906a94268169cb45345659ce`，分支 `codex/research-harness-alpha`。

**结论：本次回归修复大部分有效；完整框架尚未通过 G1/G2。** 本报告仅对应该提交，Terra 后续提交另行验收。

## 实际证据

从该提交导出独立源码快照，在 Windows Python 3.12.14 的新建项目虚拟环境中安装构建出的 wheel 及其声明依赖。测试导入路径确认为虚拟环境的 `site-packages`，没有从 Terra 工作树导入产品源码。原有 6 项 unittest 全部通过。

| 上轮发现 | 本次独立观察 | 状态 |
|---|---|---|
| F02 Schema 偏差 | 六个原有反例全部拒绝，包括负预算、非法日期、空阈值对象、内联密钥字段 | 已修复原反例；语义校验仍有缺口 |
| F03 基准选择 | 显式选择第一份资料，报告只包含该 ID | 原反例通过；完整文档版本冻结仍待集成验收 |
| F04 历史污染 | 完成后追加 discovery，再导出原报告，JSON 字节保持一致，资料数维持 1 | 原反例通过 |
| F05 错误状态 | 缺凭据 run 返回 3；不存在的 run 无法恢复，返回 3 | 原反例通过；真实恢复和能力预检仍未完成 |
| F06 只读校验 | validate 返回 0，当前目录未创建数据库或数据目录 | 通过 |
| F07 包内资源 | wheel 中含两份公共 Schema，安装后的校验实际可用 | 当前 Schema 包装通过；未来模板/语言资源仍按 A32 验收 |

包构建与安装成功仅证明当前基础包可用，未验证 full extras 或生产 RAG。

## 继续修正的具体问题

### F01：实际功能仍缺失（阻断）

三语真实输入调用 `chat --message` 均返回英文占位回复 `Interactive intake is not implemented`，退出码为 0。`chat --help` 通过不能证明 A02/A03/A33 通过。`resume` 对可恢复运行仍直接抛出未实现错误。当前 `run` 没有检索或模型调用，技术地图为空；实际 LangGraph/Docling/本地多语言 RAG、来源与分析适配、持久化预算、人工清单生命周期及完整三语路径须继续 M1–M5。

### F08：重复 criterion ID 被接受（P1，A03/R05）

在有效 spec 中放入两个相同 `id=duplicate_id` 的 qualitative criterion，`validate_spec` 未拒绝。Schema 并不能表达所有业务约束；请在公共服务层执行 CONTRACTS §1 的语义校验，并验证 CLI 与 intake 共用该校验。重复 ID 会让指标、证据和人工规则身份不明确。

### F09：hybrid 能力不可用却报告成功（P1，A01/A09/A10）

在没有 LangGraph、Docling、FastEmbed、Qdrant、LlamaIndex 的独立环境中，配置 hybrid、虚构 embedding 模型名、local 模型并关闭来源，`doctor` 返回 0 和 `ok=true`，仅将所有组件列为 false。当前配置要求的能力缺失必须影响 ready/ok 及退出状态，并给出可执行的安装或配置指引；不能只检查模型字符串是否非空。应验证受支持的真实模型 ID。此反例全程未发 API 请求。

## 复现

在设计仓库根目录执行。先用 `git archive` 将上述完整提交导出到 `.local/acceptance/ceb6aff/source`，再构建 wheel 并安装到 `.local/acceptance/ceb6aff/venv`。该环境为独立验收用途，不修改实现者工作区。

```powershell
& '.local/acceptance/ceb6aff/venv/Scripts/python.exe' -m unittest discover -s '.local/acceptance/ceb6aff/source/tests' -v
& '.local/acceptance/ceb6aff/venv/Scripts/python.exe' 'acceptance/probe_ceb6aff.py'
```

探针复用保留的上轮反例，再检验真实 chat 行为、语义校验和安装包能力预检；有验收缺口时退出 1。机器结果位于 `.local/acceptance/ceb6aff/acceptance-probes.json`。输入全部为合成文本，不含科学测量或真实密钥。

## 自动闭环

依据 D13，设计任务直接派发本报告给 Terra，并对后续提交复验；用户无需手工转交。完整框架独立验收达标后停止工程任务并暂停自动跟进。在线连接、真实聚合物案例和 GitHub 发布仍按各自门槛记录，不因本次基础修复而宣称通过。
