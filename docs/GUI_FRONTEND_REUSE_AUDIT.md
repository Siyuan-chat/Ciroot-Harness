# Zotero Web Library 前端复用审计（A 阶段）

日期：2026-09-24。结论：**暂不放行直接复制上游组件进入 `frontend/`**。上游界面和构建结构有可借鉴部分，但 Web Library 的整体许可是 AGPL-3.0，数据流依赖 Zotero API；目前未取得本地完整源码与固定 commit，不能完成组件级依赖和子模块许可核查。B 阶段若继续复用源码，须先固定上游版本并确认本项目能履行相应许可义务。

## 获取与版本状态

- 官方仓库：[zotero/web-library](https://github.com/zotero/web-library)。README 将其定义为经 Zotero API/CORS 访问数据的 JavaScript 单页应用，私有库需 `userId`、`apiKey`；配置来自 `zotero-web-library-config` DOM 节点。默认构建有 `zotero` 与实验性的 `embedded` 目标。
- 在线读取了仓库目录、README、`COPYING`、`package.json`、`.gitmodules`。在线 `master` 的 `package.json` 显示版本 `1.8.2`，这是包版本，**不是 commit 固定值**。
- 本机 `git ls-remote https://github.com/zotero/web-library.git refs/heads/master` 失败：`git: 'remote-https' is not a git command`；PowerShell 直连 `api.github.com:443` 被沙箱套接字权限拒绝；网页 API/commit 入口亦不可用。因此未克隆上游、未取得 SHA、未运行上游构建。后续不能把网页 `master` 视为固定快照。

## 可复用性矩阵

下表的路径已从官方在线目录或构建清单核对；因尚未读取完整组件源码，依赖与改造量是**待验证判断**，不能当作完成的拆分方案。

| 区域 | 已确认上游位置 | 已知依赖/耦合 | 建议 |
| --- | --- | --- | --- |
| 集合树与分栏 | `src/js/component/library.jsx`、`libraries/`、`src/js/component/libraries.jsx` | 仓库整体以 Zotero library 身份和 API 配置运行；组件内部调用待查 | 借鉴布局；源码复制待固定 SHA 后做 import/Redux 追踪 |
| 列表、筛选、选择 | `src/js/component/item/`、`src/js/component/search.jsx`、`main-search.jsx` | `package.json` 引入 Redux、react-window、react-dnd、zotero-api-client；文件级实际依赖待查 | 优先验证虚拟列表和选择逻辑能否独立抽取；数据层按本项目 API 重接 |
| 详情、字段、标签 | `src/js/component/item-details/`、`tag-selector/` | Zotero item schema 与字段/标签语义可能深入组件；需逐文件核查 | 不直接映射科学证据字段；只评估可保留的展示交互 |
| 阅读器 | `src/js/component/reader.jsx`、`modules/reader` | reader 是独立 Git submodule，构建脚本另处理静态 reader 与 pdf-worker | 单独评估许可、启动参数和 PDF 定位；XML claim/段落阅读需项目实现 |
| 入口及构建 | `src/js/init.jsx`、`main.js`、`src/html/index.html`、`scripts/build.mjs`、`rollup.config.js` | `npm run build` 先执行模块、字体、locale、style、citeproc 等准备；需递归子模块 | 如走源码复用，保留 Rollup 链并先在隔离副本验证 Windows 构建 |
| 账号、同步、云端 | `src/js/component/zotero-streaming-client.js`，以及待查 `actions/`、`reducers/` | README 明确使用 Zotero API；`package.json` 依赖 `zotero-api-client` | 排除；本项目运行、人工清单和预算以本地服务为唯一真值 |

## 构建与许可证

官方 `package.json` 的运行依赖包含 React 19、Redux、`zotero-api-client` 等，构建使用 Rollup、Babel、Sass、PostCSS；脚本会拉取或构建模块，并生成静态资源。`.gitmodules` 列出 `reader`、`pdf-worker`、`note-editor`、`web-common`、`zotero-schema` 和 CSL `locales`。因此简单复制 `src/js/component` 或只修改 API base URL 均不能视为已验证可运行。

仓库 [`COPYING`](https://raw.githubusercontent.com/zotero/web-library/master/COPYING) 明确 Web Library 源码使用 **GNU AGPLv3**，`package.json` 也标 `AGPL-3.0`；Zotero 名称是注册商标，第三方版权需另查。若复制或改造覆盖源码，分发及提供网络交互时的对应源码、修改标识和法律通知义务需要具体落实；不能仅将文件头保留即宣称许可兼容。各 Git submodule 与 npm 依赖的许可证尚未逐一核对，不能归并为 AGPLv3。此处是工程风险识别，最终发布方案需逐项许可复核。

## A→B 建议与阻断

1. 先解决上游可获取性，在**项目忽略目录或独立临时目录**执行递归克隆，记录 `git rev-parse HEAD`、submodule SHA、`npm ci` 与 `npm run build` 结果；不得把未固定的网页 `master` 复制进产品。
2. 对矩阵所列的具体组件做 import 图和 API/Redux 依赖追踪，形成确切保留/改造/排除清单；验证阅读器许可和 PDF 页码定位输入。没有此证据，不承诺源码可低成本抽取。
3. Sol 先决定 AGPLv3 义务是否符合项目未来分发/部署方式。若不符合，按 GUI 方案规定提交替代前端底座依据；可借鉴交互设计，但不能复制 AGPL 源码。
4. 合同冻结前，前端不调用 Zotero API，不把 `apiKey` 放进浏览器配置，也不自行定义运行/证据业务状态。

本 A 阶段仅写入此审计，没有改动产品代码或既有未提交工作。
