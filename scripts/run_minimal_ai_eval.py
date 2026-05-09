from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATASET = REPO_ROOT / "evals" / "minimal_ai_eval.json"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from packages.cognitive.nlu import IntentClassifier
from packages.cognitive.orchestrator import Orchestrator
from packages.core.event_bus import EventBus
from packages.core.types import ActionType, EmotionLabel, EmotionState


class _FakeMemory:
    async def recall(self, query: str, viewer_id: str | None = None) -> dict[str, Any]:
        return {
            "recent": "viewer: hi",
            "viewer_summary": "loyal viewer",
            "episodic_hints": ["likes challenge runs"],
        }


class _FakeEmotionAgent:
    def __init__(self, state: EmotionState) -> None:
        self._state = state

    @property
    def current_state(self) -> EmotionState:
        return self._state


class _FakePersonality:
    def system_prompt(self) -> str:
        return "Stay in character."

    def apply_character(self, text: str) -> str:
        return text


class _DummyTools:
    def all_definitions(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "demo_tool",
                    "description": "Demo tool",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]


def _emotion_from_name(name: str) -> EmotionState:
    mapping = {
        "neutral": EmotionState.neutral(),
        "excited": EmotionState(valence=0.8, arousal=0.9, label=EmotionLabel.EXCITED, intensity=0.9),
        "sad": EmotionState(valence=-0.5, arousal=0.3, label=EmotionLabel.SAD, intensity=0.8),
        "calm": EmotionState(valence=0.1, arousal=0.2, label=EmotionLabel.CALM, intensity=0.5),
    }
    return mapping.get(name, EmotionState.neutral())


@dataclass
class EvalResult:
    case_id: str
    category: str
    passed: bool
    intent: str
    allow_tools: bool
    rag_top_k: int
    rag_score_threshold: float
    max_tokens: int
    tone_hint: str
    response_style: str
    failures: list[str]


async def _evaluate_case(case: dict[str, Any]) -> EvalResult:
    bus = EventBus(queue_size=64)
    await bus.start()
    try:
        orchestrator = Orchestrator(
            bus=bus,
            llm=type("LLMStub", (), {"model": "eval-stub", "close": staticmethod(lambda: asyncio.sleep(0))})(),
            memory_agent=_FakeMemory(),
            emotion_agent=_FakeEmotionAgent(_emotion_from_name(case.get("emotion", "neutral"))),
            personality_agent=_FakePersonality(),
            tool_registry=_DummyTools(),
            nlu=IntentClassifier(llm_client=None),
        )
        query = case["text"]
        intent_result = await orchestrator._nlu.classify_async(query)
        plan = orchestrator._build_routing_plan(
            query=query,
            action_type=ActionType.RESPOND,
            emotion=orchestrator._emo.current_state,
            intent_result=intent_result,
        )

        expected = case["expected"]
        failures: list[str] = []
        if expected.get("intent") and intent_result.intent.value != expected["intent"]:
            failures.append(f"intent expected {expected['intent']} got {intent_result.intent.value}")
        if expected.get("intent_any_of") and intent_result.intent.value not in expected["intent_any_of"]:
            failures.append(f"intent expected one of {expected['intent_any_of']} got {intent_result.intent.value}")
        if "allow_tools" in expected and plan.allow_tools != expected["allow_tools"]:
            failures.append(f"allow_tools expected {expected['allow_tools']} got {plan.allow_tools}")
        if "rag_top_k_min" in expected and plan.rag_top_k < expected["rag_top_k_min"]:
            failures.append(f"rag_top_k expected >= {expected['rag_top_k_min']} got {plan.rag_top_k}")
        if "max_tokens_min" in expected and plan.max_tokens < expected["max_tokens_min"]:
            failures.append(f"max_tokens expected >= {expected['max_tokens_min']} got {plan.max_tokens}")
        if "max_tokens_max" in expected and plan.max_tokens > expected["max_tokens_max"]:
            failures.append(f"max_tokens expected <= {expected['max_tokens_max']} got {plan.max_tokens}")
        if "rag_score_threshold_max" in expected and plan.rag_score_threshold > expected["rag_score_threshold_max"]:
            failures.append(
                f"rag_score_threshold expected <= {expected['rag_score_threshold_max']} got {plan.rag_score_threshold}"
            )
        if expected.get("tone_hint_contains") and expected["tone_hint_contains"] not in plan.tone_hint:
            failures.append(f"tone_hint missing '{expected['tone_hint_contains']}'")
        if expected.get("style_contains") and expected["style_contains"] not in plan.response_style:
            failures.append(f"response_style missing '{expected['style_contains']}'")

        return EvalResult(
            case_id=case["id"],
            category=case["category"],
            passed=not failures,
            intent=intent_result.intent.value,
            allow_tools=plan.allow_tools,
            rag_top_k=plan.rag_top_k,
            rag_score_threshold=plan.rag_score_threshold,
            max_tokens=plan.max_tokens,
            tone_hint=plan.tone_hint,
            response_style=plan.response_style,
            failures=failures,
        )
    finally:
        await bus.stop()


async def _run(dataset_path: Path, output_path: Path | None) -> int:
    payload = json.loads(dataset_path.read_text(encoding="utf-8"))
    cases = payload.get("cases", [])
    results = [await _evaluate_case(case) for case in cases]
    passed = sum(1 for result in results if result.passed)
    report = {
        "dataset": str(dataset_path),
        "total": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "results": [asdict(result) for result in results],
    }
    encoded = json.dumps(report, ensure_ascii=False, indent=2)
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(encoded, encoding="utf-8")
    print(encoded)
    return 0 if passed == len(results) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Run NOVA minimal deterministic AI eval suite.")
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET))
    parser.add_argument("--output", default=str(REPO_ROOT / "reports" / "minimal_ai_eval_report.json"))
    args = parser.parse_args()
    dataset_path = Path(args.dataset)
    output_path = Path(args.output) if args.output else None
    return asyncio.run(_run(dataset_path, output_path))


if __name__ == "__main__":
    raise SystemExit(main())
