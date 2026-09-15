# D19-P2 继续推进验收

2026-09-15。原有本地 RAG 检索与原生 Codex/Luna 工具调用通过；OpenAlex 单源的真实调查服务协议测试通过。P2 的专利来源、带 Key 认证和 P3 科学调查质量仍未验收。

本轮保留原 23 篇参照库，未导入、重建、重新嵌入或改写原文。新获取的 PDF 和逐页证据保存在独立调查工作区。模型任务的七个角色使用显式脚本回复测试协议；另行使用真实 Luna 验证本地 RAG 调用，二者分别记录。

## 已交付行为

- RAG 状态检查不可用时返回 `index_status=unavailable`、`indexed_document_count=null` 和结构化错误；依赖异常不会被误报为零索引。
- `data_mode=live`、`allow_network=true` 显式开启 OpenAlex；拒绝混入 synthetic 来源夹具。API Key 通过调用者指定的环境变量读取，匿名配置可运行。
- 查询使用真实 collector；每次 HTTP 请求预留预算，持久保存失败、成功页与 cursor。重启复用成功页；未知 pending 不自动重发；实际限流/网络失败进入有界重试。
- 候选保留 DOI、年份、摘要和来源位置。下载分别限制文档尝试、HTTP 次数和累计接收字节，失败尝试也计数，预算拒绝保留已有 catalog；累计字节及未知下载状态跨重启保留。
- 参照证据可通过 `scenario.reference_evidence` 显式传入，保留证据、版本及位置，并经过既有访问和查询外发策略。本接口不自动查询或更新参照 RAG。
- 真实运行的任务、结果与报告使用 `synthetic=false`；CLI、MCP 和报告共用调查状态及来源账本。

## 独立验证

本地证据根目录为 `.local/d19-p2/continue-acceptance/`，属于被忽略工作区，不提交 PDF、运行数据库、会话或模型缓存。

| 检查 | 结果 | 证据 |
|---|---|---|
| 状态故障修正 | 最终 5/5；初版测试隔离问题 4/5 的失败记录保留 | `rag-status-aa78904.xml`、`rag-status-5d4ce51.xml` |
| 安装版全量回归 | 90/90，通过当时全部测试 | `installed-regression.xml` |
| 后补下载预算定向回归 | 13/13，含前述 live 测试及新增下载故障测试；不与全量数字相加 | `download-regression-6f8856d.xml` |
| 原索引实际读取 | 23/23 索引就绪，实际 8,820 个 Qdrant 点；禁止网络时搜索及 context 成功 | `../rag-restored/retrieval-acceptance.json` |
| 原库不变量 | 文档 23、版本 23、证据 8,820，活动集合与索引指纹前后相同 | `rag-before.json`、`native-host-verification.json` |
| 原生宿主 | 现有 ChatGPT 登录，`gpt-5.6-luna` 实际调用注册的 `aem_rag` 三个只读工具，逐字核对摘录及 DOI/物理页 | `native-luna-events-2.jsonl`、`native-host-verification.json` |
| 真实调查服务 | 七个角色协议环节完成，2 次 OpenAlex HTTP 请求、1 个成功 PDF、26 页证据 | `live-service-e5afe3d/acceptance.json` |
| 完成后重启 | 禁止新网络时恢复并导出，预算、冻结报告和文件字节不变 | 同上 |
| 两个外部入口 | 安装版 CLI 与真实 SDK 子进程 STDIO 的完整 status/result 一致，并与服务的预算、来源覆盖及证据一致 | `live-service-e5afe3d/readback.json` |
| 安装产物 | 9 个受影响模块/资源在源码、最终 wheel、RAG 安装环境和真实来源安装环境中一致，仅规范化 CRLF | `artifact-verification.json` |

原索引只读检查中，状态约 13.393 秒、首次搜索约 25.938 秒；不作为稳定性能基准。原生 Luna 返回的首条证据 DOI 为 `10.3390/polym15092144`，物理第 9 页，evidence ID 为 `ev-cc14e8b422d6f1c627f376b2`。该命中是章节标题；它证明工具和引文位置可用，不证明检索排序或科学回答质量。

真实公开样本使用 DOI `10.1109/access.2024.3363869`，题名查询从真实 OpenAlex 响应中定位既有协议样本，不是手工向服务注入文献。整个服务测试约 270.344 秒，包含网络正文传输；2 次来源请求、4 次下载 HTTP 请求、1 次文档尝试、接收 7,457,797 字节。获取的 PDF 与首轮成功样本相同，SHA256 为 `6ec0d064d9cd5f05cee5e1d35253dcb2c6e4b583db736f42868ad427488f76de`。

运行 `inv-9bb51c9ba1ca` 的最终 outcome 为 **partial**：有界检索保留候选覆盖限制，脚本核验明确不评价科学结论。报告出口生成规范 JSON、英文 Markdown/HTML、比较 CSV、人工复核 CSV 和 BibTeX，共 6 个文件；没有把协议成功改称完整科学调查通过。

## 运行环境恢复与失败记录

恢复环境位于 `.local/d19-p2/rag-restored/venv`，`include-system-site-packages=false`。保留 FastEmbed 0.8.0、Docling 2.126.0、Qdrant client 1.19.0、LlamaIndex core 0.14.24 和既有 E5 缓存。实际 LlamaIndex metadata 要求 `nltk>=3.9.3`，项目三处旧 3.9.2 固定版本已统一修正为 3.9.3；不更改原嵌入指纹。

恢复分阶段执行，未伪造包 metadata。完整 `.[rag-mcp,investigation]` 安装尝试在 Torch 下载阶段以非零退出，日志没有给出可归因的终止错误；记录保留于 `restore-install.log`。随后按检索与 MCP 实际依赖图补齐缺项，最终 `pip check` 通过，真实检索和宿主调用也通过。**本次恢复环境的新增 PDF Docling 解析/完整 parser extras 未验收**，不能由 pip check 或检索结果推定可用；原 23 篇的既有解析证据保持原状态。

原生 Luna 首次握手失败，单独导入 SDK 定位缺少 `cryptography`（`pyjwt[crypto]` 的依赖，普通 pip check 未暴露 extras 缺失）。补装 SDK 声明的依赖后，先使用实际注册配置验证 STDIO 握手和五个工具发现，再运行 Luna。失败输出 `native-luna-events.jsonl` 与成功输出 `native-luna-events-2.jsonl` 分开保留。

仅修改用户现有 `aem_rag` 配置中的解释器 command，指向上述恢复环境；原 catalog、workspace、缓存、超时及其他配置的解析结果未变化。`mcp-command-change.json` 保存新旧 command，供回退；不保存其他配置秘密。用户已有打开的任务是否热加载新注册未单独验证，本次证据来自新启动的原生 Codex exec 会话。

依赖清单与安装命令日志位于 `retrieval-runtime-freeze.txt`、`retrieval-dependency-install.log`、`mcp-dependency-install.log`；最终依赖检查见 `pip-check-final.txt`。

## 复现入口与下一阶段

- 真查询/协议：`python acceptance/probe_investigation_live.py --output <新的测试目录>`。会产生有界公开网络请求，不能计为模型调查质量测试。
- 对已通过运行的 CLI/MCP 读回：`python acceptance/probe_investigation_readback.py --probe-dir <上述目录>`。此检查禁止外部网络。
- 原库恢复检查：设置原模型缓存及离线环境变量后，运行 `python acceptance/probe_rag_restored.py --workspace <原库> --before <只读计数与配置快照> --output <结果 JSON>`。
- 产品 live runtime 示例：`examples/investigation/live-openalex-runtime.json`；使用方法见三语 `INVESTIGATION_USAGE` 文档。

下一阶段是在已打通接口上，让真实 Luna 根据本地 RAG 证据生成检索式、筛选新论文并形成带证据位置的技术调查报告或综述，同时独立评价漏检、证据不足和人工复核。新增 PDF 的 Docling 解析环境应先补齐并单独验收，再执行真正的回库。EPO/其他专利 API、带 Key 认证、真实公司资料与后台调度均未在本轮运行。

## 工程追溯

RAG 修正提交 `5d4ce51d8a4eec035112eaadbf6f8a33da5d0b9f`；来源实现与修正最终检查点 `6f8856da38e86055e8d2f847c13d9095892e5517`；最终构建源码检查点 `879849fb10feec72f2338e26a3480c7d25293498`。最终 wheel SHA256：`e49ac50553881ed9705b06599659be24d62720bc86034aad0d40e5773d2bf4f3`。本轮仅本地提交，未推送 GitHub。
