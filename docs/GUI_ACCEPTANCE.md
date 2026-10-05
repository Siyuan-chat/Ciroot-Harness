# GUI 本地阶段独立验收

日期：2026-09-24。候选为当前工作树的 `frontend/`、`src/research_harness/gui/` 及两处最小调查核心改动。没有运行新的研究来源或模型 API；没有推送 GitHub。原 `inv-9aa6df1cfc94` 未改写，浏览器读取在 `.local/gui-frozen-acceptance` 副本进行。

## 结果

| 门槛 | 结论与证据 |
| --- | --- |
| G01 本地安装/启动 | **通过已测 Windows 边界**。新建 `.local/gui-clean-venv`，`pip install -e '.[gui]'` 成功；该环境用 `python -m research_harness.gui` 在 127.0.0.1:8767 启动，浏览器实际打开并显示未索引状态。前端无 npm 运行依赖，Node 构建成功。 |
| G02 冻结案例与定位 | **部分通过**。浏览器显示 `inv-9aa6df1cfc94` 为 partial，双报告和 10 条主张；C6 点击后读回韩文原文、document/version ID 与 XML claim 节点，重新定位后出现已登记 claims/description XML 原件链接及 claims 全文。专利比较实际选择 WO2026182370A1。C2 读回已登记 PDF 链接和 `page=1`；后端测试确认文件返回 200，但本机内置浏览器的 PDF 页呈现为空，故不宣称页内实际可见。 |
| G03 无网络合成闭环 | **部分通过**。浏览器实际创建 synthetic host run `inv-501303be3e82` 并读回 planning 待办；TestClient 用真实本地应用服务完成创建、全部角色任务、双报告、导出、下载和重启读回，且封锁 requests 外呼。完整角色处理未逐步在浏览器手动执行。 |
| G04 停止/恢复/重启 | **部分通过**。浏览器停止后读回 `stopped`，恢复后为 `waiting_model`；浏览器从持久 `poll` 观察接口读回序号 1 与 `completed/partial` 快照。TestClient 检查断线游标、重启序号、预算、任务和幂等键。进行中的长网络调用停止时序未实测。 |
| G05 人工处理 | **通过 HTTP 契约层**。monitor 作用域决定经 HTTP 提交、重放、重开后历史可读；普通调查 issue 不可误提交。浏览器人工表单未完成真实点击验收。 |
| G06 标准导出 | **部分通过**。浏览器展示冻结标准产物的实际文件名和签发下载 URL；TestClient 完成合成 run 的标准导出与下载。浏览器下载文件重开及冻结 canonical 字节比较未在本轮新执行；既有公共导出验收记录仍有效。 |
| G07 本地安全边界 | **通过已测接口**。TestClient 覆盖 Host/Origin、写入令牌、幂等冲突、artifact 越界、普通调查 review 作用域；前端外部文本转义。未做完整恶意 HTML/XML 渲染矩阵。 |
| G08 浏览器布局/操作 | **部分通过**。浏览器实际点击库、调查、报告、阅读、专利比较、设置，确认中文与窄窗口布局；1280×800 与更宽窗口、键盘全流程和开发者工具无阻断错误尚未逐项验收。 |

## 有效检查

- `.local/d19-runtime/venv/Scripts/python.exe -m pytest tests/test_gui_contract.py tests/test_investigation_model_api.py -q`：17 passed。
- `node --test frontend/api.test.js`：3 passed；`node frontend/build.js` 成功；`git diff --check` 无补丁错误。
- 浏览器实际服务：`http://127.0.0.1:8765/` 新合成工作区、`http://127.0.0.1:8766/` 冻结案例隔离副本。截图不是本报告的唯一依据，点击后的状态读回如上。

当前交付可作为本地 GUI 候选使用；G02/G03/G04/G06/G08 尚未达到方案中的全部验收条件，故不标记 GUI 全阶段通过。特别是 PDF 页在目标浏览器中的可见性、浏览器内完整合成任务流程与指定尺寸浏览器检查仍需后续补验。事件使用可重连 `poll` 传输，未实现 SSE。无新增真实在线研究授权或科学覆盖结论。

## Figma 参考与 Windows EXE 增补验收

按用户指定的 Figma `Patent Agent v0.1 Wireframe` frame `2:2`，前端已采用白色顶栏、分组侧栏、中央工作区、右侧对象检查器和深色七阶段条。线框示例专利、企业与分析结论均未作为实际数据。独立运行 `npm test`（3/3）、`npm run check`、`npm run build` 和 GUI/模型 API 回归（17/17）通过；本地浏览器打开最终构建后读回新版布局及未索引空态。

Windows onedir 包的 `ResearchHarnessGUI.exe` SHA-256 为 `06C289F0CE06C119DC6806ED04BD85808C429DE12BA44A57479E5BC9C025A280`。Sol 独立从该 EXE 在隔离工作区原生启动，取得随机 loopback URL、首页 HTTP 200、首页会话令牌注入及 `/api/v1/capabilities` HTTP 200，并停止进程。实际文件位于 `.local/gui-package/dist/ResearchHarnessGUI/`，分发时必须复制整个目录。该增补只验收 Figma 参考与本地启动要求，不改变上表仍为部分通过的 GUI 业务门槛。

## 真实文献库、无终端启动与三语界面增补验收

本轮最终 Windows EXE SHA-256 为 `8220AD364355C91856EA9F0322CB75A9137050EE48490463A8E3B87DB6363574`，取代上一段旧候选。PE Subsystem 为 2（Windows GUI），打包参数 `--windowed`；双击不产生 CMD/PowerShell 窗口。原生启动后 `/api/v1/library?limit=50` 返回既有只读 RAG 库 23/23 篇，文献详情与登记 PDF 原件分别返回 HTTP 200；页面实际展示 23 项，论文筛选保留综述与研究论文。原文与文献库均未写入 EXE 包。

最终 EXE 页面实际切换 English 后，导航、文献库状态与数量均显示英语；开发页面另实测日本語切换及论文筛选显示 23 件。浏览器点击最终 EXE 的“Quit app”后显示退出状态，进程结束且端口关闭。前端测试 4/4、语法和构建通过，GUI 后端契约 10/10 通过。当前打包环境未安装完整 RAG 向量依赖，库状态返回 `unavailable`，页面明确提示“文献目录可浏览；当前运行环境无法核验向量索引状态”；本轮没有声称向量检索通过，也没有修改冻结 RAG 数据。三语仅处理界面文案，来源标题、原文与技术枚举保留原语言。


## 原生窗口与向量检索增补验收

最终候选 EXE SHA-256：`51640AA23AEF73BA54493B0EC2FC73C17BEBF715624623B80ABD216E68F4FA1F`。启动方式改为 Windows WebView2 原生窗口；实测最终 EXE 的进程窗口标题为 `Patent Agent`，PE Subsystem 为 2，启动代码不再调用默认浏览器。窗口内仍使用本机回环服务处理界面与业务接口。

最终打包版在只读现有文献工作区上返回 `index_status=ready`、23 篇；`/api/v1/library/search` 实际返回 3 条证据，诊断 `vector_hits=8820`，响应中不暴露原件绝对路径。带窗口的最终 EXE 亦完成同一检索。首次冷启动索引加载较慢，预热后库列表约 6 秒、检索约 12 秒；这属于本机实测，不作为性能保证。原文和模型权重仍存于 EXE 包外的本地配置路径。

`npm test` 4/4、`npm run check`、`npm run build` 与 GUI/模型 API 回归 17/17 通过。此处验收覆盖本轮原生窗口和向量检索要求，不改变上文尚未全部通过的 GUI 业务门槛。

## 独立审查清单修正复验

依据 `GUI_INDEPENDENT_REVIEW_20260924.md` 的新候选 EXE SHA-256 为 `0C8CFEF02996EF8A25E5EA0D4E4FA33F8E170C2094D9D389A0EAD17FB9A295D1`，取代前文旧候选。打包 `app.js` 与源码哈希一致，PDFium 和离线样例文件均在程序包内；Windows 进程出现 `Patent Agent` 原生窗口。

- **F01 已修复**：从最终 EXE 提供的界面筛选 `Tuning Alkaline` 后，仅显示 `doc-a2bff6c31ccf20278f3276cc`；点击详情，右侧 document_id、标题、版本 `ver-cd1ddeb795cd212356e4e1b2` 与原件链接均为同一文献。稳定 ID 选择回归覆盖原列表末项变为筛选第一项、清空筛选与追加项。
- **F03 已修复**：同一界面显示 `1 个匹配 / 已载入 23 项`，不把已载入量称为全库总量。
- **PDF 页预览**：最终 EXE 的该原件预览返回第 1 页图像；界面实际显示 `Page 1 / 33` 和标题页，可切换下一页，原 PDF 保留下载链接。预览通过本地 PDFium 页渲染，规避浏览器内置 PDF 查看器空白。本轮观察的是最终 EXE 提供的页面；自动化工具未直接捕获 WebView2 原生窗口画面。
- **F02 部分改善**：调查页可点击“载入已验证离线样例”，实际填入合成研究问题，并可改研究问题；样例文件与服务既有合成契约一致。最终 EXE 在隔离工作区经界面创建合成运行 `inv-59496d78ab15`，读回 `waiting_model`、planning 待办任务和事件序号 1。完整角色操作仍需原生 GUI 闭环验收。

有效检查：前端测试 5/5、语法与构建通过；后端 GUI/模型 API 回归 17/17；最终 EXE 对指定文献返回索引 `ready`、PDF 预览页 HTTP 200 和有效 PNG。此处不升级 G02–G08 其余未完成项，尤其未声称真实调查或原生窗口完整角色闭环通过。

## 模型与来源凭据、外部 MCP 增补验收

当前候选 EXE SHA-256 `61E381A4C325BC05C8AD4A374D49CA1F329FAE0EF5D9C6BC921331175ECD4F60`，取代前文候选；包内 `app.js` 与前端构建产物 SHA-256 均为 `3A41401B7DB9DD4BA742EA18C861A22387941CE6461DA793197151F2AA866178`。本机启动后出现 `Patent Agent` 原生窗口，HTTP 来源凭据写入/读取/清除分别得到 `session/session/missing`，响应未回显测试值。`/api/v1/mcp-setup` 返回 `python_ready=true`、既有文献库和模型缓存路径；退出后端口关闭。

GUI 中模型 API key 与 OpenAlex、EPO OPS key/secret 仅在当前应用进程保存。来源凭据单元测试验证服务调用时临时注入、调用结束恢复环境；模型测试验证一次预算内模型任务及密钥不落库。`tests/test_gui_model_credentials.py` 2/2、GUI 契约回归 11/11、前端测试 5/5、语法与构建通过。外部 MCP 的只读 RAG STDIO 握手另验证 5 工具、23 篇与索引 ready，写入操作返回 `RH_RAG_READ_ONLY`。本机未安装 Claude Code CLI，因此仅验证通用 MCP 协议和命令格式，未声称 Claude Code 客户端端到端通过。GUI 实时来源调查入口仍未实现，不将凭据入口升级为真实来源调用验收。
