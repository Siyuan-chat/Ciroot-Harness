# 专利来源规范与激活记录

2026-10-05，S4 实施前规范核对。此表记录规范，不能作为连接器实现或真实调用完成证明。公开文档下载不占用研究运行的历史额度；真实研究需新运行的明确数值预算。

| 来源 | 已定位官方规范 | 首版能力与限制 | 当前状态 |
| --- | --- | --- | --- |
| JPO | [官方参考](https://ip-data.jpo.go.jp/api_guide/api_reference.html) 的 `api_reference.js` 内 OpenAPI | 20 条专利路径：号码、进展、引用、登记、可取审查文件；OPD 独立服务器和权限；不宣称关键词搜索 | 连接器离线合同已独立通过；核心服务／CLI 已整合；凭据与真实激活待完成 |
| EPO | 既有 OPS；[Publication Server](https://data.epo.org/publication-server/rest/v1.2) REST v1.2、[Linked Open EP Data API](https://data.epo.org/linked-data/documentation/api-reference) | Publication Server 按公开日期/号码获取 XML、HTML、PDF、ZIP；Linked Data 提供出版物、申请、CPC/IPC，遵守轻量访问约束；独立法律事件接口尚未确证，标待规范 | OPS 旧候选原文回查完成；补充连接器离线合同已独立通过，核心服务／CLI 已整合；真实调用待激活 |
| USPTO ODP | [官方 Swagger](https://data.uspto.gov/swagger/swagger.yaml) 与 `odp-common-base.yaml`，[专利 schema](https://data.uspto.gov/documents/documents/patent-data-schema.json) | GET/POST 搜索、申请元数据、关联/交易与文件列表；`X-API-KEY`；正文需要实际文件获取和解析；搜索 count 总量语义未确证，保守记录覆盖 | 离线合同已独立通过，9 类官方文档响应样例本地回读通过；核心服务／CLI 已整合；真实激活待完成 |
| KIPRIS Plus | [官方检索说明](https://plus.kipris.or.kr/portal/popup/DBII_000000000000001/SC002/ADI_0000000000002944/apiDescriptionSearch.do) | 专利/实用新型检索；官方示例 HTTP，须确认 HTTPS 能力后才送凭据 | 诊断和参数契约通过离线检查；pending_secure_transport，零发送 |
| TIPO | [官方 OPD API PDF](https://www.tipo.gov.tw/wSite/public/Attachment/0/f1745825024395.pdf) | Basic 换 token，Bearer 读案件、关联案件、文件列表和可取文件；实际 `getReationCase` 拼写遵从规范 | 连接器通过离线契约；缺认证响应及 expiry 规范，默认 pending_spec、零发送；核心服务／CLI 已整合 |
| GPSS | [官方 API 简介](https://www.tipo.gov.tw/wSite/public/Attachment/007/f1744687672229.pdf) | 搜索式服务，具体请求/响应规范尚未取得 | pending_spec 诊断已实现并通过零发送测试；不能生成假接口 |
| WIPO Pearl | [官方平台迁移公告](https://www.wipo.int/en/web/wipo-pearl/w/news/2026/wipo-pearl-api-for-terminology-now-available-in-a-new-platform)，2026-09-04 迁移到 WIPO B2B | 术语、多语言对应词、记录查询；概念图和 PATENTSCOPE 搜索不作为 Pearl API 能力 | 当前业务请求规范与订阅权限待取得；门户前端的开发默认地址不能充当 Pearl API |

公开规范及来源抓取时间保存在忽略目录 `.local/integration-20261005/specs/`。实现时应记录规范哈希、契约测试和激活状态；账号权限未知时不发送项目材料试用，也不自动注册或购买服务。

第一批连接器独立运行 12 项离线合同测试通过，采用合成注入 HTTP；没有新真实来源查询。安装 wheel 内包含源码包模块。预算拒绝、无凭据、权限不足、限额、缺正文与身份不符分别可见；这项验收不能代替实际账号权限、正文解析或调查编排验收。

第一、二批联合独立检查 21 项通过。另将 USPTO 官方文档中的申请、期限调整、转让、代理人、关联、优先权、交易、文件列表和公开/授权文件元数据 9 类样例注入适配器回读，均识别正确；documents 样例 3 条按实际列表计数，不生成不存在的分页游标。官方文档样例回放属于离线规范核查，仍不是真实服务调用。

三批联合独立检查 32 项通过；最终组件 wheel 的 10 个来源模块与源码哈希一致。TIPO 单项操作认证与数据请求分别占用预算，认证记录脱敏且 token 不跨操作复用。文件 URL 在认证前检查路径穿越、编码分隔符和来源边界；失败不发送认证。来源已接入核心服务和显式 CLI；返回原件保持待解析，不自动成为正式证据。真实来源调查仍待激活。

核心来源网关修正版与关联组独立 103 项通过，仍使用合成注入运输。实际请求前按事务重新检查运行、任务版本、租约、权限和额度；停止运行后的独立竞态复现确认零派发、零预算占用。请求收据与响应原件分别留存，返回原件保持待解析，不自动创建正式证据。调查服务/runtime 完整入口与旧来源边界已另经独立关联检查，见下项。

后续任务租约与收据修正的关联组独立 80 项通过：旧已完成任务的 accepted 引擎租约不阻塞新任务；当前任务版本的 accepted 租约以及运行级未知调用继续阻断。实际请求准备收据标为 recorded_before_dispatch。这仍是网关组件验收，完整服务入口另记。

最终服务整合关联组独立 134 项通过，随后 CLI 文件输入、服务及部署/引擎关联组 51 项通过。新运行来源额度默认 0，启用来源要求明确字节限额。OPS/OpenAlex 的每次认证、查询、元数据和下载经过共享收据及预算；未知请求重开后保留占用且不重发，认证 secret/token 不落入账本或原件。显式用户入口为 patent-source-execute，当前 GUI／HTTP 没有来源执行按钮。
