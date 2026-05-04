# NOVA 客户安装与验收手册

本文档面向 1.0 交付阶段，按当前代码和 Windows 一体化 EXE 工作台的真实行为编写。

适用对象：

- 需要在 Windows 上直接运行 `NOVA.exe` 的交付用户
- 需要完成一次标准客户验收链的实施人员
- 需要演示 Studio 工作台、控制平面、配置和运行态的售前/交付人员

---

## 1. 交付物

Windows 一体化成品：

- `dist\NOVA\NOVA.exe`

工作方式：

- 双击 `NOVA.exe` 后，程序会拉起本地服务
- 自动打开内嵌工作台
- 工作台内包含：
  - Dashboard
  - Events
  - Config
  - Control

---

## 2. 推荐环境

最低建议：

- Windows 10 / Windows Server
- 8GB 内存以上
- 能正常访问本机 `127.0.0.1`

推荐企业验收环境：

- Windows 主机运行 `NOVA.exe`
- 可访问的 PostgreSQL
- 可访问的 Redis
- 可访问的 Ollama / OpenAI 兼容模型服务

说明：

- 只看界面和最小流程时，可先用本地默认配置启动
- 要完成正式 1.0 验收，建议启用 Postgres 持久化

---

## 3. 首次启动

1. 打开 `dist\NOVA\NOVA.exe`
2. 等待内嵌工作台出现
3. 进入首页 Dashboard
4. 确认首页能看到：
   - `Quick Start`
   - `Quick Actions`
   - `Current User Context`
   - `Environment Readiness`

首次启动成功的基本判断：

- 顶部状态点为绿色
- `Runtime` 卡片有数据
- `Config File` 能显示本地配置文件路径

如果程序启动但没有进入工作台：

- 查看同目录下 `nova-launcher.log`
- 检查本机 `8765` 端口是否被其他程序占用

---

## 4. 配置工作台使用

进入：

- 左侧 `Config`

可直接编辑的 1.0 核心项：

- `port`
- `runtime.role`
- `auth.enabled`
- `llm.base_url`
- `llm.model`
- `character.path`
- `voice.backend`
- `voice.voice_id`
- `knowledge.enabled`
- `persistence.backend`
- `persistence.postgres_url`
- `persistence.redis_url`

常用按钮：

- `Reload Settings`
- `Save Config`
- `Reload Character`

保存后的判断规则：

- 出现 `Config saved. Live settings updated where safe.`
  说明无需重启即可保留配置
- 出现 `Config saved. Restart required for some changes.`
  说明配置已落盘，但必须重启 `NOVA.exe`

推荐配置顺序：

1. 先填 `llm.base_url` 和 `llm.model`
2. 再填 `persistence.postgres_url`
3. 再填 `persistence.redis_url`
4. 保持 `auth.enabled = false` 完成控制面初始化
5. 初始化完成后再开启 `auth.enabled = true`

---

## 5. 控制面初始化

进入：

- 左侧 `Control`

### 5.1 创建租户

在 `Create Tenant` 中填写：

- `tenant id`
- `tenant name`
- `tenant slug`
- `plan`

点击：

- `Create Tenant`

### 5.2 创建角色

在 `Create Role` 中填写：

- `role id`
- `tenant id`
- `role name`
- `scope`

点击：

- `Create Role`

建议 1.0 最小角色：

- `tenant-admin`

### 5.3 创建权限

在 `Permissions` 中创建最小权限集：

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

### 5.4 绑定角色权限

在 `Role Permission Binding` 中：

1. 填 `role id`
2. 填权限 ID 列表
3. 点击 `Bind Permissions`

### 5.5 创建用户

在 `Users` 中填写：

- `user id`
- `tenant id`
- `email`
- `display name`

点击：

- `Create User`

### 5.6 绑定用户角色

在 `User Role Binding` 中：

1. 填 `user id`
2. 填角色 ID 列表
3. 点击 `Bind Roles`

---

## 6. 启用登录与当前用户上下文

控制面资源初始化完成后：

1. 返回 `Config`
2. 将 `Auth Enabled` 勾上
3. 点击 `Save Config`
4. 如果提示需要重启，则关闭并重新打开 `NOVA.exe`

重启后：

1. 在顶部输入框输入刚创建的 `user id`
2. 点击 `Login`

成功后应看到：

- 顶部右侧用户从 `anonymous` 变成 `user_id @ tenant`
- Dashboard 的 `Current User Context` 出现：
  - User
  - Tenant Scope
  - Roles
  - Permission Count
- Control 页的 `Workbench` 里能看到同样的身份信息

如果登录失败：

- 确认 `auth.enabled` 已开启
- 确认用户已存在
- 确认用户已绑定角色
- 确认角色已绑定权限

---

## 7. 配置版本验收

进入：

- 左侧 `Control`

在 `Create Revision` 中填写：

- `revision id`
- `tenant id`
- `resource type`
- `resource id`
- `revision no`
- `config json`

推荐示例：

- `resource type = runtime`
- `resource id = nova`

操作顺序：

1. 点击 `Create Draft`
2. 确认 `Config Revisions` 列表出现新 revision
3. 点击 `Publish`
4. 确认状态变成 `published`
5. 点击 `Rollback`
6. 确认状态变成 `rolled_back`

验收点：

- 非法状态迁移应被拒绝
- 操作结果应写入 `Control Log`

---

## 8. 运行态验收

进入：

- `Dashboard`
- `Events`

需要确认的页面元素：

- `Quick Start`
- `Quick Actions`
- `Runtime`
- `Persisted History`
- `Environment Readiness`

需要确认的运行指标：

- `Consumer Lag`
- `Pending`
- `Retries`
- `DLQ`

如果配置了运行时事件输入，验收时还应确认：

- `Events` 页能看到事件流
- `Persisted History` 有会话/安全条目
- `/health` 可用

---

## 9. 标准客户验收链

1. 启动 `NOVA.exe`
2. 工作台成功打开
3. 在 `Config` 中完成基础配置并保存
4. 在 `Control` 中创建：
   - tenant
   - role
   - permissions
   - user
   - role-permission binding
   - user-role binding
5. 开启 `auth.enabled`
6. 重启 `NOVA.exe`
7. 使用创建好的用户登录
8. 创建 config revision
9. 完成 publish
10. 完成 rollback
11. 查看 Dashboard / Events / History / Control Log

只有以上链条完整跑通，才算 1.0 客户验收通过。

---

## 10. 常见问题

### 10.1 EXE 打开后没有工作台

检查：

- 是否已有其他程序占用 `8765`
- 同目录下 `nova-launcher.log` 是否有错误

### 10.2 能打开工作台，但登录失败

检查：

- `auth.enabled` 是否已开启
- 用户是否存在
- 用户是否已绑定角色
- 角色是否已绑定权限

### 10.3 保存配置后没有立即生效

这不是错误。

部分配置允许热更新，部分配置需要重启。以界面提示为准：

- `Live settings updated where safe`
- `Restart required for some changes`

### 10.4 Control 页面能看不能改

通常是权限问题：

- 当前用户权限不足
- 当前用户 tenant scope 不匹配

请查看：

- Dashboard 的 `Current User Context`
- Control 页的 `Workbench`

### 10.5 想重新走一遍初始化流程

建议：

1. 先关闭 `NOVA.exe`
2. 备份现有 `nova.config.json`
3. 清理测试用的数据库数据
4. 重新启动后按本文档顺序执行

---

## 11. 建议的 1.0 交付口径

对外建议这样描述：

NOVA 1.0 是一个可私有化部署的互动数字人运行时与控制平面产品，当前交付形态支持：

- Windows 一体化 EXE 工作台
- 配置编辑与运行时观测
- tenant / user / role / permission 控制平面
- config revision 发布与回滚
- 面向企业内部场景的最小可交付验收链

不建议对外承诺：

- 全平台全场景开箱即用
- 完整 SaaS 组织体系
- 大规模多实例自治编排

1.0 的价值是“可交付、可验收、可私有化部署”，不是“功能无限扩张”。
