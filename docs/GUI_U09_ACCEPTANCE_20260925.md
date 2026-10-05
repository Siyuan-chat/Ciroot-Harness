# U09 持久队列：固定候选离线验收

日期：2026-09-25。用户批准 U09 后，Sol 冻结 `GUI_U09_EXECUTION_CONTRACT_20260925.md`；Luna 是唯一产品代码写入者，Terra 只读复验，Sol 最终核对源码、包与实际 EXE。原有未提交修改和历史验收记录均保留。

## 候选与范围

- 固定候选：`src/research_harness/gui/app.py`、`frontend/app.js`、`frontend/api.js`、`frontend/i18n.js`、`tests/test_gui_multicontext.py`、`tests/test_gui_queue.py`、`frontend/api.test.js`。只给已有 run 的 `advance`、`model-step`、`resume`、`export` 入队；其他内容写入保持原同步合同，`stop` 使用优先通道。
- 最终独立包：`.local/gui-package/u09-dist/ResearchHarnessGUI/ResearchHarnessGUI.exe`（47,526,358 bytes）。须连同整个 `ResearchHarnessGUI` 目录使用。独立构建日志：`.local/gui-package/u09-build.log`。
- 离线工作区：`.local/gui-layout-acceptance/u09-package-final/workspace`。实际 EXE 以 `--no-browser --workspace <该目录> --library-workspace <该目录> --port 18779` 启动；测试结束关闭。浏览器脚本只允许访问 `127.0.0.1:18779`。

## 执行命令与结果

| 层 | 命令或动作 | 结果 |
| --- | --- | --- |
| Luna 自检 | Python GUI 测试全集；`cd frontend; npm test` | Luna 回报 Python 148 passed；前端 8 passed。 |
| Sol 独立前端复验 | `cd frontend; npm test` | 8 passed，0 failed。 |
| Terra 只读复验 | 检查定向队列测试、认证请求头及固定候选行为 | PASS；指出并经 Luna 修正队列 GET 认证、重启与前置状态核对、活动命令落库、同键并发、前端队列 GET 令牌问题。 |
| 前端构建 | `cd frontend; npm run build` | 成功。 |
| 独立 EXE 构建 | `.local/gui-clean-venv/Scripts/python.exe -m PyInstaller --noconfirm --distpath .local/gui-package/u09-dist --workpath .local/gui-package/u09-build .local/gui-package/ResearchHarnessGUI.spec` | 成功；配置文本从 F04 包复制到 U09 包。 |
| 包资源核对 | 比较源码、`frontend/dist`、EXE 包内 9 个前端及合成样例资源 | 全部一致，无差异。 |
| 实际 EXE 无头检查 | `node .local/gui-layout-acceptance/u09-package-final/check.mjs` | PASS；见同目录 `result.json`。 |

实际 EXE 检查使用 Edge headless，读取包内页面注入的本地会话令牌，先确认不带令牌的 `GET /api/v1/queue` 返回 403。随后在隔离工作区创建 synthetic host 调查 `inv-b500d1c1a646`，发送 `advance`，等待队列命令实际达到 `completed`，再确认页面的持久队列区显示该 run 和完成状态。脚本结果 `ok=true`。未输出或保存会话令牌。

队列的跨 workspace 排队、取消、幂等冲突、重启核对、凭据等待、外部锁与 stop 行为由定向离线测试覆盖；本次实际 EXE 检查仅证明包内单命令路径及前端呈现。没有调用真实研究 API 或付费模型，没有使用 Computer Use；原生 WebView2 交互未复验。此次通过不代表完整研究工作台或真实调查质量通过。

Sol 尝试在独立打包虚拟环境用 `.local/gui-clean-venv/Scripts/python.exe -m pytest tests/test_gui_queue.py tests/test_gui_multicontext.py -q` 复跑，但该仅用于打包的环境未安装 pytest，故该命令未形成验收结果；Python 测试结论采用 Luna 执行记录和 Terra 只读复验。最终 EXE 测试进程已停止。
