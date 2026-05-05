# NOVA 1.0 产品边界封板清单

本文档用于冻结 `NOVA 1.0` 的产品边界，防止 1.0 在收尾阶段继续发散。

适用原则：

- 从本文档起，1.0 只解决“交付问题”，不再扩张“研发兴趣问题”
- 不新增新平台、新 Agent 玩法、新渲染协议、新运营模块
- 后续所有开发、验收、部署、文档工作都必须对齐本清单

---

## 1. 1.0 产品定义

`NOVA 1.0` 的最终产品定义是：

> 一个支持私有化部署的互动数字人运行时与企业控制平面产品。

它不是：

- 通用多 Agent 平台
- 面向消费者的桌面娱乐软件
- 大而全的全平台数字人 SaaS

它是：

- 一个可交付的企业内部系统
- 一个可运行、可配置、可验收、可私有化部署的数字人底座
- 一个带最小控制平面、最小运维链、最小 AI 评测闭环的 1.0 产品

---

## 2. 1.0 保留范围

`NOVA 1.0` 只保留以下 5 个核心目标：

### 2.1 一个主交付场景

1.0 主场景固定为：

- 实时互动数字人 / 虚拟直播助理

必须满足：

- 可接收实时输入
- 可生成文本/语音响应
- 可在控制面查看运行状态、历史和审计

### 2.2 一套稳定 runtime 拓扑

1.0 参考 runtime 拓扑固定为：

- `nova-api`
- `nova-perception`
- `nova-cognitive`
- `nova-generation`
- `redis`
- `postgres`
- `qdrant`
- `ollama`

不得在 1.0 收尾阶段继续新增新的核心运行角色。

### 2.3 一套能工作的控制平面

1.0 控制平面固定包含：

- tenants
- users
- roles
- permissions
- role_permissions
- user_roles
- config_revisions
- audit_logs

必须具备：

- DB-backed token issuance
- `/api/auth/me`
- permission code 校验
- tenant scope 校验
- Studio 登录态和最小工作台

### 2.4 一套可部署可恢复的运维链

1.0 正式交付形态只保留两条：

- Windows EXE 一体化交付版
- Docker / Kubernetes 服务端交付版

必须具备：

- migration/init 机制
- backup 机制
- restore/rollback 文档
- 健康检查与运行态观察入口

### 2.5 一套最小 AI 评测闭环

1.0 评测范围固定为 6 类：

- question
- greeting
- request/command
- emotion response
- rag answer
- tool call

目标不是追求“AI 什么都懂”，而是保证：

- 回归可测
- 质量可比较
- 修改可追踪

---

## 3. 1.0 禁止新增项

以下内容在 1.0 封板前一律暂停：

### 3.1 平台扩张

禁止新增：

- 新直播平台接入
- 新 IM / 新渠道入口
- 新的多平台统一抽象

### 3.2 Agent 扩张

禁止新增：

- 新自治 Agent 角色
- 新复杂多 Agent 协商机制
- 新实验性 orchestration 框架

### 3.3 渲染/形象扩张

禁止新增：

- 新 avatar/render 协议
- 新复杂表情系统
- 新的视频/推流协议实验

### 3.4 运营模块扩张

禁止新增：

- 商品管理系统
- 场控运营系统
- 营销玩法中心
- 面向终端用户的大型运营后台

### 3.5 云化/SaaS 扩张

禁止新增：

- 多组织复杂 SaaS 计费体系
- 大规模多集群控制面
- Marketplace / 插件生态

---

## 4. 1.0 交付物清单

1.0 最终必须交付以下内容：

### 4.1 可运行交付物

- `dist/NOVA/NOVA.exe`
- `docker-compose.yml`
- `deploy/k8s/nova-deployment.yaml`

### 4.2 控制平面能力

- 登录与用户上下文
- tenant / user / role / permission 操作
- config revision create / publish / rollback
- audit 查询

### 4.3 运行时能力

- health
- metrics
- Studio Dashboard
- Events
- Config
- Control
- 历史/审计查询

### 4.4 文档交付物

- `ENTERPRISE_ACCEPTANCE_1_0.md`
- `PRODUCT_EXECUTION.md`
- `CUSTOMER_INSTALL_ACCEPTANCE_GUIDE.md`

### 4.5 测试交付物

- API smoke
- productization smoke
- Windows launcher smoke
- control-plane auth/scope smoke
- 最小 AI 回归集（后续封板项继续补齐）

---

## 5. 1.0 使用者画像

1.0 面向的主要使用者不是普通消费者，而是：

- 企业内部交付人员
- 售前/实施工程师
- 运营管理员
- 技术管理员

这意味着 1.0 的优先级必须是：

- 能安装
- 能配置
- 能登录
- 能运行
- 能排错
- 能验收

而不是：

- 功能数量最多
- 场景覆盖最广
- UI 最花哨

---

## 6. 1.0 成功标准

只有下面这些条件同时成立，`NOVA 1.0` 才算产品层面通过：

1. 能在 Windows 上通过 `NOVA.exe` 启动工作台
2. 能通过 Studio 完成最小控制平面初始化
3. 能生成 DB-backed token 并返回 `/api/auth/me`
4. 能进行 tenant-scoped 控制面访问
5. 能创建、发布、回滚 config revision
6. 能查看 runtime history 与 audit
7. 能按文档完成一次客户视角验收链

---

## 7. Go / No-Go 判定

### Go

允许进入 1.0 封板验收，当且仅当：

- 新功能扩张已经停止
- 当前工作全部围绕交付、稳定、验收
- 所有后续任务都可以归类到 8 个封板包之一

### No-Go

如果出现以下情况，则视为偏离 1.0 封板：

- 再次新增平台
- 再次新增 Agent 角色
- 再次新增大块运营模块
- 再次新增复杂渲染协议
- 因“看起来更强”而继续扩需求

---

## 8. 后续封板顺序

在本清单之后，严格按以下顺序推进，不跳步：

1. 产品边界封板
2. 控制平面封板
3. Config Revision 封板
4. Runtime 封板
5. AI 质量封板
6. Windows EXE 封板
7. 部署与恢复封板
8. 最终验收封板

从现在开始，任何新增工作都必须先回答一个问题：

> 这个改动能不能让客户更容易部署、使用、验收？

如果答案不是“能”，则 1.0 暂缓。
