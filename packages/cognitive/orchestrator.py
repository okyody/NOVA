"""
NOVA Agent Orchestrator
=======================
The cognitive decision engine. Coordinates the four agents and
calls the LLM to generate responses.

Decision pipeline (all async, target < 800ms total):
  1. Receive a processed event (semantic cluster or high-priority platform event)
  2. Classify intent (NLU)
  3. Pull context from memory agent (recent + episodic + viewer graph)
  4. Pull current emotion state
  5. RAG retrieval (if knowledge base available)
  6. Build LLM prompt (system + context + event + RAG)
  7. Stream LLM response — emit STREAM_TOKEN for each chunk
  8. Handle tool calls if LLM requests them
  9. Pass full response to personality agent for correction
  10. Publish ORCHESTRATOR_OUT event with final text + metadata

Streaming architecture:
  - LLM tokens flow: LLMClient → STREAM_TOKEN events (for Studio UI)
  - Sentences are accumulated and published as SAFE_OUTPUT (for VoicePipeline)
  - SafetyGuard checks each sentence before it reaches VoicePipeline
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass
from typing import Any, AsyncIterator

import httpx

from packages.core.event_bus import EventBus
from packages.core.types import (
    ActionType,
    AgentDecision,
    EmotionLabel,
    EmotionState,
    EventType,
    NovaEvent,
    Priority,
)

log = logging.getLogger("nova.orchestrator")


@dataclass
class _RoutingPlan:
    intent: str = "unknown"
    intent_confidence: float = 0.0
    max_tokens: int = 150
    temperature: float = 0.85
    rag_top_k: int = 3
    rag_score_threshold: float = 0.25
    allow_tools: bool = False
    tone_hint: str = "steady and conversational"
    response_style: str = "Answer naturally and keep the response concise."

# ─── Sentence splitter ─────────────────────────────────────────────────────

# Matches sentence-ending punctuation (Chinese + English) followed by space or end
_SENTENCE_END_RE = re.compile(r'[。！？!?；;…]+[\s"]*$')
_SENTENCE_END_RE_SPLIT = re.compile(r'([。！？!?；;]+)')


def _split_sentences(text: str) -> list[str]:
    """Split text into sentence chunks at natural boundaries."""
    if not text.strip():
        return []
    parts = _SENTENCE_END_RE_SPLIT.split(text)
    sentences: list[str] = []
    current = ""
    for part in parts:
        current += part
        if _SENTENCE_END_RE.search(current):
            sentences.append(current.strip())
            current = ""
    if current.strip():
        sentences.append(current.strip())
    return sentences


# ─── LLM Client (pluggable) ───────────────────────────────────────────────────

class LLMClient:
    """
    Thin async wrapper around the LLM API.
    Swap the base_url to change providers — interface stays constant.

    Providers supported via OpenAI-compatible API:
      - OpenAI / GPT-4o
      - Anthropic via claude-openai-proxy
      - Local: Ollama, LM Studio, vLLM
    """

    def __init__(
        self,
        base_url: str = "http://localhost:11434/v1",  # Ollama default
        api_key:  str = "ollama",
        model:    str = "qwen2.5:14b",
        timeout:  float = 30.0,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
        )
        self.model = model

    async def stream_completion(
        self,
        messages: list[dict[str, str]],
        max_tokens: int = 200,
        temperature: float = 0.85,
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """
        Yield parsed chunks from the LLM streaming API.

        Each yielded chunk is a dict:
          {"type": "text", "content": "..."}  — text delta
          {"type": "tool_call", ...}          — tool call (Phase 3.2)
          {"type": "done", "finish_reason": ...} — stream end
        """
        payload: dict[str, Any] = {
            "model":       self.model,
            "messages":    messages,
            "max_tokens":  max_tokens,
            "temperature": temperature,
            "stream":      True,
        }
        if tools:
            payload["tools"] = tools

        async with self._client.stream(
            "POST", "/chat/completions", json=payload
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    data = line[6:]
                    if data == "[DONE]":
                        yield {"type": "done", "finish_reason": "stop"}
                        break
                    import json
                    try:
                        chunk = json.loads(data)
                        choice = chunk["choices"][0]
                        delta = choice.get("delta", {})
                        finish_reason = choice.get("finish_reason")

                        # Text content
                        content = delta.get("content", "")
                        if content:
                            yield {"type": "text", "content": content}

                        # Tool calls (Phase 3.2)
                        tool_calls = delta.get("tool_calls")
                        if tool_calls:
                            yield {"type": "tool_call", "tool_calls": tool_calls}

                        # Stream end
                        if finish_reason:
                            yield {"type": "done", "finish_reason": finish_reason}
                    except (json.JSONDecodeError, KeyError):
                        continue

    async def complete(
        self,
        messages: list[dict[str, str]],
        max_tokens: int = 200,
        temperature: float = 0.85,
    ) -> str:
        chunks = []
        async for chunk in self.stream_completion(messages, max_tokens, temperature):
            if chunk.get("type") == "text":
                chunks.append(chunk["content"])
        return "".join(chunks)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings via the /embeddings endpoint (Ollama / OpenAI compatible)."""
        payload = {
            "model": self.model,
            "input": texts,
        }
        resp = await self._client.post("/embeddings", json=payload)
        resp.raise_for_status()
        data = resp.json()
        return [d["embedding"] for d in data["data"]]

    async def close(self) -> None:
        await self._client.aclose()


# ─── Orchestrator ─────────────────────────────────────────────────────────────

class Orchestrator:
    """
    The central decision engine.

    Wires together: memory_agent, emotion_agent, personality_agent → LLM → output.
    Supports: RAG knowledge retrieval, tool calling, NLU intent classification.
    Streaming: tokens are published as STREAM_TOKEN events for real-time UI display.
    Sentences are accumulated and released after personality correction.
    """

    PROACTIVE_SILENCE_SEC  = 45     # trigger proactive speech after this many seconds
    MAX_CONCURRENT_REQUESTS = 2     # prevent LLM overload
    QUEUE_TIMEOUT_MS       = 150    # max wait for agent context
    SENTENCE_ACCUMULATE_S  = 0.3    # max wait to accumulate a sentence
    MAX_TOOL_ROUNDS        = 2      # max sequential tool call rounds

    def __init__(
        self,
        bus: EventBus,
        llm: LLMClient,
        memory_agent: Any,       # MemoryAgent (avoid circular import)
        emotion_agent: Any,      # EmotionAgent
        personality_agent: Any,  # PersonalityAgent
        knowledge_base: Any | None = None,  # KnowledgeBase (RAG)
        tool_registry: Any | None = None,   # ToolRegistry (function calling)
        nlu: Any | None = None,            # IntentClassifier (NLU)
        circuit_breaker: Any | None = None,  # CircuitBreaker (P4)
        fallback_responder: Any | None = None,  # FallbackResponder (P4)
        metrics: Any | None = None,        # MetricsCollector (P4)
    ) -> None:
        self._bus  = bus
        self._llm  = llm
        self._mem  = memory_agent
        self._emo  = emotion_agent
        self._per  = personality_agent
        self._kb   = knowledge_base
        self._tools = tool_registry
        self._nlu   = nlu
        self._circuit_breaker = circuit_breaker
        self._fallback = fallback_responder
        self._metrics = metrics

        # Initialize tool executor if registry provided
        self._tool_executor: Any | None = None
        if tool_registry is not None:
            from packages.cognitive.tool_calling import ToolExecutor
            self._tool_executor = ToolExecutor(tool_registry)

        self._last_output_time = time.monotonic()
        self._semaphore = asyncio.Semaphore(self.MAX_CONCURRENT_REQUESTS)
        self._proactive_task: asyncio.Task | None = None
        self._pending_events: list[NovaEvent] = []

    async def start(self) -> None:
        # Subscribe to aggregated perception outputs (not raw chat — perception
        # layer handles de-duplication and clustering first)
        self._bus.subscribe(
            EventType.SEMANTIC_CLUSTER, self._on_cluster, sub_id="orch_cluster"
        )
        self._bus.subscribe(
            EventType.SUPER_CHAT, self._on_priority_event, sub_id="orch_superchat"
        )
        self._bus.subscribe(
            EventType.GIFT_RECEIVED, self._on_priority_event, sub_id="orch_gift"
        )
        self._proactive_task = asyncio.create_task(
            self._proactive_loop(), name="nova.orchestrator.proactive"
        )
        log.info("Orchestrator started (model=%s)", self._llm.model)

    async def stop(self) -> None:
        if self._proactive_task:
            self._proactive_task.cancel()
        await self._llm.close()

    # ── Event handlers ───────────────────────────────────────────────────────

    async def _on_cluster(self, event: NovaEvent) -> None:
        """Handle a batch of semantically clustered chat messages."""
        await self._decide(event, action_type=ActionType.RESPOND)

    async def _on_priority_event(self, event: NovaEvent) -> None:
        """Handle high-priority platform events immediately."""
        await self._decide(event, action_type=ActionType.RESPOND)

    async def _proactive_loop(self) -> None:
        """Initiate speech when stream has been silent too long."""
        while True:
            await asyncio.sleep(10)
            silence = time.monotonic() - self._last_output_time
            if silence >= self.PROACTIVE_SILENCE_SEC:
                await self._initiate_proactive()

    async def _initiate_proactive(self) -> None:
        """Generate a proactive message to fill silence."""
        log.info("Proactive speech triggered (silent %.0fs)", 
                 time.monotonic() - self._last_output_time)
        synthetic = NovaEvent(
            type=EventType.SILENCE_DETECTED,
            payload={"silence_sec": time.monotonic() - self._last_output_time},
            priority=Priority.LOW,
            source="orchestrator",
        )
        await self._decide(synthetic, action_type=ActionType.INITIATE)

    # ── Core decision pipeline (streaming) ────────────────────────────────────

    async def _decide(self, trigger: NovaEvent, action_type: ActionType) -> None:
        async with self._semaphore:
            t0 = time.monotonic()
            try:
                # Check circuit breaker before calling LLM
                if self._circuit_breaker and not self._circuit_breaker.allow_request():
                    log.warning("Circuit breaker OPEN, using fallback response")
                    if self._fallback:
                        fallback_text = await self._fallback.get_fallback(
                            trigger.payload.get("text", "")
                        )
                        await self._emit_sentence(
                            fallback_text, 0,
                            trigger.trace_id or trigger.event_id,
                            trigger, self._emo.current_state,
                            trigger.payload.get("viewer", {}).get("viewer_id"),
                            action_type, is_final=True,
                        )
                    self._last_output_time = time.monotonic()
                    return

                await self._pipeline(trigger, action_type)
                elapsed_ms = (time.monotonic() - t0) * 1000

                # Record metrics
                if self._metrics:
                    self._metrics.record_pipeline_latency(elapsed_ms / 1000.0)
                if self._circuit_breaker:
                    self._circuit_breaker.record_success()

                log.info("Decision pipeline: %.0f ms | action=%s", elapsed_ms, action_type.value)
                self._last_output_time = time.monotonic()
            except Exception as exc:
                if self._circuit_breaker:
                    self._circuit_breaker.record_failure()
                if self._metrics:
                    self._metrics.record_event_dropped()
                log.exception("Orchestrator pipeline failed: %s", exc)

    async def _pipeline(
        self, trigger: NovaEvent, action_type: ActionType
    ) -> None:
        """Streaming pipeline: NLU → RAG → LLM tokens → Tool calls → sentences → output."""
        # 1. Gather context
        viewer_id = trigger.payload.get("viewer", {}).get("viewer_id")
        query     = trigger.payload.get("text", trigger.type.value)

        mem_ctx = await self._mem.recall(query, viewer_id=viewer_id)
        emotion = self._emo.current_state

        # 2. NLU intent classification (if available)
        intent_result = None
        if self._nlu is not None and query:
            intent_result = await self._nlu.classify_async(query)
            log.debug("NLU intent: %s (%.2f) for '%.30s'",
                      intent_result.intent.value, intent_result.confidence, query)

        routing_plan = self._build_routing_plan(
            query=query,
            action_type=action_type,
            emotion=emotion,
            intent_result=intent_result,
        )

        # 3. RAG retrieval (if knowledge base available)
        rag_context = ""
        if self._kb is not None and query and routing_plan.rag_top_k > 0:
            try:
                # Quick retrieval for context injection
                rag_texts = await self._kb.retrieve_texts(
                    query,
                    top_k=routing_plan.rag_top_k,
                    score_threshold=routing_plan.rag_score_threshold,
                )
                if rag_texts:
                    rag_context = "\n[相关知识]\n" + "\n---\n".join(rag_texts[:3])
            except Exception as e:
                log.debug("RAG retrieval failed: %s", e)

        # 4. Build prompt (with RAG context)
        messages = self._build_messages(
            trigger,
            mem_ctx,
            emotion,
            action_type,
            routing_plan,
            intent_result,
        )

        # Inject RAG context into user message
        if rag_context:
            messages[-1]["content"] += rag_context

        # 5. Stream LLM response — accumulate sentences
        trace_id = trigger.trace_id or trigger.event_id
        full_text = ""
        sentence_buffer = ""
        sentence_index = 0

        # Tool calling support
        tool_definitions = (
            self._tools.all_definitions()
            if self._tools and routing_plan.allow_tools
            else None
        )

        for _tool_round in range(self.MAX_TOOL_ROUNDS + 1):
            tool_calls_accumulated: list[dict[str, Any]] = []
            current_tool_call: dict[str, Any] = {}

            async for chunk in self._llm.stream_completion(
                messages,
                max_tokens=routing_plan.max_tokens,
                temperature=routing_plan.temperature,
                tools=tool_definitions if _tool_round == 0 else None,
            ):
                if chunk.get("type") == "text":
                    token = chunk["content"]
                    full_text += token
                    sentence_buffer += token

                    # Publish STREAM_TOKEN for Studio UI real-time display
                    await self._bus.publish(NovaEvent(
                        type=EventType.STREAM_TOKEN,
                        payload={
                            "token": token,
                            "accumulated": full_text,
                            "trace_id": trace_id,
                        },
                        priority=Priority.HIGH,
                        source="orchestrator",
                        trace_id=trace_id,
                    ))

                    # Check if we have a complete sentence
                    if _SENTENCE_END_RE.search(sentence_buffer):
                        sentence_text = sentence_buffer.strip()
                        sentence_buffer = ""

                        if sentence_text:
                            await self._emit_sentence(
                                sentence_text, sentence_index, trace_id,
                                trigger, emotion, viewer_id, action_type,
                            )
                            sentence_index += 1

                elif chunk.get("type") == "tool_call":
                    tc_data = chunk.get("tool_calls", [])
                    for tc in tc_data:
                        idx = tc.get("index", 0)
                        func = tc.get("function", {})
                        # Accumulate tool call fragments
                        if idx not in range(len(tool_calls_accumulated)):
                            tool_calls_accumulated.append({
                                "id": tc.get("id", ""),
                                "type": "function",
                                "function": {"name": "", "arguments": ""},
                            })
                        if func.get("name"):
                            tool_calls_accumulated[idx]["function"]["name"] = func["name"]
                        if func.get("arguments"):
                            tool_calls_accumulated[idx]["function"]["arguments"] += func["arguments"]

                elif chunk.get("type") == "done":
                    break

            # Handle tool calls
            if tool_calls_accumulated and self._tool_executor:
                tool_results = await self._tool_executor.handle_tool_calls(tool_calls_accumulated)
                # Add assistant message with tool calls + tool results to conversation
                messages.append({
                    "role": "assistant",
                    "content": full_text or None,
                    "tool_calls": tool_calls_accumulated,
                })
                for tr in tool_results:
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tr["tool_call_id"],
                        "content": tr["content"],
                    })
                # Continue LLM with tool results — reset full_text for next round
                full_text = ""
                sentence_buffer = ""
                tool_definitions = None  # Don't offer tools in follow-up
                continue
            else:
                break

        # Flush remaining buffer as final sentence
        if sentence_buffer.strip():
            await self._emit_sentence(
                sentence_buffer.strip(), sentence_index, trace_id,
                trigger, emotion, viewer_id, action_type,
                is_final=True,
            )
        elif sentence_index > 0:
            # Mark the last emitted sentence as final
            pass  # Already emitted

        # 6. Apply personality correction to full text and publish final decision
        corrected = self._per.apply_character(full_text)

        await self._bus.publish(NovaEvent(
            type=EventType.ORCHESTRATOR_OUT,
            payload={
                "text":           corrected,
                "action":         action_type.value,
                "confidence":     0.85,
                "emotion_state":  {
                    "valence": emotion.valence,
                    "arousal": emotion.arousal,
                    "label":   emotion.label.value,
                },
                "viewer_id":      viewer_id,
                "trigger_type":   trigger.type.value,
                "trace_id":       trace_id,
                "sentence_count": sentence_index + (1 if sentence_buffer.strip() else 0),
                "intent":         intent_result.intent.value if intent_result else "unknown",
                "intent_confidence": intent_result.confidence if intent_result else 0.0,
                "rag_used":       bool(rag_context),
                "routing": {
                    "tone_hint": routing_plan.tone_hint,
                    "response_style": routing_plan.response_style,
                    "max_tokens": routing_plan.max_tokens,
                    "temperature": routing_plan.temperature,
                    "rag_top_k": routing_plan.rag_top_k,
                    "allow_tools": routing_plan.allow_tools,
                },
            },
            priority=Priority.HIGH,
            source="orchestrator",
            trace_id=trace_id,
        ))

        # 7. Trigger memory store
        await self._bus.publish(NovaEvent(
            type=EventType.MEMORY_STORE,
            payload={
                "role": "nova",
                "text": corrected,
                "action": action_type.value,
            },
            priority=Priority.LOW,
            source="orchestrator",
        ))

    async def _emit_sentence(
        self,
        text: str,
        index: int,
        trace_id: str,
        trigger: NovaEvent,
        emotion: EmotionState,
        viewer_id: str | None,
        action_type: ActionType,
        is_final: bool = False,
    ) -> None:
        """Emit a complete sentence as ORCHESTRATOR_OUT for SafetyGuard → VoicePipeline."""
        # Apply personality correction per-sentence
        corrected = self._per.apply_character(text)

        await self._bus.publish(NovaEvent(
            type=EventType.ORCHESTRATOR_OUT,
            payload={
                "text":           corrected,
                "action":         action_type.value,
                "confidence":     0.85,
                "emotion_state":  {
                    "valence": emotion.valence,
                    "arousal": emotion.arousal,
                    "label":   emotion.label.value,
                },
                "viewer_id":      viewer_id,
                "trigger_type":   trigger.type.value,
                "trace_id":       trace_id,
                "sentence_index": index,
                "is_final":       is_final,
            },
            priority=Priority.HIGH,
            source="orchestrator",
            trace_id=trace_id,
        ))

    def _build_messages(
        self,
        trigger: NovaEvent,
        mem_ctx: dict,
        emotion: EmotionState,
        action_type: ActionType,
        routing_plan: _RoutingPlan,
        intent_result: Any | None,
    ) -> list[dict[str, str]]:
        system = self._per.system_prompt()
        routing_block = (
            f"Intent: {routing_plan.intent} ({routing_plan.intent_confidence:.2f})\n"
            f"Tone: {routing_plan.tone_hint}\n"
            f"Style: {routing_plan.response_style}\n"
        )
        if intent_result and getattr(intent_result, "entities", None):
            routing_block += f"Entities: {intent_result.entities}\n"

        # Inject live context
        context_block = (
            f"[当前状态]\n"
            f"情绪: {emotion.label.value} (效价={emotion.valence:.2f}, 唤醒={emotion.arousal:.2f})\n"
            f"观众概况: {mem_ctx.get('viewer_summary', '暂无数据')}\n"
            f"[最近对话]\n{mem_ctx.get('recent', '(无)')}\n"
        )

        # Add episodic hints if available
        episodic = mem_ctx.get("episodic_hints", [])
        if episodic:
            hints_text = "\n".join(f"- {h}" for h in episodic[:3])
            context_block += f"[相关记忆]\n{hints_text}\n"

        context_block += routing_block

        if action_type == ActionType.INITIATE:
            user_msg = (
                f"{context_block}\n"
                f"直播间已经安静了一段时间，请以你的角色主动发起一段自然的对话，"
                f"话题可以是今天的游戏、最近的热点、或者向观众抛出一个有趣的问题。"
                f"50字以内。"
            )
            user_msg += f"\nRoute requirement: {routing_plan.response_style}"
        else:
            event_text = trigger.payload.get("text", "")
            viewer_name = trigger.payload.get("viewer", {}).get("username", "观众")
            gift_info = ""
            if trigger.type in (EventType.GIFT_RECEIVED, EventType.SUPER_CHAT):
                amount = trigger.payload.get("amount", 0)
                gift_name = trigger.payload.get("gift_name", "礼物")
                gift_info = f"\n[{viewer_name} 送出了 {gift_name}（价值 {amount} 元）]"

            user_msg = (
                f"{context_block}"
                f"{gift_info}\n"
                f"[{viewer_name}的消息]: {event_text}\n\n"
                f"请以你的角色自然回应。50字以内。"
            )
            user_msg += (
                f"\nRoute requirement: {routing_plan.response_style}"
                "\nUse tools only when they materially help and stay in character."
            )

        return [
            {"role": "system",    "content": system},
            {"role": "user",      "content": user_msg},
        ]

    def _build_routing_plan(
        self,
        query: str,
        action_type: ActionType,
        emotion: EmotionState,
        intent_result: Any | None,
    ) -> _RoutingPlan:
        intent = intent_result.intent.value if intent_result else "unknown"
        confidence = float(intent_result.confidence) if intent_result else 0.0
        plan = _RoutingPlan(
            intent=intent,
            intent_confidence=confidence,
            temperature=self._temperature_from_emotion(emotion),
            tone_hint=self._tone_hint_from_emotion(emotion),
        )

        if action_type == ActionType.INITIATE:
            plan.max_tokens = 120
            plan.rag_top_k = 1
            plan.rag_score_threshold = 0.20
            plan.response_style = "Open a fresh topic proactively, keep momentum, and end with a hook."
            plan.temperature = min(1.15, plan.temperature + 0.05)
            return plan

        if intent == "question":
            plan.max_tokens = 220
            plan.rag_top_k = 5
            plan.rag_score_threshold = 0.18
            plan.temperature = max(0.62, min(plan.temperature, 0.82))
            plan.response_style = "Answer directly, prioritize factual grounding, and only elaborate when useful."
        elif intent in {"command", "request"}:
            plan.max_tokens = 180
            plan.rag_top_k = 2
            plan.rag_score_threshold = 0.20
            plan.allow_tools = bool(self._tool_executor) and confidence >= 0.55
            plan.temperature = max(0.60, plan.temperature - 0.08)
            plan.response_style = "Treat this as an action request, use tools when available, otherwise explain the limitation plainly."
        elif intent == "greeting":
            plan.max_tokens = 80
            plan.rag_top_k = 0
            plan.temperature = max(0.65, plan.temperature - 0.04)
            plan.response_style = "Respond warmly and quickly, greet the viewer naturally, and avoid over-explaining."
        elif intent == "emotion":
            plan.max_tokens = 120
            plan.rag_top_k = 0
            plan.temperature = min(1.10, plan.temperature + 0.03)
            plan.response_style = "Acknowledge the feeling first, mirror the emotion with empathy, then reply in character."
        elif intent == "topic":
            plan.max_tokens = 180
            plan.rag_top_k = 4
            plan.rag_score_threshold = 0.20
            plan.response_style = "Lean into the topic, add one concrete angle, and keep the conversation moving."
        else:
            plan.max_tokens = 140
            plan.rag_top_k = 2
            plan.rag_score_threshold = 0.24
            plan.response_style = "Keep the reply natural, concise, and easy to speak aloud."

        if emotion.label in (EmotionLabel.SAD, EmotionLabel.ANXIOUS):
            plan.response_style += " Keep the tone steady and reassuring."
            plan.temperature = max(0.60, plan.temperature - 0.05)
        elif emotion.label in (EmotionLabel.EXCITED, EmotionLabel.HAPPY):
            plan.response_style += " Let the response feel lively without becoming noisy."
            plan.temperature = min(1.15, plan.temperature + 0.04)

        if not query.strip():
            plan.rag_top_k = 0
            plan.allow_tools = False

        return plan

    @staticmethod
    def _tone_hint_from_emotion(emotion: EmotionState) -> str:
        if emotion.label == EmotionLabel.EXCITED:
            return "energetic and playful"
        if emotion.label == EmotionLabel.HAPPY:
            return "warm and upbeat"
        if emotion.label == EmotionLabel.CALM:
            return "calm and steady"
        if emotion.label == EmotionLabel.CURIOUS:
            return "curious and inviting"
        if emotion.label == EmotionLabel.SURPRISED:
            return "animated and reactive"
        if emotion.label == EmotionLabel.SAD:
            return "gentle and empathetic"
        if emotion.label == EmotionLabel.ANXIOUS:
            return "reassuring and controlled"
        return "steady and conversational"

    @staticmethod
    def _temperature_from_emotion(emotion: EmotionState) -> float:
        """Higher arousal → more creative/spontaneous responses."""
        return 0.72 + emotion.arousal * 0.22 + max(0.0, emotion.valence) * 0.06
