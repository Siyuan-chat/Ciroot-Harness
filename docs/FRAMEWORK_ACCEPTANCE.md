# D2 框架独立验收

日期：2026-09-09。结论：**ACCEPTANCE K01–K07 通过，本轮框架开发结束。** 已验收实现已合并到项目主工作区。设计任务负责计划、根因诊断和独立验收；Terra 负责明确编码及简单自测。

本结论只覆盖离线合成 fixture 框架。真实论文／专利 API、生产 RAG、复杂解析、独立自然语言聊天、GUI、科学案例和 GitHub 发布尚未完成。未来接入仍按“大模型 API + 数据源 API”的配置方向推进；现阶段不是填入任意 API Key 即可进行真实调查的成品。

## 验收范围与证据

| 门槛 | 已观察结果 | 独立记录 |
|---|---|---|
| K01 安装与演示 | Windows 新虚拟环境从 wheel 安装；包内 schema、JSON 夹具和基准文本可用；文档 CLI 流程实际完成；三语指南与能力一致 | 本报告下方安装验收；`acceptance/probe_d2_installed.py`，15 项通过 |
| K02 JSON 与冻结版本 | 手改字段保留、版本正确递增／复用，旧输入、基准、报告保持不变 | [c7f435a](reviews/c7f435a.md)，13 项通过 |
| K03 真实 fixture 主流程 | 实际 LangGraph 与本地存储工作；输入／基准影响判断；候选原文和双方证据持久化；错误引用降级并进入清单 | [b60b439](reviews/b60b439.md)、[43d86a5](reviews/43d86a5.md)，各 7 项通过 |
| K04 可替换边界 | 来源与模型注入函数实际被调用；接收普通结构化数据及本轮证据，不需修改核心代码 | [b60b439](reviews/b60b439.md)、[c7f435a](reviews/c7f435a.md) |
| K05 代表性失败与人工决定 | 候选预算边界、来源失败明确返回 partial/failed；可用事实保存；人工决定可重开读取；输入和异常不泄漏原始秘密值 | [ab53e19](reviews/ab53e19.md)、[98a51c4](reviews/98a51c4.md)、[7094cd1](reviews/7094cd1.md) |
| K06 中英日报告 | 共用事实、原文、ID 和引用；每语种 HTML/Markdown，加 JSON/CSV；候选、理由、引用及人工问题可见；合成数据明示、安全转义 | [b2c0548](reviews/b2c0548.md)，45 项通过；日文 HTML 已经 Edge 渲染并查看 |
| K07 未来 GUI 应用边界 | 公共服务提供配置、导入、执行、状态、结果、产物、人工决定、清理与真实阶段事件；类型错误可序列化；客户端无需读数据库或解析终端 | [471a60a](reviews/471a60a.md)、[98a51c4](reviews/98a51c4.md)、[7094cd1](reviews/7094cd1.md)，分别 13/12/7 项通过 |

旧证据对应的代码行为未被后续包装／文档改动改变，按既定范围复用，没有重复全量 D1 测试。各记录中的“尚未完成”是当时状态，本报告为 D2 最终结论。未启用路径的旧 F10–F14 保持 deferred，不改称已修复。

## 最终安装验收

验收产品代码提交：`2a8cf5de789a6c53bcc931fda32c8bc179502ddf`；随后 `3d30820` 仅同步 D2 文档与实施记录。安装包为 `research_harness-0.1.0-py3-none-any.whl`。最终合并不改变这些产品源码和包配置。

环境：Windows、Python 3.12.14，新建虚拟环境且 `include-system-site-packages=false`。实际安装 LangGraph 1.2.11、jsonschema 4.26.0、requests 2.34.2；`pip check` 报告无损坏依赖。未安装 full extras。Linux/macOS 尚无独立运行验收。

由于受控执行环境的联网账户不能读取沙箱新建 wheel，而沙箱账户不能联网，依赖先下载为 wheel 缓存，再由沙箱账户离线安装到项目内新虚拟环境。没有改全局权限、系统 Python 或用户 Python。验证的是完整新环境安装；普通用户网络环境下的直接 `pip install .` 未在此次受控环境单独复现。

核心复现步骤（已有项目 wheel 和依赖缓存时）：

```powershell
python -m venv .local/acceptance/wheel-env
.local/acceptance/wheel-env/Scripts/python -m pip install --no-index --find-links .local/acceptance/dependency-wheels path/to/research_harness-0.1.0-py3-none-any.whl
.local/acceptance/wheel-env/Scripts/python -m pip check
.local/acceptance/wheel-env/Scripts/python acceptance/probe_d2_installed.py --output .local/acceptance/fresh-installed-check
```

最后一条应使用新的输出目录。验收脚本不插入源码导入路径，断言模块来自该虚拟环境 site-packages。它实际调用安装生成的 `rh.exe`，验证默认演示完成、两个 finding／一个人工问题、八个真实导出文件、状态、人工决定持久化、冻结报告再导出、JSON 验证、自定义候选预算 partial、草稿拒绝和 chat 的 RH_UNSUPPORTED。另在同一安装包上阻断 socket 连接运行默认 demo，观察到零连接尝试。共 15 项全部为 true，退出码 0。

本地可复查材料位于被忽略的 `.local/acceptance/2a8cf5d/`：源码归档、wheel、install.log、installed/installed-result.json、运行库和报告。这些材料全部是合成测试资料，不是可用于科学判断的文献案例。

## 交付边界

GUI 后续直接复用 `Harness` 公共服务、结构化结果／错误及进度回调；本轮没有实现界面、HTTP 或后台任务平台。产品调查仍由用户手动发起。框架达标后停止 Terra 编码并暂停验收 heartbeat，不继续自动接入真实服务或增加功能。

下一阶段由用户确定聚合物设计案例的具体资料和判断目标后再启动：真实 API／文献库集成、科学验收、可再分发 demo，最后发布 GitHub。
