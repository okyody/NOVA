# NOVA DLQ Replay

Use this when Redis Streams messages were dead-lettered after exceeding
the configured retry limit.

## Replay without deleting source DLQ messages

```bash
python deploy/tools/dlq_replay.py \
  --redis-url redis://localhost:6379/0 \
  --dlq-stream nova:events:dlq \
  --target-stream nova:events \
  --limit 100
```

## Replay and delete replayed DLQ entries

```bash
python deploy/tools/dlq_replay.py \
  --redis-url redis://localhost:6379/0 \
  --dlq-stream nova:events:dlq \
  --target-stream nova:events \
  --limit 100 \
  --delete
```

## Operational guidance

- Replay only after you have fixed the consumer-side bug or dependency outage.
- Prefer small batches first.
- Monitor:
  - consumer lag
  - pending count
  - DLQ length
- If a replayed message returns to DLQ repeatedly, treat it as a poison message
  and inspect its payload instead of looping replay forever.
