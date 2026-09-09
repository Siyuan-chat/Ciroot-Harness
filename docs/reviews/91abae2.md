# D2 / 91abae2 三语报告复验

日期：2026-09-09。不可变归档 `.local/acceptance/91abae2/source`，机器证据 `report-probes.json`，实际产物 `report-view/`。

相比上一轮已修复：rationale、run/status、三语基础表头、Markdown 单元格转义；HTML 已使用表格并对外部值转义。原独立报告探针显示每语 8 项通过、2 项失败，退出 1。

剩余根因是两个格式分别拼接时遗漏字段：

- HTML evidence 只遍历 candidates，不遍历 reference_evidence；参照引用/locator 丢失。
- HTML body 未输出 sources、limits、error 和 synthetic 说明，Markdown 有。部分完成报告缺预算原因，HTML 未明确合成演示身份。
- Markdown 表删掉了 verification 列；HTML issues 只显示 ID/note，没有 status/machine_disposition/human_decision。补充现有探针的 synthetic/verification 检查以防这类不对称遗漏。
- 状态枚举仍仅英文 code；按已定基本本地化要求补显示标签，原 code 保留在括号或结构化数据。原模型理由和quote明确为原文。

下一修正仅补全当前模板字段，不增加美化、图表、GUI 或新依赖。两格式应从同一批冻结字段构造展示内容，避免复制时遗漏。修正后用同一合成报告复验，再做一次浏览器可读性检查。
