# D19-P2 首轮真实来源测试

后续状态：原 RAG 检索与真实 Codex/Luna 调用已恢复；OpenAlex 已接入调查服务并通过真实公开数据协议测试。详见 [继续推进验收记录](D19_P2_CONTINUATION_ACCEPTANCE.md)。下文保留首轮诊断原貌，其中的环境阻断与 synthetic-only 状态是当时结果。

2026-09-15。状态：首轮测试完成，OpenAlex 采集器的有界查询/正文获取/复用通过；P2 整体验收仍未通过。范围：既有 RAG 预检、OpenAlex 单源查询与一个可用 OA 正文样本。P1 离线通过记录保持不变；本文件不代表 P3 调查闭环通过。

## 测试条件

- 复用原有 23 篇参照库，禁止重建、导入和重新嵌入；新网络结果放 `.local/d19-p2/`。
- 每次检索最多两页、每页最多五条。下载以获得一个经身份校验的 PDF 为止，保留失败记录。
- OpenAlex、EPO 环境变量在当前进程及用户/机器持久环境均未配置；只保存存在状态，不保存秘密。
- 生成模型不参与本轮采集器测试，未启动专利查询、公司资料处理或后台调度。
- 独立采集器与 `rh investigate` 区分；后者目前仍为 synthetic-only，API 接线与共同状态投影尚未验收。

## 官方协议依据

本轮已核验 [认证](https://help.openalex.org/api/authentication/)、[分页](https://help.openalex.org/api/paging/)和[排序](https://help.openalex.org/api/sorting/)说明：基本匿名查询可用；密钥支持 Bearer header；分页支持 cursor 和 1–100 的页大小；有 search 时可按 relevance_score 排序。运行事实仍以真实请求为准。

## 初始诊断

安装版采集器在限制网络的环境返回安全的 `network_error`，没有收到 HTTP 响应。在获准联网的同一安装包中，查询 `piperidinium anion exchange membrane`、年份下限 2024，HTTP 200，约 2.018 秒返回 5 条记录，因候选上限为 `partial`，不是来源失败。

初始按引用数排序的五条结果含太阳能主题，说明旧排序不适合直接作为相关性评价。已有 `page_size` 与总候选数耦合，不能独立实现每页五条的两页实验。Terra 据此修正采集参数；原始输出保留在 `.local/d19-p2/initial-network/`。

## 最终实测

Terra 实现提交 `292228ce396755e6f89967b67a8dffadaa0a3304`：独立页大小、三个明确排序选项、由调用者管理的 `start_cursors`。终页没有后继时返回 `next_cursor=null`；配置错误保持结构化错误。说明见 [P2_SOURCE_IMPLEMENTATION.md](P2_SOURCE_IMPLEMENTATION.md)。

设计任务从干净实现工作树构建非 editable wheel，在新 P2 venv 中安装；逐字节比较 wheel、安装模块与提交（仅容许 Git 换行转换），三者一致。依赖共享系统 site-packages 和既有 D19 runtime，不声称全新机器隔离安装。wheel SHA256：`9d8842218c70d8486ae426bff87e3daa251e49c5c9a6daff27efba1fdb7c4607`。

| 检查 | 结果 | 本地证据，均位于 `.local/d19-p2/` |
|---|---|---|
| 已安装版定向回归 | 9/9；`python -m unittest discover -s .local/d19-worktrees/terra-p2/tests -p test_literature.py`，安装版解释器、无 PYTHONPATH | 本次命令输出；实现者源码自测另计 |
| 真实匿名查询第一页 | relevance_score:desc、5 条，HTTP 200，1.161 秒 | `page1/search.json` |
| 保存 cursor 后新进程续查 | 第二页 5 条，HTTP 200，1.171 秒；起点等于第一页后继，无重复 DOI；10 条均不在原 23 项清单中 | `page2/search.json`、`pagination.json` |
| 缺 Key 路径 | 非匿名配置在发请求前返回 `missing_api_key`，CLI exit 2 | `missing-key.json` |
| 首个 OA 候选 | Wiley 候选下载被拒，保留 `access_denied`；未伪装成功 | `download/download-probe.json`、`download/download_log.jsonl` |
| RSC OA 候选 | 下载 URL 返回非 PDF；landing 响应超过既有 2 MiB 上限；保留两个失败 | `download-rsc/download-probe.json`、`download-rsc/download_log.jsonl` |
| 机构仓储 PDF | 1 个有效 PDF，26 页，7,457,797 字节；下载及校验 12.626 秒 | `download-repository/download-probe.json` |
| 逐页文本提取 | pypdf 规范化返回 26 个物理页，耗时 14.058 秒；未执行 Docling、嵌入或 RAG 入库 | `download-repository/page-evidence.json` |
| 离线重复下载 | 禁止网络的 session 下成功复用；0 新字节、0.741 秒；文件 SHA256 一致 | `download-repository/reuse-probe.json` |
| 实际已安装 CLI | 原生模块 CLI 复用成功，exit 0、0 新字节；安装模块与源提交一致 | `installed-verification.json` |

成功样本 DOI `10.1109/access.2024.3363869`，题名 *Challenges and Opportunities in Green Hydrogen Adoption for Decarbonizing Hard-to-Abate Industries: A Comprehensive Review*。它来自初始真实 OpenAlex 响应的公开机构仓储位置，不在原 23 项清单。该绿氢综述只用于获取/身份校验/页码提取/复用的工程测试，不能计入 AEM 相关性、科学比较或自动筛选质量通过。没有通过继续换查询增加候选来掩盖两个失败；初始查询与后续相关性查询的全部结果分别保留。

成功 PDF SHA256：`6ec0d064d9cd5f05cee5e1d35253dcb2c6e4b583db736f42868ad427488f76de`。原始内容、各次 catalog 和文本仅保存在被忽略的测试目录。

## RAG 预检与阻断

Luna 经公开 CLI 实测：23 篇、23 版本、8,820 条文本证据可读，status 1.929 秒；指定 evidence 的 context 1.068 秒成功。英文 search 在 1.298 秒后因缺 `fastembed` 包元数据失败；该解释器也缺 `docling`、`qdrant-client`、`llama-index-core`。旧 RAG venv 更早在包导入阶段缺 `jsonschema`。这与前次记录的共享运行时依赖漂移一致，但本轮未安装或修复这些依赖。

`status` 返回的 `indexed_document_count=0`、`index_status=partial` **不能证明向量丢失**：现有 `_version_is_indexed()` 捕获 Qdrant 导入/读取异常后返回 False。SQLite 有证据记录，Qdrant 元数据有集合与 384 维配置，但实际点数尚不能检查。应先恢复与已有指纹匹配的隔离依赖，再只做 status/search/context，不能据此触发全库重建。该错误投影还需在后续修正为“检查不可用”，而非确定的零索引。

详见 `luna-preflight/result.json` 与 `luna-preflight/commands.txt`。没有修改旧库、重建/嵌入、MCP 注册或测试真实 Codex/Luna 工具使用。

## A01–A06 状态与下一步

- A01：匿名来源访问及缺 Key 拒绝已验证；带 Key 认证、真实调查宿主的配置链尚未验证。
- A02/A03：OpenAlex 独立采集器查询与两页分段续查通过。
- A04：一个机构仓储全文样本获取及页码提取通过；未证明所有 OA 位置可下载，也未接入调查证据库。
- A05：调用者保存 cursor 后续查、成功文件离线复用通过；故障中的自动恢复/中央累计预算不在本次 collector 接口中，仍未验收。
- A06：安装版 collector/CLI 已验证；调查 CLI、MCP、报告的共同真实来源投影仍缺接线，未通过。

后续优先恢复 RAG 检索运行环境并修正不可用索引的状态表达，然后接通 OpenAlex 到调查服务，再进入真实 Luna 的论文调查闭环。OpenAlex Key/EPO 凭据尚缺，不阻断本次匿名采集器测试；无需在聊天里发送密钥。专利 API、真实公司资料与后台监测均未执行。本轮源码修正及验收记录仅合入本地，未推送 GitHub。
