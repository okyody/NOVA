# NOVA 1.0 Config Revision 封板清单

本文档用于冻结 `NOVA 1.0` 对配置版本治理的范围、状态机、审计要求与验收标准。

目标：

- 把 `config_revisions` 从“可以存一条配置记录”收成“可治理、可发布、可回滚的企业能力”
- 防止 1.0 阶段继续扩张成复杂审批平台
- 为 `Runtime 封板` 和 `最终验收封板` 提供统一配置基线

---

## 1. 1.0 定义

`Config Revision` 在 1.0 中的定义是：

> 针对某个租户下某个资源的可追踪配置版本记录，支持创建草稿、发布、回滚，并写入审计。

它不是：

- 完整审批工作流平台
- 多层级配置中心
- 跨租户大规模配置编排系统

---

## 2. 配置版本适用资源

1.0 允许配置版本治理的资源类型冻结为：

- `runtime`
- `agent`
- `character`
- `platform_connection`

在 1.0 封板前，不继续新增新的配置资源类别，除非属于阻断交付的问题。

---

## 3. 数据模型边界

每条 config revision 至少必须具备：

- `id`
- `tenant_id`
- `resource_type`
- `resource_id`
- `revision_no`
- `config_json`
- `status`
- `created_at`
- `updated_at`

状态字段只允许使用：

- `draft`
- `published`
- `rolled_back`

1.0 阶段不新增：

- `archived`
- `approved`
- `rejected`
- `scheduled`

这些属于 1.1+ 的治理扩展，而不是 1.0 封板要求。

---

## 4. 状态机冻结

1.0 配置版本状态机冻结为：

- `draft -> published`
- `published -> rolled_back`

不允许的迁移包括但不限于：

- `draft -> rolled_back`
- `published -> draft`
- `rolled_back -> published`
- `rolled_back -> draft`

如果发生非法迁移，系统必须：

1. 拒绝操作
2. 返回明确错误
3. 不修改底层状态

---

## 5. 唯一性规则

1.0 必须满足的关键治理规则：

### 5.1 revision 编号唯一

对于同一组：

- `tenant_id`
- `resource_type`
- `resource_id`

`revision_no` 必须唯一。

### 5.2 published 唯一

对于同一组：

- `tenant_id`
- `resource_type`
- `resource_id`

在任意时刻只允许 **1 个** `published` revision。

也就是说：

- 发布新 revision 时，必须保证不会留下多个 published
- 如果当前实现还未完全在数据库约束层落死，这一项必须列为 1.0 收口重点

---

## 6. 发布规则

1.0 的 publish 语义必须固定为：

1. 目标 revision 当前状态必须是 `draft`
2. 发布成功后目标状态变为 `published`
3. 同资源下其他已发布版本不得继续保持 `published`
4. 必须写入 audit

publish 不要求 1.0 提供：

- 审批流
- 预约发布时间
- 灰度发布 UI

但必须提供：

- 明确的结果状态
- 明确的失败原因

---

## 7. 回滚规则

1.0 的 rollback 语义必须固定为：

1. 目标 revision 当前状态必须是 `published`
2. 回滚成功后目标状态变为 `rolled_back`
3. 必须写入 audit

1.0 这里要特别说明：

`rolled_back` 的 1.0 语义是“该发布版本被撤销”，不是“系统自动切换到上一个可用 published revision”。

也就是说，1.0 的回滚更偏向：

- 发布状态撤销
- 留痕
- 提供明确治理动作

而不是完整的多版本自动恢复编排。

如果后续要做“回到上一个稳定 revision”，那属于 1.1+。

---

## 8. 运行时读取原则

1.0 运行时读取配置必须遵循：

- runtime 只应消费当前有效配置
- runtime 不应直接依赖任意 draft 版本
- runtime 不应把回滚掉的 revision 继续当成当前有效配置

当前 1.0 阶段允许的简化：

- Studio / API 层先完成 create / publish / rollback / query 闭环
- effective config 的运行时消费链可以是最小版本，但必须明确：
  - 未来只读取当前有效 revision
  - 不读随机历史 revision

这项是 `Runtime 封板` 的重要前置。

---

## 9. 审计要求

以下操作必须写入 audit：

- config revision create
- config revision publish
- config revision rollback
- config file save（如果影响运行配置）

审计里至少应能看出：

- 操作类型
- 资源类型
- 资源 ID
- 谁触发的
- 何时触发的

---

## 10. Studio 要求

1.0 Studio 对 config revision 的要求冻结为：

### 10.1 可见

- revision 列表
- revision 状态
- resource_type
- resource_id
- revision_no

### 10.2 可操作

- 创建 draft
- publish
- rollback

### 10.3 不追求

1.0 不追求：

- 多层审批 UI
- 复杂 diff 视图
- 配置对比器
- 灰度发布可视化

Studio 在 1.0 对 config revision 的目标只是：

> 用户能明确创建、发布、回滚，并看清当前状态。

---

## 11. API 冻结范围

1.0 Config Revision API 冻结为：

- `GET /api/control/config-revisions`
- `POST /api/control/config-revisions`
- `POST /api/control/config-revisions/{revision_id}/publish`
- `POST /api/control/config-revisions/{revision_id}/rollback`

这些接口必须满足：

- permission code 校验
- tenant scope 校验
- 非法状态迁移拒绝
- 返回明确错误

---

## 12. 验收标准

只有下面全部成立，`Config Revision 封板` 才算通过：

1. 能创建 draft revision
2. draft 可以发布为 published
3. published 可以 rollback 为 rolled_back
4. 非法状态迁移会被拒绝
5. 同资源不会保留多个 published
6. 所有 create / publish / rollback 有 audit
7. Studio 能完成最小操作流
8. API 查询能返回状态正确的 revision 列表

---

## 13. 1.0 剩余收口重点

Config Revision 在 1.0 剩余最值得继续做的只有这些：

1. 把 published 唯一性做硬
2. 把 runtime 的 effective config 读取边界明确化
3. 确保 Studio / API / store / audit 行为一致

不再新增新的复杂治理功能。

---

## 14. Go / No-Go 判定

### Go

允许进入下一个封板项（`Runtime 封板`），当且仅当：

- 状态机规则已经冻结
- create / publish / rollback 已稳定
- 审计已打通
- Studio 最小操作流可用

### No-Go

以下任一情况成立，都不允许认为 Config Revision 已封板：

- publish/rollback 只是裸改字段，没有治理语义
- 非法迁移仍可成功
- 多个 published 并存
- audit 缺失
- Studio 不能完成最小 revision 操作链

---

## 15. 下一步

Config Revision 封板完成后，严格进入下一个封板项：

- `Runtime 封板`

后续重点不再是“再加配置玩法”，而是把运行时稳定性、可观测性、历史留痕和交付链彻底收住。
