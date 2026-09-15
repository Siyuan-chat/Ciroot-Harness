# D19-P2 Handoff — 2026-09-15

本次交接保存已完成框架和验收状态，按用户要求同步到现有私有 GitHub 仓库；本轮不继续开发、安装依赖或启动新调查。恢复工作时先读本文，再读 [详细验收记录](D19_P2_CONTINUATION_ACCEPTANCE.md)。

## 当前检查点

- 仓库：`Siyuan-chat/autoSearch-Harness`，私有，默认分支 `master`；工作目录 `C:\Users\Siyuan_ye\Documents\ChatGPT\AEM`。
- 功能及验收基线：`0b984c2`。本 handoff、三语 README 入口和同步授权记录由随后的文档提交保存；最终上传 SHA 以 Git 及交付消息为准。
- D2、D18、D19-P1 的历史验收保留；D19-P2 当前通过的是 OpenAlex 单源工程协议和原库检索/原生 Luna 调用，不是全部来源或科学调查通过。
- 设计任务负责计划、诊断、独立验收；Terra/Luna 负责被明确分配的实现。旧 AGENTS/D18 和 P1 文档的停止范围是历史阶段，后续已授权范围以用户消息、DECISIONS 和本阶段验收记录解释。
- 本次交接时两个 Terra 实现子任务均已完成，Luna 恢复子任务已中断，后续收尾由根任务完成；没有运行中的开发子任务。保留现有 worktree，不清理或重用旧环境冒充新环境。

## 已通过与尚未通过

| 项目 | 当前证据 |
|---|---|
| 原本地 RAG | 23 文档、23 版本、8,820 条文本证据/实际向量点；status、混合检索及 context 成功，原活动集合和索引指纹未变 |
| 原生 Codex/Luna | ChatGPT 登录，`gpt-5.6-luna` 实际调用注册的 `aem_rag` 三个只读工具，返回真实 DOI、物理页码和可核对摘录 |
| OpenAlex 服务链 | 真实匿名查询 → 筛选任务 → OA PDF → 26 页证据 → 六种报告产物；七个角色的输出由脚本提交，明确为协议测试 |
| 恢复与入口 | 完成后恢复不新增网络请求，预算和报告字节不变；安装版 CLI 与真实 SDK STDIO 的状态、来源和证据一致 |
| 回归 | 安装版当时全量 90/90；补充 live/下载故障定向 13/13。后者与前者有重叠，不相加 |
| 待完成 | 新 PDF 的 Docling 解析依赖与回库；真实 Luna 从 RAG 生成检索式并完成科学调查；带 Key 认证；真实专利 API/企业资料/后台监测 |

真实协议运行 `inv-9bb51c9ba1ca` 保留 `partial`：查询有候选覆盖上限，脚本不判科学结论。取得的绿氢综述 DOI `10.1109/access.2024.3363869` 只用于协议验收，不能当作 AEM 相关性基准。它已经进入独立调查的逐页证据，但没有进入原参照 RAG。

## 本机恢复入口

下列路径均相对于项目根目录，除源码/文档外都被 Git 忽略。新机器 clone 不会自动获得原文、索引、缓存、虚拟环境和会话。

| 用途 | 路径 |
|---|---|
| 当前 RAG/MCP 解释器 | `.local/d19-p2/rag-restored/venv/Scripts/python.exe` |
| 真实来源协议测试解释器 | `.local/d19-p2/venv/Scripts/python.exe`（历史共享依赖环境，不冒充全隔离） |
| 原参照库 | `.local/rag-acceptance/real-v3/workspace` |
| 原清单 | `literature/aem_oa_reviews/catalog.json` |
| 已注册 E5 模型缓存 | `.local/rag-acceptance/luna-e5-small-probe/model-cache` |
| Hugging Face 缓存 | `.local/rag-runtime/huggingface` |
| 首轮及后续所有运行材料 | `.local/d19-p2/` |
| 后续独立验收证据 | `.local/d19-p2/continue-acceptance/` |
| 真实调查工作区 | `.local/d19-p2/continue-acceptance/live-service-e5afe3d/workspace` |

用户 `~/.codex/config.toml` 中已有 `aem_rag`，仅其 command 被切换到恢复环境，其他配置保留。新旧 command 记录在 `continue-acceptance/mcp-command-change.json`；不要提交用户配置或凭据。原生成功证据来自新 Codex exec 会话，已有桌面任务是否热加载未验收。

最重要的证据文件：

- `continue-acceptance/native-host-verification.json` 与 `native-luna-events-2.jsonl`：真实宿主成功；无 `-2` 的首次握手失败记录保留。
- `rag-restored/retrieval-acceptance.json`、`continue-acceptance/rag-before.json`：原库实际读取及不变量。
- `continue-acceptance/live-service-e5afe3d/acceptance.json`、`readback.json`、`http.json`：真实来源、报告、恢复和入口一致性。
- `continue-acceptance/artifact-verification.json`、`pip-check-final.txt`、`retrieval-runtime-freeze.txt`：包与环境追溯。
- `continue-acceptance/restore-install.log`：完整 extras 安装在 Torch 下载阶段非零退出；日志没有确定根因。不能把它写成已经修复的完整解析环境。

## 下一步按此顺序推进

1. **先补齐并验收新增 PDF 解析。** 重新定位完整 Docling extras 安装中止原因，复用缓存；不要盲目重复安装或伪造 metadata。NLTK 固定版本已从 3.9.2 修正为 3.9.3。`pip check` 不能覆盖 extras 或实际服务启动，需真实 Docling 导入/解析证据。
2. **在独立发现库中验证回库。** 使用已经下载的公开协议 PDF，验证可解析、页码/版本可追溯、入库后能检索、重复导入可复用。不要把试验直接写进原 23 篇参照库，也不要先重建原索引。
3. **再做真实 Luna 科学调查。** 从自然语言问题和本地证据开始，由 Luna 产生带出处的查询、筛选真实论文、比较证据、形成技术调查报告/综述。七角色脚本回复不能作为模型表现证据；保留漏检、条件不可比、正文缺失和人工复核项。
4. **论文闭环验收后接专利。** 确定来源 API 和凭据，再调试专利增量采集、业务相关性与人工分流；不要自行启用后台调度或使用真实保密公司资料。

可以复用的脚本：

```powershell
# 仅读回已经完成的公开协议运行，不重新联网采集
& .local/d19-p2/venv/Scripts/python.exe acceptance/probe_investigation_readback.py --probe-dir .local/d19-p2/continue-acceptance/live-service-e5afe3d
```

`acceptance/probe_rag_restored.py` 提供原库只读验收；使用前设置已有模型缓存及离线变量，并确认没有其他进程持有原 Qdrant。`acceptance/probe_investigation_live.py` 会发出真实网络请求，只有新代码变化或新的验收问题需要时再运行，使用新的输出目录。用户指南和配置入口分别为 `docs/INVESTIGATION_USAGE.zh-CN.md`、`examples/investigation/live-openalex-runtime.json`。

## 给接手任务的提示词

> 先读 docs/D19_P2_HANDOFF.md 和 docs/D19_P2_CONTINUATION_ACCEPTANCE.md，核对 Git 当前状态。继续保持设计者计划/独立验收、Terra/Luna 明确分工。下一步从 Docling 完整解析依赖的失败日志诊断开始，用已有公开 PDF 在独立发现库验证解析、回库和复用，再进入真实 Luna 科学调查。保留原 23 篇库和冻结证据，不重复已有效的测试，不把脚本协议通过写成模型或科学质量通过。不要擅自启用专利 API、公司保密资料或定时监测。
