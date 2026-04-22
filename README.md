# NOVA — Next-gen Omnimodal Virtual Agent

AI 虚拟主播系统，事件驱动架构，支持多平台直播弹幕交互。

## 架构

```
平台弹幕 → EventBus → SemanticAggregator → Orchestrator(记忆+情绪+人格+LLM+RAG+NLU+Tools)
                       ContextSensor ↗                              ↓
                                                          SafetyGuard
                                                               ↓
                    AvatarDriver ← LipSyncEngine ← VoicePipeline(TTS Fallback Chain)
```

**六大核心模块**：
- `packages/core/` — EventBus 事件总线 + Types 类型系统 + Config 配置 + Logger 日志
- `packages/perception/` — SemanticAggregator 弹幕聚合 + SilenceDetector 沉默检测 + ContextSensor 情境感知
- `packages/cognitive/` — Orchestrator 编排器 + 情绪/记忆/人格代理 + NLU意图分类 + Tool调用 + 主动智能 + 记忆整合
- `packages/knowledge/` — EmbeddingService嵌入服务 + VectorStore向量存储 + KnowledgeBase知识库 + RAG提示构建
- `packages/generation/` — VoicePipeline 语音管线 + TTS Fallback Chain + LipSync 唇形同步 + AvatarDriver Live2D + SD图像生成
- `packages/ops/` — SafetyGuard 安全守卫 + CircuitBreaker熔断器 + HealthMonitor健康监控 + Metrics指标收集 + StatePersistence状态持久化
- `packages/platform/` — 多平台适配器 (Bilibili / Douyin / YouTube / Twitch / Kuaishou / WeChat) + PlatformManager

## 快速开始

### 方式一：交互式安装

```bash
# Linux/macOS
bash install.sh

# Windows
install.bat

# 或使用配置向导
python setup_wizard.py
```

### 方式二：手动安装

```bash
# 1. 安装依赖
pip install -e .

# 2. 配置
cp nova.config.example.json nova.config.json
# 编辑 nova.config.json，填入平台信息

# 3. 启动 Ollama（LLM 后端）
ollama pull qwen2.5:14b

# 4. 启动 NOVA
python -m apps.nova_server.main
```

### 方式三：Docker 部署

```bash
docker-compose up -d
```

包含：NOVA服务 + Ollama LLM + Qdrant向量库 + Grafana监控

## 功能特性

### Phase 3 新增（智能跃升）

| 功能 | 模块 | 说明 |
|------|------|------|
| RAG知识库 | `packages/knowledge/` | 文档摄入 + 向量检索 + 提示增强，支持Ollama/OpenAI嵌入 + InMemory/Qdrant存储 |
| NLU意图分类 | `packages/cognitive/nlu.py` | 规则+LLM混合意图识别（提问/闲聊/命令/问候/情感/话题/请求） |
| Tool/Function Calling | `packages/cognitive/tool_calling.py` | LLM工具调用：搜索知识库、查看观众信息、调整情绪、回忆记忆 |
| 主动智能 | `packages/cognitive/proactive.py` | 上下文驱动的主动发言策略（知识分享/话题建议/互动提示/小游戏） |
| 记忆整合 | `packages/cognitive/memory_consolidation.py` | LLM驱动的短期→长期记忆整合 + 去重 + 洞察提取 |
| 流式响应 | `packages/cognitive/orchestrator.py` | 逐token流式输出 + 句级分割 + STREAM_TOKEN实时事件 |
| Stable Diffusion | `packages/generation/sd_client.py` | 文生图能力（需SD WebUI） |

### Phase 4 新增（生产加固）

| 功能 | 模块 | 说明 |
|------|------|------|
| 熔断器 | `packages/ops/circuit_breaker.py` | 外部服务故障自动熔断 + 半开恢复 + 降级回退 |
| 健康监控 | `packages/ops/health_monitor.py` | 组件健康检查 + 内存泄漏检测 + 队列深度监控 |
| 状态持久化 | `packages/cognitive/state_persistence.py` | JSON/Redis状态存储，重启后恢复记忆和观众图 |
| 指标收集 | `packages/ops/metrics.py` | Prometheus兼容指标：LLM延迟/安全检查/TTS延迟/管线延迟等 |
| 统一日志 | `packages/core/logger.py` | structlog结构化日志 + JSON输出 + trace_id绑定 |

## 测试

```bash
pytest tests/ -v
```

Phase 1-3 集成测试全覆盖：核心单元测试 + 端到端测试 + RAG/NLU/Tool/Proactive/Consolidation测试。

## API 端点

| 端点 | 方法 | 用途 |
|------|------|------|
| `/health` | GET | 健康检查（含安全/平台/知识库/NLU/工具状态） |
| `/metrics` | GET | Prometheus 指标 |
| `/api/config/reload` | POST | 热重载角色卡片 |
| `/api/knowledge/ingest` | POST | 上传知识文档到RAG |
| `/api/knowledge/stats` | GET | 知识库统计 |
| `/ws/control` | WS | Studio 实时监控 WebSocket |
| `/studio/` | GET | Nova Studio 管理面板 |
| `/studio/api/status` | GET | Studio 状态 API |

## TTS 后端

| 后端 | 类型 | 配置值 | 说明 |
|------|------|--------|------|
| edge-tts | 免费 | `edge_tts` | 默认后端，零成本，低延迟 |
| CosyVoice2 | 本地 | `cosyvoice2` | 需要本地推理服务 |
| GPT-SoVITS | 本地 | `gptsovits` | 音色克隆 TTS |
| Azure | 云端 | `azure` | 微软认知服务 |
| ElevenLabs | 云端 | `elevenlabs` | 高质量英文 TTS |
| Chain | 混合 | `chain` | 自动降级链，按 `chain_order` 顺序尝试 |

## 平台支持

| 平台 | 协议 | 特性 |
|------|------|------|
| Bilibili | WebSocket | 弹幕、礼物、SC、舰长、关注 |
| Douyin | WebHook | 弹幕、礼物连击合并 |
| YouTube | Polling API | Live Chat 轮询、配额管理、自适应轮询 |
| Twitch | IRC WebSocket | 弹幕、Bits、订阅、Raid |
| Kuaishou | WebSocket | 弹幕、礼物（Stub） |
| WeChat | API | 评论、打赏（Stub） |

## 知识库配置

```json
{
  "knowledge": {
    "enabled": true,
    "embedding": {
      "backend": "ollama",
      "model": "nomic-embed-text"
    },
    "vector_store": {
      "backend": "memory"
    }
  }
}
```

知识文档放在 `knowledge/` 目录下，支持 `.toml` 格式，启动时自动加载。

## Phase 进度

- [x] Phase 0: 骨架已就位
- [x] Phase 1: 核心可运行（包结构 + Bug 修复 + 感知层 + 端到端联调）
- [x] Phase 2: 功能平价（多平台 + TTS Fallback Chain + Avatar/LipSync + Studio UI）
- [x] Phase 3: 智能跃升（RAG知识库 + NLU意图 + Tool调用 + 主动智能 + 记忆整合 + 流式响应）
- [x] Phase 4: 生产加固（熔断器 + 健康监控 + 状态持久化 + 指标收集 + 统一日志）
- [ ] Phase 5: 前沿探索（多模态 + Agent协作 + 长期记忆图）
