"""
NOVA Server — Main Entry Point (v2.0 Enterprise)
=================================================
Wires all components together and runs the event loop.

Startup order (dependencies must start before dependents):
  1. Logging & Tracing
  2. EventBus
  3. Perception Layer
  4. Knowledge Layer (optional — RAG)
  5. Memory Agent (with Consolidator)
  6. Emotion Agent
  7. Personality Agent
  8. NLU Intent Classifier
  9. Tool Registry + Executor
  10. Proactive Intelligence
  11. Orchestrator (depends on 5,6,7 + KB, NLU, Tools)
  12. Safety Guard (intercepts orchestrator output → publishes SAFE_OUTPUT)
  13. Voice Pipeline (depends on SAFE_OUTPUT) + LipSync
  14. Avatar Driver (receives AVATAR_COMMAND)
  15. Platform Manager (begin event ingestion last)
  16. Circuit Breaker + Fallback Responder
  17. Health Monitor
  18. State Persistence (restore on startup, save on shutdown)

FastAPI provides:
  - /health  — liveness check for container orchestration
  - /metrics — Prometheus-compatible stats
  - /ws/control — Studio UI WebSocket for real-time monitoring
  - /api/config — hot-reload character card without restart
  - /api/knowledge/ingest — upload knowledge documents
  - /api/auth/token — obtain JWT token (when auth enabled)
  - /studio/*   — Nova Studio management panel
"""
from __future__ import annotations

import asyncio
import json
import os
import signal
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, WebSocket, Request, HTTPException
from fastapi.responses import JSONResponse, PlainTextResponse

# ── Logging (must be first!) ──────────────────────────────────────────────────
from packages.core.logger import setup_logging, get_logger, bind_trace_id
from apps.nova_runtime.bootstrap import build_role_plan
from packages.core.config import NovaSettings, load_settings

# ── Component imports ─────────────────────────────────────────────────────────
from packages.core.event_bus import EventBus, create_event_transport_backend
from packages.core.types import Platform
from packages.perception.semantic_aggregator import SemanticAggregator
from packages.perception.silence_detector import SilenceDetector
from packages.perception.context_sensor import ContextSensor
from packages.knowledge.embedding_service import create_embedder
from packages.knowledge.vector_store import create_vector_store
from packages.knowledge.knowledge_base import KnowledgeBase
from packages.cognitive.emotion_agent     import EmotionAgent
from packages.cognitive.memory_agent      import MemoryAgent
from packages.cognitive.orchestrator      import Orchestrator, LLMClient
from packages.cognitive.personality_agent import PersonalityAgent
from packages.cognitive.nlu               import IntentClassifier
from packages.cognitive.tool_calling      import ToolRegistry, create_builtin_tools
from packages.cognitive.proactive         import ProactiveIntelligence
from packages.cognitive.memory_consolidation import MemoryConsolidator
from packages.generation.voice_pipeline   import VoicePipeline
from packages.generation.lip_sync         import LipSyncEngine
from packages.generation.avatar_driver    import AvatarDriver
from packages.generation.tts_factory      import create_tts_backend
from packages.ops.safety_guard            import SafetyGuard
from packages.ops.circuit_breaker         import CircuitBreaker, FallbackResponder
from packages.ops.health_monitor          import HealthMonitor, SimpleHealthCheck
from packages.ops.metrics                 import MetricsCollector, metrics as global_metrics
from packages.ops.postgres_store          import PostgresRuntimeStore
from packages.ops.security_middleware     import setup_security_middleware, InputValidator
from packages.ops.hot_state               import HotStateSync, RuntimeSessionState, RuntimeStateProjector, create_hot_state_backend
from packages.ops.tracing                 import setup_tracing
from packages.cognitive.state_persistence import StateManager, create_persistence_backend
from packages.platform.manager            import PlatformManager


# ── Application state ─────────────────────────────────────────────────────────

class NovaApp:
    """Holds all running components. Passed via app.state."""

    def __init__(self, settings: NovaSettings) -> None:
        self.settings = settings
        # Core
        self.bus:                EventBus | None              = None
        # Perception
        self.aggregator:         SemanticAggregator | None     = None
        self.silence:            SilenceDetector | None        = None
        self.context:            ContextSensor | None          = None
        # Knowledge
        self.embedder:           Any | None                    = None
        self.vector_store:       Any | None                    = None
        self.knowledge_base:     KnowledgeBase | None          = None
        # Cognitive
        self.memory:             MemoryAgent | None            = None
        self.emotion:            EmotionAgent | None           = None
        self.personality:        PersonalityAgent | None       = None
        self.nlu:                IntentClassifier | None       = None
        self.tool_registry:      ToolRegistry | None           = None
        self.proactive:          ProactiveIntelligence | None  = None
        self.consolidator:       MemoryConsolidator | None     = None
        self.orchestrator:       Orchestrator | None           = None
        # Ops
        self.safety:             SafetyGuard | None            = None
        self.circuit_breaker:    CircuitBreaker | None         = None
        self.fallback:           FallbackResponder | None      = None
        self.health_monitor:     HealthMonitor | None          = None
        self.state_mgr:          StateManager | None           = None
        self.postgres_store:     PostgresRuntimeStore | None   = None
        self.metrics:            MetricsCollector              = global_metrics
        self.jwt_auth:           Any | None                    = None
        self.hot_state:          HotStateSync | None           = None
        self.hot_projector:      RuntimeStateProjector | None  = None
        self.hot_session:        RuntimeSessionState | None    = None
        self._hot_session_started: bool                         = False
        # Generation
        self.voice:              VoicePipeline | None          = None
        self.lipsync:            LipSyncEngine | None          = None
        self.avatar:             AvatarDriver | None           = None
        # Platform
        self.platform_mgr:       PlatformManager | None        = None
        # Internal
        self._llm:               LLMClient | None              = None

    async def startup(self) -> None:
        cfg = self.settings
        log = get_logger("nova.server")
        runtime_cfg = cfg.runtime
        role_plan = build_role_plan(runtime_cfg.role)
        role = role_plan.role
        run_bus = role_plan.run_bus
        run_perception = role_plan.run_perception
        run_cognitive = role_plan.run_cognitive
        run_generation = role_plan.run_generation
        run_platform_ingress = role_plan.run_platform_ingress
        kb = cfg.knowledge

        log.info("═══════════════════════════════════")
        log.info("  NOVA — Next-gen Omnimodal Virtual Agent")
        log.info("  Version 2.0 Enterprise")
        log.info("═══════════════════════════════════")

        ingress_backend = None
        if cfg.persistence.backend == "redis" and runtime_cfg.hot_state_enabled:
            ingress_backend = create_hot_state_backend({
                "backend": "redis",
                "url": cfg.persistence.redis_url,
                "db": cfg.persistence.redis_db,
            })

        transport_backend = create_event_transport_backend({
            "backend": runtime_cfg.event_bus_backend,
            "url": cfg.persistence.redis_url,
            "db": cfg.persistence.redis_db,
            "stream": runtime_cfg.event_bus_stream,
            "consumer_group": runtime_cfg.event_bus_consumer_group,
            "consumer_name": runtime_cfg.event_bus_consumer_name,
            "pending_min_idle_ms": runtime_cfg.event_bus_pending_min_idle_ms,
            "reclaim_batch_size": runtime_cfg.event_bus_reclaim_batch_size,
            "max_retries": runtime_cfg.event_bus_max_retries,
            "dlq_stream": runtime_cfg.event_bus_dlq_stream,
        })

        # 1. Event bus
        if run_bus:
            self.bus = EventBus(
                queue_size=8192,
                transport_backend=transport_backend,
                ingress_idempotency_backend=ingress_backend,
                ingress_idempotency_namespace=runtime_cfg.instance_name,
                ingress_idempotency_ttl_s=runtime_cfg.idempotency_ttl_s,
                mode=runtime_cfg.event_bus_mode,
            )
            await self.bus.start()

        # 2. Perception layer
        perc = cfg.perception
        if run_perception and self.bus:
            if self.embedder is None:
                self.embedder = create_embedder({
                    "backend": kb.embedding_backend,
                    "base_url": kb.embedding_base_url,
                    "model": kb.embedding_model,
                    "api_key": kb.embedding_api_key.get_secret_value() if kb.embedding_api_key.get_secret_value() else "",
                })
            self.aggregator = SemanticAggregator(
                self.bus,
                window_ms=perc.aggregator_window_ms,
                embedder=self.embedder,
            )
            await self.aggregator.start()

            self.silence = SilenceDetector(self.bus, silence_sec=perc.silence_threshold_s)
            await self.silence.start()

            self.context = ContextSensor(self.bus, update_interval_s=perc.context_update_s)
            await self.context.start()

        # 3. Knowledge layer (optional — RAG)
        if run_cognitive and kb.enabled:
            if self.embedder is None:
                self.embedder = create_embedder({
                    "backend": kb.embedding_backend,
                    "base_url": kb.embedding_base_url,
                    "model": kb.embedding_model,
                    "api_key": kb.embedding_api_key.get_secret_value() if kb.embedding_api_key.get_secret_value() else "",
                })
            self.vector_store = create_vector_store({
                "backend": kb.vector_backend,
                "url": kb.qdrant_url,
            })
            self.knowledge_base = KnowledgeBase(
                embedder=self.embedder,
                store=self.vector_store,
            )
            log.info("Knowledge base initialized (embedding=%s, store=%s)",
                     kb.embedding_backend, kb.vector_backend)

            # Auto-ingest knowledge documents
            knowledge_dir = Path("knowledge")
            if knowledge_dir.exists():
                try:
                    import tomllib
                except ImportError:
                    import tomli as tomllib
                for f in knowledge_dir.glob("*.toml"):
                    try:
                        data = tomllib.loads(f.read_text(encoding="utf-8"))
                        docs = data.get("documents", [])
                        for doc in docs:
                            await self.knowledge_base.ingest(
                                text=doc.get("text", ""),
                                source_id=doc.get("source_id", f.stem),
                                metadata=doc.get("metadata"),
                            )
                        log.info("Loaded knowledge from %s (%d docs)", f.name, len(docs))
                    except Exception as e:
                        log.error("Failed to load knowledge %s: %s", f.name, e)
        elif run_cognitive:
            log.info("Knowledge base disabled (set NOVA_KNOWLEDGE__ENABLED=true)")

        # 4-6. Cognitive agents
        if run_cognitive and self.bus:
            self.memory = MemoryAgent(self.bus)
            await self.memory.start()

            self.emotion = EmotionAgent(self.bus)
            await self.emotion.start()

            char_path = cfg.character.path
            self.personality = PersonalityAgent(
                self.bus,
                character_path=Path(char_path) if char_path else None,
            )
            await self.personality.start()

        # 7. NLU Intent Classifier
        if run_cognitive and cfg.nlu.enabled:
            self.nlu = IntentClassifier(llm_client=None)
            log.info("NLU intent classifier initialized")

        # 8. Tool Registry
        if run_cognitive and cfg.tools.enabled:
            self.tool_registry = ToolRegistry()
            builtin_tools = create_builtin_tools(
                knowledge_base=self.knowledge_base,
                memory_agent=self.memory,
                emotion_agent=self.emotion,
                viewer_graph=self.memory.viewer_graph,
            )
            for tool in builtin_tools:
                self.tool_registry.register(tool)
            log.info("Tool registry initialized (%d tools)", len(self.tool_registry.list_names()))

        # 9. Proactive Intelligence
        if run_cognitive and self.bus:
            self.proactive = ProactiveIntelligence(
                bus=self.bus,
                knowledge_base=self.knowledge_base,
            )

        # Memory Consolidator
        if run_cognitive and cfg.consolidation.enabled:
            self.consolidator = MemoryConsolidator(llm_client=None)

        # 10. Orchestrator (with Circuit Breaker + Metrics)
        llm_cfg = cfg.llm
        res = cfg.resilience
        if run_cognitive and self.bus:
            self._llm = LLMClient(
                base_url=llm_cfg.base_url,
                api_key=llm_cfg.api_key.get_secret_value(),
                model=llm_cfg.model,
                timeout=llm_cfg.timeout,
            )

            if res.circuit_breaker_enabled:
                self.circuit_breaker = CircuitBreaker(
                    name="llm",
                    failure_threshold=res.circuit_breaker_threshold,
                    recovery_timeout=res.circuit_breaker_recovery_s,
                )
                self.fallback = FallbackResponder(
                    character=self.personality.character if self.personality else None
                )
                log.info("Circuit breaker enabled (threshold=%d, recovery=%.0fs)",
                         res.circuit_breaker_threshold, res.circuit_breaker_recovery_s)

            self.orchestrator = Orchestrator(
                bus=self.bus,
                llm=self._llm,
                memory_agent=self.memory,
                emotion_agent=self.emotion,
                personality_agent=self.personality,
                knowledge_base=self.knowledge_base,
                tool_registry=self.tool_registry,
                nlu=self.nlu,
                circuit_breaker=self.circuit_breaker,
                fallback_responder=self.fallback,
                metrics=self.metrics,
            )
            await self.orchestrator.start()

            # 11. Safety guard
            self.safety = SafetyGuard(self.bus)
            await self.safety.start()

        # 12. Voice pipeline
        voice_cfg = cfg.voice
        if run_generation and self.bus:
            tts_backend = create_tts_backend({
                "backend": voice_cfg.backend,
                "voice_id": voice_cfg.voice_id,
                "cosyvoice2_url": voice_cfg.cosyvoice2_url,
                "gptsovits_url": voice_cfg.gpt_sovits_url,
                "voices_dir": voice_cfg.voices_dir,
                "speaker": voice_cfg.speaker,
                "azure_key": voice_cfg.azure_api_key.get_secret_value(),
                "azure_region": voice_cfg.azure_region,
                "elevenlabs_key": voice_cfg.elevenlabs_api_key.get_secret_value(),
                "elevenlabs_voice": voice_cfg.elevenlabs_voice_id,
                "chain_order": voice_cfg.fallback_chain,
            })
            self.voice = VoicePipeline(
                self.bus,
                backend=tts_backend,
                voice_id=voice_cfg.voice_id,
            )
            await self.voice.start()

            # LipSync
            self.lipsync = LipSyncEngine(self.bus)
            await self.lipsync.start()

            # 13. Avatar driver
            avatar_cfg = cfg.avatar
            if avatar_cfg.enabled:
                self.avatar = AvatarDriver(self.bus, ws_port=avatar_cfg.ws_port)
                await self.avatar.start()

        # 14. Platform manager
        if run_platform_ingress and self.bus:
            self.platform_mgr = PlatformManager(self.bus)
            platforms_list = [
                {
                    "platform": p.platform,
                    "room_id": p.room_id,
                    "token": p.token.get_secret_value() if p.token.get_secret_value() else "",
                    "uid": p.uid,
                    "app_id": p.app_id,
                    "app_secret": p.app_secret.get_secret_value() if p.app_secret.get_secret_value() else "",
                    "live_chat_id": p.live_chat_id,
                    "api_key": p.api_key.get_secret_value() if p.api_key.get_secret_value() else "",
                    "poll_interval": p.poll_interval,
                    "channel": p.channel,
                    "oauth_token": p.oauth_token.get_secret_value() if p.oauth_token.get_secret_value() else "",
                    "username": p.username,
                    "webhook_port": p.webhook_port,
                    "mode": p.mode,
                }
                for p in cfg.platforms
            ]
            await self.platform_mgr.start(platforms_list)

        # 15. Health monitor
        if run_bus and self.bus:
            self.health_monitor = HealthMonitor(self.bus, check_interval_s=res.health_check_interval_s)
            await self.health_monitor.start()

        async def _check_event_bus():
            return SimpleHealthCheck.from_condition("event_bus", self.bus is not None)

        async def _check_safety():
            return SimpleHealthCheck.from_condition("safety", self.safety is not None)

        async def _check_orchestrator():
            return SimpleHealthCheck.from_condition("orchestrator", self.orchestrator is not None)

        async def _check_knowledge_base():
            return SimpleHealthCheck.from_condition(
                "knowledge_base",
                (not cfg.knowledge.enabled) or self.knowledge_base is not None,
            )

        if self.health_monitor:
            self.health_monitor.register_check("event_bus", _check_event_bus)
            self.health_monitor.register_check("safety", _check_safety)
            self.health_monitor.register_check("orchestrator", _check_orchestrator)
            self.health_monitor.register_check("knowledge_base", _check_knowledge_base)
            log.info("Health monitor started (interval=%ds)", res.health_check_interval_s)

        # 16. State persistence
        persist = cfg.persistence
        if persist.enabled and run_cognitive:
            backend = create_persistence_backend({
                "backend": persist.backend,
                "base_dir": persist.base_dir,
                "url": persist.redis_url,
                "db": persist.redis_db,
                "ttl": persist.redis_ttl,
            })
            self.state_mgr = StateManager(backend=backend, auto_save_interval_s=persist.auto_save_interval_s)
            await self.state_mgr.start()
            # Restore state from previous run
            if self.memory:
                restored = await self.state_mgr.restore_memory_state(self.memory)
                if restored:
                    log.info("Restored memory state from persistence")
            if self.emotion:
                restored = await self.state_mgr.restore_emotion_state(self.emotion)
                if restored:
                    log.info("Restored emotion state from persistence")

        if persist.backend == "redis" and runtime_cfg.hot_state_enabled:
            hot_backend = ingress_backend or create_hot_state_backend({
                "backend": "redis",
                "url": persist.redis_url,
                "db": persist.redis_db,
            })
            self.hot_state = HotStateSync(
                hot_backend,
                interval_s=runtime_cfg.hot_state_sync_interval_s,
                ttl_s=min(runtime_cfg.hot_state_ttl_s, 60),
                runtime_name=runtime_cfg.instance_name,
            )
            self.hot_state.bind(
                runtime=lambda: {
                    "started_at": time.time(),
                    "queue_depth": self.bus.stats().get("queue_depth", 0) if self.bus else 0,
                    "tools_enabled": bool(self.tool_registry),
                    "knowledge_enabled": self.knowledge_base is not None,
                },
                context=lambda: {
                    "heat_level": self.context.current_context.heat_level.value if self.context else "normal",
                    "chat_rate": self.context.current_context.chat_rate if self.context else 0.0,
                    "gift_rate": self.context.current_context.gift_rate if self.context else 0.0,
                    "viewer_count": self.context.current_context.viewer_count if self.context else 0,
                },
                emotion=lambda: {
                    "label": self.emotion.current_state.label.value if self.emotion else "neutral",
                    "valence": self.emotion.current_state.valence if self.emotion else 0.0,
                    "arousal": self.emotion.current_state.arousal if self.emotion else 0.0,
                    "intensity": self.emotion.current_state.intensity if self.emotion else 0.0,
                },
                platforms=lambda: self.platform_mgr.get_status() if self.platform_mgr else {},
            )
            await self.hot_state.start()
            self.hot_projector = RuntimeStateProjector(
                hot_backend,
                runtime_name=runtime_cfg.instance_name,
                ttl_s=runtime_cfg.hot_state_ttl_s,
            )
            self.hot_session = RuntimeSessionState(
                hot_backend,
                runtime_name=runtime_cfg.instance_name,
                session_id=runtime_cfg.session_id,
                ttl_s=runtime_cfg.hot_state_ttl_s,
                idempotency_ttl_s=runtime_cfg.idempotency_ttl_s,
            )
            if run_bus:
                await self.hot_session.mark_session_started({
                    "character": self.personality.character_name if self.personality else "Nova",
                    "llm_model": self._llm.model if self._llm else "",
                    "role": role,
                })
                self._hot_session_started = True

            async def _project_hot_state(event):
                if self.hot_projector:
                    await self.hot_projector.project_event(event.type.value, event.payload)
                if self.hot_session:
                    await self.hot_session.project_event(event.event_id, event.type.value, event.payload)
                    if self.postgres_store:
                        summary = await self.hot_session.get_session() or {}
                        await self.postgres_store.upsert_runtime_session(summary, status="running")
                        viewer = event.payload.get("viewer") or {}
                        viewer_id = str(viewer.get("viewer_id", "")).strip()
                        if viewer_id:
                            viewer_state = await self.hot_session.get_viewer(viewer_id)
                            if viewer_state:
                                await self.postgres_store.upsert_runtime_viewer(viewer_id, viewer_state)

            if self.bus:
                for et in (
                    EventType.CHAT_MESSAGE,
                    EventType.GIFT_RECEIVED,
                    EventType.SUPER_CHAT,
                    EventType.FOLLOW,
                    EventType.VIEWER_JOIN,
                    EventType.SAFE_OUTPUT,
                ):
                    self.bus.subscribe(et, _project_hot_state, sub_id=f"hot_state_{et.name.lower()}")

        if self.bus and (persist.persist_conversations or persist.persist_safety):
            self.postgres_store = PostgresRuntimeStore(
                persist.postgres_url,
                schema=persist.postgres_schema,
                runtime_instance=runtime_cfg.instance_name,
                session_id=runtime_cfg.session_id,
                persist_conversations=persist.persist_conversations,
                persist_safety=persist.persist_safety,
            )
            await self.postgres_store.start()

            async def _persist_runtime_event(event):
                if self.postgres_store:
                    await self.postgres_store.persist_event(event)

            if persist.persist_conversations:
                self.bus.subscribe(EventType.CHAT_MESSAGE, _persist_runtime_event, sub_id="pg_chat")
                self.bus.subscribe(EventType.SAFE_OUTPUT, _persist_runtime_event, sub_id="pg_safe_output")
            if persist.persist_safety:
                self.bus.subscribe(EventType.SAFETY_BLOCK, _persist_runtime_event, sub_id="pg_safety_block")

            if self.hot_session and self._hot_session_started:
                summary = await self.hot_session.get_session() or {}
                await self.postgres_store.upsert_runtime_session(summary, status="running")
                await self.postgres_store.write_audit_log(
                    "runtime_session_started",
                    "runtime_session",
                    summary,
                    resource_id=runtime_cfg.session_id,
                )

        log.info(
            "NOVA started. Character: %s | LLM: %s | KB: %s | NLU: %s | Tools: %s | "
            "Auth: %s | Trace: %s | Platforms: %d | Avatar: %s",
            self.personality.character_name,
            self._llm.model,
            "ON" if self.knowledge_base else "OFF",
            "ON" if self.nlu else "OFF",
            ",".join(self.tool_registry.list_names()) if self.tool_registry else "OFF",
            "ON" if cfg.auth.enabled else "OFF",
            "ON" if cfg.observability.tracing_enabled else "OFF",
            len(self.platform_mgr._adapters) if self.platform_mgr else 0,
            "ON" if self.avatar else "OFF",
        )

    async def shutdown(self) -> None:
        log = get_logger("nova.server")
        log.info("Shutting down NOVA…")

        # Save state before stopping
        if self.state_mgr and self.memory:
            try:
                await self.state_mgr.save_all(memory=self.memory, emotion=self.emotion)
                log.info("State saved before shutdown")
            except Exception as e:
                log.error("Failed to save state: %s", e)

        # Stop in reverse order of startup
        components = [
            self.health_monitor, self.platform_mgr, self.avatar, self.lipsync,
            self.voice, self.safety, self.orchestrator, self.emotion, self.memory,
            self.personality, self.context, self.silence, self.aggregator,
        ]
        for comp in components:
            if comp and hasattr(comp, "stop"):
                try:
                    await comp.stop()
                except Exception as e:
                    log.error("Error stopping %s: %s", type(comp).__name__, e)

        # Close knowledge resources
        if self.embedder and hasattr(self.embedder, "close"):
            await self.embedder.close()
        if self.postgres_store:
            if self.hot_session and self._hot_session_started:
                await self.postgres_store.stop_runtime_session()
                await self.postgres_store.write_audit_log(
                    "runtime_session_stopped",
                    "runtime_session",
                    {"session_id": self.settings.runtime.session_id},
                    resource_id=self.settings.runtime.session_id,
                )
            await self.postgres_store.stop()
        if self.hot_session and self._hot_session_started:
            await self.hot_session.mark_session_stopped()
        if self.hot_state:
            await self.hot_state.stop()
        if self.state_mgr:
            await self.state_mgr.stop()
        if self.bus:
            await self.bus.stop()
        log.info("NOVA shutdown complete.")


# ── FastAPI application ───────────────────────────────────────────────────────

log = get_logger("nova.server")


def create_app(settings_override: NovaSettings | None = None) -> FastAPI:
    settings = settings_override or load_settings()

    setup_logging(
        level=settings.observability.log_level,
        json_output=settings.observability.log_json,
        log_file=settings.observability.log_file,
    )

    setup_tracing(
        service_name=settings.observability.tracing_service_name,
        endpoint=settings.observability.tracing_endpoint,
        enabled=settings.observability.tracing_enabled,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        nova = app.state.nova
        loop = asyncio.get_running_loop()

        def _signal_handler():
            log.info("Received shutdown signal")
            asyncio.create_task(nova.shutdown())

        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(sig, _signal_handler)
            except NotImplementedError:
                pass

        await nova.startup()
        yield
        await nova.shutdown()

    app = FastAPI(
        title="NOVA Server",
        version="2.0.0",
        lifespan=lifespan,
        docs_url="/docs" if settings.debug else None,
        redoc_url="/redoc" if settings.debug else None,
    )

    app.state.nova = NovaApp(settings)

    jwt_auth = setup_security_middleware(
        app,
        auth_enabled=settings.auth.enabled,
        jwt_secret=settings.auth.jwt_secret.get_secret_value(),
        jwt_expire_minutes=settings.auth.jwt_expire_minutes,
        api_keys={settings.auth.api_key.get_secret_value()} if settings.auth.api_key.get_secret_value() else None,
        allowed_origins=settings.auth.allowed_origins,
    )
    app.state.nova.jwt_auth = jwt_auth

    from apps.nova_studio.routes import router as studio_router
    app.include_router(studio_router)
    return app


app = create_app()


async def require_permission(request: Request, permission_code: str) -> None:
    nova = request.app.state.nova
    if not nova.settings.auth.enabled:
        return

    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")

    permissions = set(user.get("permissions", []))
    if "*" in permissions or permission_code in permissions:
        return

    roles = set(user.get("roles", []))
    if {"service_admin", "super_admin", "admin"} & roles:
        return

    subject = user.get("sub")
    if subject and nova.postgres_store:
        if await nova.postgres_store.user_has_permission(subject, permission_code):
            return

    raise HTTPException(status_code=403, detail=f"Missing permission: {permission_code}")


def _is_global_admin(user: dict[str, Any]) -> bool:
    roles = set(user.get("roles", []))
    permissions = set(user.get("permissions", []))
    return bool({"service_admin", "super_admin", "admin"} & roles) or "*" in permissions


async def resolve_tenant_scope(
    request: Request,
    tenant_id: str | None = None,
    *,
    allow_global: bool = False,
) -> str | None:
    nova = request.app.state.nova
    if not nova.settings.auth.enabled:
        return tenant_id

    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")

    if _is_global_admin(user):
        return tenant_id if tenant_id or allow_global else None

    allowed_tenants = [value for value in user.get("tenant_ids", []) if value]
    if not allowed_tenants:
        raise HTTPException(status_code=403, detail="No tenant scope assigned")

    if tenant_id is None:
        return allowed_tenants[0]
    if tenant_id not in allowed_tenants:
        raise HTTPException(status_code=403, detail=f"Tenant scope denied: {tenant_id}")
    return tenant_id


def resolve_allowed_tenant_ids(request: Request, *, allow_global: bool = False) -> list[str] | None:
    nova = request.app.state.nova
    if not nova.settings.auth.enabled:
        return None
    user = getattr(request.state, "user", None)
    if not user:
        return None
    if allow_global and _is_global_admin(user):
        return None
    tenant_ids = [value for value in user.get("tenant_ids", []) if value]
    return tenant_ids or None


# ── API Endpoints ─────────────────────────────────────────────────────────────

@app.get("/health")
async def health(request: Request):
    nova = request.app.state.nova
    bus_stats = nova.bus.stats() if nova.bus else {}
    safety_stats = nova.safety.stats() if nova.safety else {}
    platform_status = nova.platform_mgr.get_status() if nova.platform_mgr else {}
    context = nova.context.current_context if nova.context else None
    kb_count = 0
    if nova.knowledge_base:
        kb_count = await nova.knowledge_base.count()
    return JSONResponse({
        "status": "ok",
        "version": "2.0.0",
        "role": nova.settings.runtime.role,
        "character": nova.personality.character_name if nova.personality else "—",
        "bus": bus_stats,
        "eventbus": {
            "pending": bus_stats.get("pending", 0),
            "lag": bus_stats.get("consumer_lag", 0),
            "retries": bus_stats.get("retries_total", 0),
            "dlq_length": bus_stats.get("dlq_length", 0),
        },
        "safety": safety_stats,
        "platforms": platform_status,
        "avatar_clients": nova.avatar.client_count if nova.avatar else 0,
        "knowledge_base": {
            "enabled": nova.knowledge_base is not None,
            "documents": kb_count,
        },
        "nlu": nova.nlu is not None,
        "tools": nova.tool_registry.list_names() if nova.tool_registry else [],
        "circuit_breaker": nova.circuit_breaker.stats() if nova.circuit_breaker else {},
        "state_persistence": nova.state_mgr is not None,
        "hot_state": nova.hot_state is not None,
        "auth": {"enabled": nova.settings.auth.enabled},
        "tracing": {"enabled": nova.settings.observability.tracing_enabled},
        "context": {
            "heat_level": context.heat_level.value,
            "chat_rate": context.chat_rate,
        } if context else {},
    })


@app.get("/metrics")
async def metrics(request: Request):
    """Prometheus-compatible plaintext metrics."""
    nova = request.app.state.nova
    stats = nova.bus.stats() if nova.bus else {}
    nova.metrics.set_queue_depth(stats.get("queue_depth", 0))
    nova.metrics.set_eventbus_pending(stats.get("pending", 0))
    nova.metrics.set_eventbus_consumer_lag(stats.get("consumer_lag", 0))
    nova.metrics.set_eventbus_stream_length(stats.get("stream_length", 0))
    nova.metrics.set_eventbus_dlq_length(stats.get("dlq_length", 0))
    nova.metrics.set_eventbus_retries_total(stats.get("retries_total", 0))
    nova.metrics.set_eventbus_reclaimed_total(stats.get("reclaimed_total", 0))
    nova.metrics.set_eventbus_dead_lettered_total(stats.get("dead_lettered_total", 0))
    content, content_type = nova.metrics.generate_metrics()
    if content:
        return PlainTextResponse(content, media_type=content_type)
    # Fallback when prometheus_client not installed
    safety = nova.safety.stats() if nova.safety else {}
    lines = [
        "# HELP nova_events_published Total events published",
        f"nova_events_published {stats.get('published', 0)}",
        f"nova_events_dropped {stats.get('dropped', 0)}",
        f"nova_safety_blocks {safety.get('blocks', 0)}",
        f"nova_safety_checks {safety.get('checks', 0)}",
        f"nova_queue_depth {stats.get('queue_depth', 0)}",
    ]
    if nova.circuit_breaker:
        cb = nova.circuit_breaker.stats()
        lines.append(f"nova_circuit_breaker_state {0 if cb['state'] == 'closed' else 1 if cb['state'] == 'open' else 2}")
    return PlainTextResponse("\n".join(lines))


@app.post("/api/config/reload")
async def reload_config(request: Request):
    """Hot-reload character card without restarting the server."""
    nova = request.app.state.nova
    if nova.personality:
        from packages.cognitive.personality_agent import CharacterCard
        char_path = nova.settings.character.path
        if char_path and Path(char_path).exists():
            nova.personality.character = CharacterCard.from_toml(Path(char_path))
            return {"status": "reloaded", "character": nova.personality.character_name}
    return JSONResponse({"status": "no character path configured"}, status_code=400)


def _resolve_config_path(nova: NovaApp) -> Path:
    path = Path(nova.settings.config_path)
    if not path.is_absolute():
        path = Path.cwd() / path
    return path


def _read_config_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _settings_to_config_json(settings: NovaSettings) -> dict[str, Any]:
    return {
        "port": settings.port,
        "llm": {
            "base_url": settings.llm.base_url,
            "model": settings.llm.model,
        },
        "voice": {
            "backend": settings.voice.backend,
            "voice_id": settings.voice.voice_id,
        },
        "character": {
            "path": settings.character.path,
        },
        "knowledge": {
            "enabled": settings.knowledge.enabled,
        },
        "persistence": {
            "backend": settings.persistence.backend,
            "redis_url": settings.persistence.redis_url,
            "postgres_url": settings.persistence.postgres_url,
        },
        "auth": {
            "enabled": settings.auth.enabled,
        },
        "runtime": {
            "role": settings.runtime.role,
        },
    }


def _validate_config_json(config_json: dict[str, Any], config_path: Path) -> NovaSettings:
    payload = dict(config_json)
    payload.setdefault("config_path", str(config_path))
    return NovaSettings(**payload)


@app.get("/api/config/current")
async def current_config(request: Request):
    """Return the persisted config document for the Studio settings workbench."""
    nova = request.app.state.nova
    if nova.settings.auth.enabled:
        await require_permission(request, "config_revision.read")
    config_path = _resolve_config_path(nova)
    config_json = _read_config_json(config_path)
    if not config_json:
        config_json = _settings_to_config_json(nova.settings)
    return {
        "status": "ok",
        "config_path": str(config_path),
        "config_json": config_json,
        "runtime": {
            "role": nova.settings.runtime.role,
            "port": nova.settings.port,
            "auth_enabled": nova.settings.auth.enabled,
        },
    }


@app.post("/api/config/current")
async def save_current_config(request: Request):
    """
    Persist the Studio-edited config file.

    This intentionally only writes validated config and reports whether a full
    runtime restart is required. Character card changes are hot-reloaded.
    """
    nova = request.app.state.nova
    if nova.settings.auth.enabled:
        await require_permission(request, "config_revision.write")
    body = await request.json()
    config_json = body.get("config_json", body)
    if not isinstance(config_json, dict):
        return JSONResponse({"status": "validation_error", "reason": "config_json must be an object"}, status_code=400)

    config_path = _resolve_config_path(nova)
    try:
        validated = _validate_config_json(config_json, config_path)
    except Exception as exc:
        return JSONResponse({"status": "validation_error", "reason": str(exc)}, status_code=400)

    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(config_json, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    previous = nova.settings
    old_character_path = previous.character.path
    new_character_path = validated.character.path
    nova.settings = validated

    character_reloaded = False
    if nova.personality and new_character_path and new_character_path != old_character_path:
        from packages.cognitive.personality_agent import CharacterCard

        char_path = Path(new_character_path)
        if char_path.exists():
            nova.personality.character = CharacterCard.from_toml(char_path)
            character_reloaded = True

    restart_required = any(
        [
            validated.port != previous.port,
            validated.auth.enabled != previous.auth.enabled,
            validated.runtime.role != previous.runtime.role,
            validated.persistence.backend != previous.persistence.backend,
            validated.knowledge.enabled != previous.knowledge.enabled,
            validated.voice.backend != previous.voice.backend,
        ]
    )

    if nova.postgres_store:
        await nova.postgres_store.write_audit_log(
            "config_file_saved",
            "config_file",
            {
                "path": str(config_path),
                "restart_required": restart_required,
                "character_reloaded": character_reloaded,
            },
            resource_id=str(config_path),
        )

    return {
        "status": "saved",
        "config_path": str(config_path),
        "restart_required": restart_required,
        "character_reloaded": character_reloaded,
    }


@app.post("/api/knowledge/ingest")
async def ingest_knowledge(request: Request):
    """Ingest text into the knowledge base for RAG retrieval."""
    nova = app.state.nova
    if not nova.knowledge_base:
        return JSONResponse({"status": "knowledge base not enabled"}, status_code=400)

    body = await request.json()
    text = body.get("text", "")
    source_id = body.get("source_id")

    # Input validation
    is_valid, reason = InputValidator.validate_text(text)
    if not is_valid:
        return JSONResponse({"status": "validation_error", "reason": reason}, status_code=400)

    chunks = await nova.knowledge_base.ingest(text=text, source_id=source_id)
    return {"status": "ingested", "chunks": chunks, "source_id": source_id}


@app.get("/api/knowledge/stats")
async def knowledge_stats(request: Request):
    """Get knowledge base statistics."""
    nova = request.app.state.nova
    if not nova.knowledge_base:
        return JSONResponse({"status": "knowledge base not enabled"}, status_code=400)
    sources = nova.knowledge_base.list_sources()
    count = await nova.knowledge_base.count()
    return {"total_documents": count, "sources": sources}


@app.get("/api/runtime/history/conversation")
async def runtime_conversation_history(request: Request):
    nova = request.app.state.nova
    if not nova.postgres_store:
        return JSONResponse({"status": "postgres runtime store not enabled"}, status_code=400)
    limit = int(request.query_params.get("limit", "100"))
    offset = int(request.query_params.get("offset", "0"))
    trace_id = request.query_params.get("trace_id")
    session_id = request.query_params.get("session_id")
    rows = await nova.postgres_store.list_conversation_turns(
        limit=limit,
        offset=offset,
        trace_id=trace_id,
        session_id=session_id,
    )
    return {"status": "ok", "count": len(rows), "items": rows}


@app.get("/api/runtime/history/safety")
async def runtime_safety_history(request: Request):
    nova = request.app.state.nova
    if not nova.postgres_store:
        return JSONResponse({"status": "postgres runtime store not enabled"}, status_code=400)
    limit = int(request.query_params.get("limit", "100"))
    offset = int(request.query_params.get("offset", "0"))
    trace_id = request.query_params.get("trace_id")
    session_id = request.query_params.get("session_id")
    category = request.query_params.get("category")
    rows = await nova.postgres_store.list_safety_events(
        limit=limit,
        offset=offset,
        trace_id=trace_id,
        session_id=session_id,
        category=category,
    )
    return {"status": "ok", "count": len(rows), "items": rows}


@app.get("/api/runtime/storage/sessions")
async def runtime_storage_sessions(request: Request):
    nova = request.app.state.nova
    if not nova.postgres_store:
        return JSONResponse({"status": "postgres runtime store not enabled"}, status_code=400)
    limit = int(request.query_params.get("limit", "100"))
    offset = int(request.query_params.get("offset", "0"))
    status = request.query_params.get("status")
    role = request.query_params.get("role")
    rows = await nova.postgres_store.list_runtime_sessions(limit=limit, offset=offset, status=status, role=role)
    return {"status": "ok", "count": len(rows), "items": rows}


@app.get("/api/runtime/storage/viewers")
async def runtime_storage_viewers(request: Request):
    nova = request.app.state.nova
    if not nova.postgres_store:
        return JSONResponse({"status": "postgres runtime store not enabled"}, status_code=400)
    limit = int(request.query_params.get("limit", "100"))
    offset = int(request.query_params.get("offset", "0"))
    session_id = request.query_params.get("session_id")
    platform = request.query_params.get("platform")
    rows = await nova.postgres_store.list_runtime_viewers(limit=limit, offset=offset, session_id=session_id, platform=platform)
    return {"status": "ok", "count": len(rows), "items": rows}


@app.get("/api/runtime/storage/audit")
async def runtime_storage_audit(request: Request):
    nova = request.app.state.nova
    if not nova.postgres_store:
        return JSONResponse({"status": "postgres runtime store not enabled"}, status_code=400)
    limit = int(request.query_params.get("limit", "100"))
    offset = int(request.query_params.get("offset", "0"))
    action = request.query_params.get("action")
    resource_type = request.query_params.get("resource_type")
    rows = await nova.postgres_store.list_audit_logs(limit=limit, offset=offset, action=action, resource_type=resource_type)
    return {"status": "ok", "count": len(rows), "items": rows}


@app.get("/api/control/tenants")
async def control_tenants(request: Request):
    nova = request.app.state.nova
    await require_permission(request, "tenant.read")
    if not nova.postgres_store:
        return JSONResponse({"status": "postgres runtime store not enabled"}, status_code=400)
    limit = int(request.query_params.get("limit", "100"))
    offset = int(request.query_params.get("offset", "0"))
    scoped_tenant_id = await resolve_tenant_scope(request, request.query_params.get("tenant_id"), allow_global=True)
    rows = await nova.postgres_store.list_tenants(
        tenant_ids=[scoped_tenant_id] if scoped_tenant_id else resolve_allowed_tenant_ids(request, allow_global=True),
        limit=limit,
        offset=offset,
    )
    return {"status": "ok", "count": len(rows), "items": rows}


@app.post("/api/control/tenants")
async def control_create_tenant(request: Request):
    nova = request.app.state.nova
    await require_permission(request, "tenant.write")
    await resolve_tenant_scope(request, None, allow_global=True)
    if not nova.postgres_store:
        return JSONResponse({"status": "postgres runtime store not enabled"}, status_code=400)
    body = await request.json()
    tenant_id = body.get("id")
    name = body.get("name")
    slug = body.get("slug")
    plan = body.get("plan", "enterprise")
    if not tenant_id or not name or not slug:
        return JSONResponse({"status": "validation_error", "reason": "id, name, slug required"}, status_code=400)
    await nova.postgres_store.create_tenant(tenant_id, name, slug, plan)
    await nova.postgres_store.write_audit_log("tenant_created", "tenant", body, resource_id=tenant_id)
    return {"status": "ok", "id": tenant_id}


@app.patch("/api/control/tenants/{tenant_id}")
async def control_update_tenant(tenant_id: str, request: Request):
    nova = request.app.state.nova
    await require_permission(request, "tenant.write")
    await resolve_tenant_scope(request, tenant_id)
    if not nova.postgres_store:
        return JSONResponse({"status": "postgres runtime store not enabled"}, status_code=400)
    body = await request.json()
    await nova.postgres_store.update_tenant(
        tenant_id,
        name=body.get("name"),
        slug=body.get("slug"),
        status=body.get("status"),
        plan=body.get("plan"),
    )
    await nova.postgres_store.write_audit_log("tenant_updated", "tenant", body, resource_id=tenant_id)
    return {"status": "ok", "id": tenant_id}


@app.get("/api/control/roles")
async def control_roles(request: Request):
    nova = request.app.state.nova
    await require_permission(request, "role.read")
    if not nova.postgres_store:
        return JSONResponse({"status": "postgres runtime store not enabled"}, status_code=400)
    tenant_id = await resolve_tenant_scope(request, request.query_params.get("tenant_id"))
    limit = int(request.query_params.get("limit", "100"))
    offset = int(request.query_params.get("offset", "0"))
    rows = await nova.postgres_store.list_roles(
        tenant_id=tenant_id,
        tenant_ids=resolve_allowed_tenant_ids(request),
        limit=limit,
        offset=offset,
    )
    return {"status": "ok", "count": len(rows), "items": rows}


@app.get("/api/control/users")
async def control_users(request: Request):
    nova = request.app.state.nova
    await require_permission(request, "user.read")
    if not nova.postgres_store:
        return JSONResponse({"status": "postgres runtime store not enabled"}, status_code=400)
    tenant_id = await resolve_tenant_scope(request, request.query_params.get("tenant_id"))
    status = request.query_params.get("status")
    limit = int(request.query_params.get("limit", "100"))
    offset = int(request.query_params.get("offset", "0"))
    rows = await nova.postgres_store.list_users(
        tenant_id=tenant_id,
        tenant_ids=resolve_allowed_tenant_ids(request),
        status=status,
        limit=limit,
        offset=offset,
    )
    return {"status": "ok", "count": len(rows), "items": rows}


@app.post("/api/control/users")
async def control_create_user(request: Request):
    nova = request.app.state.nova
    await require_permission(request, "user.write")
    if not nova.postgres_store:
        return JSONResponse({"status": "postgres runtime store not enabled"}, status_code=400)
    body = await request.json()
    user_id = body.get("id")
    tenant_id = await resolve_tenant_scope(request, body.get("tenant_id"))
    email = body.get("email")
    display_name = body.get("display_name", "")
    status = body.get("status", "active")
    if not user_id or not tenant_id or not email:
        return JSONResponse({"status": "validation_error", "reason": "id, tenant_id, email required"}, status_code=400)
    await nova.postgres_store.create_user(user_id, tenant_id, email, display_name, status)
    await nova.postgres_store.write_audit_log("user_created", "user", body, resource_id=user_id)
    return {"status": "ok", "id": user_id}


@app.patch("/api/control/users/{user_id}")
async def control_update_user(user_id: str, request: Request):
    nova = request.app.state.nova
    await require_permission(request, "user.write")
    if not nova.postgres_store:
        return JSONResponse({"status": "postgres runtime store not enabled"}, status_code=400)
    body = await request.json()
    target_user = await nova.postgres_store.get_user(
        user_id=user_id,
        tenant_ids=resolve_allowed_tenant_ids(request, allow_global=True),
    ) if nova.postgres_store else None
    if target_user:
        await resolve_tenant_scope(request, target_user.get("tenant_id"))
    await nova.postgres_store.update_user(
        user_id,
        email=body.get("email"),
        display_name=body.get("display_name"),
        status=body.get("status"),
    )
    await nova.postgres_store.write_audit_log("user_updated", "user", body, resource_id=user_id)
    return {"status": "ok", "id": user_id}


@app.get("/api/control/users/{user_id}/roles")
async def control_user_roles(user_id: str, request: Request):
    nova = request.app.state.nova
    await require_permission(request, "user.read")
    if not nova.postgres_store:
        return JSONResponse({"status": "postgres runtime store not enabled"}, status_code=400)
    target_user = await nova.postgres_store.get_user(
        user_id=user_id,
        tenant_ids=resolve_allowed_tenant_ids(request, allow_global=True),
    ) if nova.postgres_store else None
    if target_user:
        await resolve_tenant_scope(request, target_user.get("tenant_id"))
    limit = int(request.query_params.get("limit", "100"))
    offset = int(request.query_params.get("offset", "0"))
    rows = await nova.postgres_store.list_user_roles(user_id=user_id, limit=limit, offset=offset)
    return {"status": "ok", "count": len(rows), "items": rows}


@app.put("/api/control/users/{user_id}/roles")
async def control_set_user_roles(user_id: str, request: Request):
    nova = request.app.state.nova
    await require_permission(request, "user.write")
    if not nova.postgres_store:
        return JSONResponse({"status": "postgres runtime store not enabled"}, status_code=400)
    target_user = await nova.postgres_store.get_user(
        user_id=user_id,
        tenant_ids=resolve_allowed_tenant_ids(request, allow_global=True),
    )
    if target_user:
        await resolve_tenant_scope(request, target_user.get("tenant_id"))
    body = await request.json()
    role_ids = body.get("role_ids", [])
    if not isinstance(role_ids, list):
        return JSONResponse({"status": "validation_error", "reason": "role_ids must be a list"}, status_code=400)
    await nova.postgres_store.set_user_roles(user_id, role_ids)
    await nova.postgres_store.write_audit_log("user_roles_updated", "user_role", {"role_ids": role_ids}, resource_id=user_id)
    return {"status": "ok", "id": user_id, "role_count": len(role_ids)}


@app.get("/api/control/permissions")
async def control_permissions(request: Request):
    nova = request.app.state.nova
    await require_permission(request, "permission.read")
    await resolve_tenant_scope(request, request.query_params.get("tenant_id"), allow_global=True)
    if not nova.postgres_store:
        return JSONResponse({"status": "postgres runtime store not enabled"}, status_code=400)
    resource = request.query_params.get("resource")
    action = request.query_params.get("action")
    limit = int(request.query_params.get("limit", "100"))
    offset = int(request.query_params.get("offset", "0"))
    rows = await nova.postgres_store.list_permissions(resource=resource, action=action, limit=limit, offset=offset)
    return {"status": "ok", "count": len(rows), "items": rows}


@app.post("/api/control/permissions")
async def control_create_permission(request: Request):
    nova = request.app.state.nova
    await require_permission(request, "permission.write")
    await resolve_tenant_scope(request, None, allow_global=True)
    if not nova.postgres_store:
        return JSONResponse({"status": "postgres runtime store not enabled"}, status_code=400)
    body = await request.json()
    permission_id = body.get("id")
    code = body.get("code")
    resource = body.get("resource")
    action = body.get("action")
    description = body.get("description", "")
    if not permission_id or not code or not resource or not action:
        return JSONResponse({"status": "validation_error", "reason": "id, code, resource, action required"}, status_code=400)
    await nova.postgres_store.create_permission(permission_id, code, resource, action, description)
    await nova.postgres_store.write_audit_log("permission_created", "permission", body, resource_id=permission_id)
    return {"status": "ok", "id": permission_id}


@app.get("/api/control/roles/{role_id}/permissions")
async def control_role_permissions(role_id: str, request: Request):
    nova = request.app.state.nova
    await require_permission(request, "role.read")
    if not nova.postgres_store:
        return JSONResponse({"status": "postgres runtime store not enabled"}, status_code=400)
    target_role = await nova.postgres_store.get_role(
        role_id,
        tenant_ids=resolve_allowed_tenant_ids(request, allow_global=True),
    ) if nova.postgres_store else None
    if target_role:
        await resolve_tenant_scope(request, target_role.get("tenant_id"))
    limit = int(request.query_params.get("limit", "100"))
    offset = int(request.query_params.get("offset", "0"))
    rows = await nova.postgres_store.list_role_permissions(role_id=role_id, limit=limit, offset=offset)
    return {"status": "ok", "count": len(rows), "items": rows}


@app.put("/api/control/roles/{role_id}/permissions")
async def control_set_role_permissions(role_id: str, request: Request):
    nova = request.app.state.nova
    await require_permission(request, "role.write")
    if not nova.postgres_store:
        return JSONResponse({"status": "postgres runtime store not enabled"}, status_code=400)
    target_role = await nova.postgres_store.get_role(
        role_id,
        tenant_ids=resolve_allowed_tenant_ids(request, allow_global=True),
    )
    if target_role:
        await resolve_tenant_scope(request, target_role.get("tenant_id"))
    body = await request.json()
    permission_ids = body.get("permission_ids", [])
    if not isinstance(permission_ids, list):
        return JSONResponse({"status": "validation_error", "reason": "permission_ids must be a list"}, status_code=400)
    await nova.postgres_store.set_role_permissions(role_id, permission_ids)
    await nova.postgres_store.write_audit_log(
        "role_permissions_updated",
        "role_permission",
        {"permission_ids": permission_ids},
        resource_id=role_id,
    )
    return {"status": "ok", "id": role_id, "permission_count": len(permission_ids)}


@app.post("/api/control/roles")
async def control_create_role(request: Request):
    nova = request.app.state.nova
    await require_permission(request, "role.write")
    if not nova.postgres_store:
        return JSONResponse({"status": "postgres runtime store not enabled"}, status_code=400)
    body = await request.json()
    role_id = body.get("id")
    tenant_id = await resolve_tenant_scope(request, body.get("tenant_id"))
    name = body.get("name")
    scope = body.get("scope")
    description = body.get("description", "")
    if not role_id or not tenant_id or not name or not scope:
        return JSONResponse({"status": "validation_error", "reason": "id, tenant_id, name, scope required"}, status_code=400)
    await nova.postgres_store.create_role(role_id, tenant_id, name, scope, description)
    await nova.postgres_store.write_audit_log("role_created", "role", body, resource_id=role_id)
    return {"status": "ok", "id": role_id}


@app.patch("/api/control/roles/{role_id}")
async def control_update_role(role_id: str, request: Request):
    nova = request.app.state.nova
    await require_permission(request, "role.write")
    if not nova.postgres_store:
        return JSONResponse({"status": "postgres runtime store not enabled"}, status_code=400)
    target_role = await nova.postgres_store.get_role(
        role_id,
        tenant_ids=resolve_allowed_tenant_ids(request, allow_global=True),
    )
    if target_role:
        await resolve_tenant_scope(request, target_role.get("tenant_id"))
    body = await request.json()
    await nova.postgres_store.update_role(
        role_id,
        name=body.get("name"),
        scope=body.get("scope"),
        description=body.get("description"),
    )
    await nova.postgres_store.write_audit_log("role_updated", "role", body, resource_id=role_id)
    return {"status": "ok", "id": role_id}


@app.get("/api/control/config-revisions")
async def control_config_revisions(request: Request):
    nova = request.app.state.nova
    await require_permission(request, "config_revision.read")
    if not nova.postgres_store:
        return JSONResponse({"status": "postgres runtime store not enabled"}, status_code=400)
    tenant_id = await resolve_tenant_scope(request, request.query_params.get("tenant_id"))
    resource_type = request.query_params.get("resource_type")
    resource_id = request.query_params.get("resource_id")
    limit = int(request.query_params.get("limit", "100"))
    offset = int(request.query_params.get("offset", "0"))
    rows = await nova.postgres_store.list_config_revisions(
        tenant_id=tenant_id,
        tenant_ids=resolve_allowed_tenant_ids(request),
        resource_type=resource_type,
        resource_id=resource_id,
        status=request.query_params.get("status"),
        limit=limit,
        offset=offset,
    )
    return {"status": "ok", "count": len(rows), "items": rows}


@app.post("/api/control/config-revisions")
async def control_create_config_revision(request: Request):
    nova = request.app.state.nova
    await require_permission(request, "config_revision.write")
    if not nova.postgres_store:
        return JSONResponse({"status": "postgres runtime store not enabled"}, status_code=400)
    body = await request.json()
    revision_id = body.get("id")
    tenant_id = await resolve_tenant_scope(request, body.get("tenant_id"))
    resource_type = body.get("resource_type")
    resource_id = body.get("resource_id")
    revision_no = body.get("revision_no")
    config_json = body.get("config_json", {})
    status = body.get("status", "draft")
    if not revision_id or not tenant_id or not resource_type or not resource_id or revision_no is None:
        return JSONResponse(
            {"status": "validation_error", "reason": "id, tenant_id, resource_type, resource_id, revision_no required"},
            status_code=400,
        )
    await nova.postgres_store.create_config_revision(
        revision_id,
        tenant_id,
        resource_type,
        resource_id,
        int(revision_no),
        config_json,
        status=status,
    )
    await nova.postgres_store.write_audit_log("config_revision_created", "config_revision", body, resource_id=revision_id)
    return {"status": "ok", "id": revision_id}


@app.post("/api/control/config-revisions/{revision_id}/publish")
async def control_publish_config_revision(revision_id: str, request: Request):
    nova = request.app.state.nova
    await require_permission(request, "config_revision.publish")
    if not nova.postgres_store:
        return JSONResponse({"status": "postgres runtime store not enabled"}, status_code=400)
    target_revision = await nova.postgres_store.get_config_revision(
        revision_id,
        tenant_ids=resolve_allowed_tenant_ids(request, allow_global=True),
    )
    if target_revision:
        await resolve_tenant_scope(request, target_revision.get("tenant_id"))
    body = await request.json() if request.headers.get("content-length") else {}
    try:
        revision = await nova.postgres_store.publish_config_revision(
            revision_id,
            tenant_ids=resolve_allowed_tenant_ids(request, allow_global=True),
        )
    except ValueError as exc:
        return JSONResponse({"status": "invalid_transition", "reason": str(exc)}, status_code=409)
    await nova.postgres_store.write_audit_log("config_revision_published", "config_revision", body, resource_id=revision_id)
    return {"status": "ok", "id": revision_id, "revision_status": revision["status"]}


@app.post("/api/control/config-revisions/{revision_id}/rollback")
async def control_rollback_config_revision(revision_id: str, request: Request):
    nova = request.app.state.nova
    await require_permission(request, "config_revision.rollback")
    if not nova.postgres_store:
        return JSONResponse({"status": "postgres runtime store not enabled"}, status_code=400)
    target_revision = await nova.postgres_store.get_config_revision(
        revision_id,
        tenant_ids=resolve_allowed_tenant_ids(request, allow_global=True),
    )
    if target_revision:
        await resolve_tenant_scope(request, target_revision.get("tenant_id"))
    body = await request.json() if request.headers.get("content-length") else {}
    try:
        revision = await nova.postgres_store.rollback_config_revision(
            revision_id,
            tenant_ids=resolve_allowed_tenant_ids(request, allow_global=True),
        )
    except ValueError as exc:
        return JSONResponse({"status": "invalid_transition", "reason": str(exc)}, status_code=409)
    await nova.postgres_store.write_audit_log("config_revision_rolled_back", "config_revision", body, resource_id=revision_id)
    return {"status": "ok", "id": revision_id, "revision_status": revision["status"]}


@app.get("/api/runtime/hot-state")
async def runtime_hot_state(request: Request):
    nova = request.app.state.nova
    if not nova.hot_projector:
        return JSONResponse({"status": "hot state not enabled"}, status_code=400)

    summary = await nova.hot_session.get_session() or {}
    viewers = await nova.hot_session.list_viewers()
    return {
        "status": "ok",
        "instance_name": nova.settings.runtime.instance_name,
        "session_id": nova.settings.runtime.session_id,
        "summary": summary,
        "viewer_count": len(viewers),
    }


@app.get("/api/runtime/sessions")
async def runtime_sessions(request: Request):
    nova = request.app.state.nova
    if not nova.hot_session:
        return JSONResponse({"status": "hot session state not enabled"}, status_code=400)

    all_instances = request.query_params.get("scope", "") == "all"
    sessions = await nova.hot_session.list_sessions(all_instances=all_instances)
    return {
        "status": "ok",
        "instance_name": nova.settings.runtime.instance_name,
        "sessions": list(sessions.values()),
    }


@app.get("/api/runtime/sessions/{session_id}")
async def runtime_session_detail(session_id: str, request: Request):
    nova = request.app.state.nova
    if not nova.hot_session:
        return JSONResponse({"status": "hot session state not enabled"}, status_code=400)
    session = await nova.hot_session.get_session(session_id)
    if session is None:
        return JSONResponse({"status": "session not found"}, status_code=404)
    return {"status": "ok", "session": session}


@app.get("/api/runtime/viewers")
async def runtime_viewers(request: Request):
    nova = request.app.state.nova
    if not nova.hot_session:
        return JSONResponse({"status": "hot session state not enabled"}, status_code=400)

    viewers = await nova.hot_session.list_viewers()
    return {
        "status": "ok",
        "count": len(viewers),
        "viewers": list(viewers.values()),
    }


@app.get("/api/runtime/hot-state/viewers/{viewer_id}")
async def runtime_hot_state_viewer(viewer_id: str, request: Request):
    nova = request.app.state.nova
    if not nova.hot_session:
        return JSONResponse({"status": "hot state not enabled"}, status_code=400)

    viewer = await nova.hot_session.get_viewer(viewer_id)
    if viewer is None:
        return JSONResponse({"status": "viewer not found"}, status_code=404)
    return {"status": "ok", "viewer": viewer}


@app.post("/api/auth/token")
async def create_token(request: Request):
    """Create a JWT token (when auth is enabled)."""
    nova = request.app.state.nova
    if not nova.jwt_auth:
        return JSONResponse({"status": "auth not enabled"}, status_code=400)
    if not nova.postgres_store:
        return JSONResponse({"status": "postgres runtime store not enabled"}, status_code=400)

    body = await request.json()
    user_id = body.get("user_id") or body.get("subject")
    email = body.get("email")
    auth_context = await nova.postgres_store.get_user_auth_context(user_id=user_id, email=email)
    if not auth_context:
        return JSONResponse({"status": "not_found", "reason": "user not found"}, status_code=404)
    user = auth_context["user"]

    token = nova.jwt_auth.create_token(
        subject=user["id"],
        roles=auth_context["roles"],
        permissions=auth_context["permissions"],
        tenant_ids=auth_context["tenant_ids"],
    )
    return {"access_token": token, "token_type": "bearer"}


@app.get("/api/auth/me")
async def auth_me(request: Request):
    nova = request.app.state.nova
    if not nova.settings.auth.enabled:
        return JSONResponse({"status": "auth not enabled"}, status_code=400)

    user = getattr(request.state, "user", None)
    if not user:
        return JSONResponse({"detail": "Authentication required"}, status_code=401)

    subject = user.get("sub")
    db_user = None
    if nova.postgres_store and subject and subject != "api_key":
        db_user = await nova.postgres_store.get_user(user_id=subject)

    return {
        "status": "ok",
        "user": {
            "id": subject,
            "email": db_user.get("email") if db_user else None,
            "display_name": db_user.get("display_name") if db_user else None,
            "tenant_id": db_user.get("tenant_id") if db_user else None,
            "roles": user.get("roles", []),
            "permissions": user.get("permissions", []),
            "tenant_ids": user.get("tenant_ids", []),
            "auth_type": user.get("auth_type", "jwt"),
        },
    }


@app.websocket("/ws/control")
async def control_ws(websocket: WebSocket):
    """Real-time monitoring WebSocket for Nova Studio UI."""
    await websocket.accept()

    async def forward_events(event):
        try:
            import json
            await websocket.send_json({
                "type": event.type.value,
                "payload": {k: v for k, v in event.payload.items() if not isinstance(v, bytes)},
                "ts": event.timestamp.isoformat(),
            })
        except Exception:
            pass

    nova = websocket.app.state.nova
    if nova.bus:
        nova.bus.subscribe("cognitive.*", forward_events, sub_id="ws_monitor_cognitive")
        nova.bus.subscribe("perception.*", forward_events, sub_id="ws_monitor_perception")
        nova.bus.subscribe("system.*",    forward_events, sub_id="ws_monitor_system")

    try:
        while True:
            msg = await websocket.receive_text()
            import json
            data = json.loads(msg)
            if data.get("cmd") == "ping":
                await websocket.send_json({"cmd": "pong"})
    except Exception:
        pass
    finally:
        if nova.bus:
            nova.bus.unsubscribe("cognitive.*", "ws_monitor_cognitive")


def attach_runtime_routes(target_app: FastAPI) -> FastAPI:
    """Attach NOVA runtime routes to an app instance created for tests."""
    target_app.add_api_route("/health", health, methods=["GET"])
    target_app.add_api_route("/metrics", metrics, methods=["GET"])
    target_app.add_api_route("/api/config/current", current_config, methods=["GET"])
    target_app.add_api_route("/api/config/current", save_current_config, methods=["POST"])
    target_app.add_api_route("/api/config/reload", reload_config, methods=["POST"])
    target_app.add_api_route("/api/knowledge/ingest", ingest_knowledge, methods=["POST"])
    target_app.add_api_route("/api/knowledge/stats", knowledge_stats, methods=["GET"])
    target_app.add_api_route("/api/runtime/history/conversation", runtime_conversation_history, methods=["GET"])
    target_app.add_api_route("/api/runtime/history/safety", runtime_safety_history, methods=["GET"])
    target_app.add_api_route("/api/runtime/storage/sessions", runtime_storage_sessions, methods=["GET"])
    target_app.add_api_route("/api/runtime/storage/viewers", runtime_storage_viewers, methods=["GET"])
    target_app.add_api_route("/api/runtime/storage/audit", runtime_storage_audit, methods=["GET"])
    target_app.add_api_route("/api/control/tenants", control_tenants, methods=["GET"])
    target_app.add_api_route("/api/control/tenants", control_create_tenant, methods=["POST"])
    target_app.add_api_route("/api/control/tenants/{tenant_id}", control_update_tenant, methods=["PATCH"])
    target_app.add_api_route("/api/control/roles", control_roles, methods=["GET"])
    target_app.add_api_route("/api/control/roles", control_create_role, methods=["POST"])
    target_app.add_api_route("/api/control/roles/{role_id}", control_update_role, methods=["PATCH"])
    target_app.add_api_route("/api/control/users", control_users, methods=["GET"])
    target_app.add_api_route("/api/control/users", control_create_user, methods=["POST"])
    target_app.add_api_route("/api/control/users/{user_id}", control_update_user, methods=["PATCH"])
    target_app.add_api_route("/api/control/users/{user_id}/roles", control_user_roles, methods=["GET"])
    target_app.add_api_route("/api/control/users/{user_id}/roles", control_set_user_roles, methods=["PUT"])
    target_app.add_api_route("/api/control/permissions", control_permissions, methods=["GET"])
    target_app.add_api_route("/api/control/permissions", control_create_permission, methods=["POST"])
    target_app.add_api_route("/api/control/roles/{role_id}/permissions", control_role_permissions, methods=["GET"])
    target_app.add_api_route("/api/control/roles/{role_id}/permissions", control_set_role_permissions, methods=["PUT"])
    target_app.add_api_route("/api/control/config-revisions", control_config_revisions, methods=["GET"])
    target_app.add_api_route("/api/control/config-revisions", control_create_config_revision, methods=["POST"])
    target_app.add_api_route("/api/control/config-revisions/{revision_id}/publish", control_publish_config_revision, methods=["POST"])
    target_app.add_api_route("/api/control/config-revisions/{revision_id}/rollback", control_rollback_config_revision, methods=["POST"])
    target_app.add_api_route("/api/auth/token", create_token, methods=["POST"])
    target_app.add_api_route("/api/auth/me", auth_me, methods=["GET"])
    target_app.add_api_route("/api/runtime/hot-state", runtime_hot_state, methods=["GET"])
    target_app.add_api_route("/api/runtime/sessions", runtime_sessions, methods=["GET"])
    target_app.add_api_route("/api/runtime/sessions/{session_id}", runtime_session_detail, methods=["GET"])
    target_app.add_api_route("/api/runtime/viewers", runtime_viewers, methods=["GET"])
    target_app.add_api_route("/api/runtime/hot-state/viewers/{viewer_id}", runtime_hot_state_viewer, methods=["GET"])
    target_app.add_api_websocket_route("/ws/control", control_ws)
    return target_app


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    settings = app.state.nova.settings
    uvicorn.run(
        "apps.nova_server.main:app",
        host="0.0.0.0",
        port=settings.port,
        reload=settings.debug,
        log_level=settings.observability.log_level.lower(),
        log_config=None,
    )


if __name__ == "__main__":
    main()
