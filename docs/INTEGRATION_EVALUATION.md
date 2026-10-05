# 整合评测与待激活验收

本轮采用用户明确选择的离线候选。工程运行与科学效果分别记录；固定输出不能替代真实模型对照。

## 固定案例

本地 `s2-aem-paper-patent` 包含同一冻结调查中的 5 个摘录：2 段论文、3 段专利。协调者只读回查原始 ID、版本、文本和定位，5/5 精确一致；两个原件哈希与已有清单一致。包位于忽略目录 `.local/integration-20261005/s2-case/`，不得直接加入公开镜像。专利再分发许可尚未明确。

这些摘录未带历史解析修订，明确标为 `legacy_unversioned`；引用兼容不意味着新版本契约已追溯通过。全部科学支持状态保持 `not_assessed`。比较段保留比较例与实施例，不根据结论选择资料。

## 对照协议

激活时创建三个新的运行，分别执行普通 RAG、PaperQA2、STORM；每个运行使用相同冻结资料、问题、模型、物理调用额度和停止条件。不得复用历史调查额度，也不得在库内部另开隐藏调用额度。Ciroot 原文核查前后的草稿分别保存，不能只比较最后成功的输出。

实际运行前填写 profile、模型、密钥环境变量名和数值预算；不保存密钥。没有填写并授权时，记录 `pending_activation`，不产生模型质量或费用改善结论。

人工标注逐断言记录 supported、partial、unsupported、contradicted，并保存判定者、原文位置、比较条件及原因。定位、连续引句匹配与语义支持是不同字段；不得用引句存在率充当科学支持率。

## 分开报告的指标

| 指标 | 记录方式 |
| --- | --- |
| 定位通过 | 正确文档、版本、解析修订和原文位置的条数 / 待定位条数 |
| 引句通过 | 连续原文匹配条数 / 提交引句条数，规范化规则另列 |
| 语义支持 | 四类人工标注各自数量，未标注不计 supported |
| 覆盖 | 固定问题维度、资料缺口、来源失败与成功空结果分别记录 |
| 恢复 | 重开、重复点击、迟到响应、未知结果的实际状态及预算变化 |
| 成本 | 模型、嵌入、下载及元数据查询的物理发送次数；缓存命中另列；费用未知留空 |
| 复核负担 | 人工定位和判定的实测时间、待复核断言数；不推测节省比例 |

所有比率同时保存分子、分母、样本构成与规则版本。固定集合覆盖不能声称全球专利或论文召回率。

## 离线工具

`scripts/evaluate_integration.py` 读取 `examples/integration_evaluation/` 的合成 case、三组 frozen result 和空人工标注模板。执行方式：

```powershell
$env:PYTHONPATH = 'src'
python scripts/evaluate_integration.py --case examples/integration_evaluation/case.json --results-dir examples/integration_evaluation --annotations examples/integration_evaluation/annotations-template.json --output evaluation.json
```

规则版本为 `integration-evaluation/2`。工具接受字符串或结构化 locator，精确比较文档、版本和解析修订；坏主张不悄悄缩小分母，畸形引用给诊断。重复物理调用标识为 ambiguous，不作为独立发送或真实模型激活凭据。输入所给账本引用不经本工具鉴真，不能把统计工具作为真实性认证器。

修正版相关测试组独立 62 项通过；CLI 合成输入输出 `pending_activation`，没有真实模型或科学改进结论。另以私有冻结 5 摘录做字段读回：定位和连续引句各 5/5，语义全部未评判；仅显式 `parse_revision_status=legacy_unversioned` 转换为工具所需布尔标记，原件未改。这份记录没有执行三个引擎，不作为模型比较结果。

## 验收层次

离线协议夹具、实际库的离线代理运行、真实来源调用、浏览器行为、原生 Windows EXE、Docker 宿主、科学对照分别记录。缺少后一层不得覆盖前一层的有效结果，也不得将后一层改名为已通过。最终构建清单列出各层状态、源提交和工作区文件哈希，不以未提交工作区的 HEAD 代表全部代码。
