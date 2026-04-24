"""Replay messages from a Redis Streams DLQ back to the main stream."""

from __future__ import annotations

import argparse
import sys


def replay_messages(client, *, dlq_stream: str, target_stream: str, limit: int = 100, delete: bool = False) -> int:
    records = client.xrange(dlq_stream, count=limit)
    replayed = 0
    for redis_id, fields in records:
        payload = dict(fields)
        payload.pop("dead_lettered_at", None)
        payload.pop("original_stream", None)
        client.xadd(target_stream, payload)
        if delete:
            client.xdel(dlq_stream, redis_id)
        replayed += 1
    return replayed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--redis-url", default="redis://localhost:6379/0")
    parser.add_argument("--dlq-stream", default="nova:events:dlq")
    parser.add_argument("--target-stream", default="nova:events")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--delete", action="store_true")
    args = parser.parse_args()

    try:
        import redis
    except ImportError as exc:
        raise SystemExit("redis package is required for dlq replay") from exc

    client = redis.from_url(args.redis_url, decode_responses=True)
    replayed = replay_messages(
        client,
        dlq_stream=args.dlq_stream,
        target_stream=args.target_stream,
        limit=args.limit,
        delete=args.delete,
    )
    print(f"dlq_replayed={replayed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
