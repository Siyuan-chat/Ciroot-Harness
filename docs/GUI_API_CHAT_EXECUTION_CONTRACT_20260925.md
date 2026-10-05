# API 对话规划补完合同

日期：2026-09-25。W3 离线 scripted 与 W4 本地 MCP 桥已通过，API conversation 的文字规划仍为 `planning_pending`。本补完阶段只实现明确授权与额度下的受控模型规划代码，验收全部使用本地模拟响应，不发真实收费请求。

- API conversation 创建时记录 provider、model、规划调用上限、每次输出上限/超时与总模型调用上限；这些是无密钥配置，不含任意 endpoint 或路径。缺配置/当前 workspace 凭据/额度时明确等待，不发请求。
- 用户文字 turn 可启动一次持久计账的规划尝试，模型只返回结构化 ResearchSpec 和运行候选；本机现有 schema 验证通过才置 ready，失败/不完整保留错误和 UNKNOWN 用量。相同 turn/request_id 重试不得重复发送已发/结果不明的请求；重启不自动重放。原文与证据输入受既有 model policy 限制，文献文本不得成为操作指令。
- 输出的 runtime 必须保留用户选择的 data_mode、source 授权、provider、model 和总预算；模型不得自己扩大网络/收费额度。执行仍需用户明确点击，走既有 run/U09，规划消耗也计入 conversation 总额度，不用换 run 清零。真实模型端点调用仅在用户后续明确配置并提交时发生，本轮测试以 monkeypatch/fake HTTP 验证。
- 前端显示 provider/model/余额或 UNKNOWN、规划中/待凭据/失败/ready，并只在 ready 显示执行。不得把 scripted fixture 当 API 规划，也不暴露 key。

Terra 独占后端 `src/research_harness/gui/app.py`、`conversation.py`、必要新增 `gui/conversation_model_api.py` 与定向测试；如需动核心/schema 先报告。Terra 交固定候选后，Luna 独占前端 `app.js/api.js/i18n.js/style.css` 与前端测试。Sol 验收模拟 provider 响应、重复/重启/额度/凭据与现有离线路径；真实收费模型质量验收保持待定。
