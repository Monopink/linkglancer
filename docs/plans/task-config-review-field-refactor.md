# 任务配置与检查项语义重构

本计划中的大部分目标已经落地，剩余内容以 `docs/design/link-glancer/*.md` 中的最新规则为准。

## 已被新设计替代的部分

- 浏览器检查流不再使用旧的“提交后补齐缓冲”笼统语义，改为：
  - 单一当前检查页
  - 分批新增缓冲页
  - 缓冲异常立即处理
- 检查窗口不再只支持“回到最近一条已保存结果”的 `previous` 语义，改为：
  - `current_task_index`
  - `viewing_task_index`
  - 历史回看 `上一条/下一条`
- 检查项选项不再区分 `value` 和 `label`。
- `review_history` 不再保留，改为直接删除。

## 当前改造以以下文档为准

- `docs/design/link-glancer/browser-control.md`
- `docs/design/link-glancer/review-ui.md`
- `docs/design/link-glancer/storage-model.md`
- `docs/design/link-glancer/task-configuration.md`
