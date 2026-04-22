"""
NOVA Tool/Function Calling
==========================
LLM tool calling support for extending NOVA's capabilities.

Provides:
  - ToolRegistry: registers and manages available tools
  - ToolExecutor: executes tool calls from LLM responses
  - Built-in tools: search_knowledge, get_viewer_info, set_emotion, etc.
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine

log = logging.getLogger("nova.tools")


# ─── Tool definitions ────────────────────────────────────────────────────────

@dataclass
class ToolDefinition:
    """OpenAI-compatible tool/function definition."""
    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema
    function: Callable[..., Coroutine[Any, Any, str]] | None = None

    def to_openai_format(self) -> dict[str, Any]:
        """Convert to OpenAI tool calling format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


# ─── Tool Registry ──────────────────────────────────────────────────────────

class ToolRegistry:
    """
    Registry of available tools for LLM function calling.
    Tools can be registered dynamically and exposed to the LLM.
    """

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, tool: ToolDefinition) -> None:
        """Register a tool."""
        self._tools[tool.name] = tool
        log.debug("Registered tool: %s", tool.name)

    def unregister(self, name: str) -> None:
        """Unregister a tool."""
        self._tools.pop(name, None)

    def get(self, name: str) -> ToolDefinition | None:
        """Get a tool by name."""
        return self._tools.get(name)

    def all_definitions(self) -> list[dict[str, Any]]:
        """Get all tool definitions in OpenAI format."""
        return [t.to_openai_format() for t in self._tools.values()]

    def list_names(self) -> list[str]:
        """List all registered tool names."""
        return list(self._tools.keys())


# ─── Tool Executor ───────────────────────────────────────────────────────────

class ToolExecutor:
    """
    Executes tool calls requested by the LLM.
    Handles parameter validation, execution, and error recovery.
    """

    MAX_EXECUTION_TIME = 10.0  # seconds

    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    async def execute(self, tool_name: str, arguments: dict[str, Any]) -> str:
        """
        Execute a tool call and return the result as a string.
        Handles errors gracefully — never crashes the pipeline.
        """
        tool = self._registry.get(tool_name)
        if tool is None:
            return f"Error: Unknown tool '{tool_name}'"

        if tool.function is None:
            return f"Error: Tool '{tool_name}' has no implementation"

        try:
            result = await asyncio.wait_for(
                tool.function(**arguments),
                timeout=self.MAX_EXECUTION_TIME,
            )
            return str(result)
        except asyncio.TimeoutError:
            return f"Error: Tool '{tool_name}' timed out after {self.MAX_EXECUTION_TIME}s"
        except TypeError as e:
            return f"Error: Invalid arguments for '{tool_name}': {e}"
        except Exception as e:
            log.error("Tool execution failed: %s(%s) → %s", tool_name, arguments, e)
            return f"Error: Tool execution failed: {e}"

    async def handle_tool_calls(self, tool_calls: list[dict[str, Any]]) -> list[dict[str, str]]:
        """
        Process a list of tool calls from the LLM response.
        Returns a list of tool result messages for the conversation.
        """
        results = []
        for tc in tool_calls:
            func = tc.get("function", {})
            name = func.get("name", "")
            args_str = func.get("arguments", "{}")
            call_id = tc.get("id", "")

            try:
                args = json.loads(args_str) if isinstance(args_str, str) else args_str
            except json.JSONDecodeError:
                args = {}

            result = await self.execute(name, args)

            results.append({
                "tool_call_id": call_id,
                "role": "tool",
                "name": name,
                "content": result,
            })

            log.info("Tool call: %s(%s) → %.100s", name, args_str[:80], result[:80])

        return results


# ─── Built-in tools ──────────────────────────────────────────────────────────

def create_builtin_tools(
    knowledge_base: Any = None,
    memory_agent: Any = None,
    emotion_agent: Any = None,
    viewer_graph: Any = None,
) -> list[ToolDefinition]:
    """Create the standard set of NOVA tools."""

    tools: list[ToolDefinition] = []

    # ── Search knowledge base ────────────────────────────────────────────────
    async def _search_knowledge(query: str, top_k: int = 3) -> str:
        if knowledge_base is None:
            return "Error: Knowledge base not available"
        results = await knowledge_base.retrieve_texts(query, top_k=top_k)
        if not results:
            return "No relevant knowledge found."
        return "\n---\n".join(results)

    tools.append(ToolDefinition(
        name="search_knowledge",
        description="Search the knowledge base for relevant information about a topic. Use this when you need factual information to answer a question.",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The search query"},
                "top_k": {"type": "integer", "description": "Number of results (default 3)", "default": 3},
            },
            "required": ["query"],
        },
        function=_search_knowledge,
    ))

    # ── Get viewer info ──────────────────────────────────────────────────────
    async def _get_viewer_info(viewer_id: str) -> str:
        if viewer_graph is None:
            return "Error: Viewer graph not available"
        node = viewer_graph.get(viewer_id)
        if node is None:
            return f"No information found for viewer '{viewer_id}'"
        p = node.profile
        return json.dumps({
            "username": p.username,
            "interaction_count": node.interaction_count,
            "gift_total": p.gift_total,
            "is_member": p.is_member,
            "is_vip": node.is_vip,
            "last_topics": node.last_topics[:3],
        }, ensure_ascii=False)

    tools.append(ToolDefinition(
        name="get_viewer_info",
        description="Get detailed information about a specific viewer, including interaction history, gift totals, and topics they've discussed.",
        parameters={
            "type": "object",
            "properties": {
                "viewer_id": {"type": "string", "description": "The viewer's unique ID"},
            },
            "required": ["viewer_id"],
        },
        function=_get_viewer_info,
    ))

    # ── Set emotion ──────────────────────────────────────────────────────────
    async def _set_emotion(emotion: str, intensity: float = 0.5) -> str:
        if emotion_agent is None:
            return "Error: Emotion agent not available"
        from packages.core.types import EmotionLabel
        try:
            label = EmotionLabel(emotion)
        except ValueError:
            return f"Unknown emotion: {emotion}. Valid: {[e.value for e in EmotionLabel]}"
        # Apply a trigger to shift emotion
        from packages.cognitive.emotion_agent import EmotionTrigger
        valence_map = {
            "excited": 0.5, "happy": 0.4, "curious": 0.1, "surprised": 0.0,
            "neutral": 0.0, "calm": 0.0, "sad": -0.4, "anxious": -0.3,
        }
        arousal_map = {
            "excited": 0.5, "happy": 0.2, "curious": 0.1, "surprised": 0.4,
            "neutral": 0.0, "calm": -0.2, "sad": -0.1, "anxious": 0.3,
        }
        trigger = EmotionTrigger(
            valence_delta=valence_map.get(emotion, 0.0) * intensity,
            arousal_delta=arousal_map.get(emotion, 0.0) * intensity,
            intensity=intensity,
            label_hint=label,
        )
        emotion_agent._apply(trigger, triggered_by="tool_call")
        return f"Emotion shifted toward {emotion} (intensity={intensity})"

    tools.append(ToolDefinition(
        name="set_emotion",
        description="Shift the streamer's emotional state. Use sparingly — only when the conversation naturally warrants an emotion shift.",
        parameters={
            "type": "object",
            "properties": {
                "emotion": {
                    "type": "string",
                    "enum": ["excited", "happy", "curious", "surprised", "neutral", "calm", "sad", "anxious"],
                    "description": "The target emotion",
                },
                "intensity": {
                    "type": "number",
                    "description": "Intensity 0.0-1.0 (default 0.5)",
                    "default": 0.5,
                },
            },
            "required": ["emotion"],
        },
        function=_set_emotion,
    ))

    # ── Recall memory ────────────────────────────────────────────────────────
    async def _recall_memory(query: str, viewer_id: str = "") -> str:
        if memory_agent is None:
            return "Error: Memory agent not available"
        ctx = await memory_agent.recall(query, viewer_id=viewer_id or None)
        parts = []
        if ctx.get("recent"):
            parts.append(f"Recent: {ctx['recent']}")
        if ctx.get("episodic_hints"):
            parts.append(f"Episodic: {'; '.join(ctx['episodic_hints'][:3])}")
        if ctx.get("viewer_summary"):
            parts.append(f"Viewers: {ctx['viewer_summary']}")
        return "\n".join(parts) if parts else "No relevant memories found."

    tools.append(ToolDefinition(
        name="recall_memory",
        description="Search memory for relevant past interactions and context. Use when you need to recall something about a viewer or past conversation.",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to search for in memory"},
                "viewer_id": {"type": "string", "description": "Optional viewer ID to focus search", "default": ""},
            },
            "required": ["query"],
        },
        function=_recall_memory,
    ))

    return tools
