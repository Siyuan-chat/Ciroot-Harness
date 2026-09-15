# P2 OpenAlex 单源采集：有界分页与调用者续跑

本文件仅说明 D19 P2 的独立 `research_harness.literature` OpenAlex collector。它不接入 `rh investigate`、MCP、调查模型任务、D19 runtime schema 或报告；因此不构成 A06 或 P3 调查闭环的通过声明。

## 有界搜索配置

`search` 的既有必填项是 `queries`、`year_min`、`max_candidates` 和 `max_pages_per_query`。P2 可增加：

```json
{
  "queries": ["piperidinium anion exchange membrane"],
  "year_min": 2024,
  "max_candidates": 10,
  "max_pages_per_query": 2,
  "page_size": 5,
  "sort": "relevance_score:desc",
  "anonymous": true
}
```

`page_size` 必须是 1--100 的整数，且不接受布尔值。若省略，原有行为保持不变：每次最多请求 100 条或本次剩余候选数。`sort` 缺省为 `cited_by_count:desc`，只允许 OpenAlex 的 `cited_by_count:desc`、`publication_date:desc` 或（本 collector 总有 search query 时可用的）`relevance_score:desc`。

输出的每个 query 都有 `pages`、`start_cursor` 和 `next_cursor`。服务端没有后继 cursor 时，`next_cursor` 为 `null`；若候选数或页面上限先耗尽且服务端仍给出后继 cursor，状态为 `partial` 且保留该真实 cursor。

若一次请求以网络/服务端失败结束，返回的 `next_cursor` 是本次未确认完成的请求 cursor（初始页时为 `"*"`），仅可用于重试同一页；它不是已确认的后继页。

## 显式分段续跑

调用者可保存一次输出的 `next_cursor`，并在**相同 query、year/filter、sort 和范围**下传回：

```json
{
  "queries": ["piperidinium anion exchange membrane"],
  "year_min": 2024,
  "max_candidates": 10,
  "max_pages_per_query": 2,
  "page_size": 5,
  "sort": "relevance_score:desc",
  "start_cursors": {
    "piperidinium anion exchange membrane": "saved-next-cursor"
  },
  "anonymous": true
}
```

`start_cursors` 只能引用本次 `queries` 中的 query，值必须为非空字符串。它是调用者管理的分段入口：collector 不保存此前 records、不合并分段结果、不建立中央预算，也不能在请求结果未知时断言该页未执行。任何 query、filter、sort 或来源范围变更后不得复用旧 cursor。

认证错误只输出稳定错误 code/泛化信息；不得记录 API key、Authorization header、token 或含 token 的 URL query。P2 真实运行记录保存 query、非敏感来源 ID、页数、cursor、限制、耗时和 partial 原因。
