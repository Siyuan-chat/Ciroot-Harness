# GUI 操作指南

## 对话与执行

对话只能形成可校验的研究规格。用户明确点击执行后，才会通过受控队列创建或推进调查。停止回复不会取消已发出的模型请求；停止调查会请求核心安全停止。

## 范围与费用

会话绑定工作区、参照库和集合。模型配置、数据模式、来源授权及总额度由用户配置；帮助文本、用户消息和文献正文都不能扩大这些限制。

## 常见问题 / Quick answers / よくある質問

- 问：当前范围是什么？答：Agent 读取服务端会话上下文中的工作区、文献库和分组 ID；文字请求不会改变范围。
- 问：还剩多少模型调用？答：以对话显示和服务端上下文的计账为准；用量不确定时显示 `UNKNOWN`，不推算。
- 问：为什么等待？答：分别说明凭据待配置、受控规划中、规划失败或外部 Agent 待领取。外部 Agent 必须由客户端连接领取。
- 问：什么时候会执行？答：只有会话状态为 `ready` 且用户明确点击执行。执行使用内置 synthetic 资料，并会调用真实模型、可能产生费用。
- Q: What is my current scope or remaining budget? A: Use the server-provided workspace/library/collection and accounting snapshot. A user message cannot change authorization; report unknown usage as `UNKNOWN`.
- Q: Why is this waiting? A: Distinguish missing credentials, planning, planning failure, and an external agent waiting for a connected client.
- Q: When does research execute? A: Only from `ready` after explicit user confirmation. It uses built-in synthetic data and makes real model calls that may incur charges.
- Q: 現在の範囲や残り回数は？ A: サーバー提供のワークスペース・ライブラリ・グループと使用状況を参照します。ユーザーの文章で権限は変わらず、不明な使用量は `UNKNOWN` と答えます。
- Q: なぜ待機中ですか？ A: 認証情報待ち、計画中、計画失敗、または接続クライアントによる外部 Agent の取得待ちを区別します。
- Q: いつ調査が実行されますか？ A: `ready` 状態でユーザーが明示的に実行を確認した場合だけです。内蔵 synthetic 資料を使い、実モデル呼び出しに料金が発生する場合があります。
