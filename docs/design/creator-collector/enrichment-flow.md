# Creator Enrichment Flow Notes

`creator enrichment` 是任务内的数据增强能力，用于基于现有 `creator_oecuid` 回填达人详情资料，不复用 `review` 记录。

## 入口与前提

- 入口位于任务页。
- 当任务数据存在 `creator_oecuid` 列时，显示 `补充采集` 按钮。
- 第一版固定使用 `selection_region` 作为区域分组字段；缺失时归入“未知区域”分组并放到最后执行。
- 补充采集使用独立 worker、独立进度和独立浏览器会话，不与上游列表采集共用状态。

## 采集范围与写回

- 补充采集直接写回任务项 `task_data`。
- 写回字段属于源数据增强，不属于人工审核字段。
- 第一版目标字段：
  - `bio`
  - `contact_info_available`
  - `phone`
  - `whatsapp`
  - `email`
  - `line`
  - `zalo`
  - `viber`
  - `facebook`
- 未知联系方式字段使用 `contact_{field}` 命名，例如 `contact_35`。
- 单字段多值按原始顺序使用 `; ` 拼接并去重；正常单值场景直接原样保存。

## 导出顺序

- 导出列顺序为：
  - `task_snapshot.export_fields`
  - `bio`
  - `contact_info_available`
  - 已知联系方式字段，顺序固定为 `phone`、`whatsapp`、`email`、`line`、`zalo`、`viber`、`facebook`
  - 未知联系方式字段，按 `field` 数字升序追加
  - 已启用的审核字段

## 浏览器与执行队列

- 补充采集沿用受控浏览器和持久化 profile。
- 启动后直接打开首个待处理达人详情页，用户在真实页面中确认登录、区域和验证码状态。
- 详情页地址固定为 `https://affiliate.tiktokshopglobalselling.com/connection/creator/detail?cid={creator_oecuid}`。
- 内部执行队列按区域分组重排，但任务原始顺序、`task_index` 和导出顺序不改变。
- 组内按原始 `task_index` 顺序执行。

## 请求与页面动作

- 打开详情页后监听 profile 请求 `/api/v1/oec/affiliate/creator/marketplace/profile`。
- 从 profile 响应提取 `bio` 等详情字段。
- `contact_info_available.value` 是联系方式存在性的稳定标志：
  - `false`：无联系方式，写回 `contact_info_available=false` 后直接进入下一条
  - `true`：存在联系方式，写回 `contact_info_available=true` 后等待联系方式徽章展示并点击
- 若页面存在联系方式徽章，则点击一次，监听 contact 请求 `/api_sens/v1/affiliate/cmp/contact`。
- contact 请求一次性返回全部联系方式，按 `field -> 列名` 映射写回。
- `phone` 由所有非 `email` 联系方式列自动派生：
  - 包括已知联系方式字段与未知 `contact_{field}` 字段
  - 使用 `selection_region` 作为国家判断依据
  - 仅对白名单国家做手机号标准化
  - 标准化结果统一输出为带 `+国际区号` 的号码
  - 多个号码使用 `; ` 拼接
  - 明显不是手机号的内容直接忽略
  - 仅当内容疑似手机号但格式不合法时，写入 `INVALID`
- 不直接伪造联系方式请求；以浏览器真实页面动作触发为准。

## 暂停与恢复

- 补充采集独立记录逐条状态，不允许人工调整进度。
- 恢复时默认仅继续未完成项。
- 用户可跳过当前达人；跳过后处理下一个待处理项。
- 面板提供 `自动跳过` 开关，默认不勾选。
- 勾选 `自动跳过` 后：
  - 验证码与区域不匹配仍暂停并提示人工处理
  - 其他采集异常在达到重试上限后自动跳过当前项并继续后续达人
- 自动跳过不视为完成；后续再次点击 `补充采集` 时仍继续这些未完成项。
- 遇到以下情况时自动暂停并提示人工处理：
  - 验证码
  - 区域不匹配
  - 其他页面异常或接口未返回有效数据

## 暂停原因分类

- 内部暂停原因至少区分：
  - `captcha`
  - `region_mismatch`
  - `manual_action`
- 对用户仍展示清晰文案：
  - 验证码：请先完成验证后继续
  - 区域不匹配：请检查店铺区域后继续
  - 其他异常：请处理页面后继续，或跳过当前达人

## 验证码检测

- 优先通过页面 DOM 检测验证码，不依赖单一接口失败判定。
- 第一版命中以下任一特征即判定为验证码：
  - `.captcha_verify_container`
  - `#captcha-verify-image`
  - `#secsdk-captcha-drag-wrapper`
  - 文案 `请完成下列验证后继续`
  - 文案 `按住左边按钮拖动完成上方拼图`

## 区域不匹配检测

- 优先读取实际 profile 请求上下文中的 `shop_region` 参数。
- 若无法读取请求参数，则回退到当前页面 URL 的 `shop_region` 参数。
- 当 `shop_region` 与当前任务项的 `selection_region` 不匹配时，归类为 `region_mismatch`。
- profile 返回 `{"code":16901008,"msg":"creator status invalid"}` 且未命中验证码时，也作为人工处理暂停，不直接吞掉。

## 进度与通知

- 进度窗口风格与检查流程保持一致，展示：
  - 总数
  - 已完成数
  - 当前区域
  - 剩余区域
  - 进度条
  - 预计剩余时间
- 程序不在前台时，对以下事件发送系统通知：
  - 采集暂停
  - 当前项失败
  - 当前项需要验证码
  - 采集完成

## 状态模型

- 任务项内部状态建议至少包含：
  - `pending`
  - `success`
  - `no_contact`
  - `auto_skipped`
  - `paused_captcha`
  - `paused_region_mismatch`
  - `paused_manual_action`
  - `skipped`
- 附带记录最近错误原因、更新时间和已完成字段集合，供断点恢复与统计使用。
