# NOVA 1.0 最终验收证据记录（2026-05-05）

本记录对应 `FINAL_ACCEPTANCE_FREEZE_1_0.md` 的客户视角正式验收链。

## 1. 验收环境

- Host: `82.156.206.162`
- Repo path: `~/NOVA-clean`
- Runtime path: source + uvicorn
- Database: `postgresql://nova:nova@localhost:5432/nova`
- Redis: active
- 验收日期：`2026-05-05`

## 2. 实际执行链

已完成：

1. 启动 runtime
2. 检查 `/health`
3. 检查 `/studio/api/status`
4. 创建 tenant
5. 创建 role
6. 创建 permission 集
7. 绑定 role-permission
8. 创建 user
9. 绑定 user-role
10. 启用 auth 配置
11. 重启 runtime
12. 获取 token
13. 校验 `/api/auth/me`
14. 创建 config revision
15. publish revision
16. rollback revision
17. 通过 Douyin webhook 入口注入一条 runtime chat event
18. 回查 conversation history
19. 回查 audit

## 3. 验收结果摘要

- startup: PASS
- control plane init: PASS
- auth login: PASS
- revision lifecycle: PASS
- runtime event ingestion: PASS
- audit visibility: PASS

## 4. 关键证据

### 4.1 health

- `status = ok`
- `auth.enabled = true`

### 4.2 auth

- `/api/auth/me` 返回：
  - `id = user-operator`
  - `tenant_id = tenant-demo`
  - `roles = ["tenant-admin"]`
  - `tenant_ids = ["tenant-demo"]`

### 4.3 config revision

- publish 返回：
  - `revision_status = published`
- rollback 返回：
  - `revision_status = rolled_back`

### 4.4 runtime history

- `conversation history count = 1`
- 记录到 `platform.chat_message`
- source = `douyin`

### 4.5 audit

- audit count = 20
- 已包含：
  - `role_created`
  - `permission_created`
  - `user_created`
  - `user_roles_updated`
  - `config_file_saved`
  - `config_revision_created`
  - `config_revision_published`
  - `config_revision_rolled_back`

## 5. 验收过程中发现并处理的阻断项

### 阻断项 A：runtime 启动在启用 Postgres store 时崩溃

现象：

- `NameError: name 'EventType' is not defined`

原因：

- `apps/nova_server/main.py` 在 Postgres runtime store 订阅分支中使用了 `EventType`
- 但文件顶部未导入 `EventType`

处理：

- 已补齐导入

### 阻断项 B：Postgres 表权限不一致

现象：

- `permission denied for table conversation_turns`

原因：

- 现有 `nova` 数据库中表 owner / grant 状态不一致
- `nova` 应用用户无法读取运行时表

处理：

- 在 `nova` 数据库上补齐 schema / table / sequence grant

## 6. 结论

按当前冻结边界，本次正式验收链已跑通。

结论：

> NOVA 1.0 已完成一轮真实客户视角最终验收链验证。  
> 当前交付物、控制平面、配置治理、运行时与审计链已具备正式封板条件。
