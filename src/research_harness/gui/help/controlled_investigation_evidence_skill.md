# 技能：受控调查与证据

## 调查

先读取 run.status 和 run.tasks，再用 run.submit 提交符合任务版本的结构化结果。run.advance、run.resume、run.stop 和 run.export 都需要受控动作和幂等键。

## 证据

用 evidence.read 和 report.read 查看已绑定运行的结果。partial、evidence_gap、NOT_FOUND 与未知用量必须保留，不能把帮助或模型文字当作研究证据。
