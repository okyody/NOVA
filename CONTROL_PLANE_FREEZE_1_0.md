# NOVA 1.0 控制平面封板清单

本文档用于冻结 `NOVA 1.0` 的控制平面范围、边界、验收标准与剩余收口项。

目标：

- 把控制平面从“已经有接口和页面”收成“可交付、可操作、可验收的后台产品”
- 防止 1.0 阶段继续扩张控制面资源与玩法
- 为后续 `Config Revision 封板`、`Runtime 封板`、`最终验收封板` 提供统一基线

---

## 1. 控制平面定义

`NOVA 1.0` 控制平面指：

- 登录与认证
- 用户上下文
- 租户范围
- 角色与权限
- 配置版本
- 审计留痕
- Studio 最小后台工作台

它不是：

- 完整 SaaS 组织平台
- 多层组织树 / 部门树系统
- 大而全的低代码运营后台

---

## 2. 1.0 控制平面资源范围

1.0 控制平面资源冻结为以下集合：

- `tenants`
- `users`
- `roles`
- `permissions`
- `role_permissions`
- `user_roles`
- `config_revisions`
- `audit_logs`

在 1.0 封板前，禁止继续新增新的控制面核心资源类型。

---

## 3. 认证与身份边界

### 3.1 必须保留的能力

1.0 控制平面必须具备：

- DB-backed token issuance
- `/api/auth/token`
- `/api/auth/me`
- Studio 登录态
- Studio 当前用户上下文展示

### 3.2 token 必须包含的字段

token 的 claims 必须包含：

- `sub`
- `roles`
- `permissions`
- `tenant_ids`

### 3.3 当前用户上下文必须可见

在 Studio 与 API 中，必须能明确看到：

- 当前用户 ID
- 当前租户范围
- 当前角色
- 当前权限

---

## 4. 权限模型冻结

1.0 权限码集合冻结为：

- `tenant.read`
- `tenant.write`
- `user.read`
- `user.write`
- `role.read`
- `role.write`
- `permission.read`
- `permission.write`
- `config_revision.read`
- `config_revision.write`
- `config_revision.publish`
- `config_revision.rollback`

1.0 阶段不再新增大批新的 permission code，除非属于封板阻断项。

---

## 5. tenant scope 边界

### 5.1 原则

控制平面所有资源访问必须满足两层校验：

1. `permission code` 校验
2. `tenant scope` 校验

### 5.2 合法访问边界

- 全局管理员：允许跨租户
- 租户管理员：只允许本租户
- 非本租户资源：必须拒绝

### 5.3 1.0 要求

以下查询与操作必须受 tenant scope 约束：

- tenants
- users
- roles
- config revisions

并且应尽量在 store 层完成 scoped 查询，而不是在应用层先查全量再过滤。

---

## 6. Studio 控制面冻结范围

Studio 作为 1.0 最小后台工作台，必须支持：

### 6.1 可见

- 当前用户上下文
- tenant scope
- roles
- permissions
- control log
- config revision 状态

### 6.2 可操作

- 创建 tenant
- 创建 role
- 创建 permission
- 创建 user
- 绑定 role-permission
- 绑定 user-role
- 创建 config revision
- publish revision
- rollback revision

### 6.3 不追求

1.0 不要求 Studio 具备：

- 复杂表格筛选器
- 多级后台导航体系
- 大型前端组件系统
- 复杂审批流 UI

Studio 在 1.0 的目标是：

> 能完成最小控制面初始化和最小验收链，而不是做成全功能 SaaS 管理台。

---

## 7. 审计要求

1.0 控制平面所有写操作必须有审计。

至少包括：

- tenant create/update
- role create/update
- permission create
- role-permission bind
- user create/update
- user-role bind
- config revision create
- config revision publish
- config revision rollback
- config file save

审计能力必须满足：

- 能被写入
- 能通过 API 查询
- 能在验收时被核对

---

## 8. 控制平面 API 冻结范围

1.0 最小控制面 API 集冻结为：

### 8.1 Auth

- `POST /api/auth/token`
- `GET /api/auth/me`

### 8.2 Tenants

- `GET /api/control/tenants`
- `POST /api/control/tenants`
- `PATCH /api/control/tenants/{tenant_id}`

### 8.3 Roles

- `GET /api/control/roles`
- `POST /api/control/roles`
- `PATCH /api/control/roles/{role_id}`
- `GET /api/control/roles/{role_id}/permissions`
- `PUT /api/control/roles/{role_id}/permissions`

### 8.4 Users

- `GET /api/control/users`
- `POST /api/control/users`
- `PATCH /api/control/users/{user_id}`
- `GET /api/control/users/{user_id}/roles`
- `PUT /api/control/users/{user_id}/roles`

### 8.5 Permissions

- `GET /api/control/permissions`
- `POST /api/control/permissions`

### 8.6 Config Revisions

- `GET /api/control/config-revisions`
- `POST /api/control/config-revisions`
- `POST /api/control/config-revisions/{revision_id}/publish`
- `POST /api/control/config-revisions/{revision_id}/rollback`

### 8.7 Runtime / Audit Readbacks

- runtime history APIs
- storage session/viewer/audit APIs

---

## 9. 控制平面验收标准

只有下面全部成立，控制平面才算 1.0 封板通过：

1. 能创建 tenant
2. 能创建 user
3. 能创建 role
4. 能创建 permission
5. 能给 role 绑定 permission
6. 能给 user 绑定 role
7. 能通过数据库装配 token
8. `/api/auth/me` 能返回用户上下文
9. 跨 tenant 访问会被拒绝
10. config revision 可 create / publish / rollback
11. 所有控制面写操作有 audit
12. Studio 可完成最小控制面初始化

---

## 10. 1.0 剩余收口重点

控制平面在 1.0 剩余最重要的工作只保留以下几项：

1. 继续把 tenant-scoped 查询下沉到 store 层
2. 把 config revision 治理闭环做硬
3. 让 Studio 的控制面操作流更直观
4. 保证控制面 API、Studio、审计三者行为一致

不再新增新的控制平面资源与大块功能模块。

---

## 11. Go / No-Go 判定

### Go

允许进入下一封板项（`Config Revision 封板`），当且仅当：

- 控制平面资源集合冻结
- token -> user -> role -> permission -> tenant_ids 链路成立
- Studio 能完成最小初始化
- API 和 UI 的最小操作流可用

### No-Go

如果出现以下任意情况，不允许认为控制平面封板完成：

- 仍然依赖手工 claims 伪装用户上下文
- tenant scope 不稳定
- 关键写操作不记审计
- Studio 只能看不能完成初始化
- config revision 只是“能改字段”而不是“能治理配置”

---

## 12. 下一步

控制平面封板完成后，严格进入下一个封板项：

- `Config Revision 封板`

后续的重点不再是“再多几个后台资源”，而是把配置版本治理收成真正的企业能力。
