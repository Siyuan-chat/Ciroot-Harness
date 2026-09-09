# 中文使用指南（目标接口，尚待实现）

本指南描述 Terra 需要实现的用户流程。当前设计包没有可运行的 rh 命令；安装步骤由 Terra 完成验证后补充。本项目先本地运行、用户手动更新，随后用聚合物设计案例验收。

## 1. 准备工作区和 API

将模型服务、数据源服务分别配置。调查内容放 research.json，运行服务放 runtime.json；API 密钥由运行配置引用环境变量。

[运行模板](../examples/runtime.example.json) 中模型和 Embedding 模型为 null，表示尚未选定，不能直接运行。实现完成后，Terra 会提供已验证的本地多语言 Embedding 默认值；用户填写自己有权限使用的生成模型。仅 Schema 校验成功不足以证明 API 或模型可用。

OpenAlex 和 EPO 各自有凭据和内容覆盖；查到题录不保证取得全文。新增 API 服务需要适配器，已支持的服务只改配置即可。

原始文件、数据库、索引、需求会话和报告保存到 workspace/，默认不提交到 Git。Embedding 在本地生成，相关原文片段可发给所配置的模型用于分析。原文不会为了向量化上传到远程服务。外部语音转写可直接粘贴；首版没有录音界面。

## 2. 检查和描述需求

以下是待实现的命令契约：

```text
rh doctor --runtime runtime.json --workspace workspace
rh chat --runtime runtime.json --workspace workspace --lang zh
```

doctor 默认只做本地检查；凭据缺失、依赖缺失、未选择模型会给出具体说明。显式在线检测必须与本地检测区分。

在 chat 中输入，例如：“我想调查选定聚合物的设计，结合本地论文和专利，比较设计路线和相关性能证据。”

系统逐个询问影响判断的缺失信息，给出需求摘要和默认假设，形成 JSON。已有答案不重复问；未知指标不会被补造阈值。仅修改需求先保存新版本；明确说“按这个需求开始调查”或“更新调查”才启动。

[聚合物设计草案](../examples/polymer-design.draft.json) 只记录当前方向，不是完整案例。它不会自动运行。

## 3. 导入参照资料

```text
rh import ./my-paper.pdf --workspace workspace --collection baseline --kind paper
rh import ./my-patent.xml --workspace workspace --collection baseline --kind patent
```

每份原文保留版本和定位信息。新检索到的资料进入发现库；只有明确选择后才纳入参照库。本轮调查开始时冻结基准，避免边检索边改变比较对象。

## 4. 更新、恢复和查看结果

可以在 chat 中发出“更新调查”“查看进度”“调整关注点后重新判断”等自然语言指令。也可以使用明确命令：

```text
rh validate --spec research.json
rh run --spec research.json --runtime runtime.json --workspace workspace
rh status --workspace workspace
rh resume RUN_ID --runtime runtime.json --workspace workspace
rh report RUN_ID --workspace workspace --languages zh,en,ja
```

调查采用候选数量、查询轮数、模型调用、下载量和活动时间上限。达到上限后保留结果并生成部分报告。估算模型费用不是服务商账单；没有价格数据时显示费用未知，而不是零。

输出包括 HTML/Markdown 报告、JSON 事实数据和 CSV 人工清单。三语版本引用同一组事实与记录 ID。报告显示每个来源是否完成，区分无新增与源不可用；技术地图和注目项都可以回到原文证据。

## 5. 人工判断

```text
rh review list --workspace workspace --lang zh
rh review decide ISSUE_ID --decision watch --note "继续观察，等待相关证据" --workspace workspace
```

可选决定为 include（纳入）、exclude（排除）、watch（继续观察）、request_more_evidence（请求补查）。人工选择 watch 是已作出的决定，和未处理的证据不足项分开显示。请求补查在下一次用户启动时处理。

同一问题不会反复新增；新证据影响判断时重新打开，并保留此前的人工处理。三语状态同步。单条决定不修改全局规则；如果要修改全局规则，请明确描述。

## 6. 结果的解释

- 未报告数值不等于零，也不等于不达标。
- 测试条件不同的数值不能直接比较。
- 摘要、权利要求、说明书、实施例和论文结果具有不同证据角色。
- 引用可定位不自动等于推论正确，重要判断仍可人工复核。
- 历史报告保留原状态；新的人工决定通过新视图呈现，不抹去原记录。
- 当前只有设计文档。后续版本必须明确列出本地自测、真实 API 和科学案例的验证状态。
