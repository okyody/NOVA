# NOVA 1.0 Runtime 封板清单

本文档用于冻结 `NOVA 1.0` 运行时的边界、职责、拓扑、运行规则与验收标准。

目标：

- 把 runtime 从“工程骨架”收成“可交付运行系统”
- 明确 1.0 的角色划分、事件链路、持久化、可观测性和降级策略
- 为 `AI 质量封板`、`Windows EXE 封板`、`部署与恢复封板` 提供统一运行基线

---

## 1. 1.0 Runtime 定义

`NOVA 1.0 Runtime` 的定义是：

> 一个能够接收实时事件、完成感知/认知/生成处理、输出结果、留下状态与审计，并可被控制面观察和验证的运行系统。

它不是：

- 通用多 Agent 计算平台
- 大规模自治协商系统
- 任意拓扑任意角色的动态编排框架

1.0 的 runtime 必须强调：

- 稳定
- 可观察
- 可解释
- 可验收

---

## 2. Runtime 拓扑冻结

1.0 参考拓扑冻结为：

- `nova-api`
- `nova-perception`
- `nova-cognitive`
- `nova-generation`
- `redis`
- `postgres`
- `qdrant`
- `ollama`

其中：

- `api`：控制面、健康检查、Studio、配置入口
- `perception`：事件入口、聚合、上下文检测、静默检测
- `cognitive`：memory / emotion / personality / nlu / tools / orchestrator
- `generation`：voice / lip sync / avatar command

1.0 阶段不再新增新的核心 runtime role。

---

## 3. Role 边界冻结

### 3.1 `api`

负责：

- HTTP API
- Studio
- auth / control-plane access
- health / metrics
- config APIs

不负责：

- 承担全部 perception/cognitive/generation 实时负载

### 3.2 `perception`

负责：

- 入口事件处理
- semantic aggregation
- context update
- silence detection

不负责：

- 最终回复生成
- 配置治理

### 3.3 `cognitive`

负责：

- memory
- emotion
- personality
- nlu
- tool routing
- orchestrator
- safety 前的认知主链

### 3.4 `generation`

负责：

- TTS
- lip sync
- avatar command generation

不负责：

- 控制平面逻辑
- 租户权限逻辑

---

## 4. 事件链冻结

1.0 运行时链路冻结为：

1. 入口事件进入 perception
2. perception 完成语义聚合和上下文信号提取
3. cognitive 完成 NLU / memory / emotion / tool / orchestrator
4. safety 对输出进行检查
5. generation 生成语音与表现参数
6. history / hot state / audit / metrics 可回查

1.0 不再继续扩张新的主链阶段。

---

## 5. Event Bus 边界

1.0 EventBus 的目标不是“终极分布式系统”，而是：

- local mode 可用
- external_consumer mode 可用
- Redis Streams consumer group 基础可用
- pending / reclaim / retry / DLQ 可见

必须具备：

- ingress idempotency
- runtime queue/lag 可观测
- DLQ replay 工具链

1.0 不强求：

- 大规模跨集群路由
- 复杂 topic mesh
- 完整通用工作流引擎

---

## 6. 热状态与持久化冻结

### 6.1 热状态

1.0 必须具备：

- runtime hot state
- session summary
- viewer hot state
- idempotency key

热状态目的：

- 运行时观察
- 当前 session 可见
- 多 worker 基础一致性

### 6.2 持久化

1.0 必须具备：

- conversation history
- safety events
- runtime sessions
- runtime viewers
- audit logs

1.0 不要求：

- 完整历史湖仓
- 高级分析仓

---

## 7. 可观测性冻结

1.0 运行时必须通过以下入口可观察：

- `/health`
- `/metrics`
- Studio Dashboard
- Studio Events
- runtime history APIs
- audit APIs

至少要能看见：

- runtime role
- queue depth
- lag
- pending
- retries
- DLQ length
- history count
- current user context

---

## 8. 降级与容错边界

1.0 必须保留的容错能力：

- circuit breaker
- fallback responder
- retry / DLQ 基础设施
- health monitor
- config save 后的 restart_required 提示

1.0 不继续扩张：

- 复杂自愈编排
- 大规模自动故障迁移
- 多集群自动接管

---

## 9. AI 运行边界

Runtime 与 AI 的边界在 1.0 必须明确：

- semantic aggregation 使用 embedding 路径
- NLU / emotion 参与 routing
- runtime 负责“稳定执行”
- AI 质量评估由后续 `AI 质量封板` 单独冻结

Runtime 封板不再扩写新的 AI 能力模块，只保证：

- 链路稳定
- 状态可见
- 输入输出可追踪

---

## 10. Windows EXE 与 Runtime 关系

1.0 的 Windows EXE 不是独立逻辑产品，而是 runtime 的桌面封装。

因此 EXE 必须满足：

- 能启动同一套 runtime
- 能打开同一套 Studio
- 能读写同一套配置
- 不引入第二套隐藏逻辑

这意味着：

- EXE 封板必须从属于 Runtime 封板
- 不允许 EXE 和服务端运行时行为长期分叉

---

## 11. 运行时验收标准

只有下面全部成立，Runtime 封板才算通过：

1. runtime 角色边界明确
2. perception -> cognitive -> generation 主链可运行
3. hot state 可查询
4. history / safety / audit 可查询
5. `/health` 可返回关键运行态
6. `/metrics` 可返回关键指标
7. Studio 能看到 runtime 核心状态
8. Redis Streams / pending / retry / DLQ 基础存在并可观察
9. config 保存/角色重载链可用
10. Windows EXE 能拉起同一套 runtime

---

## 12. 1.0 剩余收口重点

Runtime 在 1.0 剩余最值得继续做的事只保留：

1. 保持角色边界稳定
2. 保持 health / metrics / Studio 三者一致
3. 保持 history / audit / hot state 回查稳定
4. 避免新的运行角色和新链路继续插入主路径

不再新增新的主运行阶段。

---

## 13. Go / No-Go 判定

### Go

允许进入下一个封板项（`AI 质量封板`），当且仅当：

- runtime 主链已稳定
- 角色边界已冻结
- 可观测性入口齐备
- 历史与审计回查可用

### No-Go

以下任一情况成立，都不允许认为 Runtime 已封板：

- 角色职责仍然混乱
- 主链不稳定
- 关键运行态不可见
- history / audit / hot state 不能稳定回查
- EXE 和 runtime 行为明显分叉

---

## 14. 下一步

Runtime 封板完成后，严格进入下一个封板项：

- `AI 质量封板`

后续重点将从“系统能不能跑”转到“AI 响应质量能不能稳定达标”。 
