"""
NOVA Load Test
==============
Locust-based load testing for the NOVA API.

Usage:
    pip install locust
    locust -f deploy/testing/locustfile.py --host=http://localhost:8765

Then open http://localhost:8089 for the Locust UI.
"""
from __future__ import annotations

import json
import random
import time

try:
    from locust import HttpUser, task, between, events
except ImportError:
    raise ImportError("locust not installed. Run: pip install locust")


# ─── Test data ───────────────────────────────────────────────────────────────

_CHAT_MESSAGES = [
    "你好啊！", "今天直播什么游戏？", "666666", "主播好可爱",
    "哈哈哈哈", "这个操作太秀了", "大家晚上好", "第一次来直播间",
    "主播唱首歌吧", "加油加油！", "笑死了哈哈哈", "这是哪个游戏？",
    "主播今天好美", "我要送礼！", "主播能加个好友吗", "快看我快看我",
]

_GIFT_NAMES = ["小心心", "棒棒糖", "啤酒", "火箭", "飞机", "皇冠"]


class NovaChatUser(HttpUser):
    """Simulates a viewer sending chat messages."""

    wait_time = between(1, 5)

    @task(10)
    def send_chat_message(self) -> None:
        """Send a chat message via the health/polling endpoint."""
        # In production, this would be via WebSocket from the platform adapter
        # For load testing, we use the API endpoints
        self.client.get("/health", name="health_check")

    @task(3)
    def check_knowledge_stats(self) -> None:
        """Check knowledge base stats."""
        self.client.get("/api/knowledge/stats", name="knowledge_stats")

    @task(1)
    def check_metrics(self) -> None:
        """Check Prometheus metrics."""
        self.client.get("/metrics", name="metrics")


class NovaAdminUser(HttpUser):
    """Simulates an admin ingesting knowledge and reloading config."""

    wait_time = between(10, 30)

    @task(1)
    def ingest_knowledge(self) -> None:
        """Ingest a knowledge document."""
        self.client.post(
            "/api/knowledge/ingest",
            params={
                "text": f"测试知识文档 {random.randint(1, 1000)}：这是一段用于负载测试的知识文本。",
                "source_id": f"load_test_{int(time.time())}",
            },
            name="knowledge_ingest",
        )

    @task(1)
    def reload_config(self) -> None:
        """Reload character config."""
        self.client.post("/api/config/reload", name="config_reload")


class NovaWebSocketUser(HttpUser):
    """Simulates a Studio UI WebSocket connection."""

    @task
    def connect_ws(self) -> None:
        """Connect to the control WebSocket."""
        try:
            with self.client.websocket_connect("/ws/control", name="ws_control") as ws:
                # Send ping
                ws.send(json.dumps({"cmd": "ping"}))
                # Receive for a while
                for _ in range(5):
                    msg = ws.recv()
                    if msg:
                        data = json.loads(msg)
                        if data.get("cmd") == "pong":
                            break
                    time.sleep(1)
        except Exception:
            pass


# ─── Event listeners ─────────────────────────────────────────────────────────

@events.request.add_listener
def on_request(request_type, name, response_time, response_length, exception, **kwargs):
    """Log request details for analysis."""
    if exception:
        pass  # Locust logs this already
