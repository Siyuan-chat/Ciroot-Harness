# 研究引擎与多地区专利整合指南

本轮交付按离线候选推进。能力和验收状态见 [阶段记录](INTEGRATION_STAGE.md)，真实运行条件见 [待激活清单](INTEGRATION_ACTIVATION.md)。安装成功、组件测试通过和真实研究验收分别记录。

## 冻结输入与开始调查

先确认问题、资料范围、来源权限、模型配置和预算。冻结文档版本和解析修订后开始运行；后续重新解析生成新修订，旧报告仍读取原绑定版本。公开资料、合成示例和公司资料分别标记。

PaperQA2／STORM 只生成草稿和候选断言。每项引用需要对应本系统的文档、版本、解析修订和原文位置。不唯一或缺原文时进入复核。引句存在不代表语义支持；解释和改写也需要独立接受。

## 可选运行环境

桌面 EXE 和研究引擎使用独立环境。安装脚本是 `packaging/install_research_env.ps1`，传入绝对路径的基础 Python、核心 wheel、核心锁和对应引擎锁；两个锁有版本冲突时在创建环境前停止。

安装记录含 wheel 和锁文件哈希。把生成配置中的 `research_engine.python_executable` 加入完整运行配置，并补齐所选引擎要求的模型、嵌入及缓存配置。安装记录本身不是完整运行配置。运行时不安装包；缺少依赖或能力时查看诊断。

在交付包根目录使用 PowerShell 7.0 或更新版运行以下示例；Windows PowerShell 5.1 不支持这些安装和构建脚本。先替换基础 Python 为已安装的本地 CPython 3.12；环境和配置路径由用户选择。安装需要取得锁定的公开依赖，安装后不会自动开始研究。

```powershell
$basePython = 'C:\replace\Python312\python.exe'
$bundle = (Get-Location).Path
$runtime = Join-Path $bundle 'optional-runtime'
& (Join-Path $runtime 'install_research_env.ps1') -Profile paperqa -BasePython $basePython -CoreWheel (Join-Path $runtime 'wheels\research_harness-0.1.0-py3-none-any.whl') -CoreLockFile (Join-Path $runtime 'requirements\core-lock.txt') -LockFile (Join-Path $runtime 'requirements\paperqa-runtime.txt') -EnvironmentPath (Join-Path $bundle 'research-envs\paperqa') -ConfigPath (Join-Path $bundle 'research-envs\paperqa.installation.json')
```

STORM 使用另一个环境与配置路径，以及它自己的锁，不能复用 PaperQA 环境。

凭据仅通过指定环境变量配置，不粘贴进资料、运行 JSON、报告或仓库。真实运行使用新建运行和明确数值预算。模型、嵌入和来源物理请求共用额度；结果未知的请求不自动重发。

## 来源能力

号码查询、关键词搜索、案件补充、文件下载和术语查询各自声明能力。启用一个来源不能推定它支持全部操作。当前官方规范和限制见 [来源矩阵](SOURCE_API_MATRIX.md)。缺凭据为待激活；缺规范为待规范；失败和成功空结果分别显示。

## 复核、导出与重开

先查看原文位置和连续引句，再判断断言在相同条件下是否得到支持。未通过块保留草稿和诊断；接受后再进入正式报告。导出后关闭、重开并核对旧报告、复核历史、收据和预算；回放使用保存的输入，不重新搜索。

## 三种部署

Windows 保留轻量 EXE，加装可选研究环境。自托管服务通过 `python -m research_harness.gui` 启动，默认监听 `127.0.0.1`；使用 `--host` 监听其他地址时必须同时配置精确 `--allowed-hosts`。首版面向单用户或受信网络。

Docker 使用核心、可选研究和独立 Demo 配置，工作区和资料库挂持久卷。镜像重建后需在实际 Docker 宿主核对数据和恢复行为。公开 Demo 仅展示合成或已获再分发许可的冻结材料，服务端禁止真实模型、抓取、上传和管理写操作。本轮只交部署配置，不发布公网。

科学对照按 [评测协议](INTEGRATION_EVALUATION.md) 执行；未标注项保持未评判，不推测费用或质量提升。

## 离线评测命令

专利结构入口读取本地冻结 JSON：`rh patent-analyze --input "C:\path\to\AEM\examples\patent_analysis\frozen-input.synthetic.json"`。替换为实际绝对路径；示例是合成材料。算法依赖见 `requirements/patent-analysis-lock.txt`，缺依赖时返回部分结果及诊断，退出码为 4。分析输出不自动接受断言，也不写调查数据库。

在源码根目录、安装好核心包的 Python 环境中执行：

```powershell
python scripts/evaluate_integration.py --case examples/integration_evaluation/case.json --results-dir examples/integration_evaluation --annotations examples/integration_evaluation/annotations-template.json --output evaluation-offline.json
```

示例用于检查协议和未激活状态，不代表三种研究方式已经完成真实对照。请将真实逐项标注保存到单独文件，再替换 `--annotations`；不要覆盖冻结示例或把未评判项改成通过。

## 来源执行

来源诊断入口为 `rh patent-source-diagnose --workspace "C:\path\to\调查数据库目录" --run-id RUN_ID`。显式来源调用使用下面的 CLI；当前 GUI／HTTP 尚未提供来源执行按钮。工作区参数指含 `investigation.sqlite` 的调查目录。

```powershell
rh patent-source-execute --workspace "C:\path\to\调查数据库目录" --run-id RUN_ID --task-id TASK_ID --task-version 1 --request-id NEW_REQUEST_ID --source jpo --operation app_progress --params-file "C:\path\to\jpo-params.json" --input-refs-file "C:\path\to\frozen-task-refs.json"
```

先替换运行、任务、版本和请求 ID。当前待处理任务可通过应用的 `GET /api/v1/runs/{run_id}/tasks` 或 `InvestigationService.get_pending_tasks` 读取；引用文件必须保存该任务实际的 `input_refs` 数组。参数文件是所选操作的 UTF-8 JSON 对象；JPO `app_progress` 要求有效的 `application_number`。凭据仍只通过配置指定的环境变量提供。默认新运行的来源额度为 0，缺权限或预算不会派发。返回原件是待解析草稿，不自动成为证据；完成／无匹配退出码为 0，待激活或部分结果为 4，输入错误为 2。不要换请求 ID 自动重发结果未知的请求。

## Docker 构建入口

以下命令需要完整源码根目录作为构建上下文，以及可用的 Docker 宿主：

```sh
docker compose --env-file compose.env.example up --build research
docker compose --env-file compose.env.example --profile demo up --build demo
docker compose --env-file compose.env.example --profile paperqa up --build research_paperqa
docker compose --env-file compose.env.example --profile storm up --build research_storm
```

默认只映射本机地址；自托管主机名通过 `RH_ALLOWED_HOSTS` 明确配置。卷保存工作区和资料库；重建时不要加 `down -v`。单独复制 Dockerfile 或 Compose 文件不能提供完整构建上下文。本机尚未构建或运行这些镜像。
