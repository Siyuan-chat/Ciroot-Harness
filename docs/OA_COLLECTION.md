# 开放文献检索与下载

2026-09-10 · D17 实施规范。目标：其他 AI 在普通命令行环境中，读取本说明、安装包、配置数据源凭据和检索 JSON 后，能够复现检索与有效 PDF 下载；不依赖 Codex 私有工具、个人 skill、浏览器会话或本机绝对路径。

## 本次案例

主题为阴离子交换膜；目标 25 篇，接受 20–30 篇；优先综述，兼顾聚合物骨架/哌啶鎓、耐碱降解、交联增强、传导溶胀、电解水和燃料电池。优先近五年，允许经典综述。排除只讨论催化剂或仅顺带提及 AEM 的文章。原始全文和实际查询响应保存于 `literature/aem_oa_reviews/`（Git 忽略），公开案例配置和经核验的 DOI/开放 URL 清单可提交，PDF 不提交。公开清单记录许可，不能把免费可读等同于任意再分发。

## 最小实现交接

Terra 在原隔离工作树实现，提交检查点供本任务独立验收；不要更改本文件、DECISIONS 或另一任务的 RAG 计划。首选一个 `research_harness.literature` 模块，提供共用 Python 函数及 `python -m research_harness.literature` 命令；无需完整调查状态机或新框架。

1. `search --config <json> --output <candidates.json>`：OpenAlex 原生搜索与有界分页。JSON 含 queries、year_min、review_only、max_candidates、max_pages_per_query。凭据仅从 OPENALEX_API_KEY 环境变量读取，仅向 API 本源发送 Authorization；匿名模式可显式使用且标明。保留题名、DOI、作者、年份、type、摘要（如有）、OA 位置/许可/版本、查询出处、cursor/截断/失败状态。分页不完整不能伪称穷尽检索。保存候选对象 {records:[...], search_status:..., queries:[...]}。
2. `download --manifest <json> --output <dir> --limit 25`：接受 search 输出或经筛选清单。record 最小字段 title、doi、year、authors（字符串列表）、type、locations（is_oa、pdf_url、landing_page_url、license、version）。仅下载 OA 位置；先直接 PDF，再从允许公开落地页 citation_pdf_url 元标签发现 PDF。可配置启用 Unpaywall（UNPAYWALL_EMAIL）作补充，缺少时不阻断已知开放 URL。不要求模型 key。
3. requests 复用现有依赖；PDF 校验用 pypdf（独立 literature extra）。HTTP 限时、有界重试、低速、按响应 Retry-After 上限退避；认证失败不重试。仅 http/https，逐跳检查重定向目标，拒绝私网/回环/带用户凭据 URL，限制单文件 30 MiB 和总接收 300 MiB（含失败与重试）。不把 API key 发给 PDF 域名，不在日志输出 secrets。拒绝 HTML 伪 PDF，检查 %PDF、可解析/非加密、页数>0；核对前两页 DOI 或题名身份，无法核对进入 review，不计成功。
4. DOI/来源 ID 去重，SHA256 识别重复字节；按安全短文件名原子保存 PDF，重跑校验并复用成功文件。候选失败继续，输出 catalog.json/csv、references.bib、README.md 和 download_log.jsonl（时间、来源、状态、错误代码、页数、哈希、路径、版本/许可）；不将摘要、补充文件或仅搜索命中数计入全文成功数。程序成功目标是 limit 个有效 PDF；不足返回 partial 及非零退出码，保留已有成果。
5. 提供机器可读结果及简洁 stdout；CLI 只组装参数，共用函数供未来 MCP/其他 AI 调用。服务不依赖任何 LLM。宿主 AI 根据用户需求生成 query JSON 并筛选候选，本模块负责确定性 I/O。暂不实现 RAG、科学分析、EPO、GUI 或宿主模型调用器。
6. scripts/ 下仅保留必要薄入口（如果模块命令已足够，无需重复脚本）。examples/ 下提供通用/AEM 查询配置；README 及三语用户指南新增最短命令和准确范围。

## 验收

- 真正下载 20–30 篇不同相关论文全文，报告综述数量、年份、来源、总大小、PDF 可读性及身份检查；公开出处与实际文件一一对应。
- search 使用真实网络验证，并分开记录匿名/带 key；没有 key 不声称已验收带 key 请求。
- 重点故障：HTML 200、重复 DOI、错文 PDF、私网重定向、缺 key、部分失败、重复执行和字节上限。少量有意义测试即可，禁止以测试夹具冒充外部 API。
- 单独运行搜索/下载，普通 Python 调用可获得同一结果；干净 wheel 检查模块及配置说明可用。
- 采集结果不是 RAG/科学问答验收，也不修改旧 frozen ReportData。

## 已核查的官方依据

- OpenAlex 认证（2026-09-10）：https://help.openalex.org/api/authentication/ ，支持匿名有限查询及环境 key 的 Bearer 请求。
- OpenAlex 全文：https://help.openalex.org/access/fulltext/ 。缓存 content API 可能消耗账户配额；本次优先来源开放链接，不自动开启缓存内容付费路线。
- Unpaywall 字段：https://unpaywall.org/data-format 。保留实际 OA 位置、许可及版本。
- PMC 旧 OA Web Service 自 2026-08-25 停止：https://pmc.ncbi.nlm.nih.gov/tools/oa-service/ 。不得依赖旧 oa.fcgi 下载教程。

## 当前状态

已完成。实现提交 `7a8f0ce` 已独立验收，并以 `143ed6c` 合入本项目。23 篇全文已落盘；通过已安装 wheel 的公开命令重新下载 23/23，哈希全部一致，重跑接收 0 字节。完整证据见 [D17 验收记录](reviews/oa-7a8f0ce.md)。

## 交给其他 AI 的执行提示词

> 请读取本仓库 docs/OA_COLLECTION.md 和 examples/aem_oa_reviews.json。使用 Python 命令行执行开放获取文献的检索和下载，默认不操作浏览器。我的数据源凭据通过 OPENALEX_API_KEY 环境变量提供，请勿打印凭据。
>
> 若要复现已经选定的 AEM 文献库，直接以 examples/aem_oa_manifest.json 执行 download，目标 23 篇。若要检索新主题，先生成查询 JSON 执行 search，保存原始候选与每条查询的状态；根据标题、摘要和必要的出版页面筛选，保留 DOI、开放位置、文章类型和理由。不要只依赖数据库 type:review，不要把搜索数量当作完整论文数量。下载完成后检查 catalog.json 的真实成功数、页数、来源和错误；保留 partial 结果和需要人工判断的项目。
>
> 执行完毕给我本地 PDF 目录、中文阅读索引、BibTeX、成功与失败统计及可复现命令。不得把采集成功描述成 RAG 或科学质量验证通过。

该提示词适用于能运行命令行并访问工作目录的 AI。采集器本身不调用 LLM，因而不绑定模型；这里 OPENALEX_API_KEY 是数据源凭据。若宿主 AI 使用模型 API，其模型、服务地址和模型 key 由宿主单独配置，不与数据源 key 混用。


## 最短复现命令

在仓库根目录、Python 3.11+ 环境中执行。Windows 推荐使用虚拟环境：

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install ".[literature]"
.venv\Scripts\python -m research_harness.literature download --manifest examples/aem_oa_manifest.json --output workspace/aem_papers --limit 23
```

这一步只用清单中的公开 PDF 地址，无需模型 key 或数据源 key。输出目录包含 pdf、catalog.json/csv、references.bib、README.md、download_log.jsonl；以 catalog.json 的 valid_pdf_count 和 outcome 判断结果，不能只看文件数量。重复执行会验证并复用已下载文件。当前自动生成的 README 是简要运行概况；宿主 AI 根据 manifest 中的 topic/selection_reason 组织中文阅读索引，本次成品见 `literature/aem_oa_reviews/README.md`。

如要检索新候选：

```powershell
.venv\Scripts\python -m research_harness.literature search --config examples/aem_oa_reviews.json --output workspace/aem_candidates.json
```

示例以 `anonymous: true` 显式使用匿名访问；使用自己的 OpenAlex key 时，在运行进程环境中配置 `OPENALEX_API_KEY` 并将 JSON 的 anonymous 改为 false。不把 key 写入 JSON 或命令日志。查询配置支持 queries、year_min、title_search、review_only、max_candidates、max_pages_per_query、anonymous。AEM 示例 max_candidates 为 80；达到上限返回 partial 和退出码 4，剩余查询标 not_run。希望继续其它方向时，用单独配置/输出运行该方向的查询并按 DOI 合并候选；分页游标会留在查询状态中，但当前 search 不实现从旧输出恢复 cursor。

宿主 AI 在候选上筛选并生成 `{ "records": [...] }` 清单，再交给 download。每条保留题名、DOI、年份、作者字符串列表、类型、开放位置和选择理由；不把全文阅读结论写成仅凭摘要已证实的事实。使用可靠页面/全文已知页数时可加 expected_min_pages。OpenAlex 的 OA 地点中 pdf_url 可能指向图片或不可达地址，程序会拒绝非 PDF；宿主可从出版社/机构仓储找到公开替代地址，保留实际来源后重试。download 没有搜索引擎或浏览器依赖，不会自行获取付费文献。

`--use-unpaywall` 可选启用补充 OA 定位，另需 `UNPAYWALL_EMAIL`。本次未配置该项。带 key 的 OpenAlex 与 Unpaywall 的真实认证未在本次环境验证；已验证匿名搜索和无 key 的开放地址下载。

本次收藏使用的公开清单固定在仓库中，PDF、候选响应和运行记录存入忽略目录。GitHub 尚未发布。
