# D19 模型 API 自动执行阶段

日期：2026-09-24。目标是复用既有 `ModelTask` / `ModelResult`、来源和报告服务，让用户配置模型 API 后执行调查；host 模式继续可用。本阶段不启用企业保密监测、GUI 或 GitHub 发布。

## 当前实现

- `mode=api` 的 `auto-start` / `auto-resume` 会领取既有待办任务，向所选模型发送角色提示、授权 payload 和输出 schema，经现有 `submit_model_result()` 校验后推进服务，结束时重试标准报告导出。Python 调用方可使用 `advance_api_run(service, run_id)`。
- 首批提供 OpenAI、Anthropic、DeepSeek、Qwen、Kimi 五个配置档；另有显式 HTTPS 地址的 OpenAI 兼容配置档。Anthropic 使用 Messages 的指定工具输入；OpenAI、DeepSeek、Qwen 使用 Chat Completions 的 JSON Object；Kimi 使用 Chat Completions 并通过提示要求 JSON。所有返回均再过本地任务 schema 和证据引用检查，不把厂商响应格式等同于科学核查通过。
- 凭据只从 `api_key_env` 指向的环境变量读取。runtime、数据库、报告和错误消息不保存密钥。自定义端点必须是无凭据、无查询参数的 HTTPS URL；模型响应重定向不跟随。
- 每次 HTTP 之前在 SQLite 预留 `max_model_calls`，失败也占用额度；不会自动无限重试。额度耗尽时 run 为 `partial`，保留既有事实和问题记录。`max_output_tokens` 限制单次输出；尚无价格表与货币硬上限，实际账单以供应商为准。

## 运行配置

以下配置用于合成资料的接口演示；真实资料需要另外设置 `data_mode=live`、明确来源配置及其各自的凭据/网络边界。

```json
{
  "mode": "api",
  "data_mode": "synthetic",
  "allow_network": true,
  "model_api": {
    "provider": "deepseek",
    "model": "YOUR_MODEL_ID",
    "api_key_env": "DEEPSEEK_API_KEY",
    "max_output_tokens": 4096,
    "timeout_seconds": 60
  },
  "budget": {"max_tasks": 10, "max_model_calls": 10}
}
```

将 `provider` 和 `api_key_env` 改为下表即可选择厂商；模型 ID 须使用该账号实际可调用的值。Qwen 默认国际站点，按密钥地区可通过 `endpoint` 指定对应 HTTPS `/chat/completions` 地址。

| provider | 默认端点 | 典型环境变量名 |
| --- | --- | --- |
| `openai` | `https://api.openai.com/v1/chat/completions` | `OPENAI_API_KEY` |
| `anthropic` | `https://api.anthropic.com/v1/messages` | `ANTHROPIC_API_KEY` |
| `deepseek` | `https://api.deepseek.com/chat/completions` | `DEEPSEEK_API_KEY` |
| `qwen` | `https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions` | `DASHSCOPE_API_KEY` |
| `kimi` | `https://api.moonshot.ai/v1/chat/completions` | `MOONSHOT_API_KEY` |

```powershell
$env:PYTHONPATH = (Resolve-Path src).Path
& .local/d19-runtime/venv/Scripts/python.exe -m research_harness.investigation_cli --workspace .local/my-api-run auto-start --spec examples/investigation/synthetic-spec.json --runtime my-api-runtime.json --scenario examples/investigation/synthetic-scenario.json
& .local/d19-runtime/venv/Scripts/python.exe -m research_harness.investigation_cli --workspace .local/my-api-run auto-resume RUN_ID
```

上面的 Python 路径是本机已有环境示例，安装用户应使用自己的 Python 环境。首次运行会调用付费模型；不要把合成示例当作真实科学调查。

## 验收状态

五个配置档的请求、鉴权头、响应解析和任务提交已用无网络协议替身测试；完整合成调查的 API 自动推进、报告导出、重开复用和失败额度处理已测试。调查模块 96 项测试通过；wheel 可构建，隔离安装目录可导入新模块并读取随包 schema/提示文件。当前进程的五家模型密钥环境变量均未设置。**五家真实账号的在线模型调用及真实论文＋专利全自动案例仍待验收**，所以当前不能宣称“给 key 即可稳定完成真实 MVP”。旧 host 模式回归继续通过。在线验收应按供应商逐一执行最小额度样本，记录实际模型、HTTP、usage、失败/修复与报告证据；不得用替身测试代替。

接口依据：[OpenAI Chat Completions](https://platform.openai.com/docs/api-reference/chat/create)、[Anthropic Messages](https://platform.claude.com/docs/en/api/messages/create)、[DeepSeek JSON Output](https://api-docs.deepseek.com/guides/json_mode/)、[Qwen OpenAI 兼容入口](https://help.aliyun.com/en/model-studio/base-url)、[Moonshot 官方客户端配置](https://github.com/MoonshotAI/kimi-code/blob/main/docs/en/configuration/providers.md)。端点与可用模型可能更新，实际在线验收以账号所在地区和当时官方文档为准。
