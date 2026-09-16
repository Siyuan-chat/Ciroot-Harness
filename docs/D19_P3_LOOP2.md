# D19-P3 第二轮真实闭环

最终结果：用户批准的替代运行已完成有界科学与标准导出验收。交付入口及证据边界见 [验收报告](D19_P3_LOOP2_ACCEPTANCE.md)；下文保留执行和根因记录。

2026-09-16。用户明确同意使用修复后的安装包，再执行一次与上一轮预算相同的真实闭环。

## 范围与交付

研究问题、验收标准与排除项沿用 `D19_P3_LOOP.md`。交付中文技术调查报告、主题综述、标准导出及 Astra 独立验收。使用 `.local/d19-p3-loop/engineering/target-fixed`，本轮运行材料单独保存在 `.local/d19-p3-loop2/`。原库及上一轮失败结果保留。

预算不变：OpenAlex 一个逻辑查询、2020 年起、最多两页各五条候选；来源 HTTP 8 次；一次下载尝试，下载 HTTP 12 次、10 MiB；正常服务 7 个角色任务，宿主生成及修订共最多 12 次。新预算仅用于本次获准案例，不允许失败后自行再建运行。

Luna 负责脚本后台执行、实际角色生成和自检；Astra 负责指令、根因与验收；需要产品修复时明确交 Terra。复用已通过的安装检查，不重跑无关测试。继续使用 software-validation-loop 按实际用户边界验收。

## 提交前检查点

1. acquisition 与公共 attach 后，检查持久化 analysis payload：原库 baseline 与发现库证据都属于正式 evidence。记录实际模块路径，避免仅凭启动脚本推断执行身份。
2. synthesis 与 writing 提交前，Astra 集中核查证据支持、化学键、测试条件、跨文献比较和 Markdown 换行/表格；在宿主修订预算内修正，已完成任务不覆写。
3. 标准导出并重开复验；科学通过与覆盖 partial 分开报告。相同论文再次命中时明确是已知案例，不声称陌生文献泛化。

## 当前状态

本轮 `inv-5f669903cdbe` 在第一次检索阶段结束为 partial，未到分析证据检查点。实际来源请求 3/8，角色任务 1/7，候选与下载均为零。没有生成科学报告。

## Astra 根因复核

两处执行要求未落实：复制脚本时把安装路径写成不存在的 `loop2/engineering/target-fixed`；联网推进没有按指定方式申请沙箱外执行。`prompt-snapshot.json` 确实包含旧版说明，证明没有加载当前 fixed 资源。历史进程未保存实际模块路径，不能确定回落到哪一个包。

实际持久化错误只有三次 `RH_SOURCE_NETWORK_ERROR`，没有底层 traceback 或 WinError。Luna 的 `failure-summary.json` 将其归为权限问题过于确定；Astra 将该归因限定为推断，不能排除其他网络层原因。失败记录保留，不覆盖。

Terra 只读确认：公开 resume 只是 advance，并不把 completed/partial 恢复为 source；没有公开重开接口。本轮不能在原 run 内合法继续，未调用可能错误推进的 resume，也未改数据库。

已授权范围内完成脚本路径修正，独立进程预检实际加载 `loop/engineering/target-fixed/research_harness/investigation.py`，见 `.local/d19-p3-loop2/module-path-precheck2.json`。补充每个实际执行脚本的模块路径核对与输出，避免预检和正式进程不一致。未重建产品、未新增网络、未创建替代 run。

## 最小恢复授权（用户已批准）

保留失败 run，允许新建一个替代 run，使用相同问题与查询，新的来源请求上限为剩余 5 次，两次运行累计最多 8 次；下载仍累计最多 1 次尝试、12 次 HTTP、10 MiB。替代 run 需完整 7 个服务角色，因此累计服务任务上限从 7 增至 8（仅多一个 planning）；宿主生成及修订仍累计最多 12 次。分析与正文提交前检查点不变。

用户已明确“允许”。这是对“一次真实案例、不得自动重开”的有限例外。产品新增重开/修订 API 不在此次恢复范围中。

替代运行材料使用 `.local/d19-p3-loop2-replacement/`；安装路径保持指向既有 `loop/engineering/target-fixed`，不随运行目录改变。Luna 先准备并自检脚本，Astra 核对路径及预算后实际启动；联网步骤由 Astra 使用明确的沙箱外工具请求执行。此阶段仍由 Luna 生成科学角色结果并自检。

### 替代运行部署诊断

已创建 `inv-b7b6c9cbba4e`，尚未提交 planning 时，实际联网执行身份的模块断言捕获了回落旧包；此拦截没有发出网络请求。只读检查确认 `target-fixed/research_harness` 子目录禁用 ACL 继承，仅许可 Administrators、SYSTEM 和 OWNER RIGHTS，所有者为沙箱离线主体；因此沙箱内导入通过不代表沙箱外可读。既有修复版 wheel 在沙箱外可读。

部署修复采用从同一 wheel 离线安装到 `loop/engineering/target-host`，由实际执行身份验证模块加载；不修改系统 ACL，不重新构建产品。运行目录、既有 run 和冻结输入保持不变。此前历史进程未记录模块来源，不能仅凭本次 ACL 证据精确还原每一次旧运行。

### 替代运行实际进展

同一 run 已在真实联网执行身份下成功完成两页 OpenAlex 检索和首选全文获取：来源请求 2 次，与失败运行合计 5/8；下载 1 次尝试、11/12 次 HTTP、7,818,339 字节。再次选择 DOI `10.1039/d0ee01133a`，属于已知文献上的流程验收。

公共 attach 前的实际 analysis payload 含 40 条证据，6/6 baseline 均已进入正式 evidence；Astra 对原库身份、正文与原 locator 的核对也通过。检查保存在 replacement 的 `astra/pre-attach-check.json` 与 `astra/baseline-check.json`。后续仍须发现库接入与科学报告验收。

发现库完成独立 Docling 解析 34 页、导入 585 条证据。公共 attach 后分析事实为 48 条，含原有 6 条 baseline 与 8 条新 RAG 命中；Astra 逐条核对发现库正文/身份/locator，见 `astra/attach-check.json`。解析复用已下载 PDF 与模型资源，本轮重新解析，不宣称复用解析缓存。

综合候选包含 12 条主张，实际使用 3 篇本地文献与 1 篇新全文。Astra 一次集中反馈要求引句覆盖复合主张并正式列明条件；修订后 12/12 身份与连续引句检查通过，科学语义核对通过，允许提交 synthesis。原 PDF 物理第 12 页的 ≤4 M/80°C、8 M/120°C、5% RH/100°C 三组条件已用页面图像独立确认，原始失真提取文本保留。该阶段记录不替代最终正文验收。
