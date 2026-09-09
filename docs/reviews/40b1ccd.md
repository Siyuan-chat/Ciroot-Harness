# D2 / 40b1ccd 公开应用接口验收

日期：2026-09-09。提交：`40b1ccdef00804b4ee102f1cfb7bec8046da6fbe`。

在不可变归档运行独立 `probe_d2_services.py`，仅使用公开 Harness 方法，不访问 Store/SQLite/CLI；13 项中 11 项通过，退出 1。实际完成导入、保存、运行、结果/产物查询、一次人工决定、close/重新打开，所有返回值可 json.dumps，服务没有 stdout 依赖。

get_result 的冻结事实、产物路径/语言、人工当前状态及冻结状态区分均通过。实现的 get_artifacts 返回 `{report,files}` 而非裸list，与 get_result 一致且满足 GUI 需要；接受该常规结构选择，CONTRACTS 已同步，避免无收益返工。

两项失败源于同一缺口：status 摘要漏 error/limits/artifacts，失败运行无法直接提供安全错误。复用 get_result 的这些字段投影即可，无需新状态逻辑。

## 后续 K07 错误边界

已知根因：HarnessError 没有 to_dict，部分公开方法直接抛 KeyError/OSError；run_fixture 在读取和验证 fixture 前创建run，坏输入可能留下running。先补既定安全错误表示及输入预检；非法spec/fixture必须在run创建前拒绝。缺资源和报告导出错误接着使用同一类边界。保留现有 source_failed 结果，不扩大重试/恢复或真实API场景。

K06 已关闭，其它未受影响的有效证据复用。当前仍未满足全部 K07 和 K01 停止条件。
