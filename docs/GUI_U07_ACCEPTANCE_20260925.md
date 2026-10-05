# U07 选定库参照输入：离线独立验收

日期：2026-09-25。用户批准 `GUI_U07_NEXT_STAGE_PLAN_20260925.md` 后，Luna 作为唯一代码写入者提交固定候选；Terra 只读复验，Sol 核对核心输入路径与验收边界。本轮未调用 OpenAlex、EPO、真实模型 API，未改旧 run、冻结文献、索引或持久队列。

## 候选与行为

代码改动限于 `src/research_harness/gui/app.py`、`src/research_harness/investigation.py`、`tests/test_gui_multicontext.py`、`tests/test_investigation_query_loop.py`。GUI 从已注册库只读冻结分组成员、`current_version_id` 和索引状态，按精确版本检索选定库证据及上下文；向核心传 `registered_reference_snapshot`、`reference_evidence` 与检索诊断。核心校验快照与证据版本一致，将证据写入持久 `scenario`、`baseline_snapshot` 和规划任务。浏览库或分组后续变化不会重写旧 run。

无成员或无命中保留 `evidence_gap`；失效/不匹配版本返回明确错误，不退回现版。不同实体库可有相同 `document_id`，但版本证据仍按创建时的库隔离。此次未改公开 schema 或 API 合同文件。

## 命令与结果

在仓库根目录对固定候选执行：

```powershell
$env:PYTHONPATH='src'
& '.local\d19-runtime\venv\Scripts\python.exe' -m pytest -q tests/test_gui_multicontext.py tests/test_investigation_query_loop.py
& '.local\d19-runtime\venv\Scripts\python.exe' -m py_compile src/research_harness/gui/app.py src/research_harness/investigation.py tests/test_gui_multicontext.py tests/test_investigation_query_loop.py
git diff --check
```

Luna 自检、Terra 独立复验均为 **8 passed**；编译及补丁格式检查通过。测试仅有一条 Starlette/AnyIO 第三方弃用警告。离线测试构造 A/B 临时 RAG 库：相同 `document_id` 对应不同 `version_id`；A 创建后改变分组成员、重开服务，旧 run 的快照和规划证据仍是 A 原版本；空分组保留缺口；核心拒绝版本不匹配快照。

## 结论与边界

**U07 的离线选库输入、冻结和跨库版本隔离通过。** 这说明选定库证据已进入核心调查输入，不证明真实资料的科学结论、外部检索效果、付费模型运行或原生 WebView2 交互。测试中的合成文档只作离线夹具。U09 持久队列和恢复、U11 原生窗口交互仍未完成，不随 U07 改判。
