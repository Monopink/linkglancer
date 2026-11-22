# Stage Handoff

上游采集与下游审核之间通过标准化文件和应用层接口衔接。

顺序：

1. `creator_collector` 完成采集
2. 用户确认结束
3. 导出标准 `xlsx`
4. 调用 `LinkGlancer` 的应用层接口
5. 创建审核任务并自动填充默认审核配置

衔接原则：

- `xlsx` 文件保留，既是源文件也是排错依据
- 采集阶段不直接操作 `LinkGlancer` 的 SQLite
- 浏览器配置由 `LinkGlancer` 管理，采集阶段只选择和复用
- 自动填充配置针对 creator 数据集提供固定默认值，不在采集阶段重复定义审核结构
