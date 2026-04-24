from __future__ import annotations

from deploy.tools.dlq_replay import replay_messages


class _FakeRedis:
    def __init__(self):
        self.dlq = [("1-0", {"event_id": "evt-1", "type": "platform.chat_message", "payload": "{}"})]
        self.target = []
        self.deleted = []

    def xrange(self, stream, count=100):
        return self.dlq[:count]

    def xadd(self, stream, payload):
        self.target.append((stream, payload))

    def xdel(self, stream, redis_id):
        self.deleted.append((stream, redis_id))


def test_dlq_replay_requeues_messages():
    client = _FakeRedis()
    replayed = replay_messages(client, dlq_stream="nova:events:dlq", target_stream="nova:events", limit=10, delete=False)

    assert replayed == 1
    assert client.target[0][0] == "nova:events"
    assert client.deleted == []


def test_dlq_replay_can_delete_source_messages():
    client = _FakeRedis()
    replayed = replay_messages(client, dlq_stream="nova:events:dlq", target_stream="nova:events", limit=10, delete=True)

    assert replayed == 1
    assert client.deleted == [("nova:events:dlq", "1-0")]
