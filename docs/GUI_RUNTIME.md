# GUI 本地启动（Windows）

在仓库根目录运行。以下命令已在本机 Windows 验证；本机没有 `py` 命令。

```powershell
node frontend/build.js
& '.local\d19-runtime\venv\Scripts\python.exe' -m venv .local\gui-clean-venv
& '.local\gui-clean-venv\Scripts\python.exe' -m pip install -e '.[gui]'
& '.local\gui-clean-venv\Scripts\python.exe' -m research_harness.gui --workspace '.local\gui-workspace' --static-dir 'frontend\dist' --port 8765
```

服务只监听 `127.0.0.1`。打开 `http://127.0.0.1:8765/`，将终端打印的会话令牌输入页面；令牌只存于页面内存。结束服务时回到启动终端按 `Ctrl+C`。若端口被占用，改用 `--port 8766` 并打开对应地址。Sol 已在本机 8765/8766 浏览器中完成页面实测；工作区路径是启动参数，浏览器不能任意切换磁盘目录。

本机后端契约测试命令：

```powershell
$env:PYTHONPATH = 'src'
& '.local\d19-runtime\venv\Scripts\python.exe' -m pytest -q tests/test_gui_contract.py
```

新环境安装与浏览器启动已在 `.local/gui-clean-venv` 和端口 8767 实测。上面的 venv 创建行使用本机已有 Python 路径；其他机器应替换成自己的 Python 3.11+ 可执行路径。`node` 需在 PATH。写入测试使用隔离工作区；不要将原冻结调查工作区作为写入目标。
# Windows EXE（本地双击）

构建要求：Windows、Python 3.11+、已安装本项目 `.[gui,rag]`、PyInstaller 6.22.3，以及已生成的 `frontend/dist`。在仓库根目录执行：

```powershell
& '.local\gui-clean-venv\Scripts\python.exe' -m pip install pyinstaller==6.22.3
& '.local\gui-clean-venv\Scripts\python.exe' -m pip install -e '.[gui,rag]'
Set-Location frontend; npm run build; Set-Location ..
powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1
```

完整交付目录为 `.local/gui-package/dist/ResearchHarnessGUI/`。双击其中 `ResearchHarnessGUI.exe`，程序在 Windows WebView2 独立窗口内显示工作台，不打开默认浏览器或 CMD/PowerShell 窗口；关闭窗口或在顶栏点击“停止应用”即可结束服务。默认可写工作区为 EXE 文件夹旁的 `ResearchHarnessGUI-workspace`，不在会被重建的发行文件夹内；也可指定 `--workspace C:\path\to\workspace`。使用空闲随机端口，只绑定 `127.0.0.1`。会话令牌仅注入本机页面，不显示在界面或控制台。移动时需复制整个 `ResearchHarnessGUI` 程序目录，数据目录若需迁移应单独复制。构建资源不包含 `.local` 原始文献、模型权重或凭据。

本机打包脚本在现有 23 篇 RAG 文献库可用时，将其绝对路径写入 EXE 同目录的 `library-workspace.txt`，并把 E5 模型缓存路径写入 `rag-model-cache.txt`。桌面版只读文献库和模型缓存，调查及 GUI 状态仍写入独立的 `ResearchHarnessGUI-workspace`。移动到另一台机器后，需将两个文本文件改为新机器上的真实路径，或使用 `--library-workspace C:\path\to\rag-workspace` 指定文献库；模型缓存不会复制进 EXE 包。文献目录、原件及证据级混合检索由同一 RAG 核心提供。顶栏可选择中文、English、日本語；界面选择保存在应用窗口的本地存储中，原始文献标题和内容保持原文。

此前放在发行目录内的本机旧工作区已保留至 `.local/gui-package/dist/ResearchHarnessGUI-workspace/`，新版默认继续使用该位置；重建程序只替换 `ResearchHarnessGUI/`。若自选工作区，始终使用 `--workspace` 指定，不要将调查数据库放进程序目录。

EXE 模式由页面自动读取注入的会话令牌，无需在“设置”页手动输入；源码启动方式仍支持手动输入。

文献详情与证据阅读中的“预览原件”使用本机 PDFium 将已登记 PDF 渲染为页图像，在同一窗口内显示指定页；预览页提供上一页、下一页及原 PDF 下载入口。离线调查页可加载仓库内已验证的合成样例，并编辑研究问题；样例不代表真实文献调查。

2026-09-24 构建验收：最终前端 dist 打入 Windows onedir 包，EXE SHA-256 `06C289F0CE06C119DC6806ED04BD85808C429DE12BA44A57479E5BC9C025A280`；全目录约 45.4 MB。实际启动 EXE 后，`127.0.0.1:18765` 返回 HTTP 200 且首页含会话 token；关闭进程后端口停止监听。`tests/test_gui_contract.py` 为 10 passed（隔离 d19-runtime 解释器，`PYTHONPATH=src`）。构建使用 Python 3.12.14、PyInstaller 6.22.3。

独立审查修正后的 EXE SHA-256 为 `0C8CFEF02996EF8A25E5EA0D4E4FA33F8E170C2094D9D389A0EAD17FB9A295D1`；当前凭据/MCP 增补候选以 `GUI_ACCEPTANCE.md` 末尾的 SHA-256 为准。

## API 凭据与外部 MCP

“设置”页可在本次应用会话中输入模型 API key、OpenAlex API key，以及 EPO OPS consumer key/secret。EPO 的两项须配套填写。界面只返回 `session`、`environment` 或 `missing` 状态；密钥不会写入调查数据库、浏览器存储或打包目录，关闭应用即清除会话输入。现有调查服务在创建和推进任务时临时读取这些凭据，调用结束恢复进程环境。实际调用仍受运行配置和来源预算约束；当前 GUI 新建流程只提供已验证的合成离线样例，配置来源凭据本身不会发起实时检索。

Codex 和 Claude Code 按用户选择以外部 MCP 客户端连接。设置页生成本机 STDIO 启动命令：文献 MCP 使用现有 RAG 工作区只读模式；调查 MCP 使用独立调查工作区。外部 MCP 是单独进程，不能读取 GUI 会话内存中的密钥；如需它直接调用来源或模型 API，应在该 MCP 进程的环境中单独提供所需变量。`mcp-python.txt` 指向已安装项目 RAG/MCP 依赖的 Python 解释器；跨机器复制程序目录时须更新此文件及文献库、模型缓存路径。
