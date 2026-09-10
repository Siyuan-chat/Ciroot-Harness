# D17 开放文献采集独立验收

2026-09-10。实现检查点：`7a8f0ce`；当前根目录合入提交：`143ed6c`。结论：本次开放文献采集与可移植 CLI/Python 模块通过局部真实集成验收。D2 既有结果不变，RAG/MCP/模型推理与科学案例评估未在本任务执行。

## 用户可见结果

`literature/aem_oa_reviews/pdf/` 共 23 个完整 PDF，23 个独立 DOI、23 个不同 SHA256，584 页、91,445,721 字节（87.21 MiB）。21 篇综述（含 mini-review）、1 篇 Perspective、1 篇研究论文。英文原文，年份为来源记录的 2017–2026。包含 publication/accepted 版本，来源和许可逐篇记录。中文 README、CSV/JSON、BibTeX 与日志齐备。

已人工检查首页身份与正文末页/参考文献；四份代表性文件进行了首页渲染抽查。发现 Chalmers DOI 10.1080/00219592.2023.2210195 的开放文件仅含仓储封面和浏览器打印的 Page1/44，已排除，单独保留 rejected 证据。PDF 可解析和 DOI 匹配不单独作为全文证明。旧文章年份沿用来源元数据，接受稿与正式刊期可能不同。

## 工程证据

从 `git archive 7a8f0ce` 构建 wheel，SHA256：`970b6a5193d5187af4dc2d19a5d243a8bb2dfb0a59d69ec4f0182f7db680f460`。wheel 含 literature 模块与原有 schema，不含论文 PDF。新 venv 使用 `--system-site-packages` 复用本机依赖，再非 editable 安装本 wheel；实际 import 指向 venv/Lib/site-packages/research_harness/literature.py。此项验证安装包，不声称离线从零安装全部依赖。

- 仓库测试：`python -m unittest discover -s .local/oa_collection/checkpoint/tests -v`，17 passed。
- 独立探针：`.local/oa_collection/probe_d17.py`，11 passed。包括缺凭据、私网拒绝、真实4页mini-review、已知页数不足、真实预览、HTML与流中断后继续、零网络复用、真实哈希、跨DOI相同字节和字节预算停止。
- 真实搜索：安装包 `python -m research_harness.literature search --config examples/aem_oa_reviews.json --output ...`。匿名 OpenAlex 返回80条候选；到候选上限后 exit 4 / partial，其他3条查询 not_run，无网络错误。该搜索并非穷尽检索，也不代表80篇均已完成相关性筛选。
- 真实下载：安装包 `python -m research_harness.literature download --manifest examples/aem_oa_manifest.json --output .local/oa_collection/reproduction --limit 23`，exit 0；completed，23，received_bytes=91445721。23/23 与初次采集的 SHA256 一致。
- 原命令再运行：exit 0；completed，23，received_bytes=0。在默认禁止出网的沙箱中完成，证实有效缓存复用。
- 公共 manifest SHA256：`3e742c3a9093c3deb1ac3ecfe202f506e51f3aa7a614c466d3d648fa13f3a3bc`。

真实网络命令在沙箱外按用户已授权范围执行；默认沙箱最初出现 WinError10013，不能当作产品网络故障。未操控浏览器。未提供真实 OpenAlex key/Unpaywall 邮箱，所以这两项真实认证保留 pending，不妨碍当前公开下载路径交付。

本地复现输出、渲染抽查图、初始响应和故障记录保存在 `.local/oa_collection/` 与 `literature/aem_oa_reviews/`。普通用户复制命令见 [使用说明](../OA_COLLECTION.md)。公开组件不依赖上述个人路径或 Codex 专属工具。
