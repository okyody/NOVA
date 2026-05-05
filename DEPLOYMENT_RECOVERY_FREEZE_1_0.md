# NOVA 1.0 部署与恢复封板清单

本文档用于冻结 `NOVA 1.0` 的部署路径、迁移机制、备份恢复边界、运维交付物与验收标准。

目标：

- 把部署链从“能启动一些服务”收成“客户可重复执行的交付路径”
- 把恢复链从“理论上可回滚”收成“有文档、有步骤、有边界的恢复方案”
- 为 `最终验收封板` 提供正式交付环境基线

---

## 1. 1.0 部署定义

`NOVA 1.0` 的部署与恢复定义是：

> 一套可重复执行的安装、迁移、启动、备份、恢复、回滚流程，能够支撑 runtime、control-plane 和 Studio 在客户环境中稳定运行。

它不是：

- 多云多集群统一运维平台
- SaaS 级平台工程体系
- 自动化灾备平台

1.0 强调的是：

- 可部署
- 可迁移
- 可备份
- 可恢复
- 可验收

---

## 2. 1.0 正式部署路径冻结

1.0 只保留两条正式部署路径：

### 2.1 Windows 一体化交付

交付物：

- `dist/NOVA/NOVA.exe`

适用：

- 本地演示
- PoC
- 单机交付
- 快速客户验收

### 2.2 服务端部署交付

交付物：

- `docker-compose.yml`
- `deploy/k8s/nova-deployment.yaml`

适用：

- 私有化部署
- 企业内网环境
- 正式服务端验收

1.0 不再新增第三套正式部署路线。

---

## 3. Compose 路径冻结

1.0 Compose 参考拓扑冻结为：

- `nova-api`
- `nova-perception`
- `nova-cognitive`
- `nova-generation`
- `redis`
- `postgres`
- `qdrant`
- `ollama`

Compose 路径必须满足：

- 配置模型与当前 settings 一致
- 服务声明完整
- 关键依赖都在清单里
- 能用于最小客户验收链

1.0 不要求 Compose 成为复杂生产编排平台，但必须是可运行的最小交付基线。

---

## 4. Kubernetes 路径冻结

1.0 K8s 路径必须保留：

- `Deployment: nova-api`
- `Deployment: nova-perception`
- `Deployment: nova-cognitive`
- `Deployment: nova-generation`
- `StatefulSet: postgres`
- `Job: nova-postgres-migrate`
- `CronJob: postgres-backup`
- 相关 `Secret / PVC / ConfigMap`

K8s 路径在 1.0 的目标是：

- 能表达参考拓扑
- 能表达初始化与备份链
- 能作为正式服务端交付蓝本

1.0 不再继续扩张：

- 复杂多集群联邦
- 多环境自动推广
- 高级 Service Mesh 策略

---

## 5. 迁移机制冻结

1.0 迁移机制必须明确且唯一：

- schema init / migration 必须有正式入口
- 不能依赖手工临时 SQL

必须保留：

- 本地初始化 SQL
- K8s migration job

至少要覆盖：

- runtime history 表
- safety 表
- runtime session/viewer 表
- audit 表
- tenants / users / roles / permissions / config revisions 表

1.0 不要求复杂在线迁移框架，但必须保证：

- 初始交付能落表
- 客户验收能执行

---

## 6. 备份冻结

1.0 备份要求只聚焦 Postgres。

必须具备：

- 备份机制
- 备份路径/目标说明
- 恢复入口文档

K8s 路径中，必须保留：

- `postgres-backup` CronJob
- 备份 PVC

1.0 不要求：

- 企业级全自动灾备编排
- 跨地域复制
- 多活恢复

---

## 7. 恢复与回滚冻结

### 7.1 恢复范围

1.0 恢复只要求覆盖：

- 配置文件恢复
- Postgres 数据恢复
- Config Revision 回滚
- EXE / 服务端重启恢复

### 7.2 回滚范围

1.0 回滚主要指：

- 配置版本回滚
- 部署版本回退到上一个稳定交付物

1.0 不要求：

- 自动多阶段灾难恢复编排

---

## 8. 运维文档冻结

1.0 必须具备以下文档：

- 安装手册
- 验收手册
- 升级手册
- 回滚手册
- 备份恢复手册

当前至少必须保证：

- `CUSTOMER_INSTALL_ACCEPTANCE_GUIDE.md`
- 企业 1.0 验收边界文档
- 产品执行清单

后续若再补运维文档，也必须围绕 1.0 交付，不扩张成平台知识库工程。

---

## 9. 环境边界冻结

1.0 部署环境必须明确：

### 9.1 Windows

- 用于 EXE 一体化交付

### 9.2 服务端环境

- Redis
- Postgres
- Qdrant
- Ollama / OpenAI-compatible model service

1.0 不承诺：

- 任意环境零配置运行
- 全云厂商一键适配

---

## 10. 客户视角部署链冻结

1.0 客户视角部署链固定为：

1. 准备环境
2. 启动 EXE 或 Compose/K8s
3. 确认 migration/init 完成
4. 登录 Studio
5. 初始化控制平面
6. 保存配置
7. 创建并发布 revision
8. 触发 runtime 事件
9. 查看 history / audit / health / metrics

部署与恢复封板的意义，是保证这条链“可以执行”，而不是“理论存在”。

---

## 11. 1.0 部署验收标准

只有下面全部成立，部署与恢复封板才算通过：

1. Windows EXE 可交付
2. Compose 路径存在且结构完整
3. K8s 路径存在且结构完整
4. migration/init 机制明确
5. backup 机制明确
6. restore/rollback 边界明确
7. 客户安装与验收手册可执行

---

## 12. 1.0 剩余收口重点

部署与恢复在 1.0 剩余最值得继续做的事情只保留：

1. 保持交付路径不分叉
2. 保持 migration/init 入口唯一
3. 保持备份/恢复文档与实际行为一致
4. 保持 EXE 与服务端路径都能支撑最终验收链

不再新增新的部署产品方向。

---

## 13. Go / No-Go 判定

### Go

允许进入最后一个封板项（`最终验收封板`），当且仅当：

- EXE、Compose、K8s 三条交付物边界已明确
- migration/init 边界已明确
- backup/restore 边界已明确
- 客户手册已能指导验收链

### No-Go

以下任一情况成立，都不允许认为部署与恢复已封板：

- 交付路径还在继续增加
- init/migration 仍然依赖临时手工步骤
- backup/restore 只是口头方案
- 文档与实际产品行为不一致

---

## 14. 下一步

部署与恢复封板完成后，严格进入最后一个封板项：

- `最终验收封板`

接下来重点不再是补模块，而是按冻结好的 1.0 边界完成最终客户视角的验收定义与封板判定。 
