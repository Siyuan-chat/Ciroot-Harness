# U07 选定文献库进入调查：下一阶段计划

状态：2026-09-25 用户批准后已按下列白名单实施；原方案和验收口径保留。实施前 GUI 仅把选库、分组、文档版本和索引状态冻结到 `run_references` sidecar，核心未消费该快照。旧 run、原文和索引保持冻结。

## 建议修改白名单

- `src/research_harness/gui/app.py`：从已注册 `library_id` 解析只读库，按冻结成员和版本验证证据，向核心传明确的参照输入；禁止浏览器提交任意路径，切换浏览库不追写已建 run。
- `src/research_harness/investigation.py`：在现有 `create_investigation` 的参照 RAG/`baseline_snapshot` 路径增加受控输入合同；记录选定库身份、版本、证据 ID、原文、locator 和覆盖诊断，使规划、查询引用校验、报告证据使用同一冻结事实。保留 synthetic fixture 与真实资料语义分隔，不靠修改 synthetic 假装真实调查通过。
- `tests/test_gui_multicontext.py` 与一个定向核心测试文件（优先 `tests/test_investigation_query_loop.py`）：覆盖 scope 错配、同名 document_id、版本变化、空命中、只读与冻结后的切库。若需更改公开 schema/合同，实施前列精确字段和文件，由用户另行批准；本计划不授权扩围。

## 离线验收

在临时工作区建两个小型实体 RAG 库和两个 run，使用离线合成文档**仅作为测试夹具**。从 A 的选定分组建 run，读回核心持久 scenario/规划任务中的 A 证据身份、版本、locator 与快照；切到 B 浏览并改变 A 分组成员后，再读旧 run，确认其输入和引用未改变。B 含相同 document_id 但不同版本，不能串到 A。未知/失效版本应明确失败或保留 `partial`，不得静默用当前版本代替。用现有无网络执行方式完成规划与引用校验，不发 OpenAlex、EPO 或付费模型请求；这只证明输入合同与隔离，真实科学效果仍需单独验收。

本阶段未运行真实调查、未修改冻结资料或持久队列、未推送 GitHub。实施与独立验收见 `GUI_U07_ACCEPTANCE_20260925.md`。
