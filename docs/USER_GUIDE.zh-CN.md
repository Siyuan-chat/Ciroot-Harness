# 中文使用指南：D2 fixture 框架

本阶段证明离线框架和扩展接口。真实 API、生产 RAG、PDF/OCR、独立聊天和 GUI 尚未接入；安装可选依赖不代表已支持。自然语言需求由当前宿主助手逐项澄清，整理为 ResearchSpec JSON。产品调查默认手动启动。

## 安装和默认演示

Python 3.11+。在源码根目录执行：

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install .
.venv\Scripts\rh demo --workspace .local\demo
.venv\Scripts\rh status --workspace .local\demo
```

依赖安装需要网络或预先准备的包缓存；demo 不需要网络和密钥。已构建 wheel 可用 `.venv\Scripts\python -m pip install 路径\research_harness-0.1.0-py3-none-any.whl` 安装。使用独立演示目录，以便与真实资料分开。

默认包内 ready 配置的项目为 `fixture-demo`，包含两条合成候选和一条合成参照。命令返回 `run_id/outcome/stage/error/artifacts.report`。报告目录内有 `report.zh.html`、`report.en.html`、`report.ja.html`、对应 Markdown、`report.json` 和 `review.csv`。默认一条候选进入人工清单。

## 自定义合成输入

以下脚本可保存为 `prepare_fixture.py` 并运行。它从已安装包复制示例，不读取真实科研资料：

```python
from importlib.resources import files
from pathlib import Path
base = files('research_harness').joinpath('fixtures')
for source, target in [('demo-spec.json', 'research.json'), ('demo.json', 'candidates.json')]:
    Path(target).write_text(base.joinpath(source).read_text(encoding='utf-8'), encoding='utf-8')
```

修改 research.json 中的关注点、objectives 或预算后执行：

```powershell
.venv\Scripts\rh validate --spec research.json
.venv\Scripts\rh demo --workspace .local\custom --spec research.json --fixture candidates.json
```

`validate` 只校验，不启动运行。执行要求 `status=ready` 且 `unresolved_questions=[]`。同一 project/revision 的手改内容保存为新版本，重复保存同一正文复用版本，输入文件不被自动覆盖。旧运行的配置、参照和报告保持冻结。

fixture 格式为 `{"candidates":[{"id":"synthetic-1","quote":"Synthetic text.","locator":"line:1"}]}`；ID 必须唯一，quote 非空，可选 `missing:true` 演示证据不足。它是测试数据，不是实际检索或科学结论。指定 `--spec` 时不会自动添加默认演示参照。可先导入自己选择的简单 `.txt`：

```powershell
.venv\Scripts\rh import baseline.txt --workspace .local\custom --collection baseline --kind paper
```

配置的 `reference_library.collection_ids/document_ids` 选择参照；新发现不自动成为基准。聚合物设计的仓库示例仍是 draft，应在后续案例阶段补齐真实需求，不直接改状态冒充案例。

## 人工决定和报告

用实际命令输出替换 `RUN_ID` 和 `ISSUE_ID`：

```powershell
.venv\Scripts\rh review list --workspace .local\demo
.venv\Scripts\rh review decide ISSUE_ID --decision watch --note "保留，等待更多证据" --workspace .local\demo
.venv\Scripts\rh report RUN_ID --workspace .local\demo --languages zh,en,ja
```

include/exclude/watch 保存单条决定并标为已处理；request_more_evidence 保持待处理。决定不修改全局规则或旧报告；重新导出旧运行仍使用其冻结事实。当前人工状态通过 review list 查看。

## Python 与后续 GUI 接口

```python
from research_harness.service import Harness
from research_harness.errors import HarnessError
h = Harness('.local/custom')
try:
    result = h.run_fixture('research.json', 'candidates.json', on_progress=lambda e: print(e))
    print(h.status())
    print(h.get_result(result['run_id']))
    print(h.get_artifacts(result['run_id']))
except HarnessError as exc:
    print(exc.to_dict())
finally:
    h.close()
```

服务自身不打印；示例中的 print 是调用者选择。进度事件有 run_id/stage/status。get_result 返回解析后的冻结事实，get_artifacts 返回 `{report,files}`，文件有 language/format/path；review_decide 返回更新后的问题。无需读取 SQLite 或解析 CLI 输出。

可注入 `source_adapter(candidates)` 和 `model_adapter(spec,candidate,candidate_evidence,reference_evidence)`。模型返回的 disposition/comparison_result/rationale 与双方 citations 使用普通 JSON 数据；引用为 `{evidence_id,quote}`，由框架核查所属与原文匹配。详见 [契约](CONTRACTS.md)。这是可替换 fixture 接口，真实服务需后续实现对应适配器。

## 状态与范围

CLI demo 退出码：completed=0、partial=4、failed=3、非法输入=2。超过 max_candidates 保存部分结果；来源失败和导出失败明确记录。RH_INVALID_INPUT、RH_PRECONDITION、RH_NOT_FOUND、RH_EXPORT_FAILED、RH_UNSUPPORTED 是机器可读错误码。错误对象不含原始外部异常。

仅验证代表性预算/失败路径，不承诺崩溃恢复或全部预算维度。chat/live 未支持；旧 lexical_test_only 只用于历史测试。原始资料、凭据、SQLite 和报告留在被忽略的工作区。后续顺序是实际 API/资料库接入、聚合物案例验收、带 demo 的 GitHub 发布。

## OA 检索与 PDF 采集

安装 `.[literature]` 后，运行 `python -m research_harness.literature search --config examples\aem_oa_reviews.json --output .local\candidates.json`；提供已核验清单时，再运行 `python -m research_harness.literature download --manifest examples\aem_oa_manifest.json --output .local\pdfs --limit 23`。`anonymous: true` 是明确的无密钥请求，否则需要 `OPENALEX_API_KEY`。`review_only: false` 是有意设置，因为 OpenAlex type 标签不完整。模块只访问公开 OA 地址、校验 PDF；有效全文不足时保留部分 catalog 并以退出码 4 返回。
