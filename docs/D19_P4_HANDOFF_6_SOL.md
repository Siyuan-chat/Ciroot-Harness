# P4 → 新对话 6-sol 开发交接

日期：2026-09-24。工作区：`C:/Users/Siyuan_ye/Documents/ChatGPT/AEM`。

## 目标与授权

用户已明确批准 D19_P4_INTEGRATION_READY.md 的开发计划和预算，并要求迁移到另一个对话使用 6-sol 开发。新对话直接执行本阶段实现、自测、必要修正与验收准备，无须再次询问是否启动。当前对话在交接处停止，未启动代理、后台调查或自动任务。

目标：EPO OPS 正常服务接入；一个相关专利族、最多两份独立公开文本；与 P3 冻结论文证据对照，生成中文技术调查报告和主题综述，同时交付可复制检索式和可追溯执行历史。

此次用户指定 6-sol 为新对话开发者，取代旧计划中 Terra 核心实现的人员安排。新对话先由 6-sol 单写实现和自测，不因历史 Terra/Luna 分工自动创建代理或改模型。科学角色执行保留真实任务/答案记录；独立验收由另一审阅者/后续设计对话针对固定候选执行，6-sol 自测不标为独立验收。需要额外开发代理时再按用户授权安排。

批准的累计上限（不是每批重置）：

| 项目 | 总上限 |
|---|---|
| OPS HTTP 尝试 | 20，包括认证、失败、分页、重试；两请求探针占用同一总账 |
| 接收数据 | 20 MiB 累计、单响应 5 MiB |
| 研究服务角色任务 | 10 |
| 宿主研究答案生成及修订 | 14，包含上述任务答案，不是额外 14 |
| 查询/候选 | 至多三个查询版本，每式两页，每页五条，最多保留二十个唯一公开候选 |
| 正文 | 一个族，最多两公开文本，首轮 XML，不下载 PDF |

认证2、主题检索6、族/书目/可用性6、章节获取4、额外重试2的分项见 P4_PLAN。开发/测试模型用量与研究角色总账分开，不声称上述额度包含全部开发 token。预算耗尽保存 partial；不换 run 清零、不重开替代运行。GUI、监测、三语全评价、法律结论、新来源真实运行和 GitHub 推送不在此次执行范围。

## 权威输入与有效检查

1. 当前 AGENTS.md（含用户最新替换内容）：一般工作纪律；本交接和用户明确要求优先于历史阶段/人员安排。
2. `docs/D19_P4_TASKS_6_SOL.md`：直接执行的任务清单。
3. `docs/D19_P4_INTEGRATION_READY.md`：接入合同、四批执行顺序；`docs/D19_P4_PLAN.md`：详细检索、预算和交付口径。
4. `docs/PRD.md`、`ARCHITECTURE.md`、`CONTRACTS.md`、`ACCEPTANCE.md`：开工前读取，保留旧阶段与本阶段边界。
5. `docs/D19_P3_LOOP2_ACCEPTANCE.md`：P3 最终有效验收；确有恢复缺口时读 `D19_P3_HANDOFF_TO_P4.md`，不用重放全部历史。
6. `docs/D19_P4_FALLBACK.md`：备用设计，不自动切换来源。

P3 有界论文案例已通过：正常服务、Docling/发现库、论文双正文、导出/重开；覆盖 partial。不得重跑 P3 或重建原库。上次同步提交为 `5a89898834adaa29b13d3234f7715ecd853c8e78`，私人仓库 `Siyuan-chat/autoSearch-Harness` master。当时34项相关检查通过，干净副本相对路径契约3项通过（后者属于前者的复核，不相加）；当时无CI。以上不证明尚未实现的 EPO 接线。

## 凭据与执行环境

- EPO 批准邮件已读取，账号获批；API 认证尚未执行。OPS 真实请求累计为0，P4研究角色生成累计为0。
- 密文：`.local/credentials/epo/epo-credentials.dpapi`。内容是 UTF-8 JSON 加密字节，字段为 EPO_CONSUMER_KEY、EPO_CONSUMER_SECRET；Windows DPAPI `CurrentUser`，optional entropy 为 null。
- 加密后在当前执行环境回读逐字节一致，明文 TXT 已删除。密文目录被 `.local/` Git 规则忽略且未跟踪。不读取/输出秘密到对话、日志、参数、持久配置，不创建解密 key 文件。
- **实际联网进程的 Windows 身份可能不同。** 在真正执行身份内先离线解密验证；不成功则停止该路径并诊断身份/权限，不能把密钥导出为明文绕过。必要时由用户在目标身份下重新保存/加密。原有沙箱内成功不证明沙箱外可解密。
- 启动层将凭据只注入目标子进程环境；通用 Python 包继续读取命名环境变量，不依赖 Windows DPAPI。
- 调查 Python：`.local/d19-p2/venv/Scripts/python.exe`，默认 site-packages 可能是旧版。构建新 wheel 并隔离安装，在真实执行进程记录一次模块路径；不要依赖当前目录碰巧导入源码。
- P3 有效安装物：`.local/d19-p3-loop/engineering/target-host-review`；不要覆写。Docling Python：`.local/d19-p3/parser/Scripts/python.exe`；RAG Python：`.local/d19-p2/rag-restored/venv/Scripts/python.exe`。
- 原库：`.local/rag-acceptance/real-v3/workspace/rag.sqlite`，冻结23文档/23版本/8820证据；只读。
- P3 最终工作区：`.local/d19-p3-loop2-replacement/investigation-workspace`，run `inv-b7b6c9cbba4e`；对应 discovery-workspace 为同级目录。

## 未解问题与下一步

现有 providers.py 有 EPO 搜索草稿，但 runtime/查询/schema/live分发仍绑定 OpenAlex，专利族/正文和公共 attach 尚未接通。不能只加来源枚举；attach 当前含 OpenAlex DOI/下载身份绑定，必须有真实专利版本映射。

下一步从任务清单 T1 开始：固定实现前基线，完成离线接线和预算/身份测试，再由实际联网身份进行一次认证和一次首页面检索，复用这次成功结果继续同一预算下的单族闭环。

当前存在未提交的接入准备文档及本次交接修改，保留并继续使用；本次不自动提交/推送。本地 `.local` 数据不随 Git 迁移，新对话若仍在此机器/工作区可复用；跨机器不能假定 DPAPI 密文或运行库可用。

## 可直接复制的新对话任务

> 使用我在新对话实际选择的 6-sol，在 C:/Users/Siyuan_ye/Documents/ChatGPT/AEM 继续开发。先读 docs/D19_P4_HANDOFF_6_SOL.md 和 docs/D19_P4_TASKS_6_SOL.md。本阶段计划和预算已批准：单专利族、最多两公开文本、中文双出口、可查检索式与执行历史，20次OPS HTTP/20MiB/10服务任务/14宿主研究答案总上限。由你单写产品实现和自测，遵守文件/凭据边界，不默认派代理。按检查点推进、修正并交固定候选与独立验收入口，不重复请求启动授权，不重跑P3、不自动推送GitHub。先离线实现，再验证实际联网身份DPAPI解密与模块路径，之后按同一预算账本开展真实小样。自测、真实运行和独立验收分开报告。
